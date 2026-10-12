"""Window-local resize handles for a frameless Qt surface."""
from PySide6.QtCore import QEvent, QObject, QPoint, QRect, QSize, Qt
from PySide6.QtWidgets import QWidget


def edges_at(position: QPoint, size: QSize, margin: int = 6) -> Qt.Edge:
    """Return the edges in the inner margin, or no edges outside the window."""
    x, y = position.x(), position.y()
    width, height = size.width(), size.height()
    edges = Qt.Edge(0)
    if margin <= 0 or not (0 <= x < width and 0 <= y < height):
        return edges
    if x < margin:
        edges |= Qt.Edge.LeftEdge
    elif x >= width - margin:
        edges |= Qt.Edge.RightEdge
    if y < margin:
        edges |= Qt.Edge.TopEdge
    elif y >= height - margin:
        edges |= Qt.Edge.BottomEdge
    return edges


def cursor_for_edges(edges: Qt.Edge) -> Qt.CursorShape:
    """Map all four edges and four corners to their standard resize cursors."""
    horizontal = edges & (Qt.Edge.LeftEdge | Qt.Edge.RightEdge)
    vertical = edges & (Qt.Edge.TopEdge | Qt.Edge.BottomEdge)
    if horizontal and vertical:
        if edges in (
            Qt.Edge.LeftEdge | Qt.Edge.TopEdge,
            Qt.Edge.RightEdge | Qt.Edge.BottomEdge,
        ):
            return Qt.CursorShape.SizeFDiagCursor
        return Qt.CursorShape.SizeBDiagCursor
    if horizontal:
        return Qt.CursorShape.SizeHorCursor
    if vertical:
        return Qt.CursorShape.SizeVerCursor
    return Qt.CursorShape.ArrowCursor


def resized_geometry(
    initial: QRect, delta: QPoint, edges: Qt.Edge, minimum: QSize,
    maximum: QSize | None = None,
) -> QRect:
    """Resize from an initial rectangle, keeping the opposite sides anchored."""
    x, y, width, height = initial.getRect()
    if edges & Qt.Edge.LeftEdge:
        width -= delta.x()
    elif edges & Qt.Edge.RightEdge:
        width += delta.x()
    if edges & Qt.Edge.TopEdge:
        height -= delta.y()
    elif edges & Qt.Edge.BottomEdge:
        height += delta.y()
    if edges & (Qt.Edge.LeftEdge | Qt.Edge.RightEdge):
        width = max(minimum.width(), width)
        if maximum is not None:
            width = min(maximum.width(), width)
    if edges & (Qt.Edge.TopEdge | Qt.Edge.BottomEdge):
        height = max(minimum.height(), height)
        if maximum is not None:
            height = min(maximum.height(), height)
    if edges & Qt.Edge.LeftEdge:
        x = initial.x() + initial.width() - width
    if edges & Qt.Edge.TopEdge:
        y = initial.y() + initial.height() - height
    return QRect(x, y, width, height)


