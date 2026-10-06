import sys
import os
import time
import ctypes
import random
import hashlib
import requests
import qrcode
from io import BytesIO
from collections import deque
from toolmethods import (
    resource_path, log_info, log_success, log_warning, log_error, log_debug,
    list_removable_drives, get_usb_id, get_volume_label,
)

from PySide6.QtCore import (
    Qt, QEventLoop, QTimer, QCoreApplication, QMetaObject, QSize,
    QRegularExpression
)
from PySide6.QtGui import (
    QIcon, QPixmap, QPainter, QRegularExpressionValidator, QColor
)
from PySide6.QtWidgets import (
    QApplication, QWidget, QLabel, QLineEdit, QHBoxLayout, QVBoxLayout,
    QGridLayout, QSpacerItem, QSizePolicy
)
from qfluentwidgets import (
    FluentWidget, setThemeColor, InfoBar, InfoBarPosition,
    BodyLabel, CheckBox, HyperlinkButton, LineEdit, PrimaryPushButton,
    ComboBox, TitleLabel, SubtitleLabel,
    ProgressBar, PushButton, setCustomStyleSheet,
    FluentIcon, TransparentToolButton, ToolTipFilter, ToolTipPosition,
    isDarkTheme, qconfig
)
from qframelesswindow import FramelessWindow
from base_plugin import BasePlugin

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
from login_questions import get_questions, check_answer

try:
    import win32crypt
    _HAS_DPAPI = True
except ImportError:
    _HAS_DPAPI = False

try:
    import pyotp
    _HAS_TOTP = True
except ImportError:
    _HAS_TOTP = False


class LoginConfig:
    CRED_DIR = os.path.join(os.getenv('APPDATA', os.path.expanduser('~')), 'FimtaleClient')
    CRED_FILE = 'credentials.dat'

    MAX_ATTEMPTS = 5
    ATTEMPT_WINDOW = 900
    LOCK_DURATION = 300

    RISK_LEVELS = [
        (20,  'normal',  0,  0, False),
        (40,  'low',     3,  2, False),
        (60,  'medium',  5,  3, False),
        (80,  'high',    8,  5, False),
        (100, 'extreme', 12, 8, False),
    ]

    TOTP_PROBABILITY = {
        'normal':  0.00,
        'low':     0.05,
        'medium':  0.15,
        'high':    0.40,
        'extreme': 1.00,
    }

    API_BASE = None
    ENABLE_SERVER = False

    DEBUG_FORCE_SCORE = int(os.getenv('FT_DEBUG_SCORE', '0')) or None

    API_KEY_LEN = 8
    API_PASS_LEN = 12
    API_KEY_RE = r"[A-Za-z0-9]{8}"
    API_PASS_RE = r"[A-Za-z0-9]{12}"

    AUTO_LOGIN_DAYS = 7
    AUTO_LOGIN_MAX_RISK = 20


class CredentialStore:
    def __init__(self):
        try:
            os.makedirs(LoginConfig.CRED_DIR, exist_ok=True)
        except OSError:
            pass
        self.path = os.path.join(LoginConfig.CRED_DIR, LoginConfig.CRED_FILE)

    def save(self, api_key: str, api_pass: str,
             totp_secret: str = "", usb_id: str = "",
             last_verified: float = 0.0,
             auto_login: bool = False) -> bool:
        if not _HAS_DPAPI:
            return False
        import pickle
        blob = None
        try:
            blob = pickle.dumps({
                'api_key': api_key,
                'api_pass': api_pass,
                'totp_secret': totp_secret,
                'usb_id': usb_id,
                'last_verified': last_verified,
                'auto_login': auto_login,
            })
            encrypted = win32crypt.CryptProtectData(blob, None, None, None, None, 0)
            with open(self.path, 'wb') as f:
                f.write(encrypted)
            return True
        except Exception:
            return False
        finally:
            if blob is not None:
                try:
                    blob = b'\x00' * len(blob)
                except Exception:
                    pass

    def load(self):
        if not _HAS_DPAPI or not os.path.exists(self.path):
            return None
        import pickle
        try:
            with open(self.path, 'rb') as f:
                encrypted = f.read()
            _, blob = win32crypt.CryptUnprotectData(encrypted, None, None, None, 0)
            data = pickle.loads(blob)
            if isinstance(data, tuple):
                return {
                    'api_key': data[0],
                    'api_pass': data[1],
                    'totp_secret': '',
                    'usb_id': '',
                    'last_verified': 0.0,
                    'auto_login': False,
                }
            data.setdefault('usb_id', '')
            data.setdefault('last_verified', 0.0)
            data.setdefault('auto_login', False)
            return data
        except Exception:
            return None

    def clear(self):
        if os.path.exists(self.path):
            try:
                os.remove(self.path)
            except OSError:
                pass

    def set_totp(self, secret: str) -> bool:
        cred = self.load()
        if not cred:
            return False
        return self.save(
            cred.get('api_key', ''),
            cred.get('api_pass', ''),
            secret,
            cred.get('usb_id', ''),
            cred.get('last_verified', 0.0),
            cred.get('auto_login', False),
        )

    def clear_totp(self) -> bool:
        cred = self.load()
        if not cred:
            return False
        return self.save(
            cred.get('api_key', ''),
            cred.get('api_pass', ''),
            '',
            cred.get('usb_id', ''),
            cred.get('last_verified', 0.0),
            cred.get('auto_login', False),
        )

    def set_usb(self, usb_id: str) -> bool:
        cred = self.load()
        if not cred:
            return False
        return self.save(
            cred.get('api_key', ''),
            cred.get('api_pass', ''),
            cred.get('totp_secret', ''),
            usb_id,
            cred.get('last_verified', 0.0),
            cred.get('auto_login', False),
        )

    def clear_usb(self) -> bool:
        return self.set_usb('')


class RateLimiter:
    def __init__(self):
        self._attempts = deque(maxlen=LoginConfig.MAX_ATTEMPTS)
        self._lock_until = 0.0

    def check(self):
        now = time.time()
        if now < self._lock_until:
            return False, int(self._lock_until - now)

        while self._attempts and now - self._attempts[0] > LoginConfig.ATTEMPT_WINDOW:
            self._attempts.popleft()

        if len(self._attempts) >= LoginConfig.MAX_ATTEMPTS:
            self._lock_until = now + LoginConfig.LOCK_DURATION
            return False, LoginConfig.LOCK_DURATION

        return True, 0

    def record_failure(self):
        self._attempts.append(time.time())

    def reset(self):
        self._attempts.clear()
        self._lock_until = 0.0


