# plugins/_default/settings.py
# coding: utf-8
"""
设置插件：外观 / 账号 / 幻形灵测试 / 日志 / 关于
"""
import os
from styles import AppStyle
from PySide6.QtCore import Qt, QEventLoop
from PySide6.QtWidgets import QWidget, QVBoxLayout, QFrame
from plugins._default.login import CredentialStore, _FluentDialog, TOTPDialog, TOTPBindDialog

from qfluentwidgets import (
    FluentIcon as FIF,
    ScrollArea,
    SettingCardGroup,
    PushSettingCard,
    PrimaryPushSettingCard,
    SwitchSettingCard,
    ComboBoxSettingCard,
    HyperlinkCard,
    InfoBar,
    InfoBarPosition,
    Theme,
    TitleLabel, 
    BodyLabel
)
from qfluentwidgets.common.config import (
    QConfig,
    ConfigItem,
    OptionsConfigItem,
    OptionsValidator,
    BoolValidator,
    qconfig,
    EnumSerializer
)

from base_plugin import BasePlugin, PluginType
from toolmethods import (
    get_version, log_info, log_success, log_warning, log_error, log_debug,
    resource_path, supports_mica,
)

class ConfirmDialog(_FluentDialog):
    """不依赖遮罩的确认框，替代 MessageBox"""

    def __init__(self, title: str, content: str, parent=None):
        super().__init__(title, parent)

        title_label = TitleLabel(title, self)
        self.addContent(title_label)

        content_label = BodyLabel(content, self)
        content_label.setWordWrap(True)
        self.addContent(content_label)

        self.yesButton.setText('确认')
        self.cancelButton.setText('取消')
        self.resize(440, 240)

# ══════════════════════════════════════════════════════════════
#  客户端配置
# ══════════════════════════════════════════════════════════════

class ClientConfig(QConfig):
    # 外观
    themeMode = OptionsConfigItem(
        "Appearance", "ThemeMode", Theme.AUTO,
        OptionsValidator([Theme.AUTO, Theme.LIGHT, Theme.DARK]),
        EnumSerializer(Theme)
    )
    micaEnabled = ConfigItem("Appearance", "Mica", True, BoolValidator())

    # 行为
    debugLog = ConfigItem("Behavior", "DebugLog", False, BoolValidator())
    keepCredentials = ConfigItem("Behavior", "KeepCredentials", True, BoolValidator())

    # 幻形灵测试调试
    forceRiskLevel = OptionsConfigItem(
        "Testing", "ForceRiskLevel", "off",
        OptionsValidator(["off", "low", "medium", "high", "extreme"]),
    )


cfg = ClientConfig()

from toolmethods import get_user_settings_path
qconfig.load(get_user_settings_path(), cfg)

# ══════════════════════════════════════════════════════════════
#  设置界面
# ══════════════════════════════════════════════════════════════

CRED_PATH = os.path.join(
    os.getenv('APPDATA', os.path.expanduser('~')),
    'FimtaleClient', 'credentials.dat'
)


