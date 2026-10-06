from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QIcon, QColor
from PySide6.QtWidgets import QWidget, QLabel, QVBoxLayout
from qfluentwidgets import (
    MSFluentWindow, FluentIcon, NavigationItemPosition,
    setTheme, isDarkTheme, qconfig,
)
from base_plugin import BasePlugin, PluginType
from plugin_manager import PluginManager
from toolmethods import (
    resource_path,
    log_info, log_success, log_warning, log_debug,
    get_version, supports_mica,
)
from plugins._default.settings import cfg
import sys

class MainWindowPlugin(MSFluentWindow, BasePlugin):
    def __init__(self):
        log_debug("开始初始化 MainWindowPlugin")
        MSFluentWindow.__init__(self)
        BasePlugin.__init__(self, plugin_path="")

        self.setObjectName("MainWindow")
        self.setWindowTitle(f"FluentTale Client - v{get_version()}")
        self.setWindowIcon(QIcon(resource_path("images/ftclogo.png")))

        self._apply_settings()
        qconfig.themeChanged.connect(self._on_theme_changed)

        self.services = self._create_services()

        mgr = PluginManager(resource_path("plugins"), self.services)
        plugins_dict = mgr.discover_and_load()

        all_plugins = []
        for plugin_list in plugins_dict.values():
            all_plugins.extend(plugin_list)

        self._all_plugins = all_plugins

        privacy_plugin = self._find_plugin_by_id(all_plugins, "隐私政策")
        if privacy_plugin:
            log_info("准备显示隐私政策")
            if not privacy_plugin.show_policy(self):
                log_info("用户未同意隐私政策，退出程序")
                sys.exit(0)
            log_success("用户已同意隐私政策")
        else:
            log_warning("未找到隐私政策插件，跳过")

        login_plugin = self._find_plugin_by_id(all_plugins, "登录")
        if login_plugin:
            log_info("找到登录插件，准备进行登录")
            if not login_plugin.show_login(self):
                log_info("登录失败或取消，退出程序")
                sys.exit(0)
            log_success("登录成功")
        else:
            log_warning("未找到登录插件，继续运行")

        TOP_ORDER = {
            "主页": 0,
        }
        BOTTOM_ORDER = {
            "设置": 0,
        }
        DEFAULT_TOP = 500
        DEFAULT_BOTTOM = 999

        ui_plugins = [
            p for p in all_plugins
            if PluginType.UI in p.plugin_types and p.plugin_id != "登录"
        ]

        ui_plugins.sort(
            key=lambda p: (0 if p.plugin_id == "主页" else 1)
        )

        _POS_MAP = {
            "top":    NavigationItemPosition.TOP,
            "scroll": NavigationItemPosition.SCROLL,
            "bottom": NavigationItemPosition.BOTTOM,
        }

        for plugin in ui_plugins:
            widget = plugin.get_widget()
            if widget:
                widget.setObjectName(plugin.plugin_id)
                pos = _POS_MAP.get(
                    getattr(plugin, "navigation_position", "scroll"),
                    NavigationItemPosition.SCROLL,
                )
                self.addSubInterface(
                    widget,
                    plugin.get_navigation_icon() or FluentIcon.APPLICATION,
                    plugin.get_navigation_text(),
                    position=pos,
                )
        log_success(f"加载 {len(ui_plugins)} 个 UI 插件")

        for plugin in all_plugins:
            if PluginType.SERVICE in plugin.plugin_types:
                plugin.on_load()

        if not ui_plugins:
            self._add_placeholder()
            log_warning("未找到任何 UI 插件，已添加占位界面")

        self.showMaximized()
        log_success("窗口已最大化显示")

    def _apply_settings(self):
        """应用配置：Mica、主题模式、标题栏颜色"""

        cfg.themeMode.valueChanged.connect(lambda t: setTheme(t))

        # 仅 Win11
        if supports_mica():
            self.setMicaEffectEnabled(cfg.get(cfg.micaEnabled))
            cfg.micaEnabled.valueChanged.connect(self.setMicaEffectEnabled)
            log_info("[窗口] Mica 效果已启用")
        else:
            self.setMicaEffectEnabled(False)
            log_info("[窗口] 当前系统不支持 Mica，已跳过")

        self._apply_titlebar_color()
        self.titleBar.update()
        qconfig.themeChanged.connect(self._apply_titlebar_color)

    def _apply_titlebar_color(self):
        """标题栏文字颜色：浅色主题黑色，深色主题白色"""
        try:
            self.titleBar.titleLabel.setTextColor(
                QColor(0, 0, 0),
                QColor(255, 255, 255),
            )
        except AttributeError:
            pass

    def _find_plugin_by_id(self, plugins, plugin_id):
        for p in plugins:
            if getattr(p, 'plugin_id', '') == plugin_id:
                return p
        return None

    def get_plugin_by_id(self, plugin_id: str):
        """供插件按 plugin_id 查找插件实例"""
        for p in getattr(self, "_all_plugins", []):
            if getattr(p, "plugin_id", "") == plugin_id:
                return p
        return None

    def _create_services(self):
        class Services:
            def __init__(self, main_window):
                self.main_window = main_window

            def log(self, message: str):
                log_info(message)

            def get_config(self, key: str, default=None):
                return default

            def set_config(self, key: str, value):
                pass

        return Services(self)

    def _add_placeholder(self):
        widget = QWidget()
        widget.setObjectName("placeholder")
        layout = QVBoxLayout(widget)
        layout.addWidget(QLabel(
            "暂无可用插件，请检查文件完整性。\n"
            "若您找到了插件文件，请将插件放入 plugins/ 目录"
        ))
        self.addSubInterface(widget, FluentIcon.INFO, "提示")

    def get_widget(self) -> QWidget:
        return self

    def get_navigation_text(self) -> str:
        return ""

    def get_navigation_icon(self):
        return None

    def _on_theme_changed(self):
        setTheme(cfg.themeMode.value)

        self._apply_titlebar_color()

        if hasattr(self, 'titleBar'):
            self.titleBar.update()

        self.update()