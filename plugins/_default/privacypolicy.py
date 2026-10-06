import os
import re
import sys
from PySide6.QtCore import Qt, QTimer, QEventLoop, Signal, QPoint
from PySide6.QtGui import QColor, QGuiApplication
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
)
from qfluentwidgets import (
    FluentIcon, TitleLabel, BodyLabel,
    PushButton, PrimaryPushButton,
    SegmentedWidget, PivotItem,
    CaptionLabel,
    SmoothScrollArea, SmoothMode,
    RoundMenu, Action, FluentIcon as FIF,
    isDarkTheme, qconfig,
)
from qframelesswindow import FramelessWindow
from base_plugin import BasePlugin
from toolmethods import resource_path, log_info, log_success, log_error, \
    get_json_info, set_json_info

_VERSION_RE = re.compile(r'版本[：:]\s*([0-9]+(?:\.[0-9]+)*)')


def _read_file_version(path: str) -> str:
    try:
        with open(path, 'r', encoding='utf-8') as f:
            head = f.read(2048)
    except OSError:
        return '0'
    m = _VERSION_RE.search(head)
    return m.group(1) if m else '0'


def _privacy_version() -> str:
    return _read_file_version(
        resource_path('content/_default/privacypolicy.txt')
    )


def _tos_version() -> str:
    return _read_file_version(
        resource_path('content/_default/user_agreement.txt')
    )


def _combined_version() -> str:
    return f"ToS-{_tos_version()}|Privacy-{_privacy_version()}"


def _version_needs_reconfirm(read_version: str, current_version: str) -> bool:
    if not read_version:
        return True
    if read_version != current_version:
        return True
    return False

class PolicyTextLabel(QLabel):
    """支持 Fluent 风格右键菜单的文本标签"""

    def __init__(self, text: str = "", parent=None):
        super().__init__(text, parent)
        self.setWordWrap(True)
        self.setTextInteractionFlags(
            Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard
        )
        self.setContentsMargins(12, 12, 12, 12)
        self.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.setObjectName("policyText")
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)

    def _show_context_menu(self, pos: QPoint):
        menu = RoundMenu(parent=self)

        has_selection = bool(self.selectedText())
        copyAction = Action(FIF.COPY, "复制")
        copyAction.setEnabled(has_selection)
        copyAction.triggered.connect(self._copy_selection)
        menu.addAction(copyAction)

        selectAllAction = Action(FIF.CHECKBOX, "全选")
        selectAllAction.triggered.connect(self._select_all)
        menu.addAction(selectAllAction)

        menu.exec(self.mapToGlobal(pos))

    def _copy_selection(self):
        text = self.selectedText()
        if text:
            QGuiApplication.clipboard().setText(text)

    def _select_all(self):
        self.setSelection(0, len(self.text()))