class RiskEvaluator:
    def __init__(self):
        self.fingerprint = self._collect_fingerprint()

    def _collect_fingerprint(self) -> dict:
        fp = {
            'hostname': os.environ.get('COMPUTERNAME', ''),
            'vm_detected': self._detect_vm(),
            'screen': self._get_screen_info(),
            'uptime_minutes': self._get_uptime_minutes(),
            'install_age_days': self._get_install_age_days(),
            'total_ram_gb': self._get_total_ram_gb(),
            'cpu_cores': os.cpu_count() or 1,
            'system_drive_free_gb': self._get_system_drive_free_gb(),
            'timezone': self._get_timezone(),
            'language': self._get_language(),
        }
        fp['hash'] = hashlib.sha256(
            repr(sorted(fp.items())).encode()
        ).hexdigest()
        return fp

    def _detect_vm(self) -> bool:
        import winreg
        try:
            k = winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r'SYSTEM\CurrentControlSet\Control\SystemInformation'
            )
            v, _ = winreg.QueryValueEx(k, 'SystemManufacturer')
            winreg.CloseKey(k)
            return any(s in v.lower() for s in
                       ('vmware', 'virtualbox', 'qemu', 'xen'))
        except Exception:
            return False

    def _get_screen_info(self) -> dict:
        try:
            from PySide6.QtWidgets import QApplication
            app = QApplication.instance()
            if app is None:
                return {'width': 0, 'height': 0, 'count': 0, 'dpi': 0}
            screens = app.screens()
            if not screens:
                return {'width': 0, 'height': 0, 'count': 0, 'dpi': 0}
            primary = app.primaryScreen()
            geo = primary.geometry()
            return {
                'width': geo.width(),
                'height': geo.height(),
                'count': len(screens),
                'dpi': int(primary.logicalDotsPerInch()),
            }
        except Exception:
            return {'width': 0, 'height': 0, 'count': 0, 'dpi': 0}

    def _get_uptime_minutes(self) -> int:
        try:
            return int(ctypes.windll.kernel32.GetTickCount64() / 60000)
        except Exception:
            return 0

    def _get_install_age_days(self) -> int:
        import winreg
        try:
            k = winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r'SOFTWARE\Microsoft\Windows NT\CurrentVersion'
            )
            install_ts, _ = winreg.QueryValueEx(k, 'InstallDate')
            winreg.CloseKey(k)
            return int((time.time() - install_ts) / 86400)
        except Exception:
            return 0

    def _get_total_ram_gb(self) -> float:
        try:
            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [
                    ('dwLength', ctypes.c_ulong),
                    ('dwMemoryLoad', ctypes.c_ulong),
                    ('ullTotalPhys', ctypes.c_ulonglong),
                    ('ullAvailPhys', ctypes.c_ulonglong),
                    ('ullTotalPageFile', ctypes.c_ulonglong),
                    ('ullAvailPageFile', ctypes.c_ulonglong),
                    ('ullTotalVirtual', ctypes.c_ulonglong),
                    ('ullAvailVirtual', ctypes.c_ulonglong),
                    ('ullAvailExtendedVirtual', ctypes.c_ulonglong),
                ]
            stat = MEMORYSTATUSEX()
            stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))
            return round(stat.ullTotalPhys / (1024 ** 3), 1)
        except Exception:
            return 0.0

    def _get_system_drive_free_gb(self) -> float:
        try:
            import shutil
            _, _, free = shutil.disk_usage('C:\\')
            return round(free / (1024 ** 3), 1)
        except Exception:
            return 0.0

    def _get_timezone(self) -> str:
        import winreg
        try:
            k = winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r'SYSTEM\CurrentControlSet\Control\TimeZoneInformation'
            )
            v, _ = winreg.QueryValueEx(k, 'TimeZoneKeyName')
            winreg.CloseKey(k)
            return v
        except Exception:
            return ''

    def _get_language(self) -> str:
        try:
            lang_id = ctypes.windll.kernel32.GetUserDefaultUILanguage()
            return 'zh-CN' if lang_id == 0x0804 else f'0x{lang_id:04X}'
        except Exception:
            return ''

    def evaluate(self, api_key: str):
        if LoginConfig.DEBUG_FORCE_SCORE is not None:
            s = LoginConfig.DEBUG_FORCE_SCORE
            return s, {'debug': f'强制评分 {s}'}

        if LoginConfig.ENABLE_SERVER and LoginConfig.API_BASE:
            return self._evaluate_server(api_key)
        return self._evaluate_local(api_key)

    def _evaluate_local(self, api_key: str):
        score = 10
        detail = {}

        fp = self.fingerprint

        if fp['vm_detected']:
            score += 20
            detail['vm'] = '检测到虚拟机环境'

        screen = fp['screen']
        if screen['count'] == 0:
            score += 15
            detail['no_display'] = '未检测到显示器'
        elif screen['width'] < 1280 or screen['height'] < 720:
            score += 10
            detail['low_res'] = f"分辨率偏低: {screen['width']}×{screen['height']}"

        if fp['uptime_minutes'] < 30:
            score += 10
            detail['uptime'] = f"系统运行时长过短: {fp['uptime_minutes']} 分钟"

        if 0 < fp['install_age_days'] < 7:
            score += 10
            detail['install_age'] = f"系统安装时间过短: {fp['install_age_days']} 天"

        if 0 < fp['total_ram_gb'] < 4:
            score += 10
            detail['ram'] = f"内存偏低: {fp['total_ram_gb']} GB"

        if fp['cpu_cores'] < 2:
            score += 5
            detail['cpu'] = f"CPU 核心数: {fp['cpu_cores']}"

        if 0 < fp['system_drive_free_gb'] < 10:
            score += 5
            detail['disk'] = f"C 盘剩余空间不足: {fp['system_drive_free_gb']} GB"

        hostname = fp['hostname'].upper()
        if (hostname.startswith('VM-')
                or 'VIRTUAL' in hostname):
            score += 10
            detail['hostname'] = f"计算机名疑似默认: {fp['hostname']}"

        if fp['timezone'] != 'China Standard Time':
            score += 15
            detail['timezone'] = f"时区异常: {fp['timezone']}"

        if fp['language'] != 'zh-CN':
            score += 10
            detail['language'] = f"语言异常: {fp['language']}"

        return min(score, 100), detail

    def _evaluate_server(self, api_key: str):
        return self._evaluate_local(api_key)


