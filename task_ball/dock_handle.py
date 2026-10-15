"""A compact, themed water drop for a ball tucked against a screen edge."""

from PySide6.QtCore import QPoint, QPointF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPen, QTransform
from PySide6.QtWidgets import QWidget

from .water_ball import THEMES


class DockHandle(QWidget):
    """Paint the edge handle and report gestures without managing its window."""

    revealed = Signal()
    dragStarted = Signal()
    dragMoved = Signal(QPoint)
    dragFinished = Signal()
    menuRequested = Signal(QPoint)

    def __init__(self, parent=None, *, theme="amber", side="left"):
        super().__init__(parent)
        self.theme = theme if theme in THEMES else "amber"
        self.side = side if side in ("left", "right", "top", "bottom") else "left"
        self._press = None
        self._moved = False
        self._hovering = False
        self._hover_generation = 0
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setCursor(Qt.CursorShape.SizeAllCursor)
        self.setAccessibleName("贴边悬浮球")
        self.setToolTip("悬停展开，拖离边缘取消贴边")
        self.resize(self.sizeHint())

    def sizeHint(self):
        return QSize(12, 32) if self.side in ("left", "right") else QSize(32, 12)

    def set_appearance(self, theme, side=None):
        self.theme = theme if theme in THEMES else "amber"
        if side is not None:
            self.side = side if side in ("left", "right", "top", "bottom") else "left"
        self.updateGeometry()
        self.update()

    def set_side(self, side):
        self.set_appearance(self.theme, side)

    def is_pressed(self):
        return self._press is not None

    def _shape_transform(self):
        width, height = self.width(), self.height()
        if self.side == "right":
            return QTransform(-width / 12, 0, 0, height / 32, width, 0)
        if self.side == "top":
            return QTransform(0, height / 12, width / 32, 0, 0, 0)
        if self.side == "bottom":
            return QTransform(0, -height / 12, width / 32, 0, 0, height)
        return QTransform(width / 12, 0, 0, height / 32, 0, 0)

    def paintEvent(self, event):
        theme = THEMES[self.theme]
        transform = self._shape_transform()
        path = QPainterPath(QPointF(0, 0))
        path.lineTo(0, 32)
        path.cubicTo(6, 32, 12, 25, 12, 16)
        path.cubicTo(12, 7, 6, 0, 0, 0)
        path.closeSubpath()
        path = transform.map(path)

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        gradient = QLinearGradient(QPointF(0, 0), QPointF(self.width(), self.height()))
        for stop, key in ((0.0, "top"), (.46, "middle"), (1.0, "bottom")):
            gradient.setColorAt(stop, QColor(theme[key]))
        painter.fillPath(path, gradient)
        painter.setClipPath(path)

        # The only decoration follows the inner curved edge of the water drop.
        reflection = QPainterPath(QPointF(4, 5))
        reflection.cubicTo(8, 8, 10, 12, 10, 17)
        color = QColor(theme["light"])
        color.setAlphaF(theme["upper"] * .85)
        painter.setPen(QPen(color, .7, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.drawPath(transform.map(reflection))
        painter.end()

    def _queue_reveal(self, *, hover=False):
        generation = self._hover_generation

        def reveal_if_current():
            if (generation == self._hover_generation and self.isVisible()
                    and self._press is None and (not hover or self._hovering)):
                self.revealed.emit()

        # A QObject context cancels the callback if the handle is destroyed.
        # Deferring also lets Qt release its implicit press capture first.
        QTimer.singleShot(0, self, reveal_if_current)

    def enterEvent(self, event):
        self._hovering = True
        self._hover_generation += 1
        self._queue_reveal(hover=True)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hovering = False
        self._hover_generation += 1
        super().leaveEvent(event)

    def hideEvent(self, event):
        self._hovering = False
        self._hover_generation += 1
        self._press = None
        super().hideEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._hover_generation += 1
            self._press = event.globalPosition().toPoint()
            self._moved = False
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._press is not None and event.buttons() & Qt.MouseButton.LeftButton:
            current = event.globalPosition().toPoint()
            if not self._moved and (current - self._press).manhattanLength() > 4:
                self._moved = True
                self.dragStarted.emit()
            if self._moved:
                self.dragMoved.emit(current - self._press)
                self._press = current
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._press is not None:
            moved = self._moved
            self._press = None
            if moved:
                self.dragFinished.emit()
            elif self.rect().contains(event.position().toPoint()):
                self._queue_reveal()
            event.accept()
        else:
            super().mouseReleaseEvent(event)

    def contextMenuEvent(self, event):
        self._hover_generation += 1
        self.menuRequested.emit(event.globalPos())
        event.accept()