class PrivacyPolicyDialog(FramelessWindow):

    COUNTDOWN_SECONDS = 30

    closed = Signal(bool)

    def __init__(self, parent=None):
        super().__init__()
        self.titleBar.minBtn.hide()
        self.titleBar.maxBtn.hide()
        self.titleBar.setDoubleClickEnabled(False)
        self.setWindowTitle('用户协议与隐私政策')
        self.setObjectName("PrivacyPolicyDialog")
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        if parent is not None:
            top = parent.window() if isinstance(parent, QWidget) else None
            target = top if top is not None else parent
            self.setParent(target, Qt.Dialog)

        self.accepted = False
        self._remaining = self.COUNTDOWN_SECONDS

        self._build_ui()
        self._apply_theme()
        qconfig.themeChanged.connect(self._apply_theme)

        self._load_contents()

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(1000)

        self.resize(760, 660)

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 48, 0, 0)
        root.setSpacing(0)

        content = QWidget(self)
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(28, 12, 28, 20)
        content_layout.setSpacing(12)
        root.addWidget(content)

        title = TitleLabel('用户协议与隐私政策', self)
        content_layout.addWidget(title)

        hint = BodyLabel(
            '请您仔细阅读以下两份文件。只有在完整阅读后，'
            '您才能自愿确认并进入登录界面。',
            self,
        )
        hint.setWordWrap(True)
        content_layout.addWidget(hint)

        self.segmented = SegmentedWidget(self)
        self.segmented.addWidget(
            "tos",
            PivotItem("用户协议", self),
            onClick=lambda: self._switch_tab("tos"),
        )
        self.segmented.addWidget(
            "privacy",
            PivotItem("隐私政策", self),
            onClick=lambda: self._switch_tab("privacy"),
        )
        content_layout.addWidget(self.segmented)

        self.tosView = self._make_text_view(self)
        content_layout.addWidget(self.tosView, 1)

        self.privacyView = self._make_text_view(self)
        self.privacyView.hide()
        content_layout.addWidget(self.privacyView, 1)

        self.segmented.setCurrentItem("tos")

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)

        self.quitButton = PushButton('不同意，退出', self)
        self.quitButton.clicked.connect(self._on_quit)
        btn_row.addWidget(self.quitButton)

        self.agreeButton = PrimaryPushButton(
            f'我已知悉并同意上述条款中的所有内容（{self.COUNTDOWN_SECONDS}）', self
        )
        self.agreeButton.setEnabled(False)
        self.agreeButton.clicked.connect(self._on_agree)
        btn_row.addWidget(self.agreeButton)

        content_layout.addLayout(btn_row)

    def _make_text_view(self, parent) -> SmoothScrollArea:
        scroll = SmoothScrollArea(parent)
        scroll.setObjectName("policyScroll")
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setFrameShape(SmoothScrollArea.NoFrame)
        try:
            scroll.setSmoothMode(SmoothMode.NO_SMOOTH)
        except Exception:
            pass

        label = PolicyTextLabel("", scroll)
        scroll.setWidget(label)

        try:
            scroll.enableTransparentBackground()
        except Exception:
            pass

        return scroll

    def _switch_tab(self, key: str):
        if key == "tos":
            self.tosView.show()
            self.privacyView.hide()
        else:
            self.privacyView.show()
            self.tosView.hide()

    def _load_contents(self):
        path = resource_path('content/_default/user_agreement.txt')
        try:
            with open(path, 'r', encoding='utf-8') as f:
                text = f.read()
        except OSError:
            text = f'[错误] 找不到用户协议文件:\n{path}'
            log_error(f'[Privacy] 找不到用户协议: {path}')
        self.tosView.widget().setText(text)

        path = resource_path('content/_default/privacypolicy.txt')
        try:
            with open(path, 'r', encoding='utf-8') as f:
                text = f.read()
        except OSError:
            text = f'[错误] 找不到隐私政策文件:\n{path}'
            log_error(f'[Privacy] 找不到隐私政策: {path}')
        self.privacyView.widget().setText(text)

    def _tick(self):
        self._remaining -= 1
        if self._remaining > 0:
            self.agreeButton.setText(f'请阅读（{self._remaining}）')
        else:
            self._timer.stop()
            self.agreeButton.setText('同意并继续')
            self.agreeButton.setEnabled(True)
            log_info('[Privacy] 倒计时结束，允许同意')

    def _on_agree(self):
        self.accepted = True
        self.close()

    def _on_quit(self):
        self.accepted = False
        self.close()

    def _apply_theme(self):
        if isDarkTheme():
            bg = "#202020"
            fg = "#e0e0e0"
            border = "#555555"
            btn_normal = QColor(255, 255, 255)
            btn_hover_bg = QColor(255, 255, 255, 30)
            btn_pressed_bg = QColor(255, 255, 255, 50)
        else:
            bg = "#f5f5f5"
            fg = "#1a1a1a"
            border = "#cccccc"
            btn_normal = QColor(0, 0, 0)
            btn_hover_bg = QColor(0, 0, 0, 15)
            btn_pressed_bg = QColor(0, 0, 0, 30)

        self.setStyleSheet(f"""
            #PrivacyPolicyDialog {{ background-color: {bg}; }}
            #PrivacyPolicyDialog QWidget {{ color: {fg}; }}

            #PrivacyPolicyDialog SmoothScrollArea#policyScroll {{
                background-color: transparent;
                border: 1px solid {border};
                border-radius: 6px;
            }}

            #PrivacyPolicyDialog QLabel#policyText {{
                background-color: transparent;
                color: {fg};
                font-family: 'Microsoft YaHei', 'Consolas', monospace;
                font-size: 13px;
                line-height: 1.7;
            }}
        """)

        if hasattr(self, 'titleBar'):
            try:
                self.titleBar.titleLabel.setTextColor(
                    QColor(0, 0, 0), QColor(255, 255, 255),
                )
            except AttributeError:
                pass
            for btn in (self.titleBar.minBtn,
                        self.titleBar.maxBtn,
                        self.titleBar.closeBtn):
                try:
                    btn.setNormalColor(btn_normal)
                    btn.setHoverColor(btn_normal)
                    btn.setPressedColor(btn_normal)
                    btn.setNormalBackgroundColor(QColor(0, 0, 0, 0))
                    btn.setHoverBackgroundColor(btn_hover_bg)
                    btn.setPressedBackgroundColor(btn_pressed_bg)
                except AttributeError:
                    pass

    def showEvent(self, e):
        super().showEvent(e)
        self.raise_()
        self.activateWindow()
        p = self.parent()
        if isinstance(p, QWidget) and p.isVisible():
            self.move(
                p.x() + (p.width() - self.width()) // 2,
                p.y() + (p.height() - self.height()) // 2,
            )
        else:
            screen = QApplication.primaryScreen().availableGeometry()
            self.move(
                screen.center().x() - self.width() // 2,
                screen.center().y() - self.height() // 2,
            )

    def closeEvent(self, e):
        if hasattr(self, '_timer') and self._timer.isActive():
            self._timer.stop()
        self.closed.emit(self.accepted)
        super().closeEvent(e)

class PrivacyPolicyPlugin(BasePlugin):

    def __init__(self, plugin_path=""):
        super().__init__(plugin_path)
        self.plugin_id = "隐私政策"
        self.plugin_types = []
        self.icon = FluentIcon.INFO

    def show_policy(self, parent=None) -> bool:
        current_version = _combined_version()
        read_version = get_json_info("privacy_policy_read_version", "")

        if not _version_needs_reconfirm(read_version, current_version):
            log_info(f"[Privacy] 已同意 {read_version}，跳过")
            return True

        if read_version:
            log_info(f"[Privacy] 版本变更: {read_version} -> {current_version}")

        dlg = PrivacyPolicyDialog(parent=parent)
        result = [False]
        loop = QEventLoop()

        def on_closed(accepted):
            result[0] = accepted
            if accepted:
                set_json_info("privacy_policy_read_version", current_version)
                log_success(f"[Privacy] 用户已同意 {current_version}")
            else:
                log_info("[Privacy] 用户拒绝")
            loop.quit()

        dlg.closed.connect(on_closed)
        dlg.show()
        loop.exec()
        return result[0]