class _FluentDialog(FramelessWindow):
    def __init__(self, title: str, parent=None):
        super().__init__()
        self.setWindowTitle(title)
        self.setObjectName("FluentDialog")

        self.setAttribute(Qt.WA_StyledBackground, True)

        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        if parent is not None:
            top = parent.window() if isinstance(parent, QWidget) else None
            target = top if top is not None else parent
            self.setParent(target, Qt.Dialog)

        self.setAttribute(Qt.WA_DeleteOnClose, True)
        self.titleBar.setDoubleClickEnabled(False)

        if hasattr(self.titleBar, 'minBtn'):
            self.titleBar.minBtn.hide()
        if hasattr(self.titleBar, 'maxBtn'):
            self.titleBar.maxBtn.hide()

        self.passed = False
        self._build_base()
        self._apply_dialog_theme()
        qconfig.themeChanged.connect(self._apply_dialog_theme)

    def _build_base(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 48, 0, 0)
        root.setSpacing(0)

        self.content = QWidget(self)
        self.content.setObjectName("dialogContent")
        self.content.setAttribute(Qt.WA_StyledBackground, True)
        self.contentLayout = QVBoxLayout(self.content)
        self.contentLayout.setContentsMargins(28, 12, 28, 20)
        self.contentLayout.setSpacing(12)
        root.addWidget(self.content)

        self.buttonLayout = QHBoxLayout()
        self.buttonLayout.setSpacing(10)
        self.buttonLayout.addStretch(1)

        self.cancelButton = PushButton('取消', self)
        self.yesButton = PrimaryPushButton('确定', self)
        self.buttonLayout.addWidget(self.cancelButton)
        self.buttonLayout.addWidget(self.yesButton)

        self.contentLayout.addStretch(1)
        self.contentLayout.addLayout(self.buttonLayout)

        self.yesButton.clicked.connect(self._on_yes)
        self.cancelButton.clicked.connect(self._on_cancel)

    def addContent(self, widget):
        idx = self.contentLayout.count() - 2
        self.contentLayout.insertWidget(idx, widget)

    def validate(self) -> bool:
        return True

    def _on_yes(self):
        if self.validate():
            self.passed = True
            self.close()

    def _on_cancel(self):
        self.passed = False
        self.close()

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

    def _apply_dialog_theme(self):
        if isDarkTheme():
            bg = "#202020"
            fg = "#e0e0e0"
            btn_normal = QColor(255, 255, 255)
            btn_hover_bg = QColor(255, 255, 255, 30)
            btn_pressed_bg = QColor(255, 255, 255, 50)
        else:
            bg = "#f5f5f5"
            fg = "#1a1a1a"
            btn_normal = QColor(0, 0, 0)
            btn_hover_bg = QColor(0, 0, 0, 15)
            btn_pressed_bg = QColor(0, 0, 0, 30)

        self.setStyleSheet(f"""
            #FluentDialog, #dialogContent {{
                background-color: {bg};
                color: {fg};
            }}
        """)

        if hasattr(self, 'titleBar'):
            try:
                self.titleBar.titleLabel.setTextColor(
                    QColor(0, 0, 0), QColor(255, 255, 255),
                )
            except AttributeError:
                pass

            for btn in (self.titleBar.minBtn, self.titleBar.maxBtn):
                try:
                    btn.setNormalColor(btn_normal)
                    btn.setHoverColor(btn_normal)
                    btn.setPressedColor(btn_normal)
                    btn.setNormalBackgroundColor(QColor(0, 0, 0, 0))
                    btn.setHoverBackgroundColor(btn_hover_bg)
                    btn.setPressedBackgroundColor(btn_pressed_bg)
                except AttributeError:
                    pass

            try:
                self.titleBar.closeBtn.setNormalColor(btn_normal)
            except AttributeError:
                pass