class SettingsWidget(ScrollArea):

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("settingsWidget")
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        self.container = QWidget()
        self.container.setObjectName("scrollWidget")
        self.vBoxLayout = QVBoxLayout(self.container)
        self.vBoxLayout.setContentsMargins(36, 36, 36, 36)
        self.vBoxLayout.setSpacing(24)
        self.vBoxLayout.setAlignment(Qt.AlignTop)

        self._build_appearance()
        self._build_account()
        self._build_testing()
        self._build_logging()
        self._build_about()

        self.setWidget(self.container)
        self.setFrameShape(QFrame.NoFrame)
        self.enableTransparentBackground()

        self.setWidget(self.container)
        AppStyle.SETTINGS_SCROLL.apply(self)

    # ── 外观 ──
    def _build_appearance(self):
        group = SettingCardGroup("外观", self.container)

        self.themeCard = ComboBoxSettingCard(
            cfg.themeMode,
            FIF.BRUSH,
            "主题模式",
            "浅色 / 深色 / 跟随系统",
            texts=["跟随系统", "浅色", "深色"],
            parent=group,
        )

        self.micaCard = SwitchSettingCard(
            FIF.TRANSPARENT,
            "云母效果",
            "为窗口启用云母材质（仅 Windows 11）",
            configItem=cfg.micaEnabled,
            parent=group,
        )

        # Win10 及以下：禁用 Mica 开关并强制关闭
        if not supports_mica():
            self.micaCard.setEnabled(False)
            cfg.micaEnabled.value = False

        group.addSettingCard(self.themeCard)
        group.addSettingCard(self.micaCard)
        self.vBoxLayout.addWidget(group)

    # ── 账号 ──
    def _build_account(self):
        group = SettingCardGroup("账号", self.container)

        self.clearCredCard = PushSettingCard(
            "清除本地凭据",
            FIF.DELETE,
            "凭据管理",
            "删除保存在本机的 FimTale APIKey / APIPass / TOTP 密钥",
            parent=group,
        )
        self.clearCredCard.clicked.connect(self._on_clear_credentials)

        # ── 双因素验证 ──
        self.totpCard = PushSettingCard(
            "绑定",
            FIF.FINGERPRINT,
            "双因素验证",
            "",
            parent=group,
        )
        self.totpCard.clicked.connect(self._on_totp_action)

        self.openFimtaleCard = HyperlinkCard(
            "https://fimtale.com/settings",
            "前往 FimTale 设置",
            FIF.LINK,
            "管理 APIKey / APIPass",
            "在站点设置页生成或吊销凭据",
            parent=group,
        )

        group.addSettingCard(self.clearCredCard)
        group.addSettingCard(self.totpCard)
        group.addSettingCard(self.openFimtaleCard)
        self.vBoxLayout.addWidget(group)

        # 初始化卡片状态
        self._refresh_totp_card()

    def _refresh_totp_card(self):
        store = CredentialStore()
        cred = store.load()

        if not cred:
            self.totpCard.button.setText("未登录")
            self.totpCard.setEnabled(False)
            self.totpCard.setContent("请先登录账号")
            return

        self.totpCard.setEnabled(True)
        if cred.get('totp_secret'):
            self.totpCard.button.setText("解绑")
            self.totpCard.setContent("已绑定，用于保护本机凭据")
        else:
            self.totpCard.button.setText("绑定")
            self.totpCard.setContent("未绑定。绑定后可作为第二因素")

    def _on_clear_credentials(self):
        if not os.path.exists(CRED_PATH):
            InfoBar.info(
                "无凭据", "本地没有保存的凭据",
                parent=self, position=InfoBarPosition.TOP, duration=2000,
            )
            return

        dlg = ConfirmDialog(
            "确认清除？",
            "这会删除本机保存的 APIKey / APIPass / TOTP 密钥，"
            "下次登录需要重新输入并重新绑定双因素验证。",
            parent=self,
        )
        if not self._run_dialog(dlg):
            return

        try:
            os.remove(CRED_PATH)
            log_success('[设置] 本地凭据已清除')
            InfoBar.success(
                "已清除", "本地凭据已删除",
                parent=self, position=InfoBarPosition.TOP, duration=2000,
            )
        except OSError as e:
            log_error(f'[设置] 清除凭据失败: {e}')
            InfoBar.error(
                "清除失败", str(e),
                parent=self, position=InfoBarPosition.TOP, duration=3000,
            )

    # ── 幻形灵测试调试 ──
    def _build_testing(self):
        group = SettingCardGroup("幻形灵测试（调试）", self.container)

        self.forceRiskCard = ComboBoxSettingCard(
            cfg.forceRiskLevel,
            FIF.VPN,
            "强制风控等级",
            "调试用：跳过真实评分，直接进入指定等级",
            texts=["关闭", "low", "medium", "high", "extreme"],
            parent=group,
        )

        group.addSettingCard(self.forceRiskCard)
        self.vBoxLayout.addWidget(group)

    # ── 日志 ──
    def _build_logging(self):
        group = SettingCardGroup("日志", self.container)

        self.debugLogCard = SwitchSettingCard(
            FIF.DEVELOPER_TOOLS,
            "调试日志",
            "在控制台输出 DEBUG 级别日志",
            configItem=cfg.debugLog,
            parent=group,
        )

        group.addSettingCard(self.debugLogCard)
        self.vBoxLayout.addWidget(group)

    # ── 关于 ──
    def _build_about(self):
        group = SettingCardGroup("关于", self.container)

        version = get_version()
        self.versionCard = PrimaryPushSettingCard(
            "检查更新",
            FIF.INFO,
            "FimTale 客户端",
            f"版本 {version} · 开源 · GPLv3",
            parent=group,
        )
        self.versionCard.clicked.connect(self._on_check_update)

        self.repoCard = HyperlinkCard(
            "https://github.com/yourname/fimtale-client",
            "打开仓库",
            FIF.CODE,
            "源码仓库",
            "GPLv3 · 欢迎提交 Issue 和 PR",
            parent=group,
        )

        group.addSettingCard(self.versionCard)
        group.addSettingCard(self.repoCard)
        self.vBoxLayout.addWidget(group)

    def _on_check_update(self):
        InfoBar.info(
            "已是最新", "你正在使用最新版本",
            parent=self, position=InfoBarPosition.TOP, duration=2000,
        )

    @staticmethod
    def _run_dialog(dialog) -> bool:
        dialog.show()
        loop = QEventLoop()
        dialog.destroyed.connect(loop.quit)
        loop.exec()
        return dialog.passed

    def _on_totp_action(self):
        store = CredentialStore()
        cred = store.load()

        if not cred:
            InfoBar.warning(
                "未登录", "请先登录账号",
                parent=self, position=InfoBarPosition.TOP, duration=2000,
            )
            return

        existing = cred.get('totp_secret', '')

        if existing:
            # ── 解绑：先验证当前 TOTP ──
            dlg = TOTPDialog(secret=existing, parent=self)
            if not self._run_dialog(dlg):
                InfoBar.warning(
                    "验证失败", "解绑已取消",
                    parent=self, position=InfoBarPosition.TOP, duration=2000,
                )
                return

            store.clear_totp()
            log_success('[设置] 已解绑双因素验证')
            InfoBar.success(
                "已解绑", "双因素验证已移除",
                parent=self, position=InfoBarPosition.TOP, duration=2000,
            )
            self._refresh_totp_card()

        else:
            # ── 绑定 ──
            dlg = TOTPBindDialog(user=cred.get('api_key', ''), parent=self)
            if not self._run_dialog(dlg):
                InfoBar.warning(
                    "未绑定", "已取消绑定流程",
                    parent=self, position=InfoBarPosition.TOP, duration=2000,
                )
                return

            store.set_totp(dlg.secret)
            log_success('[设置] 已绑定双因素验证')
            InfoBar.success(
                "已绑定", "下次高风险登录将要求输入动态码",
                parent=self, position=InfoBarPosition.TOP, duration=2500,
            )
            self._refresh_totp_card()


# ══════════════════════════════════════════════════════════════
#  插件入口
# ══════════════════════════════════════════════════════════════

class SettingsPlugin(BasePlugin):
    def __init__(self, plugin_path=""):
        super().__init__(plugin_path)
        self.plugin_id = "设置"
        self.plugin_types = [PluginType.UI]
        self.icon = FIF.SETTING
        self.navigation_position = "bottom"

    def get_widget(self):
        return SettingsWidget()