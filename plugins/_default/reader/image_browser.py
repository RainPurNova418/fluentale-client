from PySide6.QtCore import Qt, QUrl, QPoint, QPointF, Signal, QRect
from PySide6.QtGui import QImage, QTextDocument
from PySide6.QtWidgets import QTextBrowser

from . import cache

_IMG_EXTS = ('.png', '.jpg', '.jpeg', '.gif', '.webp', '.bmp')

def _is_image_url(url: str) -> bool:
    lower = url.lower().split('?')[0]
    return any(lower.endswith(e) for e in _IMG_EXTS)

class ImageBrowser(QTextBrowser):
    contextMenuRequested = Signal(QPoint, QPoint)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._mem = {}
        self._max_image_width = 800
        self.viewport().setCursor(Qt.ArrowCursor)

    def set_max_image_width(self, w: int):
        w = max(200, int(w))
        if w == self._max_image_width:
            return
        self._max_image_width = w
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

    def contextMenuEvent(self, e):
        self.contextMenuRequested.emit(e.pos(), e.globalPos())
        e.accept()

    def mouseMoveEvent(self, e):
        super().mouseMoveEvent(e)

        pos = e.position().toPoint()

        anchor = self.anchorAt(pos)
        if anchor and not anchor.startswith("spoiler:"):
            self.viewport().setCursor(Qt.PointingHandCursor)
            return

        cursor = self.cursorForPosition(pos)
        if cursor.charFormat().isImageFormat():
            self.viewport().setCursor(Qt.PointingHandCursor)
            return

        if self._is_on_text(pos):
            self.viewport().setCursor(Qt.IBeamCursor)
        else:
            self.viewport().setCursor(Qt.ArrowCursor)

    def _is_on_text(self, pos: QPoint) -> bool:
        """
        用 documentLayout().hitTest() 精确判断坐标是否落在字符上。
        viewport 坐标 → 文档坐标需要加上滚动偏移。
        """
        try:
            layout = self.document().documentLayout()
            h_offset = self.horizontalScrollBar().value()
            v_offset = self.verticalScrollBar().value()
            doc_pos = QPointF(pos.x() + h_offset, pos.y() + v_offset)
            hit = layout.hitTest(doc_pos, Qt.ExactHit)
            return hit >= 0
        except Exception:
            return False

    def leaveEvent(self, e):
        self.viewport().setCursor(Qt.ArrowCursor)
        super().leaveEvent(e)