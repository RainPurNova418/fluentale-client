# plugins/_default/reader/image_browser.py
# coding: utf-8
"""
支持本地缓存图片的 QTextBrowser

- loadResource 只从磁盘缓存读，不发网络请求
- 图片由 LoadWorker 后台预下载
- 按外部传入的最大宽度缩放图片
"""
from PySide6.QtCore import Qt, QUrl
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
        self._mem = {}
        self._max_image_width = 800   # 兜底，由外部 set_max_image_width 更新

    def set_max_image_width(self, w: int):
        """由外部设置图片最大宽度（一般 = viewport 宽度 - padding）"""
        w = max(200, int(w))
        if w == self._max_image_width:
            return
        self._max_image_width = w
        # 缩放参数变了，清内存缓存，强制重新缩放
        self._mem.clear()

    def loadResource(self, type_, url: QUrl):
        url_str = url.toString() if isinstance(url, QUrl) else str(url)
        if not url_str:
            return super().loadResource(type_, url)

        is_img_type = (type_ == QTextDocument.ResourceType.ImageResource)
        if is_img_type or _is_image_url(url_str):
            img = self._get_image(url_str, self._max_image_width)
            if img is not None and not img.isNull():
                return img
        return super().loadResource(type_, url)

    def _get_image(self, url: str, max_w: int):
        key = (url, max_w)
        if key in self._mem:
            return self._mem[key]

        data = cache.read_image(url)
        if data is None:
            return None

        img = QImage()
        img.loadFromData(data)
        if img.isNull():
            return None

        if img.width() > max_w:
            img = img.scaledToWidth(max_w, Qt.SmoothTransformation)

        self._mem[key] = img
        return img

    def clear_memory_cache(self):
        self._mem.clear()