class EquestrianTestDialog(_FluentDialog):

    DEMO_QUESTION = (
        "本题是一道示例题，请回答“友谊是魔法”，不计分。\n"
        "需要注意的是，在回答中，不要包括额外的内容，"
        "如语气词、标点符号等，这可能会影响得分，导致误判。",
        ["“友谊是魔法”", "友谊是魔法",
         "答“友谊是魔法”", "答“友谊是魔法”，不计分。"],
    )

    _DESC_DEMO = (
        '我们认为您可能是幻形灵。\n'
        '请完成以下测试，以证明您是真正的小马。\n'
        '不过需要注意的是，在回答过程中，请不要包含多余的标点符号、'
        '语气词、连词等，这可能会影响计分导致误判。\n'
        '第一道题是示例题，不进行计分。'
    )

    _DESC_NORMAL = (
        '我们认为您可能是幻形灵。\n'
        '请完成以下测试，以证明您是真正的小马。'
    )

    def __init__(self, risk_score: int, level: str,
                 total: int, need: int, parent=None):
        super().__init__('幻形灵验证', parent)
        self.total = total
        self.need = need
        self.level = level
        self._current = -1
        self._correct = 0
        self._risk_score = risk_score
        self._current_question_raw = ''

        self.questions = get_questions(level, total)

        self._build_ui()
        self._show_question()
        self.resize(700, 460)

    def _build_ui(self):
        title = TitleLabel('幻形灵验证', self)
        self.addContent(title)

        self.descLabel = BodyLabel('', self)
        self.descLabel.setWordWrap(True)
        self.addContent(self.descLabel)

        self.progressBar = ProgressBar(self)
        self.progressBar.setRange(0, self.total)
        self.progressBar.setValue(0)
        self.addContent(self.progressBar)

        self.indexLabel = BodyLabel('', self)
        self.addContent(self.indexLabel)

        question_row = QWidget(self)
        row_layout = QHBoxLayout(question_row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(8)

        self.questionLabel = SubtitleLabel('', question_row)
        self.questionLabel.setWordWrap(True)
        row_layout.addWidget(self.questionLabel, 1)

        self.copyButton = TransparentToolButton(FluentIcon.COPY, question_row)
        self.copyButton.setFixedSize(28, 28)
        self.copyButton.setToolTip('复制题干')
        self.copyButton.installEventFilter(
            ToolTipFilter(self.copyButton, showDelay=250, position=ToolTipPosition.TOP)
        )
        self.copyButton.clicked.connect(self._copy_question)
        row_layout.addWidget(self.copyButton, 0, Qt.AlignTop)

        self.addContent(question_row)

        self.answerInput = LineEdit(self)
        self.answerInput.setPlaceholderText('输入答案')
        self.answerInput.setClearButtonEnabled(True)
        self.answerInput.returnPressed.connect(self.yesButton.click)
        self.addContent(self.answerInput)

        self.yesButton.setText('提交')
        self.cancelButton.setText('放弃')

    def _copy_question(self):
        if not self._current_question_raw:
            return
        QApplication.clipboard().setText(self._current_question_raw)
        InfoBar.success(
            '已复制', '题干已复制到剪贴板',
            parent=self, position=InfoBarPosition.TOP, duration=1500,
        )

    def _show_question(self):
        if self._current == -1:
            self.descLabel.setText(self._DESC_DEMO)
            q, _ = self.DEMO_QUESTION
            self._current_question_raw = q
            self.indexLabel.setText("示例题（不计分）")
            self.questionLabel.setText(q)
            self.progressBar.setValue(0)
            self.answerInput.clear()
            self.answerInput.setFocus()
            self.yesButton.setText('开始验证')
            return

        if self._current >= self.total:
            return

        self.descLabel.setText(self._DESC_NORMAL)
        q, _ = self.questions[self._current]
        self._current_question_raw = q
        self.indexLabel.setText(
            f'第 {self._current + 1} / {self.total} 题  '
            f'（评分 {self._risk_score}，需答对 {self.need} 题）'
        )
        self.questionLabel.setText(q)
        self.answerInput.clear()
        self.answerInput.setFocus()
        self.progressBar.setValue(self._current)
        self.yesButton.setText('提交')

    def validate(self):
        ans = self.answerInput.text().strip()
        if not ans:
            InfoBar.warning(
                '请输入答案', '答案不能为空',
                parent=self, position=InfoBarPosition.TOP, duration=1500,
            )
            return False

        if self._current == -1:
            self._current = 0
            self._show_question()
            return False

        _, accepted = self.questions[self._current]
        if check_answer(ans, accepted):
            self._correct += 1
        self._current += 1

        if self._current >= self.total:
            self.passed = self._correct >= self.need
            return True
        self._show_question()
        return False

    def _on_yes(self):
        if self.validate():
            self.close()


class TOTPDialog(_FluentDialog):
    def __init__(self, secret: str = '', usb_id: str = '', parent=None):
        super().__init__('双因素验证', parent)
        self.secret = secret
        self.usb_id = usb_id

        title = TitleLabel('双因素验证', self)
        self.addContent(title)

        desc = BodyLabel('请输入身份验证器中的 6 位动态码', self)
        desc.setWordWrap(True)
        self.addContent(desc)

        self.input = LineEdit(self)
        self.input.setPlaceholderText('000000')
        self.input.setMaxLength(6)
        self.input.setClearButtonEnabled(True)
        self.input.returnPressed.connect(self.yesButton.click)
        self.addContent(self.input)

        if usb_id:
            self.usbButton = PushButton('使用 U 盘解锁', self)
            self.usbButton.clicked.connect(self._try_usb)
            self.addContent(self.usbButton)

        self.yesButton.setText('验证')
        self.cancelButton.setText('取消')
        self.resize(400, 340 if usb_id else 280)

    def _try_usb(self):
        drives = list_removable_drives()
        for d in drives:
            current = get_usb_id(d)
            if current and current == self.usb_id:
                self.passed = True
                self.close()
                return
        InfoBar.error(
            '未匹配', '未检测到匹配的 U 盘',
            parent=self, position=InfoBarPosition.TOP, duration=2000,
        )

    def validate(self):
        if not _HAS_TOTP:
            InfoBar.error(
                '无法验证', 'TOTP 模块未安装（pip install pyotp）',
                parent=self, position=InfoBarPosition.TOP, duration=2500,
            )
            return False

        code = self.input.text().strip()

        if not self.secret:
            self.passed = True
            return True

        if pyotp.TOTP(self.secret).verify(code, valid_window=1):
            self.passed = True
            return True

        InfoBar.error(
            '验证失败', '动态码错误',
            parent=self, position=InfoBarPosition.TOP, duration=2000,
        )
        return False


class TOTPBindDialog(_FluentDialog):
    def __init__(self, user: str = '', parent=None):
        super().__init__('绑定双因素验证', parent)
        self.secret = pyotp.random_base32()
        self.passed = False

        title = TitleLabel('绑定双因素验证', self)
        self.addContent(title)

        desc = BodyLabel(
            '这是客户端本地的第二因素，用于保护本机凭据。\n'
            '请使用验证器 App（如微软 Authenticator、1Password）'
            '扫描下方二维码，或手动输入密钥。',
            self,
        )
        desc.setWordWrap(True)
        self.addContent(desc)

        uri = pyotp.totp.TOTP(self.secret).provisioning_uri(
            name=user or 'FimTale',
            issuer_name='FimTale Client',
        )
        self.qrLabel = QLabel(self)
        self.qrLabel.setPixmap(self._make_qr(uri, 220))
        self.qrLabel.setAlignment(Qt.AlignCenter)
        self.addContent(self.qrLabel)

        key_row = QWidget(self)
        key_layout = QHBoxLayout(key_row)
        key_layout.setContentsMargins(0, 0, 0, 0)
        key_layout.setSpacing(8)

        self.keyLabel = BodyLabel(self.secret, key_row)
        self.keyLabel.setTextInteractionFlags(Qt.TextSelectableByMouse)
        key_layout.addWidget(self.keyLabel, 1)

        self.copyKeyBtn = TransparentToolButton(FluentIcon.COPY, key_row)
        self.copyKeyBtn.setFixedSize(28, 28)
        self.copyKeyBtn.setToolTip('复制密钥')
        self.copyKeyBtn.installEventFilter(
            ToolTipFilter(self.copyKeyBtn, 250, ToolTipPosition.TOP)
        )
        self.copyKeyBtn.clicked.connect(self._copy_key)
        key_layout.addWidget(self.copyKeyBtn, 0)

        self.addContent(key_row)

        self.input = LineEdit(self)
        self.input.setPlaceholderText('输入验证器中的 6 位动态码')
        self.input.setMaxLength(6)
        self.input.setClearButtonEnabled(True)
        self.input.returnPressed.connect(self.yesButton.click)
        self.addContent(self.input)

        self.yesButton.setText('确认绑定')
        self.cancelButton.setText('取消')
        self.resize(460, 580)

    def _make_qr(self, text: str, size: int) -> QPixmap:
        img = qrcode.make(text)
        buf = BytesIO()
        img.save(buf, format="PNG")
        pix = QPixmap()
        pix.loadFromData(buf.getvalue(), "PNG")
        return pix.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation)

    def _copy_key(self):
        QApplication.clipboard().setText(self.secret)
        InfoBar.success(
            '已复制', '密钥已复制到剪贴板',
            parent=self, position=InfoBarPosition.TOP, duration=1500,
        )

    def validate(self):
        if not _HAS_TOTP:
            InfoBar.error(
                '无法绑定', 'pyotp 未安装（pip install pyotp）',
                parent=self, position=InfoBarPosition.TOP, duration=2500,
            )
            return False

        code = self.input.text().strip()
        if not code or len(code) != 6:
            InfoBar.warning(
                '请输入 6 位动态码', '验证码格式不正确',
                parent=self, position=InfoBarPosition.TOP, duration=1500,
            )
            return False

        if pyotp.TOTP(self.secret).verify(code, valid_window=1):
            self.passed = True
            return True

        InfoBar.error(
            '验证失败', '动态码错误，请检查手机时间是否准确',
            parent=self, position=InfoBarPosition.TOP, duration=2000,
        )
        return False


