import random, re
from typing import Optional

from PySide6.QtCore import (
    Qt, QUrl, QTimer, QEventLoop, Signal, QSize, QRect, QModelIndex,
    QPoint, QPropertyAnimation, QEasingCurve,
)
from PySide6.QtGui import (
    QDesktopServices, QPainter, QColor, QFontMetrics, QImage,
)
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QSizePolicy,
    QListWidgetItem, QStyle, QStyleOptionViewItem, QStyledItemDelegate,
    QLayout, QApplication, QGraphicsOpacityEffect,
)

from qfluentwidgets import (
    FluentIcon as FIF,
    FluentWindow, NavigationItemPosition,
    SmoothScrollArea, TransparentToolButton, TransparentToggleToolButton,
    PrimaryPushButton, LineEdit, BodyLabel, TitleLabel,
    CaptionLabel, ProgressBar,
    IndeterminateProgressBar,
    ListWidget, ListItemDelegate,
    BreadcrumbBar,
    InfoBar, InfoBarPosition,
    isDarkTheme, qconfig,
    ToolTipFilter, ToolTipPosition,
    RoundMenu, Action,
)

from toolmethods import log_info

from .api import ApiError, NotFoundError
from .loader import LoadWorker, get_loader
from .markdown import md_to_html
from .image_browser import ImageBrowser
from . import cache
from . import favorites

from app_state import app_state

ROLE_TOPIC_ID = Qt.UserRole + 1
ROLE_BADGES = Qt.UserRole + 2
ROLE_DISPLAY = Qt.UserRole + 3

def _fade_in(widget, duration: int = 200):
    """
    给 widget 做一次性淡入。结束后自动清掉 effect。

    - 用 widget._fade_anim 保活，防止 Python GC 回收动画对象
    - 动画结束 setGraphicsEffect(None)，避免长期挂载增加渲染开销
    """
    try:
        old = getattr(widget, "_fade_anim", None)
        if old is not None:
            try:
                old.stop()
            except RuntimeError:
                pass

        effect = QGraphicsOpacityEffect(widget)
        widget.setGraphicsEffect(effect)

        anim = QPropertyAnimation(effect, b"opacity", widget)
        anim.setDuration(duration)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setEasingCurve(QEasingCurve.OutCubic)

        def _cleanup():
            try:
                widget.setGraphicsEffect(None)
            except RuntimeError:
                pass

        anim.finished.connect(_cleanup)
        widget._fade_anim = anim
        anim.start(QPropertyAnimation.DeleteWhenStopped)
    except Exception:
        # 动画炸了一样加载
        pass

