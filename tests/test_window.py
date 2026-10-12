import pytest
from PySide6.QtCore import QPoint, QRect, QSize, Qt

from dowidget.window import cursor_for_edges, edges_at, resized_geometry


LEFT = Qt.Edge.LeftEdge
RIGHT = Qt.Edge.RightEdge
TOP = Qt.Edge.TopEdge
BOTTOM = Qt.Edge.BottomEdge


@pytest.mark.parametrize("position,edges", [
    ((0, 40), LEFT), ((5, 40), LEFT),
    ((99, 40), RIGHT), ((94, 40), RIGHT),
    ((40, 0), TOP), ((40, 5), TOP),
    ((40, 79), BOTTOM), ((40, 74), BOTTOM),
    ((0, 0), LEFT | TOP), ((99, 0), RIGHT | TOP),
    ((0, 79), LEFT | BOTTOM), ((99, 79), RIGHT | BOTTOM),
    ((6, 6), Qt.Edge(0)), ((93, 73), Qt.Edge(0)),
    ((50, 40), Qt.Edge(0)),
])
def test_edges_at_six_pixel_margin(position, edges):
    assert edges_at(QPoint(*position), QSize(100, 80)) == edges


@pytest.mark.parametrize("position", [(-1, 0), (0, -1), (100, 40), (40, 80)])
def test_edges_at_does_not_capture_positions_outside_window(position):
    assert edges_at(QPoint(*position), QSize(100, 80)) == Qt.Edge(0)


def test_edges_at_custom_margin_and_empty_size():
    assert edges_at(QPoint(8, 40), QSize(100, 80), 10) == LEFT
    assert edges_at(QPoint(10, 40), QSize(100, 80), 10) == Qt.Edge(0)
    assert edges_at(QPoint(0, 0), QSize(0, 0)) == Qt.Edge(0)
    assert edges_at(QPoint(0, 0), QSize(100, 80), 0) == Qt.Edge(0)


@pytest.mark.parametrize("edges,cursor", [
    (LEFT, Qt.CursorShape.SizeHorCursor),
    (RIGHT, Qt.CursorShape.SizeHorCursor),
    (TOP, Qt.CursorShape.SizeVerCursor),
    (BOTTOM, Qt.CursorShape.SizeVerCursor),
    (LEFT | TOP, Qt.CursorShape.SizeFDiagCursor),
    (RIGHT | BOTTOM, Qt.CursorShape.SizeFDiagCursor),
    (RIGHT | TOP, Qt.CursorShape.SizeBDiagCursor),
    (LEFT | BOTTOM, Qt.CursorShape.SizeBDiagCursor),
    (Qt.Edge(0), Qt.CursorShape.ArrowCursor),
])
def test_cursor_mapping_for_each_edge_and_corner(edges, cursor):
    assert cursor_for_edges(edges) == cursor


@pytest.mark.parametrize("edges,expected", [
    (LEFT, (120, 200, 380, 300)),
    (RIGHT, (100, 200, 420, 300)),
    (TOP, (100, 230, 400, 270)),
    (BOTTOM, (100, 200, 400, 330)),
    (LEFT | TOP, (120, 230, 380, 270)),
    (RIGHT | TOP, (100, 230, 420, 270)),
    (LEFT | BOTTOM, (120, 200, 380, 330)),
    (RIGHT | BOTTOM, (100, 200, 420, 330)),
    (Qt.Edge(0), (100, 200, 400, 300)),
])
def test_resize_all_directions_keeps_opposite_sides_fixed(edges, expected):
    initial = QRect(100, 200, 400, 300)
    assert resized_geometry(initial, QPoint(20, 30), edges, QSize(100, 100)) == QRect(*expected)
    assert initial == QRect(100, 200, 400, 300)


@pytest.mark.parametrize("minimum", [QSize(340, 280), QSize(260, 130)])
@pytest.mark.parametrize("edges,delta", [
    (LEFT | TOP, QPoint(1000, 1000)),
    (RIGHT | TOP, QPoint(-1000, 1000)),
    (LEFT | BOTTOM, QPoint(1000, -1000)),
    (RIGHT | BOTTOM, QPoint(-1000, -1000)),
])
def test_resize_corner_clamps_to_view_minimum_without_moving_opposite_corner(minimum, edges, delta):
    initial = QRect(-50, -20, 400, 300)
    result = resized_geometry(initial, delta, edges, minimum)
    assert result.size() == minimum
    if edges & LEFT:
        assert result.right() == initial.right()
    else:
        assert result.left() == initial.left()
    if edges & TOP:
        assert result.bottom() == initial.bottom()
    else:
        assert result.top() == initial.top()


@pytest.mark.parametrize("edges,delta,expected", [
    (LEFT, QPoint(-500, 1000), (-150, 200, 650, 300)),
    (RIGHT, QPoint(500, 1000), (100, 200, 650, 300)),
    (TOP, QPoint(1000, -500), (100, 0, 400, 500)),
    (BOTTOM, QPoint(1000, 500), (100, 200, 400, 500)),
])
def test_resize_respects_maximum_and_does_not_change_unselected_axis(edges, delta, expected):
    initial = QRect(100, 200, 400, 300)
    result = resized_geometry(initial, delta, edges, QSize(340, 280), QSize(650, 500))
    assert result == QRect(*expected)


def test_resize_single_axis_does_not_expand_unrelated_axis_to_minimum():
    initial = QRect(10, 20, 400, 100)
    assert resized_geometry(initial, QPoint(10, 1000), RIGHT, QSize(340, 280)) == QRect(10, 20, 410, 100)
