# plugins/_default/reader/interface.py
# coding: utf-8
import random, re
from typing import Optional

from PySide6.QtCore import (
    Qt, QUrl, QTimer, QEventLoop, Signal, QSize, QRect, QModelIndex,
)
from PySide6.QtGui import (
    QDesktopServices, QPainter, QColor, QFontMetrics,
)
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QSizePolicy,
    QListWidgetItem, QStyle, QStyleOptionViewItem, QStyledItemDelegate,
)

from qfluentwidgets import (
    FluentIcon as FIF,
    FluentWindow, NavigationItemPosition,
    SmoothScrollArea, TransparentToolButton,
    PrimaryPushButton, LineEdit, BodyLabel, TitleLabel,
    CaptionLabel, ProgressBar,
    IndeterminateProgressBar,
    ListWidget, ListItemDelegate,
    InfoBar, InfoBarPosition,
    isDarkTheme, qconfig,
    ToolTipFilter, ToolTipPosition,
)

from toolmethods import log_info

from .api import ApiError, NotFoundError
from .loader import LoadWorker, get_loader
from .markdown import md_to_html
from .image_browser import ImageBrowser
from . import cache

from app_state import app_state

# ══════════════════════════════════════════════════════════════
#  自定义 role
# ══════════════════════════════════════════════════════════════

ROLE_TOPIC_ID = Qt.UserRole + 1
ROLE_BADGES = Qt.UserRole + 2
ROLE_DISPLAY = Qt.UserRole + 3


# ══════════════════════════════════════════════════════════════
#  Placeholder 生成
# ══════════════════════════════════════════════════════════════

# 全新用户没有任何浏览记录时的兜底列表
_DEFAULT_PLACEHOLDER_IDS = [
    "4", "5", "86574", "268", "4310", "4809", "5272", "2520", "53207",
    "85746", "57519", "53229", "56187", "87659", "88789", "87266",
    "87349", "32953", "91116", "9984", "5332", "29930", "76800", 
    "89705", "1788", "84930", "81520"
]

# "16326" - 《3小时47分钟》
# 作者：Accurate_Balance
# 感谢您的付出与贡献。
# 获奖记录：
# 2020年 - Raa征文比赛一等奖获奖作品
# 2023年 - FimFiction第二届科幻小说征文比赛“委员会奖”（英文版）
# 3小时47分不但臻于剧情和文笔，而且其反映的内核深刻地讽刺了当下娱乐化的发展。
# 除此之外，本文中的部分情节精确反映了当下社会问题。作者也曾说，“本以为是寓言故事，后来才发现，原来是预言故事”。
# 这篇优秀的文章在 FimTale 上已被删除，可能是作者自删。但无论如何，我们都不可否认的是她的作品，和她真正臻于热爱的创作。
# 以及她本身。
# 谨以此，献给 Accurate_Balance 以及其对马圈不可磨灭的贡献。

# 如果你看到了这一段注释，那么也感谢你看完这一段对于理解代码并没有用的一大串文字。
# 祝您生活愉快！

def _make_placeholder() -> str:
    """
    生成输入框的 placeholder。

    规则：
    1. 根帖足够多（>= 8）→ 只从根帖里抽
    2. 根帖不够 → 根帖 + 内置名帖 一起抽
    3. 完全没历史 → 只用内置名帖
    """
    defaults = list(_DEFAULT_PLACEHOLDER_IDS)

    try:
        recent = cache.get_recent_topics(30)
    except Exception:
        recent = []

    roots = [str(it["id"]) for it in recent if not it.get("parent_title")]
    others = [str(it["id"]) for it in recent if it.get("parent_title")]

    if len(roots) >= 8:
        pool = roots
    elif roots:
        # 根帖不够，拿内置名帖补齐
        merged = roots + [x for x in defaults if x not in roots]
        pool = merged
    elif others:
        pool = others
    else:
        pool = defaults

    return f"例如：{random.choice(pool)}"


# ══════════════════════════════════════════════════════════════
#  最近阅读 delegate
# ══════════════════════════════════════════════════════════════