class FlowLayout(QLayout):
    """自动换行的横向布局"""

    def __init__(self, parent=None, margin=0, h_spacing=8, v_spacing=8):
        super().__init__(parent)
        self._items = []
        self._h = h_spacing
        self._v = v_spacing
        self.setContentsMargins(margin, margin, margin, margin)

    def addItem(self, item):
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, index):
        if 0 <= index < len(self._items):
            return self._items[index]
        return None

    def takeAt(self, index):
        if 0 <= index < len(self._items):
            return self._items.pop(index)
        return None

    def expandingDirections(self):
        return Qt.Orientations(Qt.Orientation(0))

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._do_layout(QRect(0, 0, width, 0), test_only=True)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._do_layout(rect, test_only=False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        m = self.contentsMargins()
        size += QSize(m.left() + m.right(), m.top() + m.bottom())
        return size

    def _do_layout(self, rect, test_only):
        m = self.contentsMargins()
        x = rect.x() + m.left()
        y = rect.y() + m.top()
        line_height = 0
        right = rect.right() - m.right()

        for item in self._items:
            hint = item.sizeHint()
            w, h = hint.width(), hint.height()

            if x + w > right and line_height > 0:
                x = rect.x() + m.left()
                y += line_height + self._v
                line_height = 0

            if not test_only:
                item.setGeometry(QRect(QPoint(x, y), hint))

            x += w + self._h
            line_height = max(line_height, h)

        return y + line_height - rect.y() + m.bottom()

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
# 2023年 - FimFiction第二届科幻小说征文比赛"委员会奖"（英文版）
# 3小时47分不但臻于剧情和文笔，而且其反映的内核深刻地讽刺了当下娱乐化的发展。
# 除此之外，本文中的部分情节精确反映了当下社会问题。作者也曾说，"本以为是寓言故事，后来才发现，原来是预言故事"。
# 这篇优秀的文章在 FimTale 上已被删除，可能是作者自删。但无论如何，我们都不可否认的是她的作品，和她真正臻于热爱的创作。
# 以及她本身。
# 谨以此，献给 Accurate_Balance 以及其对马圈不可磨灭的贡献。

# 如果你看到了这一段注释，那么也感谢你看完这一段对于理解代码并没有用的一大串文字。
# 祝您生活愉快！

def _make_placeholder() -> str:
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
        merged = roots + [x for x in defaults if x not in roots]
        pool = merged
    elif others:
        pool = others
    else:
        pool = defaults

    return f"例如：{random.choice(pool)}"

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

            title = TitleLabel(self)
            title.setText("打开新作品")
            self.addContent(title)

            desc = BodyLabel(self)
            desc.setText("输入 FimTale 帖子 ID，将加载对应内容。")
            desc.setWordWrap(True)
            self.addContent(desc)

            self.input = LineEdit(self)
            self.input.setPlaceholderText(_make_placeholder())
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


    class _FavoritesDialog(_FluentDialog):
        """我的收藏对话框"""

        def __init__(self, parent=None):
            super().__init__("我的收藏", parent)
            self.selected_topic_id = None

            title = TitleLabel(self)
            title.setText("我的收藏")
            self.addContent(title)

            desc = CaptionLabel(self)
            desc.setText("双击打开，右键移除。")
            self.addContent(desc)

            self.listWidget = ListWidget(self)
            self.listWidget.itemDoubleClicked.connect(self._on_double_click)
            self.listWidget.setContextMenuPolicy(Qt.CustomContextMenu)
            self.listWidget.customContextMenuRequested.connect(
                self._on_context_menu
            )
            self.addContent(self.listWidget)

            self.yesButton.setText("关闭")
            self.cancelButton.hide()
            self.yesButton.clicked.disconnect()
            self.yesButton.clicked.connect(self.close)

            self._reload()
            self.resize(520, 560)

        def _reload(self):
            self.listWidget.clear()
            items = favorites.list_all()
            if not items:
                item = QListWidgetItem("（还没有收藏）")
                item.setFlags(Qt.NoItemFlags)
                self.listWidget.addItem(item)
                return

            for it in items:
                text = it["title"] or f"Topic {it['id']}"
                if it["author"]:
                    text += f"  ·  {it['author']}"
                item = QListWidgetItem(text)
                item.setData(Qt.UserRole, it["id"])
                item.setToolTip(f"Topic ID: {it['id']}")
                self.listWidget.addItem(item)

        def _on_double_click(self, item):
            tid = item.data(Qt.UserRole)
            if tid is None:
                return
            self.selected_topic_id = int(tid)
            self.close()

        def _on_context_menu(self, pos):
            item = self.listWidget.itemAt(pos)
            if item is None:
                return
            tid = item.data(Qt.UserRole)
            if tid is None:
                return

            menu = RoundMenu(parent=self.listWidget)
            act_del = Action(FIF.DELETE, "从收藏中移除")
            act_del.triggered.connect(lambda: self._remove(tid))
            menu.addAction(act_del)
            menu.exec(self.listWidget.mapToGlobal(pos))

        def _remove(self, tid):
            favorites.remove(tid)
            self._reload()

class ReaderInterface(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("readerInterface")
        self._window: Optional[ReaderWindow] = None
        self._favDialog = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(36, 36, 36, 36)
        layout.setSpacing(12)

        titleRow = QHBoxLayout()
        titleRow.setSpacing(8)

        t = TitleLabel(self)
        t.setText("阅读器")
        titleRow.addWidget(t)
        titleRow.addStretch(1)

        self.favEntryBtn = TransparentToolButton(self)
        try:
            self.favEntryBtn.setIcon(FIF.HEART)
        except AttributeError:
            self.favEntryBtn.setIcon(FIF.BOOK_SHELF)
        self.favEntryBtn.setFixedSize(32, 32)
        self.favEntryBtn.setToolTip("我的收藏")
        self.favEntryBtn.installEventFilter(
            ToolTipFilter(self.favEntryBtn, showDelay=250,
                          position=ToolTipPosition.BOTTOM)
        )
        self.favEntryBtn.clicked.connect(self._open_favorites)
        titleRow.addWidget(self.favEntryBtn)

        layout.addLayout(titleRow)

        b = BodyLabel(self)
        b.setText("输入 FimTale 帖子 ID 打开新窗口，或从下方最近阅读中选择。")
        layout.addWidget(b)

        row = QHBoxLayout()
        self.input = LineEdit(self)
        self.input.setPlaceholderText(_make_placeholder())
        self.input.setClearButtonEnabled(True)
        self.input.returnPressed.connect(self._open_from_input)
        row.addWidget(self.input, 1)

        btn = PrimaryPushButton("打开", self)
        btn.clicked.connect(self._open_from_input)
        row.addWidget(btn)

        layout.addLayout(row)
        layout.addSpacing(12)

        self.recentLabel = BodyLabel(self)
        self.recentLabel.setText("最近阅读")
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

    def _open_favorites(self):
        if _FluentDialog is None:
            return

        if self._favDialog is not None:
            try:
                self._favDialog.raise_()
                self._favDialog.activateWindow()
                return
            except RuntimeError:
                self._favDialog = None

        dlg = _FavoritesDialog(parent=self)
        self._favDialog = dlg

        dlg.show()
        loop = QEventLoop()
        dlg.destroyed.connect(loop.quit)
        loop.exec()

        self._favDialog = None

        if dlg.selected_topic_id is not None:
            self._open_window(dlg.selected_topic_id)

    def showEvent(self, e):
        super().showEvent(e)
        self._refresh_recent()
        self.input.setPlaceholderText(_make_placeholder())

class ReaderWindow(FluentWindow):

    ROUTE_INTERACTIVE_PREFACE = "interactive_preface"
    ROUTE_INTERACTIVE_CHAPTER = "interactive_chapter"

    DEFAULT_FONT_SIZE = 15
    # 文字太长我是不加载的
    FADE_THRESHOLD = 10000
    # 单位：ms
    SLOW_LOAD_TIMEOUT = 15000

    def __init__(self, topic_id: int, parent=None):
        super().__init__(parent)
        self.topic_id = topic_id
        self.topic = None
        self._font_size = self.DEFAULT_FONT_SIZE
        self._chapter_items = []
        self._interactive_items = []
        self._last_chapter_id = None
        self._raw_md = ""
        self._raw_html = ""
        self._revealed_spoilers = set()

        self._nav_history: list = []
        self._suppress_crumb_signal = False

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

        self._resize_timer = QTimer(self)
        self._resize_timer.setSingleShot(True)
        self._resize_timer.setInterval(200)
        self._resize_timer.timeout.connect(self._on_resize_settled)

        self._height_sync_timer = QTimer(self)
        self._height_sync_timer.setSingleShot(True)
        self._height_sync_timer.setInterval(80)
        self._height_sync_timer.timeout.connect(self._sync_browser_height)

        self._slow_load_timer = QTimer(self)
        self._slow_load_timer.setSingleShot(True)
        self._slow_load_timer.timeout.connect(self._show_slow_hint)

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

        self.breadcrumbWrapper = QWidget(container)
        self.breadcrumbWrapper.setObjectName("breadcrumbWrapper")
        wrapperLayout = QHBoxLayout(self.breadcrumbWrapper)
        wrapperLayout.setContentsMargins(36, 10, 36, 10)
        wrapperLayout.setSpacing(0)

        self.breadcrumbBar = BreadcrumbBar(self.breadcrumbWrapper)
        self.breadcrumbBar.currentItemChanged.connect(self._on_crumb_changed)
        wrapperLayout.addWidget(self.breadcrumbBar)

        self.breadcrumbWrapper.hide()
        layout.addWidget(self.breadcrumbWrapper)

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
        self.browser.contextMenuRequested.connect(self._on_browser_context_menu)
        self.scrollArea.setWidget(self.browser)

        layout.addWidget(self.scrollArea, 1)

        self.browser.document().documentLayout().documentSizeChanged.connect(
            lambda: self._height_sync_timer.start()
        )
        self.scrollArea.verticalScrollBar().valueChanged.connect(self._on_scroll)

        self.branchPanel = QWidget(container)
        self.branchPanel.setObjectName("branchPanel")
        self.branchLayout = FlowLayout(
            self.branchPanel, margin=0, h_spacing=8, v_spacing=8
        )
        self.branchPanel.setContentsMargins(24, 10, 24, 10)
        self.branchPanel.hide()
        layout.addWidget(self.branchPanel)

        bottom = QWidget(container)
        bottom.setObjectName("readerBottom")
        bottom.setFixedHeight(44)
        bottom_layout = QHBoxLayout(bottom)
        bottom_layout.setContentsMargins(16, 6, 16, 6)
        bottom_layout.setSpacing(12)

        self.readingLabel = CaptionLabel(bottom)
        self.readingLabel.setText("阅读进度 0%")
        bottom_layout.addWidget(self.readingLabel)

        self.progressBar = ProgressBar(bottom)
        self.progressBar.setRange(0, 100)
        self.progressBar.setValue(0)
        self.progressBar.setFixedHeight(6)
        bottom_layout.addWidget(self.progressBar, 1)

        self.favBtn = TransparentToggleToolButton(bottom)
        try:
            self.favBtn.setIcon(FIF.HEART)
        except AttributeError:
            self.favBtn.setIcon(FIF.BOOK_SHELF)
        self.favBtn.setFixedSize(28, 28)
        self.favBtn.setCheckable(True)
        self.favBtn.setToolTip("收藏本文")
        self.favBtn.installEventFilter(
            ToolTipFilter(self.favBtn, showDelay=250,
                          position=ToolTipPosition.TOP)
        )
        self.favBtn.clicked.connect(self._on_toggle_favorite)
        bottom_layout.addWidget(self.favBtn)

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

    def closeEvent(self, e):
        app_state.clear_reader_topic(self)
        super().closeEvent(e)

    def _start_load(self, force_refresh: bool = False):
        self._set_loading(True)

        self._slow_load_timer.start(self.SLOW_LOAD_TIMEOUT)

        worker = LoadWorker(self.topic_id, force_refresh)
        worker.meta_ready.connect(self._on_meta_ready)
        worker.content_ready.connect(self._on_content_ready)
        worker.failed.connect(self._on_load_failed)
        self._worker = worker
        get_loader().submit(worker)

    def _on_meta_ready(self, topic_id: int, topic):
        self.topic = topic
        self.setWindowTitle(topic.title)

        root_id = topic.parent_id or topic.id
        if topic.id != root_id:
            self._last_chapter_id = topic.id

        self._rebuild_chapter_list()
        app_state.set_reader_topic(topic, self)

    def _on_content_ready(self, topic_id: int, topic):
        self._slow_load_timer.stop()
        self._render_content(topic)
        self._set_loading(False)
        self._refresh_interactive_ui()
        self._refresh_fav_button()

    def _on_load_failed(self, topic_id: int, msg: str):
        self._slow_load_timer.stop()
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

    def _show_slow_hint(self):
        """加载超过 SLOW_LOAD_TIMEOUT 还没完成，显示提示 + 重新加载入口"""
        if not self.loadingBar.isVisible():
            return

        if isDarkTheme():
            fg = "#e0e0e0"
            muted = "#888888"
        else:
            fg = "#1a1a1a"
            muted = "#666666"

        html = f"""
        <div style="text-align:center; margin-top:80px;">
            <h2 style="color:{fg};">加载时间较长…</h2>
            <p style="color:{muted};">请检查网络连接，或者稍后重试。</p>
            <p style="margin-top:24px;">
                <a href="reload:" style="color:#28afe9;
                   font-size:16px; text-decoration:none;">
                    [ 重新加载 ]
                </a>
            </p>
        </div>
        """
        self.browser.setHtml(html)
        self._sync_browser_height()

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
        self._nav_history.clear()
        self._last_chapter_id = None
        self._load_chapter(dlg.topic_id, push_history=False)

    def _is_interactive_topic(self) -> bool:
        if not self.topic:
            return False
        # 互动文，爽！
        return getattr(self.topic, "is_custom_branch", False)

    def _root_id(self) -> Optional[int]:
        if not self.topic:
            return None
        return self.topic.parent_id or self.topic.id

    def _clear_nav_items(self):
        for route in self._chapter_items:
            try:
                self.navigationInterface.removeWidget(route)
            except Exception:
                pass
        self._chapter_items = []

        for route in self._interactive_items:
            try:
                self.navigationInterface.removeWidget(route)
            except Exception:
                pass
        self._interactive_items = []

    def _rebuild_chapter_list(self):
        if not self.topic:
            return

        self._clear_nav_items()

        if self._is_interactive_topic():
            self._add_interactive_nav_items()
            return

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

    def _add_interactive_nav_items(self):
        root_id = self._root_id()
        if root_id is None:
            return

        self._interactive_items.append(self.ROUTE_INTERACTIVE_PREFACE)
        self.navigationInterface.addItem(
            routeKey=self.ROUTE_INTERACTIVE_PREFACE,
            icon=FIF.HOME,
            text="前言",
            onClick=lambda checked=False: self._go_to_root(),
            position=NavigationItemPosition.SCROLL,
            tooltip="作品前言",
        )

        self._interactive_items.append(self.ROUTE_INTERACTIVE_CHAPTER)
        self.navigationInterface.addItem(
            routeKey=self.ROUTE_INTERACTIVE_CHAPTER,
            icon=FIF.DOCUMENT,
            text="章节",
            onClick=lambda checked=False: self._go_to_last_chapter(),
            position=NavigationItemPosition.SCROLL,
            tooltip="当前章节",
        )

        self._highlight_interactive_nav()

    def _highlight_interactive_nav(self):
        root_id = self._root_id()
        if root_id is None:
            return
        is_preface = (self.topic.id == root_id)

        for route, should_select in (
            (self.ROUTE_INTERACTIVE_PREFACE, is_preface),
            (self.ROUTE_INTERACTIVE_CHAPTER, not is_preface),
        ):
            try:
                item = self.navigationInterface.widget(route)
                if item:
                    item.setSelected(should_select)
            except Exception:
                pass

    def _highlight_chapter(self, tid: int):
        target_route = f"chapter_{tid}"
        for route in self._chapter_items:
            try:
                item = self.navigationInterface.widget(route)
                if item:
                    item.setSelected(route == target_route)
            except Exception:
                pass

    def _load_chapter(self, topic_id: int, push_history: bool = True):
        if self.topic and topic_id == self.topic.id:
            return
        if push_history and self.topic:
            self._nav_history.append((self.topic.id, self.topic.title))
        self.topic_id = topic_id
        self._start_load()

    def _refresh_interactive_ui(self):
        self._render_breadcrumb()
        self._render_branches()

    @staticmethod
    def _short_title(title: str, n: int = 10) -> str:
        t = (title or "").strip()
        return t if len(t) <= n else t[:n - 1] + "…"

    def _render_breadcrumb(self):
        self._suppress_crumb_signal = True
        self.breadcrumbBar.clear()

        if not self._is_interactive_topic():
            self.breadcrumbWrapper.hide()
            self._suppress_crumb_signal = False
            return

        self.breadcrumbWrapper.show()

        root_id = self._root_id()

        in_history = any(tid == root_id for tid, _ in self._nav_history)
        if self.topic.id != root_id and not in_history:
            self.breadcrumbBar.addItem("__root__", "⟪ 从头开始")

        for tid, title in self._nav_history:
            self.breadcrumbBar.addItem(
                str(tid), self._short_title(title)
            )

        self.breadcrumbBar.addItem(
            str(self.topic.id), self._short_title(self.topic.title)
        )

        self._suppress_crumb_signal = False

    def _on_crumb_changed(self, route_key: str):
        if self._suppress_crumb_signal:
            return
        if not route_key:
            return

        if route_key == "__root__":
            self._go_to_root()
            return

        try:
            tid = int(route_key)
        except ValueError:
            return

        if self.topic and tid == self.topic.id:
            return

        for i, (h_tid, _) in enumerate(self._nav_history):
            if h_tid == tid:
                self._jump_to_history(i)
                return
            
    def _render_branches(self):
        while self.branchLayout.count():
            item = self.branchLayout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        if not self.topic:
            self.branchPanel.hide()
            return

        branches = getattr(self.topic, "branches", {}) or {}
        branches = {k: v for k, v in branches.items() if k != "下一章"}

        if not branches:
            self.branchPanel.hide()
            return

        self.branchPanel.show()

        for name, tid in branches.items():
            btn = PrimaryPushButton(name, self.branchPanel)
            btn.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
            btn.setMaximumWidth(360)
            btn.clicked.connect(
                lambda _, t=tid: self._load_chapter(t, push_history=True)
            )
            self.branchLayout.addWidget(btn)

        _fade_in(self.branchPanel, 150)

    def _go_to_root(self):
        root_id = self._root_id()
        if root_id is None:
            return
        self._nav_history.clear()
        self._load_chapter(root_id, push_history=False)

    def _go_to_last_chapter(self):
        root_id = self._root_id()
        if root_id is None:
            return
        if self.topic and self.topic.id != root_id:
            return
        if self._last_chapter_id and self._last_chapter_id != root_id:
            self._load_chapter(self._last_chapter_id, push_history=False)

    def _jump_to_history(self, idx: int):
        if idx < 0 or idx >= len(self._nav_history):
            return
        tid, _ = self._nav_history[idx]
        self._nav_history = self._nav_history[:idx]
        self._load_chapter(tid, push_history=False)

    def _current_root_info(self):
        if not self.topic:
            return None
        root_id = self.topic.parent_id or self.topic.id
        root_title = self.topic.parent_title or self.topic.title
        return (root_id, root_title or "", self.topic.author_name or "")

    def _refresh_fav_button(self):
        info = self._current_root_info()
        if info is None:
            self.favBtn.setEnabled(False)
            return

        root_id, _, _ = info
        is_fav = favorites.is_favorite(root_id)

        self.favBtn.blockSignals(True)
        self.favBtn.setChecked(is_fav)
        self.favBtn.blockSignals(False)

        self.favBtn.setToolTip(
            "已收藏（点击取消）" if is_fav else "收藏本文"
        )
        self.favBtn.setEnabled(True)

    def _on_toggle_favorite(self):
        info = self._current_root_info()
        if info is None:
            return

        root_id, title, author = info
        now_fav = self.favBtn.isChecked()

        if now_fav:
            favorites.add(root_id, title, author)
        else:
            favorites.remove(root_id)

        self.favBtn.setToolTip(
            "已收藏（点击取消）" if now_fav else "收藏本文"
        )

        if now_fav:
            InfoBar.success(
                "已收藏", title or f"#{root_id}",
                parent=self, position=InfoBarPosition.TOP, duration=1500,
            )
        else:
            InfoBar.info(
                "已取消收藏", title or f"#{root_id}",
                parent=self, position=InfoBarPosition.TOP, duration=1500,
            )

    def _toggle_favorite_by_menu(self, root_id: int):
        info = self._current_root_info()
        if info is None:
            return

        _, title, author = info
        now_fav = favorites.toggle(root_id, title, author)

        self._refresh_fav_button()

        if now_fav:
            InfoBar.success(
                "已收藏", title or f"#{root_id}",
                parent=self, position=InfoBarPosition.TOP, duration=1500,
            )
        else:
            InfoBar.info(
                "已取消收藏", title or f"#{root_id}",
                parent=self, position=InfoBarPosition.TOP, duration=1500,
            )

    def _on_browser_context_menu(self, local_pos, global_pos):
        cursor_click = self.browser.cursorForPosition(local_pos)
        cursor_current = self.browser.textCursor()

        menu = RoundMenu(parent=self.browser)

        in_selection = False
        if cursor_current.hasSelection():
            s = cursor_current.selectionStart()
            e = cursor_current.selectionEnd()
            in_selection = (s <= cursor_click.position() <= e)

        if in_selection:
            self._build_selection_menu(menu)
        else:
            anchor = self.browser.anchorAt(local_pos)
            if anchor and not anchor.startswith("spoiler:"):
                self._build_link_menu(menu, anchor)
            else:
                fmt = cursor_click.charFormat()
                if fmt.isImageFormat():
                    img_url = fmt.toImageFormat().name()
                    self._build_image_menu(menu, img_url)
                else:
                    self._build_blank_menu(menu)

        menu.exec(global_pos)

    def _build_selection_menu(self, menu: RoundMenu):
        act_copy = Action(FIF.COPY, "复制")
        act_copy.triggered.connect(self._copy_selection)
        menu.addAction(act_copy)

        menu.addSeparator()

        act_sel_all = Action(FIF.CHECKBOX, "全选")
        act_sel_all.triggered.connect(self.browser.selectAll)
        menu.addAction(act_sel_all)

    def _build_link_menu(self, menu: RoundMenu, url: str):
        is_fimtale = (
            url.startswith("https://fimtale.com/t/")
            or url.startswith("http://fimtale.com/t/")
        )

        if is_fimtale:
            act_open = Action(FIF.DOCUMENT, "在客户端中打开")
            act_open.triggered.connect(
                lambda: self._open_fimtale_link(url)
            )
            menu.addAction(act_open)
            menu.addSeparator()

        act_copy = Action(FIF.COPY, "复制链接")
        act_copy.triggered.connect(
            lambda: QApplication.clipboard().setText(url)
        )
        menu.addAction(act_copy)

        act_browser = Action(FIF.GLOBE, "在浏览器中打开")
        act_browser.triggered.connect(
            lambda: QDesktopServices.openUrl(QUrl(url))
        )
        menu.addAction(act_browser)

    def _build_image_menu(self, menu: RoundMenu, url: str):
        act_copy_img = Action(FIF.COPY, "复制图片")
        act_copy_img.triggered.connect(lambda: self._copy_image(url))
        menu.addAction(act_copy_img)

        act_copy_url = Action(FIF.LINK, "复制图片地址")
        act_copy_url.triggered.connect(
            lambda: QApplication.clipboard().setText(url)
        )
        menu.addAction(act_copy_url)

        menu.addSeparator()

        act_browser = Action(FIF.GLOBE, "在浏览器中查看原图")
        act_browser.triggered.connect(
            lambda: QDesktopServices.openUrl(QUrl(url))
        )
        menu.addAction(act_browser)

    def _build_blank_menu(self, menu: RoundMenu):
        act_top = Action(FIF.UP, "返回顶部")
        act_top.triggered.connect(self._scroll_to_top)
        menu.addAction(act_top)

        act_bottom = Action(FIF.DOWN, "前往底部")
        act_bottom.triggered.connect(self._scroll_to_bottom)
        menu.addAction(act_bottom)

        menu.addSeparator()

        act_zoom_in = Action(FIF.ZOOM_IN, "增大字号")
        act_zoom_in.triggered.connect(lambda: self._change_font(1))
        menu.addAction(act_zoom_in)

        act_zoom_out = Action(FIF.ZOOM_OUT, "减小字号")
        act_zoom_out.triggered.connect(lambda: self._change_font(-1))
        menu.addAction(act_zoom_out)

        act_zoom_reset = Action(FIF.ZOOM, "重置字号")
        act_zoom_reset.triggered.connect(self._reset_font)
        menu.addAction(act_zoom_reset)

        menu.addSeparator()

        info = self._current_root_info()
        if info is not None:
            root_id, _, _ = info
            is_fav = favorites.is_favorite(root_id)

            if is_fav:
                act_fav = Action(FIF.HEART, "取消收藏")
                act_fav.triggered.connect(
                    lambda: self._toggle_favorite_by_menu(root_id)
                )
            else:
                act_fav = Action(FIF.HEART, "收藏本文")
                act_fav.triggered.connect(
                    lambda: self._toggle_favorite_by_menu(root_id)
                )

            menu.addAction(act_fav)
            menu.addSeparator()

        act_refresh = Action(FIF.SYNC, "刷新本文")
        act_refresh.triggered.connect(self._on_refresh_clicked)
        menu.addAction(act_refresh)

    def _copy_selection(self):
        c = self.browser.textCursor()
        if c.hasSelection():
            QApplication.clipboard().setText(c.selectedText())

    def _copy_image(self, url: str):
        data = cache.read_image(url)
        if data is None:
            InfoBar.warning(
                "未缓存", "图片尚未下载完成或未缓存到本地",
                parent=self, position=InfoBarPosition.TOP, duration=2000,
            )
            return

        img = QImage()
        img.loadFromData(data)
        if img.isNull():
            InfoBar.error(
                "加载失败", "图片数据无法解析",
                parent=self, position=InfoBarPosition.TOP, duration=2000,
            )
            return

        QApplication.clipboard().setImage(img)
        InfoBar.success(
            "已复制", "图片已复制到剪贴板",
            parent=self, position=InfoBarPosition.TOP, duration=1500,
        )

    def _open_fimtale_link(self, url: str):
        try:
            tid = int(url.rstrip("/").split("/")[-1])
        except ValueError:
            return
        self._load_chapter(tid)

    def _scroll_to_top(self):
        self.scrollArea.verticalScrollBar().setValue(0)

    def _scroll_to_bottom(self):
        sb = self.scrollArea.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _reset_font(self):
        if self._font_size == self.DEFAULT_FONT_SIZE:
            return
        self._font_size = self.DEFAULT_FONT_SIZE
        self._apply_theme()
        if self._raw_md:
            self._rerender()

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

        if len(self._raw_md) < self.FADE_THRESHOLD:
            _fade_in(self.browser.viewport(), 200)

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

        if u == "reload:":
            self._start_load()
            return

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

        if u.startswith('/') and not u.startswith('//'):
            u = 'https://fimtale.com' + u

        if (u.startswith("https://fimtale.com/t/")
                or u.startswith("http://fimtale.com/t/")):
            try:
                tid = int(u.rstrip("/").split("/")[-1])
                self._load_chapter(tid)
                return
            except ValueError:
                pass

        QDesktopServices.openUrl(QUrl(u))

    def _apply_theme(self):
        if isDarkTheme():
            bg, fg = "#1e1e1e", "#e0e0e0"
            code_bg = "#2a2a2a"
            quote_color = "#aaa"
        else:
            bg, fg = "#fafafa", "#1a1a1a"
            code_bg = "#f0f0f0"
            quote_color = "#555"

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
        """)

        self.browser.document().setDefaultStyleSheet(f"""
            blockquote {{
                margin-left: 14px;
                color: {quote_color};
            }}
            pre.code-block {{
                background-color: {code_bg};
                padding: 8px;
                font-family: Consolas, monospace;
            }}
            code {{
                background-color: {code_bg};
                padding: 1px 4px;
                font-family: Consolas, monospace;
            }}
        """)

        self.scrollArea.setStyleSheet(f"""
            SmoothScrollArea#readerScroll {{
                background-color: {bg};
                border: none;
            }}
        """)

        if hasattr(self, "breadcrumbWrapper"):
            self.breadcrumbWrapper.setStyleSheet(f"""
                QWidget#breadcrumbWrapper {{
                    background-color: {bg};
                }}
            """)

        if hasattr(self, "breadcrumbBar"):
            self.breadcrumbBar.setStyleSheet(f"""
                BreadcrumbBar {{
                    background-color: transparent;
                    font-size: 13px;
                }}
                BreadcrumbBar QLabel {{
                    font-size: 13px;
                }}
            """)

        if self._raw_md:
            self._rerender()