# plugins/_default/home.py
# coding: utf-8
from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout, QHBoxLayout, QWidget
from qfluentwidgets import (
    FluentIcon, IconWidget, TextWrap, SingleDirectionScrollArea,
    isDarkTheme, qconfig,
)
from base_plugin import BasePlugin, PluginType


class LinkCard(QFrame):
    """Gallery 首页同款卡片：198×220，左上图标，右下链接角标"""

    def __init__(self, icon, title, content, url=None, on_click=None, parent=None):
        super().__init__(parent=parent)
        self.url = QUrl(url) if url else None
        self.on_click = on_click
        self.setFixedSize(198, 220)
        self.setCursor(Qt.PointingHandCursor)

        self.iconWidget = IconWidget(icon, self)
        self.titleLabel = QLabel(title, self)
        self.contentLabel = QLabel(TextWrap.wrap(content, 28, False)[0], self)
        self.urlWidget = IconWidget(FluentIcon.LINK, self)

        self.__initWidget()
        self._apply_theme()
        qconfig.themeChanged.connect(self._apply_theme)

    def __initWidget(self):
        self.iconWidget.setFixedSize(54, 54)
        self.urlWidget.setFixedSize(16, 16)

        self.vBoxLayout = QVBoxLayout(self)
        self.vBoxLayout.setSpacing(0)
        self.vBoxLayout.setContentsMargins(24, 24, 0, 13)
        self.vBoxLayout.addWidget(self.iconWidget)
        self.vBoxLayout.addSpacing(16)
        self.vBoxLayout.addWidget(self.titleLabel)
        self.vBoxLayout.addSpacing(8)
        self.vBoxLayout.addWidget(self.contentLabel)
        self.vBoxLayout.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self.urlWidget.move(170, 192)

        self.titleLabel.setObjectName('titleLabel')
        self.contentLabel.setObjectName('contentLabel')

        # 没有 url 的卡片不显示右下角链接图标
        if self.url is None:
            self.urlWidget.hide()

    def _apply_theme(self):
        if isDarkTheme():
            bg = "rgba(255, 255, 255, 0.06)"
            bg_hover = "rgba(255, 255, 255, 0.10)"
            border = "rgba(255, 255, 255, 0.10)"
            border_hover = "rgba(255, 255, 255, 0.18)"
            title_color = "#ffffff"
            content_color = "#a0a0a0"
        else:
            bg = "rgba(255, 255, 255, 0.7)"
            bg_hover = "rgba(255, 255, 255, 0.9)"
            border = "rgba(0, 0, 0, 0.08)"
            border_hover = "rgba(0, 0, 0, 0.12)"
            title_color = "#1a1a1a"
            content_color = "#666666"

        self.setStyleSheet(f"""
            LinkCard {{
                background-color: {bg};
                border: 1px solid {border};
                border-radius: 10px;
            }}
            LinkCard:hover {{
                background-color: {bg_hover};
                border: 1px solid {border_hover};
            }}
            #titleLabel {{
                font: 14px 'Microsoft YaHei';
                font-weight: 600;
                color: {title_color};
            }}
            #contentLabel {{
                font: 12px 'Microsoft YaHei';
                color: {content_color};
            }}
        """)

    def mouseReleaseEvent(self, e):
        super().mouseReleaseEvent(e)
        if e.button() != Qt.LeftButton:
            return
        if self.on_click is not None:
            self.on_click()
        elif self.url is not None:
            QDesktopServices.openUrl(self.url)


class LinkCardView(SingleDirectionScrollArea):
    """横向卡片条"""

    def __init__(self, parent=None):
        super().__init__(parent, Qt.Horizontal)
        self.view = QWidget(self)
        self.hBoxLayout = QHBoxLayout(self.view)

        self.hBoxLayout.setContentsMargins(36, 0, 36, 0)
        self.hBoxLayout.setSpacing(12)
        self.hBoxLayout.setAlignment(Qt.AlignLeft)

        self.setWidget(self.view)
        self.setWidgetResizable(True)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setFixedHeight(220)

        self.view.setObjectName('view')
        self.enableTransparentBackground()

    def addCard(self, icon, title, content, url=None, on_click=None):
        card = LinkCard(icon, title, content, url, on_click, self.view)
        self.hBoxLayout.addWidget(card, 0, Qt.AlignLeft)


class HomeWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("home")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(36, 36, 36, 36)
        layout.setSpacing(12)

        self.title = QLabel("FimTale", self)
        layout.addWidget(self.title)

        self.subtitle = QLabel("小马同人创作社区客户端", self)
        layout.addWidget(self.subtitle)

        layout.addSpacing(20)

        card_view = LinkCardView(self)
        card_view.addCard(FluentIcon.HOME, "首页",
                          "浏览 FimTale 最新作品、推荐与活动",
                          url="https://fimtale.com/")
        card_view.addCard(FluentIcon.BOOK_SHELF, "阅读器",
                          "在客户端内阅读 FimTale 作品",
                          on_click=self._open_reader)
        card_view.addCard(FluentIcon.EDIT, "创作",
                          "发布、管理你的同人作品与草稿",
                          url="https://fimtale.com/writer")
        card_view.addCard(FluentIcon.PEOPLE, "社区",
                          "加入讨论，认识其他马迷作者",
                          url="https://fimtale.com/forum")
        card_view.addCard(FluentIcon.HEART, "收藏",
                          "查看你收藏的作品、关注与订阅",
                          url="https://fimtale.com/favorites")
        layout.addWidget(card_view)

        layout.addStretch(1)

        self._apply_theme()
        qconfig.themeChanged.connect(self._apply_theme)

    def _open_reader(self, topic_id: int = None):
        main = self.window()
        if main is None or not hasattr(main, "switchTo"):
            return

        # 在 stackedWidget 里按 objectName 找
        target = None
        sw = main.stackedWidget
        for i in range(sw.count()):
            w = sw.widget(i)
            if w.objectName() == "阅读器":
                target = w
                break

        if target is None:
            print(">>> [Home] stackedWidget 里找不到 readerInterface")
            # 打印一下有哪些，方便排查
            for i in range(sw.count()):
                w = sw.widget(i)
                print(f"    [{i}] objectName={w.objectName()!r} class={type(w).__name__}")
            return

        main.switchTo(target)

        if topic_id is not None and hasattr(target, "open_topic"):
            target.open_topic(int(topic_id))

    def _find_reader_plugin(self, main):
        """在主窗口的所有插件里找 plugin_id == '阅读器' 的"""
        # 优先用主窗口暴露的方法
        if hasattr(main, "get_plugin_by_id"):
            return main.get_plugin_by_id("阅读器")
        # 回退：遍历 MainWindowPlugin 里存的 plugins
        for plugin_list in getattr(main, "plugins", {}).values() \
                if isinstance(getattr(main, "plugins", None), dict) else []:
            for p in plugin_list:
                if getattr(p, "plugin_id", "") == "阅读器":
                    return p
        return None
    
    def _apply_theme(self):
        if isDarkTheme():
            title_color = "#ffffff"
            sub_color = "#a0a0a0"
        else:
            title_color = "#1a1a1a"
            sub_color = "#666666"

        self.title.setStyleSheet(
            f"font: 600 28px 'Microsoft YaHei'; color: {title_color};"
        )
        self.subtitle.setStyleSheet(
            f"font: 14px 'Microsoft YaHei'; color: {sub_color};"
        )


class HomePlugin(BasePlugin):
    def __init__(self, plugin_path=""):
        super().__init__(plugin_path)
        self.plugin_id = "主页"
        self.plugin_types = [PluginType.UI]
        self.icon = FluentIcon.HOME
        self.navigation_position = "top"

    def get_widget(self):
        return HomeWidget()