class USBBindDialog(_FluentDialog):
    def __init__(self, parent=None):
        super().__init__('绑定 U 盘解锁', parent)
        self.usb_id = ''

        title = TitleLabel('绑定 U 盘解锁', self)
        self.addContent(title)

        desc = BodyLabel(
            '你可以把一枚 U 盘绑为本机的备选解锁方式。\n'
            '插入匹配的 U 盘即可跳过 TOTP 动态码验证。\n'
            '这一步是可选的，不绑定也能正常使用。',
            self,
        )
        desc.setWordWrap(True)
        self.addContent(desc)

        drives = list_removable_drives()

        if not drives:
            self.driveLabel = BodyLabel('当前未检测到可移动磁盘', self)
            self.driveLabel.setWordWrap(True)
            self.addContent(self.driveLabel)
            self.yesButton.setEnabled(False)
        else:
            self.driveLabel = BodyLabel('检测到以下 U 盘：', self)
            self.addContent(self.driveLabel)

            self.combo = ComboBox(self)
            for d in drives:
                label = get_volume_label(d) or '未命名'
                self.combo.addItem(f'{d}  {label}', userData=d)
            self.addContent(self.combo)

        self.yesButton.setText('绑定')
        self.cancelButton.setText('跳过')
        self.resize(460, 320)

    def validate(self):
        drive = self.combo.currentData() if hasattr(self, 'combo') else None
        if not drive:
            return False
        usb_id = get_usb_id(drive)
        if not usb_id:
            InfoBar.error(
                '读取失败', '无法读取该磁盘的标识',
                parent=self, position=InfoBarPosition.TOP, duration=2500,
            )
            return False
        self.usb_id = usb_id
        self.passed = True
        return True


class EmailCodeDialog(_FluentDialog):
    def __init__(self, api_key: str, parent=None):
        super().__init__('邮件验证', parent)
        self.api_key = api_key

        title = TitleLabel('邮件验证', self)
        self.addContent(title)

        desc = BodyLabel(
            '验证码已发送至绑定邮箱\n（5 分钟内有效，请查看收件箱）',
            self,
        )
        desc.setWordWrap(True)
        self.addContent(desc)

        self.input = LineEdit(self)
        self.input.setPlaceholderText('6 位验证码')
        self.input.setMaxLength(6)
        self.input.setClearButtonEnabled(True)
        self.input.returnPressed.connect(self.yesButton.click)
        self.addContent(self.input)

        self.yesButton.setText('验证')
        self.cancelButton.setText('取消')
        self.resize(400, 300)

    def validate(self):
        code = self.input.text().strip()
        if not code or len(code) != 6:
            InfoBar.error(
                '格式错误', '请输入 6 位验证码',
                parent=self, position=InfoBarPosition.TOP, duration=2000,
            )
            return False

        if not LoginConfig.ENABLE_SERVER:
            self.passed = True
            return True

        InfoBar.error(
            '验证失败', '验证码错误',
            parent=self, position=InfoBarPosition.TOP, duration=2000,
        )
        return False


def verify_fimtale_credentials(api_key: str, api_pass: str, server: str) -> bool:
    base = server.rstrip('/')
    if not base.startswith('http'):
        base = f'https://{base}'

    url = f'{base}/api/v1/settings'
    log_info(f'[FimTale] 验证凭据 server={base} key={api_key[:2]}***')

    try:
        r = requests.get(
            url,
            params={'APIKey': api_key, 'APIPass': api_pass},
            timeout=10,
        )
    except requests.Timeout:
        log_warning(f'[FimTale] 请求超时: {url}')
        return False
    except requests.RequestException as e:
        log_error(f'[FimTale] 请求异常: {e}')
        return False

    log_debug(f'[FimTale] HTTP {r.status_code} body={r.text[:200]}')

    try:
        data = r.json()
    except ValueError:
        log_warning(f'[FimTale] 非 JSON 响应: {r.text[:200]}')
        return False

    if data.get('Status') == 0:
        log_warning(
            f'[FimTale] 凭据无效 ErrorCode={data.get("ErrorCode")} '
            f'Message={data.get("Message", "")}'
        )
        return False

    if 'CurrentUser' in data:
        user = data['CurrentUser'].get('UserName', '?')
        log_success(f'[FimTale] 凭据有效 user={user}')
        return True

    if r.status_code == 200:
        log_success('[FimTale] 凭据有效（HTTP 200，无明确失败标记）')
        return True

    log_warning(f'[FimTale] 未预期响应 status={r.status_code} data={data}')
    return False