class EdgeResize(QObject):
    """Own eight transparent edge strips; controls and other windows stay untouched.

    Instantiate after creating the window's layout and keep this controller on
    the window. Layout margins must leave the resize strip clear of controls.
    Qt's native resize is preferred; a captured mouse drag is the fallback.
    """

    def __init__(self, window: QWidget, margin: int = 6):
        super().__init__(window)
        if margin < 1:
            raise ValueError("Resize margin must be positive.")
        self.window = window
        self.margin = margin
        self._active_grip = None
        self._drag_edges = Qt.Edge(0)
        self._drag_start = QPoint()
        self._drag_geometry = QRect()
        self._grips = {}
        for edges in (
            Qt.Edge.LeftEdge, Qt.Edge.RightEdge, Qt.Edge.TopEdge, Qt.Edge.BottomEdge,
            Qt.Edge.LeftEdge | Qt.Edge.TopEdge,
            Qt.Edge.RightEdge | Qt.Edge.TopEdge,
            Qt.Edge.LeftEdge | Qt.Edge.BottomEdge,
            Qt.Edge.RightEdge | Qt.Edge.BottomEdge,
        ):
            grip = QWidget(window)
            grip.setObjectName("resizeGrip")
            grip.setStyleSheet("background: transparent; border: none;")
            grip.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            grip.setCursor(cursor_for_edges(edges))
            grip.setMouseTracking(True)
            grip.installEventFilter(self)
            self._grips[edges] = grip
        window.installEventFilter(self)
        self._layout_grips()

    def _layout_grips(self):
        width, height = self.window.width(), self.window.height()
        margin = self.margin
        rectangles = {
            Qt.Edge.LeftEdge: QRect(0, margin, margin, max(0, height - 2 * margin)),
            Qt.Edge.RightEdge: QRect(width - margin, margin, margin, max(0, height - 2 * margin)),
            Qt.Edge.TopEdge: QRect(margin, 0, max(0, width - 2 * margin), margin),
            Qt.Edge.BottomEdge: QRect(margin, height - margin, max(0, width - 2 * margin), margin),
            Qt.Edge.LeftEdge | Qt.Edge.TopEdge: QRect(0, 0, margin, margin),
            Qt.Edge.RightEdge | Qt.Edge.TopEdge: QRect(width - margin, 0, margin, margin),
            Qt.Edge.LeftEdge | Qt.Edge.BottomEdge: QRect(0, height - margin, margin, margin),
            Qt.Edge.RightEdge | Qt.Edge.BottomEdge: QRect(width - margin, height - margin, margin, margin),
        }
        resizable = not (self.window.isMaximized() or self.window.isFullScreen())
        for edges, grip in self._grips.items():
            grip.setGeometry(rectangles[edges])
            grip.setVisible(resizable)
            grip.raise_()

    def _end_resize(self):
        grip = self._active_grip
        self._active_grip = None
        self._drag_edges = Qt.Edge(0)
        if grip is not None and QWidget.mouseGrabber() is grip:
            grip.releaseMouse()

    def _begin_resize(self, grip, event):
        self._end_resize()
        position = event.globalPosition().toPoint()
        edges = edges_at(self.window.mapFromGlobal(position), self.window.size(), self.margin)
        if not edges:
            return False
        handle = self.window.windowHandle()
        if handle is not None and handle.startSystemResize(edges):
            # Native resizing owns the gesture and may swallow its release.
            return True
        self._active_grip = grip
        self._drag_edges = edges
        self._drag_start = position
        self._drag_geometry = self.window.geometry()
        grip.grabMouse()
        return True

    def eventFilter(self, watched, event):
        event_type = event.type()
        if watched is self.window:
            if event_type in (QEvent.Type.Resize, QEvent.Type.Show, QEvent.Type.WindowStateChange):
                self._layout_grips()
            elif event_type in (QEvent.Type.WindowDeactivate, QEvent.Type.Hide, QEvent.Type.Close):
                self._end_resize()
            return False
        if event_type == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
            if self._begin_resize(watched, event):
                event.accept()
                return True
        elif event_type == QEvent.Type.MouseMove and watched is self._active_grip:
            if event.buttons() & Qt.MouseButton.LeftButton:
                delta = event.globalPosition().toPoint() - self._drag_start
                self.window.setGeometry(resized_geometry(
                    self._drag_geometry, delta, self._drag_edges,
                    self.window.minimumSize(), self.window.maximumSize(),
                ))
                event.accept()
                return True
            self._end_resize()
        elif event_type == QEvent.Type.MouseButtonRelease and event.button() == Qt.MouseButton.LeftButton:
            if self._active_grip is not None:
                self._end_resize()
                event.accept()
                return True
        elif event_type == QEvent.Type.UngrabMouse and watched is self._active_grip:
            self._end_resize()
        return False
