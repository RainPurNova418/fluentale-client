# plugins/_default/reader/__init__.py
# coding: utf-8
from base_plugin import BasePlugin, PluginType
from qfluentwidgets import FluentIcon as FIF
from .interface import ReaderInterface


class ReaderPlugin(BasePlugin):
    def __init__(self, plugin_path=""):
        super().__init__(plugin_path)
        self.plugin_id = "阅读器"
        self.plugin_types = [PluginType.UI]
        self.icon = FIF.BOOK_SHELF
        self.navigation_position = "scroll"

    def get_widget(self):
        return ReaderInterface()