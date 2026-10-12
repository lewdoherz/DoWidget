import pytest
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLineEdit

from dowidget.app import STYLE, Widget
from dowidget.models import ProviderError


@pytest.fixture
def compact_widget(tmp_path):
    app = QApplication.instance() or QApplication([])
    previous_style = app.styleSheet()
    app.setStyleSheet(STYLE)
    widget = Widget(tmp_path, demo=True)
    widget.show()
    widget.toggle_view()
    QTest.qWait(20)
    try:
        yield widget
    finally:
        if not widget.closing:
            widget.close()
        app.processEvents()
        app.setStyleSheet(previous_style)


def test_reload_icon_recovers_stale_demo_state_without_switching_view(compact_widget):
    widget = compact_widget
    state = widget.runtime.accounts["deepseek-default"].state
    state.fail(ProviderError("Offline demo.", "network"), 1, 300)
    widget.render()
    assert state.status == "stale"
    assert widget.refresh_button.text() == ""
    QTest.mouseClick(widget.refresh_button, Qt.MouseButton.LeftButton)
    assert state.status == "ready"
    assert state.message == ""
    assert widget.config.view == "compact"
    assert state.snapshot.demo


def test_cog_opens_masked_settings_and_view_button_restores_detailed(compact_widget):
    widget = compact_widget
    assert "DoWidget" not in widget.header.text()
    assert widget.settings_button.text() == ""
    QTest.mouseClick(widget.settings_button, Qt.MouseButton.LeftButton)
    assert widget.settings.isVisible()
    assert widget.settings.key.echoMode() == QLineEdit.EchoMode.Password
    widget.settings.accept()
    QTest.mouseClick(widget.view_button, Qt.MouseButton.LeftButton)
    assert widget.config.view == "detailed"
    assert widget.refresh_button.text() == "Refresh"
    assert widget.settings_button.text() == "Settings"
    assert "DoWidget" in widget.header.text()


def test_translucent_margins_remain_hit_testable_and_rows_remain_opaque(compact_widget):
    widget = compact_widget
    image = widget.grab().toImage()
    assert image.hasAlphaChannel()
    assert 0 < image.pixelColor(3, 3).alpha() < 255
    card = widget.compact_cards["deepseek-default"].grab().toImage()
    assert card.pixelColor(card.width() // 2, card.height() // 2).alpha() == 255


def test_translucent_fallback_drag_resizes_without_losing_capture(compact_widget, monkeypatch):
    widget = compact_widget
    monkeypatch.setattr(widget, "windowHandle", lambda: None)
    original = widget.geometry()
    grip = widget.edge_resize._grips[Qt.Edge.RightEdge | Qt.Edge.BottomEdge]
    start = grip.mapToGlobal(grip.rect().center())
    end = start + QPoint(40, 30)
    for event_type, position, button, buttons in (
        (QEvent.Type.MouseButtonPress, start, Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton),
        (QEvent.Type.MouseMove, end, Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton),
        (QEvent.Type.MouseButtonRelease, end, Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton),
    ):
        event = QMouseEvent(event_type, QPointF(grip.mapFromGlobal(position)), QPointF(position),
                            button, buttons, Qt.KeyboardModifier.NoModifier)
        QApplication.sendEvent(grip, event)
    assert widget.width() == original.width() + 40
    assert widget.height() == original.height() + 30
    assert widget.pos() == original.topLeft()
    assert widget.edge_resize._active_grip is None