class RecentItemDelegate(ListItemDelegate):
    """最近阅读 item：徽章 pill + 作品名 + 章节名 + ID"""

    PADDING_H = 12
    PADDING_V = 8
    BADGE_H = 20
    BADGE_PADDING_H = 8
    BADGE_GAP = 6
    TITLE_ID_GAP = 12
    ROW_HEIGHT = 40

    def paint(self, painter: QPainter, option: QStyleOptionViewItem,
              index: QModelIndex):
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)

        if option.state & QStyle.State_Selected:
            painter.setBrush(QColor(0, 0, 0, 15) if not isDarkTheme()
                             else QColor(255, 255, 255, 25))
            painter.setPen(Qt.NoPen)
            r = option.rect.adjusted(2, 1, -2, -1)
            painter.drawRoundedRect(r, 5, 5)
        elif option.state & QStyle.State_MouseOver:
            painter.setBrush(QColor(0, 0, 0, 10) if not isDarkTheme()
                             else QColor(255, 255, 255, 15))
            painter.setPen(Qt.NoPen)
            r = option.rect.adjusted(2, 1, -2, -1)
            painter.drawRoundedRect(r, 5, 5)

        badges = index.data(ROLE_BADGES) or []
        display = index.data(ROLE_DISPLAY) or ""
        topic_id = index.data(ROLE_TOPIC_ID)

        text_color = QColor("#e0e0e0") if isDarkTheme() else QColor("#1a1a1a")
        badge_bg = QColor("#4a6c8f") if isDarkTheme() else QColor("#d0e4f5")
        badge_fg = QColor("#ffffff") if isDarkTheme() else QColor("#1a4a6c")
        id_color = QColor("#888888")

        x = option.rect.x() + self.PADDING_H
        y = option.rect.y() + self.PADDING_V
        h = option.rect.height() - self.PADDING_V * 2

        badge_font = painter.font()
        badge_font.setPointSize(9)
        painter.setFont(badge_font)
        fm = QFontMetrics(badge_font)

        for b in badges:
            w = fm.horizontalAdvance(b) + self.BADGE_PADDING_H * 2
            badge_rect = QRect(x, y + (h - self.BADGE_H) // 2, w, self.BADGE_H)
            painter.setBrush(badge_bg)
            painter.setPen(Qt.NoPen)
            painter.drawRoundedRect(badge_rect, self.BADGE_H // 2,
                                    self.BADGE_H // 2)
            painter.setPen(badge_fg)
            painter.drawText(badge_rect, Qt.AlignCenter, b)
            x += w + self.BADGE_GAP

        id_text = f"#{topic_id}" if topic_id else ""
        id_font = painter.font()
        id_font.setPointSize(9)
        id_fm = QFontMetrics(id_font)
        id_w = id_fm.horizontalAdvance(id_text) if id_text else 0

        title_font = painter.font()
        title_font.setPointSize(10)
        painter.setFont(title_font)

        avail_w = option.rect.right() - self.PADDING_H - x
        if id_text:
            avail_w -= id_w + self.TITLE_ID_GAP

        fm2 = QFontMetrics(title_font)
        elided = fm2.elidedText(display, Qt.ElideRight, max(0, avail_w))

        painter.setPen(text_color)
        painter.drawText(
            QRect(x, option.rect.y(), max(0, avail_w), option.rect.height()),
            Qt.AlignVCenter | Qt.AlignLeft, elided
        )

        if id_text:
            id_x = option.rect.right() - self.PADDING_H - id_w
            painter.setFont(id_font)
            painter.setPen(id_color)
            painter.drawText(
                QRect(id_x, option.rect.y(), id_w, option.rect.height()),
                Qt.AlignVCenter | Qt.AlignRight, id_text
            )

        painter.restore()

    def sizeHint(self, option, index):
        return QSize(option.rect.width(), self.ROW_HEIGHT)


# ══════════════════════════════════════════════════════════════
#  Topic ID 输入对话框
# ══════════════════════════════════════════════════════════════

try:
    from plugins._default.login import _FluentDialog
except ImportError:
    _FluentDialog = None


if _FluentDialog is not None:
    class _TopicInputDialog(_FluentDialog):
        """输入 Topic ID 打开新作品"""

        def __init__(self, parent=None):
            super().__init__("打开新作品", parent)
            self.topic_id = None

            title = TitleLabel("打开新作品", self)
            self.addContent(title)

            desc = BodyLabel("输入 FimTale 帖子 ID，将加载对应内容。", self)
            desc.setWordWrap(True)
            self.addContent(desc)

            self.input = LineEdit(self)
            self.input.setPlaceholderText(_make_placeholder())   # ← 改这里
            self.input.setClearButtonEnabled(True)
            self.input.returnPressed.connect(self.yesButton.click)
            self.addContent(self.input)

            self.yesButton.setText("打开")
            self.cancelButton.setText("取消")
            self.resize(400, 260)

        def validate(self):
            text = self.input.text().strip()
            if not text.isdigit():
                InfoBar.warning(
                    "无效 ID", "请输入数字",
                    parent=self, position=InfoBarPosition.TOP, duration=1500,
                )
                return False
            self.topic_id = int(text)
            self.passed = True
            return True
else:
    _TopicInputDialog = None


# ══════════════════════════════════════════════════════════════
#  导航入口（最近阅读 + ID 输入）
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
            "输入 FimTale 帖子 ID 打开新窗口，或从下方最近阅读中选择。", self
        ))

        row = QHBoxLayout()
        self.input = LineEdit(self)
        self.input.setPlaceholderText(_make_placeholder())   # ← 改这里
        self.input.setClearButtonEnabled(True)
        self.input.returnPressed.connect(self._open_from_input)
        row.addWidget(self.input, 1)

        btn = PrimaryPushButton("打开", self)
        btn.clicked.connect(self._open_from_input)
        row.addWidget(btn)

        layout.addLayout(row)
        layout.addSpacing(12)

        self.recentLabel = BodyLabel("最近阅读", self)
        layout.addWidget(self.recentLabel)

        self.recentList = ListWidget(self)
        self.recentList.setItemDelegate(
            RecentItemDelegate(self.recentList)
        )
        self.recentList.itemClicked.connect(self._on_recent_clicked)
        layout.addWidget(self.recentList, 1)

        qconfig.themeChanged.connect(self.recentList.viewport().update)

        self._refresh_recent()

    def open_topic(self, topic_id: int):
        self._open_window(int(topic_id))

    @staticmethod
    def _wrap_title(title: str) -> str:
        t = (title or "").strip()
        if not t:
            return t
        if (t.startswith("《") and t.endswith("》")) or \
           (t.startswith("〈") and t.endswith("〉")):
            return t
        return f"《{t}》"

    @staticmethod
    def _extract_badges(title: str):
        if not title:
            return [], ""
        pattern = re.compile(r'[\[【]([^\]】]+)[\]】]')
        badges = pattern.findall(title)
        clean = pattern.sub("", title).strip()
        return badges, clean

    def _refresh_recent(self):
        self.recentList.clear()
        items = cache.get_recent_topics(30)

        if not items:
            item = QListWidgetItem("（暂无阅读记录）")
            item.setFlags(Qt.NoItemFlags)
            self.recentList.addItem(item)
            return

        for it in items:
            if it["parent_title"]:
                badges, work = self._extract_badges(it["parent_title"])
                work = self._wrap_title(work)
                display = f"{work} · {it['title']}"
            else:
                badges, work = self._extract_badges(it["title"])
                work = self._wrap_title(work)
                display = work

            item = QListWidgetItem()
            item.setData(ROLE_TOPIC_ID, it["id"])
            item.setData(ROLE_BADGES, badges)
            item.setData(ROLE_DISPLAY, display)
            item.setSizeHint(QSize(0, RecentItemDelegate.ROW_HEIGHT))
            self.recentList.addItem(item)

    def _on_recent_clicked(self, item: QListWidgetItem):
        tid = item.data(ROLE_TOPIC_ID)
        if tid is None:
            return
        self._open_window(int(tid))

    def _open_from_input(self):
        text = self.input.text().strip()
        if not text.isdigit():
            InfoBar.warning(
                "无效 ID", "请输入数字",
                parent=self, position=InfoBarPosition.TOP, duration=1500,
            )
            return
        self._open_window(int(text))

    def _open_window(self, topic_id: int):
        if self._window is not None:
            try:
                self._window.close()
            except Exception:
                pass
        self._window = ReaderWindow(topic_id)
        self._window.show()
        self._window.raise_()
        self._window.activateWindow()

    def showEvent(self, e):
        super().showEvent(e)
        self._refresh_recent()
        self.input.setPlaceholderText(_make_placeholder())   # ← 改这里


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

        # resize 防抖
        self._resize_timer = QTimer(self)
        self._resize_timer.setSingleShot(True)
        self._resize_timer.setInterval(200)
        self._resize_timer.timeout.connect(self._on_resize_settled)

        # 文档尺寸变化防抖
        self._height_sync_timer = QTimer(self)
        self._height_sync_timer.setSingleShot(True)
        self._height_sync_timer.setInterval(80)
        self._height_sync_timer.timeout.connect(self._sync_browser_height)

        self._apply_theme()
        qconfig.themeChanged.connect(self._apply_theme)

        self._show_skeleton()
        self._start_load()

    def _hide_nav_item(self, route_key: str):
        try:
            item = self.navigationInterface.widget(route_key)
            if item:
                item.hide()
                item.setFixedHeight(0)
        except Exception:
            pass

    def _build_content_container(self):
        container = QWidget(self)
        container.setObjectName("readerContent")
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.loadingBar = IndeterminateProgressBar(container)
        self.loadingBar.setFixedHeight(3)
        self.loadingBar.hide()
        layout.addWidget(self.loadingBar)

        self.scrollArea = SmoothScrollArea(container)
        self.scrollArea.setObjectName("readerScroll")
        self.scrollArea.setWidgetResizable(True)
        self.scrollArea.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scrollArea.setFrameShape(SmoothScrollArea.NoFrame)

        self.browser = ImageBrowser(self.scrollArea)
        self.browser.setObjectName("readerBrowser")
        self.browser.setOpenExternalLinks(False)
        self.browser.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.browser.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.browser.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.browser.anchorClicked.connect(self._on_anchor_clicked)
        self.scrollArea.setWidget(self.browser)

        layout.addWidget(self.scrollArea, 1)

        # 文档尺寸变化 → 防抖
        self.browser.document().documentLayout().documentSizeChanged.connect(
            lambda: self._height_sync_timer.start()
        )
        self.scrollArea.verticalScrollBar().valueChanged.connect(self._on_scroll)

        # ── 底部栏 ──
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

        self.openBtn = TransparentToolButton(FIF.FOLDER_ADD, bottom)
        self.openBtn.setFixedSize(28, 28)
        self.openBtn.setToolTip("打开新作品")
        self.openBtn.installEventFilter(
            ToolTipFilter(self.openBtn, showDelay=250,
                          position=ToolTipPosition.TOP)
        )
        self.openBtn.clicked.connect(self._on_open_new)
        bottom_layout.addWidget(self.openBtn)

        self.refreshBtn = TransparentToolButton(FIF.SYNC, bottom)
        self.refreshBtn.setFixedSize(28, 28)
        self.refreshBtn.setToolTip("忽略缓存，重新拉取当前章节")
        self.refreshBtn.installEventFilter(
            ToolTipFilter(self.refreshBtn, showDelay=250,
                          position=ToolTipPosition.TOP)
        )
        self.refreshBtn.clicked.connect(self._on_refresh_clicked)
        bottom_layout.addWidget(self.refreshBtn)

        self.fontDownBtn = TransparentToolButton(FIF.REMOVE, bottom)
        self.fontDownBtn.setFixedSize(28, 28)
        self.fontDownBtn.setToolTip("减小字号")
        self.fontDownBtn.installEventFilter(
            ToolTipFilter(self.fontDownBtn, showDelay=250,
                          position=ToolTipPosition.TOP)
        )
        self.fontDownBtn.clicked.connect(lambda: self._change_font(-1))
        bottom_layout.addWidget(self.fontDownBtn)

        self.fontUpBtn = TransparentToolButton(FIF.ADD, bottom)
        self.fontUpBtn.setFixedSize(28, 28)
        self.fontUpBtn.setToolTip("增大字号")
        self.fontUpBtn.installEventFilter(
            ToolTipFilter(self.fontUpBtn, showDelay=250,
                          position=ToolTipPosition.TOP)
        )
        self.fontUpBtn.clicked.connect(lambda: self._change_font(1))
        bottom_layout.addWidget(self.fontUpBtn)

        layout.addWidget(bottom)

        return container

    def _set_loading(self, on: bool):
        if on:
            if not self.loadingBar.isVisible():
                self.loadingBar.show()
            self.loadingBar.start()
        else:
            self.loadingBar.stop()
            self.loadingBar.hide()

    def _sync_browser_height(self):
        if not hasattr(self, "browser") or not hasattr(self, "scrollArea"):
            return
        try:
            viewport_h = self.scrollArea.viewport().height()
            if viewport_h <= 0:
                return
            doc_h = int(self.browser.document().size().height())
            target = max(doc_h + 96, viewport_h)
            if self.browser.minimumHeight() != target:
                self.browser.setMinimumHeight(target)
        except Exception:
            pass

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._sync_browser_height()
        if hasattr(self, "_resize_timer"):
            self._resize_timer.start()

    def _on_resize_settled(self):
        if not self._raw_md:
            return
        self._rerender()

    def showEvent(self, e):
        super().showEvent(e)
        self._sync_browser_height()

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
        app_state.set_reader_topic(topic, self)   # ← 加这行

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

    def _on_refresh_clicked(self):
        if not self.topic_id:
            return
        log_info(f"[Reader] 用户强制刷新 topic {self.topic_id}")
        self._start_load(force_refresh=True)

    def _on_open_new(self):
        if _TopicInputDialog is None:
            InfoBar.warning(
                "不可用", "未找到输入对话框组件",
                parent=self, position=InfoBarPosition.TOP, duration=2000,
            )
            return

        dlg = _TopicInputDialog(parent=self)
        dlg.show()
        loop = QEventLoop()
        dlg.destroyed.connect(loop.quit)
        loop.exec()

        if not dlg.passed or dlg.topic_id is None:
            return
        if dlg.topic_id == self.topic_id:
            return

        log_info(f"[Reader] 打开新作品: {dlg.topic_id}")
        self._load_chapter(dlg.topic_id)

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

        QTimer.singleShot(200, self._height_sync_timer.start)
        QTimer.singleShot(500, self._height_sync_timer.start)

    def _rerender(self):
        vp_w = self.scrollArea.viewport().width()
        if vp_w < 200:
            vp_w = 1000
        max_img_w = max(200, vp_w - 130)
        self.browser.set_max_image_width(max_img_w)

        self._raw_html = md_to_html(
            self._raw_md,
            revealed_spoilers=self._revealed_spoilers,
            logged_in=True,
        )

        html = self._raw_html.replace(
            '<img ',
            f'<img style="max-width:{max_img_w}px;height:auto;" '
        )

        self.browser.setHtml(html)
        self._sync_browser_height()
        self._update_progress_display()

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

    def _change_font(self, delta: int):
        self._font_size = max(10, min(30, self._font_size + delta))
        self._apply_theme()
        if self._raw_md:
            self._rerender()

    def _on_anchor_clicked(self, url: QUrl):
        u = url.toString()

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

        if u.startswith("https://fimtale.com/t/") or u.startswith("http://fimtale.com/t/"):
            try:
                tid = int(u.rstrip("/").split("/")[-1])
                self._load_chapter(tid)
                return
            except ValueError:
                pass

        QDesktopServices.openUrl(url)

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