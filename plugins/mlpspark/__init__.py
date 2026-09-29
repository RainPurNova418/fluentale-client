from base_plugin import BasePlugin, PluginType
from qfluentwidgets import FluentIcon
from .widget import MLPSparkWidget

class MLPSparkPlugin(BasePlugin):
    def __init__(self, plugin_path=""):
        super().__init__(plugin_path)
        self.plugin_id = "灵感火花"
        self.plugin_types = [PluginType.UI]
        self.icon = FluentIcon.LIGHTBULB

    def get_widget(self):
        return MLPSparkWidget()