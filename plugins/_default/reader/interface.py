# plugins/_default/reader/interface.py
# coding: utf-8
from typing import Optional

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QSizePolicy

from qfluentwidgets import (
    FluentIcon as FIF,
    FluentWindow, NavigationItemPosition,
    SmoothScrollArea, TransparentToolButton,
    PrimaryPushButton, LineEdit, BodyLabel, TitleLabel,
    CaptionLabel, ProgressBar,
    IndeterminateProgressBar,
    InfoBar, InfoBarPosition,
    isDarkTheme, qconfig,
)

from toolmethods import log_info

from .api import ApiError, NotFoundError
from .loader import LoadWorker, get_loader
from .markdown import md_to_html
from .image_browser import ImageBrowser


# ══════════════════════════════════════════════════════════════
#  导航入口
# ══════════════════════════════════════════════════════════════

class ReaderInterface(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("readerInterface")
        self._window: Optional[ReaderWindow] = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(36, 36, 36, 36)
        layout.setSpacing(12)

        layout.addWidget(TitleLabel("阅读器", self))
        layout.addWidget(BodyLabel(
            "输入 FimTale 帖子 ID，打开独立阅读窗口。", self
        ))

        row = QHBoxLayout()
        self.input = LineEdit(self)
        self.input.setPlaceholderText("例如：1431")
        self.input.setClearButtonEnabled(True)
        self.input.returnPressed.connect(self._open)
        row.addWidget(self.input, 1)

        btn = PrimaryPushButton("打开", self)
        btn.clicked.connect(self._open)
        row.addWidget(btn)

        layout.addLayout(row)
        layout.addStretch(1)

    def _open(self):
        text = self.input.text().strip()
        if not text.isdigit():
            InfoBar.warning(
                "无效 ID", "请输入数字",
                parent=self, position=InfoBarPosition.TOP, duration=1500,
            )
            return
        if self._window is not None:
            self._window.close()
        self._window = ReaderWindow(int(text))
        self._window.show()


# ══════════════════════════════════════════════════════════════
#  阅读器窗口
# ══════════════════════════════════════════════════════════════

class ReaderWindow(FluentWindow):

    def __init__(self, topic_id: int, parent=None):
        super().__init__(parent)
        self.topic_id = topic_id
        self.topic = None
        self._font_size = 15
        self._chapter_items = []
        self._raw_md = ""
        self._raw_html = ""
        self._revealed_spoilers = set()

        self.setObjectName("ReaderWindow")
        self.setWindowTitle("加载中…")
        self.resize(1100, 760)
        self.setMinimumSize(800, 600)

        self.navigationInterface.setCollapsible(True)

        self.contentContainer = self._build_content_container()
        self.addSubInterface(
            self.contentContainer, FIF.DOCUMENT, "正文",
            position=NavigationItemPosition.TOP,
        )
        self._hide_nav_item("readerContent")

        self._apply_theme()
        qconfig.themeChanged.connect(self._apply_theme)

        self._show_skeleton()
        self._start_load()

    # ── 隐藏"正文"导航项 ──

    def _hide_nav_item(self, route_key: str):
        try:
            item = self.navigationInterface.widget(route_key)
            if item:
                item.hide()
                item.setFixedHeight(0)
        except Exception:
            pass

    # ── 内容容器 ──

    def _build_content_container(self):
        container = QWidget(self)
        container.setObjectName("readerContent")
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 顶部 Fluent 加载条
        self.loadingBar = IndeterminateProgressBar(container)
        self.loadingBar.setFixedHeight(3)
        self.loadingBar.hide()
        layout.addWidget(self.loadingBar)

        # 平滑滚动容器
        self.scrollArea = SmoothScrollArea(container)
        self.scrollArea.setObjectName("readerScroll")
        self.scrollArea.setWidgetResizable(True)
        self.scrollArea.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scrollArea.setFrameShape(SmoothScrollArea.NoFrame)

        # 内层 QTextBrowser
        self.browser = ImageBrowser(self.scrollArea)
        self.browser.setObjectName("readerBrowser")
        self.browser.setOpenExternalLinks(False)
        self.browser.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.browser.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.browser.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.browser.anchorClicked.connect(self._on_anchor_clicked)
        self.scrollArea.setWidget(self.browser)

        layout.addWidget(self.scrollArea, 1)

        self.browser.document().documentLayout().documentSizeChanged.connect(
            self._sync_browser_height
        )
        self.scrollArea.verticalScrollBar().valueChanged.connect(self._on_scroll)

        # 底部栏
        bottom = QWidget(container)
        bottom.setObjectName("readerBottom")
        bottom.setFixedHeight(44)
        bottom_layout = QHBoxLayout(bottom)
        bottom_layout.setContentsMargins(16, 6, 16, 6)
        bottom_layout.setSpacing(12)

        self.readingLabel = CaptionLabel("阅读进度 0%", bottom)
        bottom_layout.addWidget(self.readingLabel)

        self.progressBar = ProgressBar(bottom)
        self.progressBar.setRange(0, 100)
        self.progressBar.setValue(0)
        self.progressBar.setFixedHeight(6)
        bottom_layout.addWidget(self.progressBar, 1)

        # 刷新按钮
        self.refreshBtn = TransparentToolButton(FIF.SYNC, bottom)
        self.refreshBtn.setFixedSize(28, 28)
        self.refreshBtn.setToolTip("忽略缓存，重新拉取当前章节")
        self.refreshBtn.clicked.connect(self._on_refresh_clicked)
        bottom_layout.addWidget(self.refreshBtn)

        # 字号按钮
        self.fontDownBtn = TransparentToolButton(FIF.REMOVE, bottom)
        self.fontDownBtn.setFixedSize(28, 28)
        self.fontDownBtn.setToolTip("减小字号")
        self.fontDownBtn.clicked.connect(lambda: self._change_font(-1))
        bottom_layout.addWidget(self.fontDownBtn)

        self.fontUpBtn = TransparentToolButton(FIF.ADD, bottom)
        self.fontUpBtn.setFixedSize(28, 28)
        self.fontUpBtn.setToolTip("增大字号")
        self.fontUpBtn.clicked.connect(lambda: self._change_font(1))
        bottom_layout.addWidget(self.fontUpBtn)

        layout.addWidget(bottom)

        return container

    # ── 加载指示 ──

    def _set_loading(self, on: bool):
        if on:
            if not self.loadingBar.isVisible():
                self.loadingBar.show()
            self.loadingBar.start()
        else:
            self.loadingBar.stop()
            self.loadingBar.hide()

    # ── 尺寸同步 ──

    def _sync_browser_height(self):
        if not hasattr(self, "browser") or not hasattr(self, "scrollArea"):
            return

        viewport_h = self.scrollArea.viewport().height()
        if viewport_h <= 0:
            return

        doc_h = int(self.browser.document().size().height())
        target = max(doc_h + 96, viewport_h)

        if self.browser.minimumHeight() != target:
            self.browser.setMinimumHeight(target)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._sync_browser_height()

    def showEvent(self, e):
        super().showEvent(e)
        self._sync_browser_height()

    # ── 加载 ──

    def _start_load(self, force_refresh: bool = False):
        self._set_loading(True)
        worker = LoadWorker(self.topic_id, force_refresh)
        worker.meta_ready.connect(self._on_meta_ready)
        worker.content_ready.connect(self._on_content_ready)
        worker.failed.connect(self._on_load_failed)
        self._worker = worker
        get_loader().submit(worker)

    def _on_meta_ready(self, topic_id: int, topic):
        self.topic = topic
        self.setWindowTitle(topic.title)
        self._rebuild_chapter_list()

    def _on_content_ready(self, topic_id: int, topic):
        self._render_content(topic)
        self._set_loading(False)

    def _on_load_failed(self, topic_id: int, msg: str):
        self.setWindowTitle("加载失败")
        self._raw_md = ""
        self._raw_html = f"<h2>加载失败</h2><p>{msg}</p>"
        self.browser.setHtml(self._raw_html)
        self._sync_browser_height()
        self._set_loading(False)
        InfoBar.error(
            "加载失败", msg,
            parent=self, position=InfoBarPosition.TOP_RIGHT, duration=3000,
        )

    # ── 刷新 ──

    def _on_refresh_clicked(self):
        if not self.topic_id:
            return
        log_info(f"[Reader] 用户强制刷新 topic {self.topic_id}")
        self._start_load(force_refresh=True)

    # ── 章节目录 ──

    def _rebuild_chapter_list(self):
        if not self.topic:
            return
        for route in self._chapter_items:
            try:
                self.navigationInterface.removeWidget(route)
            except Exception:
                pass
        self._chapter_items = []

        for ch in self.topic.menu:
            route = f"chapter_{ch.id}"
            self._chapter_items.append(route)
            self.navigationInterface.addItem(
                routeKey=route,
                icon=FIF.DOCUMENT,
                text=ch.title,
                onClick=lambda checked=False, tid=ch.id: self._load_chapter(tid),
                position=NavigationItemPosition.SCROLL,
                tooltip=ch.title,
            )

        self._highlight_chapter(self.topic_id)

    def _highlight_chapter(self, tid: int):
        target_route = f"chapter_{tid}"
        for route in self._chapter_items:
            try:
                item = self.navigationInterface.widget(route)
                if item:
                    item.setSelected(route == target_route)
            except Exception:
                pass

    def _load_chapter(self, topic_id: int):
        if self.topic and topic_id == self.topic.id:
            return
        self.topic_id = topic_id
        self._start_load()

    # ── 渲染 ──

    def _show_skeleton(self):
        self._raw_md = ""
        self._raw_html = "<h1>加载中…</h1><p>正在获取内容，请稍候。</p>"
        self.browser.setHtml(self._raw_html)
        self._sync_browser_height()

    def _render_content(self, topic):
        self.browser.clear_memory_cache()
        self._raw_md = topic.content or ""
        self._revealed_spoilers.clear()
        self._rerender()

    def _rerender(self):
        self._raw_html = md_to_html(
            self._raw_md,
            revealed_spoilers=self._revealed_spoilers,
            logged_in=True,
        )
        self.browser.setHtml(self._raw_html)
        self._sync_browser_height()
        self.scrollArea.verticalScrollBar().setValue(0)
        self._update_progress_display()

    # ── 阅读进度 ──

    def _on_scroll(self, value: int):
        self._update_progress_display()

    def _update_progress_display(self):
        sb = self.scrollArea.verticalScrollBar()
        maximum = sb.maximum()
        if maximum <= 0:
            pct = 100
        else:
            pct = int(sb.value() / maximum * 100)
        self._update_progress(pct)

    def _update_progress(self, pct: int):
        self.progressBar.setValue(pct)
        self.readingLabel.setText(f"阅读进度 {pct}%")

    # ── 字号 ──

    def _change_font(self, delta: int):
        self._font_size = max(10, min(30, self._font_size + delta))
        self._apply_theme()
        if self._raw_md:
            self._rerender()

    # ── 链接 & spoiler ──

    def _on_anchor_clicked(self, url: QUrl):
        u = url.toString()

        # spoiler 点击展开
        if u.startswith("spoiler:"):
            try:
                idx = int(u.split(":", 1)[1])
            except ValueError:
                return
            if idx in self._revealed_spoilers:
                return
            self._revealed_spoilers.add(idx)
            self._rerender()
            return

        # FimTale topic 链接 → 内部加载
        if u.startswith("https://fimtale.com/t/") or u.startswith("http://fimtale.com/t/"):
            try:
                tid = int(u.rstrip("/").split("/")[-1])
                self._load_chapter(tid)
                return
            except ValueError:
                pass

        QDesktopServices.openUrl(url)

    # ── 主题 ──

    def _apply_theme(self):
        if isDarkTheme():
            bg, fg = "#1e1e1e", "#e0e0e0"
            code_bg = "#2a2a2a"
        else:
            bg, fg = "#fafafa", "#1a1a1a"
            code_bg = "#f0f0f0"

        self.browser.setStyleSheet(f"""
            QTextBrowser#readerBrowser {{
                background-color: {bg};
                color: {fg};
                border: none;
                padding: 32px 48px;
                font-size: {self._font_size}px;
                font-family: 'Microsoft YaHei', 'PingFang SC', sans-serif;
                selection-background-color: #28afe9;
            }}
            pre.code-block {{
                background-color: {code_bg};
                padding: 8px;
                font-family: Consolas, monospace;
            }}
        """)

        self.scrollArea.setStyleSheet(f"""
            SmoothScrollArea#readerScroll {{
                background-color: {bg};
                border: none;
            }}
        """)