class Ui_Form(object):
    def setupUi(self, Form):
        Form.setObjectName("Form")
        Form.resize(1250, 809)
        Form.setMinimumSize(QSize(700, 500))
        self.horizontalLayout = QHBoxLayout(Form)
        self.horizontalLayout.setContentsMargins(0, 0, 0, 0)
        self.horizontalLayout.setSpacing(0)
        self.horizontalLayout.setObjectName("horizontalLayout")

        self.label = QLabel(Form)
        self.label.setText("")
        self.label.setPixmap(QPixmap(resource_path("images/LoginBackground.png")))
        self.label.setScaledContents(True)
        self.label.setObjectName("label")
        self.horizontalLayout.addStretch(1)
        self.horizontalLayout.addWidget(self.label)

        self.widget = QWidget(Form)
        sizePolicy = QSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        sizePolicy.setHorizontalStretch(0)
        sizePolicy.setVerticalStretch(0)
        sizePolicy.setHeightForWidth(self.widget.sizePolicy().hasHeightForWidth())
        self.widget.setSizePolicy(sizePolicy)
        self.widget.setMinimumSize(QSize(360, 0))
        self.widget.setMaximumSize(QSize(360, 16777215))
        self.widget.setAttribute(Qt.WA_StyledBackground, True)
        self.widget.setObjectName("widget")

        self.verticalLayout_2 = QVBoxLayout(self.widget)
        self.verticalLayout_2.setContentsMargins(20, 20, 20, 20)
        self.verticalLayout_2.setSpacing(9)
        self.verticalLayout_2.setObjectName("verticalLayout_2")

        spacerItem = QSpacerItem(20, 40, QSizePolicy.Minimum, QSizePolicy.Expanding)
        self.verticalLayout_2.addItem(spacerItem)

        self.label_2 = QLabel(self.widget)
        self.label_2.setEnabled(True)
        sizePolicy = QSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
        sizePolicy.setHorizontalStretch(0)
        sizePolicy.setVerticalStretch(0)
        sizePolicy.setHeightForWidth(self.label_2.sizePolicy().hasHeightForWidth())
        self.label_2.setSizePolicy(sizePolicy)
        self.label_2.setMinimumSize(QSize(100, 100))
        self.label_2.setMaximumSize(QSize(100, 100))
        self.label_2.setText("")
        self.label_2.setPixmap(QPixmap(resource_path("images/ftclogo.png")))
        self.label_2.setScaledContents(True)
        self.label_2.setObjectName("label_2")
        self.verticalLayout_2.addWidget(self.label_2, 0, Qt.AlignHCenter)

        spacerItem1 = QSpacerItem(20, 15, QSizePolicy.Minimum, QSizePolicy.Fixed)
        self.verticalLayout_2.addItem(spacerItem1)

        self.gridLayout = QGridLayout()
        self.gridLayout.setHorizontalSpacing(4)
        self.gridLayout.setVerticalSpacing(9)
        self.gridLayout.setObjectName("gridLayout")

        self.label_server = BodyLabel(self.widget)
        self.label_server.setObjectName("label_server")
        self.gridLayout.addWidget(self.label_server, 0, 0, 1, 2)

        self.combo_server = ComboBox(self.widget)
        self.combo_server.setObjectName("combo_server")
        self.combo_server.addItems(["fimtale.com", "fimtale.net"])
        self.combo_server.setCurrentIndex(0)
        self.gridLayout.addWidget(self.combo_server, 1, 0, 1, 2)

        self.verticalLayout_2.addLayout(self.gridLayout)

        self.label_5 = BodyLabel(self.widget)
        self.label_5.setObjectName("label_5")
        self.verticalLayout_2.addWidget(self.label_5)

        self.lineEdit_3 = LineEdit(self.widget)
        self.lineEdit_3.setClearButtonEnabled(True)
        self.lineEdit_3.setObjectName("lineEdit_3")
        self.lineEdit_3.setMaxLength(LoginConfig.API_KEY_LEN)
        self.lineEdit_3.setValidator(
            QRegularExpressionValidator(
                QRegularExpression(LoginConfig.API_KEY_RE),
                self.lineEdit_3,
            )
        )
        self.verticalLayout_2.addWidget(self.lineEdit_3)

        self.label_6 = BodyLabel(self.widget)
        self.label_6.setObjectName("label_6")
        self.verticalLayout_2.addWidget(self.label_6)

        self.lineEdit_4 = LineEdit(self.widget)
        self.lineEdit_4.setEchoMode(QLineEdit.Password)
        self.lineEdit_4.setClearButtonEnabled(True)
        self.lineEdit_4.setObjectName("lineEdit_4")
        self.lineEdit_4.setMaxLength(LoginConfig.API_PASS_LEN)
        self.lineEdit_4.setValidator(
            QRegularExpressionValidator(
                QRegularExpression(LoginConfig.API_PASS_RE),
                self.lineEdit_4,
            )
        )
        self.verticalLayout_2.addWidget(self.lineEdit_4)

        spacerItem2 = QSpacerItem(20, 5, QSizePolicy.Minimum, QSizePolicy.Fixed)
        self.verticalLayout_2.addItem(spacerItem2)

        self.checkBox = CheckBox(self.widget)
        self.checkBox.setChecked(True)
        self.checkBox.setObjectName("checkBox")
        self.verticalLayout_2.addWidget(self.checkBox)

        self.autoLoginCheckBox = CheckBox(self.widget)
        self.autoLoginCheckBox.setChecked(True)
        self.autoLoginCheckBox.setObjectName("autoLoginCheckBox")
        self.verticalLayout_2.addWidget(self.autoLoginCheckBox)

        spacerItem3 = QSpacerItem(20, 5, QSizePolicy.Minimum, QSizePolicy.Fixed)
        self.verticalLayout_2.addItem(spacerItem3)

        self.pushButton = PrimaryPushButton(self.widget)
        self.pushButton.setObjectName("pushButton")
        self.verticalLayout_2.addWidget(self.pushButton)

        spacerItem4 = QSpacerItem(20, 6, QSizePolicy.Minimum, QSizePolicy.Fixed)
        self.verticalLayout_2.addItem(spacerItem4)

        self.pushButton_2 = HyperlinkButton(self.widget)
        self.pushButton_2.setObjectName("pushButton_2")
        self.verticalLayout_2.addWidget(self.pushButton_2)

        spacerItem5 = QSpacerItem(20, 40, QSizePolicy.Minimum, QSizePolicy.Expanding)
        self.verticalLayout_2.addItem(spacerItem5)

        self.horizontalLayout.addWidget(self.widget)
        self.retranslateUi(Form)
        QMetaObject.connectSlotsByName(Form)

    def retranslateUi(self, Form):
        _translate = QCoreApplication.translate
        Form.setWindowTitle(_translate("Form", "Form"))
        self.label_server.setText(_translate("Form", "域名"))
        self.label_5.setText(_translate("Form", "APIKey"))
        self.lineEdit_3.setPlaceholderText(_translate("Form", "1234abcd"))
        self.label_6.setText(_translate("Form", "APIPass"))
        self.lineEdit_4.setPlaceholderText(_translate("Form", "••••••••••••"))
        self.checkBox.setText(_translate("Form", "记住密码"))
        self.autoLoginCheckBox.setText(_translate(
            "Form", f"{LoginConfig.AUTO_LOGIN_DAYS}天内自动登录"
        ))
        self.pushButton.setText(_translate("Form", "登录"))
        self.pushButton_2.setText(_translate("Form", "找回密码"))


