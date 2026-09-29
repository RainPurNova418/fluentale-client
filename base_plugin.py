# base_plugin.py
from enum import Enum
from PySide6.QtCore import QObject
from PySide6.QtWidgets import QWidget
from typing import Optional

class PluginType(Enum):
    UI = "ui"          # 导航栏界面（含装饰/主题）
    TOOL = "tool"      # 工具栏/菜单/快捷键
    SERVICE = "service" # 后台服务（无界面）

class BasePlugin:
    """插件基类（纯 Python，不继承 Qt 类，避免多重继承冲突）"""
    def __init__(self, plugin_path: str = ""):
        self.plugin_id = "未命名"
        self.plugin_version = "1.0"
        self.plugin_types = [PluginType.UI]
        self.navigation_position = "scroll"
        self.author = "未知"
        self.icon = None
        self.plugin_path = plugin_path
        self._services = None
        self._main_window = None

    def set_services(self, services):
        self._services = services

    def set_main_window(self, main_window):
        self._main_window = main_window

    def get_widget(self) -> QWidget:
        """UI 插件必须返回界面，其他类型返回 None"""
        return None

    def get_navigation_text(self) -> str:
        return self.plugin_id if PluginType.UI in self.plugin_types else ""

    def get_navigation_icon(self):
        return self.icon

    def on_load(self):
        """插件加载后调用（可用于初始化后台服务）"""
        pass

    def on_unload(self):
        """插件卸载前调用（可用于清理资源）"""
        pass

    # ---------- 工具插件专用 ----------
    def register_shortcut(self):
        """工具插件可以重写此方法注册快捷键"""
        pass

    # ---------- 服务插件专用 ----------
    def get_service(self):
        """服务插件返回自己提供的服务对象"""
        return None