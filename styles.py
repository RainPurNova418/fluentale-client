from enum import Enum
from qfluentwidgets import StyleSheetBase, Theme, qconfig
from toolmethods import resource_path

class AppStyle(StyleSheetBase, Enum):
    SETTINGS_SCROLL = "settings_scroll"

    def path(self, theme=Theme.AUTO):
        theme = qconfig.theme if theme == Theme.AUTO else theme
        return resource_path(
            f"qss/{theme.value.lower()}/{self.value}.qss"
        )