class LoginWidget(FluentWidget, Ui_Form):
    login_success = False

    def __init__(self):
        super().__init__()
        self._totp_secret = ''
        self._usb_id = ''
        self._logging_in = False
        self.setupUi(self)
        setThemeColor('#28afe9')

        self.credentials = CredentialStore()
        self.rate_limiter = RateLimiter()
        self.risk = RiskEvaluator()

        self._bg = QPixmap()

        if sys.platform != "darwin":
            try:
                self.titleBar.titleLabel.setTextColor(
                    Qt.GlobalColor.darkGray, Qt.GlobalColor.darkGray
                )
            except AttributeError:
                pass
        self.titleBar.raise_()
        self.titleBar.maxBtn.hide()
        self.titleBar.setDoubleClickEnabled(False)
        self.label.setScaledContents(False)

        self.setWindowIcon(QIcon(resource_path("images/ftclogo.png")))
        self._apply_images()

        self.label.hide()
        self._apply_panel_style()
        qconfig.themeChanged.connect(self._apply_panel_style)
        if not self._bg.isNull():
            screen = QApplication.primaryScreen().availableGeometry()
            max_w = int(screen.width() * 0.8)
            max_h = int(screen.height() * 0.8)
            scaled = self._bg.scaled(
                max_w, max_h,
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation
            )
            self.setFixedSize(scaled.size())

        self.setWindowTitle('登录')
        self._center_on_screen()

        self.pushButton.clicked.connect(self.do_login)

        light_qss = """
        PrimaryPushButton:disabled {
            background-color: rgba(40, 175, 233, 120);
            color: rgba(255, 255, 255, 180);
        }
        """
        dark_qss = """
        PrimaryPushButton:disabled {
            background-color: rgba(40, 175, 233, 80);
            color: rgba(255, 255, 255, 140);
        }
        """
        setCustomStyleSheet(self.pushButton, light_qss, dark_qss)

        self.lineEdit_3.textChanged.connect(self._update_login_button)
        self.lineEdit_4.textChanged.connect(self._update_login_button)

        self._prefill_saved_credentials()
        self._update_login_button()

    def _apply_images(self):
        logo = QPixmap(resource_path("images/ftclogo.png"))
        if not logo.isNull():
            self.label_2.setPixmap(logo.scaled(100, 100, Qt.KeepAspectRatio,
                                               Qt.SmoothTransformation))
        self._bg = QPixmap(resource_path("images/LoginBackground.png"))
        if not self._bg.isNull():
            self.label.setPixmap(self._bg.scaled(self.label.size(),
                                                 Qt.KeepAspectRatioByExpanding,
                                                 Qt.SmoothTransformation))

    def _apply_panel_style(self):
        if isDarkTheme():
            bg = "rgba(32, 32, 32, 180)"
            fg = "#e0e0e0"
        else:
            bg = "rgba(255, 255, 255, 180)"
            fg = "#1a1a1a"
        self.widget.setStyleSheet(
            f"QWidget#widget {{ background-color: {bg}; }}\n"
            f"QLabel {{ font: 13px 'Microsoft YaHei'; color: {fg}; }}"
        )

    def _center_on_screen(self):
        d = QApplication.screens()[0].availableGeometry()
        self.move(d.width() // 2 - self.width() // 2,
                  d.height() // 2 - self.height() // 2)

    def _prefill_saved_credentials(self):
        cred = self.credentials.load()
        if not cred:
            return
        self.lineEdit_3.setText(cred.get('api_key', ''))
        self.lineEdit_4.setText(cred.get('api_pass', ''))
        self.checkBox.setChecked(True)
        self.autoLoginCheckBox.setChecked(
            bool(cred.get('auto_login', True))
        )

    def _update_login_button(self):
        ok = (
            len(self.lineEdit_3.text()) == LoginConfig.API_KEY_LEN
            and len(self.lineEdit_4.text()) == LoginConfig.API_PASS_LEN
        )
        self.pushButton.setEnabled(ok)

    def _set_busy(self, busy: bool):
        if busy:
            self.pushButton.setText("验证中…")
            self.pushButton.setEnabled(False)
        else:
            self.pushButton.setText("登录")
            self._update_login_button()
        QApplication.processEvents()

    @staticmethod
    def _resolve_level(risk_score: int):
        for upper, name, total, need, email in LoginConfig.RISK_LEVELS:
            if risk_score <= upper:
                return name, total, need, email
        return LoginConfig.RISK_LEVELS[-1][1:]

    def _error(self, title: str, msg: str):
        InfoBar.error(title, msg, parent=self,
                      position=InfoBarPosition.TOP_RIGHT, duration=3000)

    @staticmethod
    def _run_dialog(dialog) -> bool:
        dialog.show()
        loop = QEventLoop()
        dialog.destroyed.connect(loop.quit)
        loop.exec()
        return dialog.passed

    def do_login(self):
        if self._logging_in:
            return
        self._logging_in = True
        self._set_busy(True)
        try:
            self._do_login_impl()
        finally:
            self._logging_in = False
            if not self.login_success:
                self._set_busy(False)

    def _do_login_impl(self):
        allowed, wait = self.rate_limiter.check()
        if not allowed:
            self._error('登录受限', f'尝试过于频繁，请 {wait} 秒后再试')
            return

        api_key = self.lineEdit_3.text().strip()
        api_pass = self.lineEdit_4.text().strip()
        server = self.combo_server.currentText()

        if len(api_key) != LoginConfig.API_KEY_LEN:
            self._error('登录失败',
                        f'APIKey 必须为 {LoginConfig.API_KEY_LEN} 位字母或数字')
            self.rate_limiter.record_failure()
            return
        if len(api_pass) != LoginConfig.API_PASS_LEN:
            self._error('登录失败',
                        f'APIPass 必须为 {LoginConfig.API_PASS_LEN} 位字母或数字')
            self.rate_limiter.record_failure()
            return

        risk_score, _detail = self.risk.evaluate(api_key)
        level, total, need, need_email = self._resolve_level(risk_score)

        cred = self.credentials.load() or {}
        last_verified = cred.get('last_verified', 0.0)
        auto_login_opt = self.autoLoginCheckBox.isChecked()
        now = time.time()
        elapsed = now - last_verified
        within_window = 0 < elapsed < LoginConfig.AUTO_LOGIN_DAYS * 86400
        low_risk = risk_score <= LoginConfig.AUTO_LOGIN_MAX_RISK
        cred_match = (
            cred.get('api_key') == api_key
            and cred.get('api_pass') == api_pass
        )

        if auto_login_opt and within_window and low_risk and cred_match:
            log_success(
                f'[Login] 7 天自动登录命中（'
                f'{elapsed / 86400:.1f} 天前验证，风险 {risk_score}），'
                f'跳过 FimTale 校验与全部验证'
            )
            self._totp_secret = cred.get('totp_secret', '')
            self._usb_id = cred.get('usb_id', '')
            self.rate_limiter.reset()
            self.login_success = True
            self.close()
            return

        if auto_login_opt and cred_match and not within_window:
            log_info(f'[Login] 自动登录已过期（{elapsed / 86400:.1f} 天），走完整流程')
        elif auto_login_opt and not low_risk:
            log_info(f'[Login] 风险 {risk_score} 超过自动登录阈值 '
                     f'{LoginConfig.AUTO_LOGIN_MAX_RISK}，走完整流程')

        if total > 0:
            dlg = EquestrianTestDialog(risk_score, level, total, need, parent=self)
            if not self._run_dialog(dlg):
                self._error('验证失败', '幻形灵测试未通过，登录已拦截。')
                self.rate_limiter.record_failure()
                return

        if need_email:
            dlg = EmailCodeDialog(api_key, parent=self)
            if not self._run_dialog(dlg):
                self._error('验证失败', '邮件验证码未通过')
                self.rate_limiter.record_failure()
                return

        existing_secret = cred.get('totp_secret', '')
        existing_usb = cred.get('usb_id', '')
        totp_chance = LoginConfig.TOTP_PROBABILITY.get(level, 0.0)
        trigger_totp = random.random() < totp_chance
        log_debug(f'[TOTP] level={level} chance={totp_chance} '
                  f'trigger={trigger_totp} bound={bool(existing_secret)} '
                  f'usb={bool(existing_usb)}')

        if trigger_totp:
            if not existing_secret:
                dlg = TOTPBindDialog(
                    user=cred.get('api_key', '') or api_key,
                    parent=self,
                )
                if not self._run_dialog(dlg):
                    self._error('未绑定', '需要绑定双因素验证才能继续')
                    self.rate_limiter.record_failure()
                    return
                self._totp_secret = dlg.secret
            else:
                dlg = TOTPDialog(secret=existing_secret,
                                 usb_id=existing_usb,
                                 parent=self)
                if not self._run_dialog(dlg):
                    self._error('验证失败', '双因素验证未通过')
                    self.rate_limiter.record_failure()
                    return
                self._totp_secret = existing_secret
        else:
            self._totp_secret = existing_secret

        self._usb_id = existing_usb

        self.pushButton.setText("连接 FimTale…")
        QApplication.processEvents()

        if not verify_fimtale_credentials(api_key, api_pass, server):
            self._error('登录失败', 'APIKey 或 APIPass 错误')
            self.rate_limiter.record_failure()
            return

        last_verified = time.time()

        if trigger_totp and not self._usb_id:
            dlg = USBBindDialog(parent=self)
            self._run_dialog(dlg)
            if dlg.passed and dlg.usb_id:
                self._usb_id = dlg.usb_id
                log_info(f'[USB] 已绑定 {self._usb_id[:8]}***')

        self.rate_limiter.reset()
        if self.checkBox.isChecked():
            self.credentials.save(
                api_key, api_pass,
                totp_secret=self._totp_secret or '',
                usb_id=self._usb_id or '',
                last_verified=last_verified,
                auto_login=self.autoLoginCheckBox.isChecked(),
            )
        else:
            self.credentials.clear()

        self.login_success = True
        self.close()

    def paintEvent(self, event):
        super().paintEvent(event)
        if self._bg.isNull():
            return
        painter = QPainter(self)
        painter.drawPixmap(self.rect(), self._bg)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if not self._bg.isNull():
            self.label.setPixmap(self._bg.scaled(self.label.size(),
                                                 Qt.KeepAspectRatioByExpanding,
                                                 Qt.SmoothTransformation))


class LoginPlugin(BasePlugin):
    def __init__(self, plugin_path=""):
        super().__init__(plugin_path)
        self.plugin_id = "登录"
        self.plugin_types = []

    def show_login(self, main_window) -> bool:
        widget = LoginWidget()
        widget.setWindowFlags(Qt.Window)
        widget.show()
        widget.raise_()
        widget.activateWindow()

        loop = QEventLoop()

        def check():
            if widget.login_success or not widget.isVisible():
                loop.quit()

        timer = QTimer()
        timer.timeout.connect(check)
        timer.start(100)
        loop.exec()
        timer.stop()
        widget.close()
        return widget.login_success