# plugins/_default/reader/image_browser.py
# coding: utf-8
"""
支持本地缓存图片的 QTextBrowser

- loadResource 只从磁盘缓存读，不发网络请求
- 图片由 LoadWorker 后台预下载
- 缓存未命中时返回 None，Qt 显示空白占位
"""
from PySide6.QtCore import QUrl
from PySide6.QtGui import QImage, QTextDocument
from PySide6.QtWidgets import QTextBrowser

from . import cache


_IMG_EXTS = ('.png', '.jpg', '.jpeg', '.gif', '.webp', '.bmp')


def _is_image_url(url: str) -> bool:
    lower = url.lower().split('?')[0]
    return any(lower.endswith(e) for e in _IMG_EXTS)


class ImageBrowser(QTextBrowser):
    """带图片缓存的 QTextBrowser"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._mem = {}   # url -> QImage

    def loadResource(self, type_, url: QUrl):
        url_str = url.toString() if isinstance(url, QUrl) else str(url)
        if not url_str:
            return super().loadResource(type_, url)

        # 只处理图片资源
        is_img_type = (type_ == QTextDocument.ResourceType.ImageResource)
        if is_img_type or _is_image_url(url_str):
            img = self._get_image(url_str)
            if img is not None and not img.isNull():
                return img
            # 未命中：返回 None，Qt 显示空白

        return super().loadResource(type_, url)

    def _get_image(self, url: str):
        if url in self._mem:
            return self._mem[url]

        data = cache.read_image(url)
        if data is None:
            return None

        img = QImage()
        img.loadFromData(data)
        if not img.isNull():
            self._mem[url] = img
            return img
        return None

    def clear_memory_cache(self):
        self._mem.clear()