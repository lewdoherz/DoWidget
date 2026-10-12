import pytest
from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QDialog, QSystemTrayIcon, QWidget

from dowidget import tray as tray_module
from dowidget.tray import TrayController


class FakeNativeTray(QObject):
    """Model native availability and registration without depending on a desktop."""

    activated = Signal(object)
    ActivationReason = QSystemTrayIcon.ActivationReason
    native_available = True
    registration_succeeds = True

    def __init__(self, icon, parent):
        super().__init__(parent)
        self.visible = False

    @staticmethod
    def isSystemTrayAvailable():
        return FakeNativeTray.native_available

    def setToolTip(self, text):
        self.tooltip = text

    def setContextMenu(self, menu):
        self.menu = menu

    def show(self):
        self.visible = self.native_available and self.registration_succeeds

    def hide(self):
        self.visible = False

    def isVisible(self):
        return self.visible


class StubWindow(QWidget):
    """Only the window interface needed by the tray; no accounts or providers."""

    def __init__(self):
        super().__init__()
        self.settings = None
        self.controller = None
        self.events = []
        self.saved_position = None
        self.refreshes = 0
        self.closed = False
        self.ticks = 0
        self.refresh_timer = QTimer(self)
        self.refresh_timer.timeout.connect(self.tick)
        self.refresh_timer.start(60_000)

    def tick(self):
        self.ticks += 1

    def save_position(self):
        self.saved_position = self.geometry()
        self.events.append(("save", self.isVisible()))

    def refresh(self, force):
        if force:
            self.refreshes += 1

    def open_settings(self):
        self.events.append(("settings", self.isVisible()))
        self.settings = QDialog(self)
        self.settings.show()

    def closeEvent(self, event):
        self.closed = True
        self.refresh_timer.stop()
        if self.controller is not None:
            self.controller.close()
        event.accept()


@pytest.fixture(scope="module")
def qt_app():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def widget_tray(qt_app, monkeypatch):
    FakeNativeTray.native_available = True
    FakeNativeTray.registration_succeeds = True
    monkeypatch.setattr(tray_module, "QSystemTrayIcon", FakeNativeTray)
    window = StubWindow()
    window.setGeometry(100, 120, 380, 560)
    window.show()
    controller = TrayController(window, QIcon())
    window.controller = controller
    yield window, controller
    controller.close()
    window.close()
    window.deleteLater()


def action(controller, text):
    return next(item for item in controller.menu.actions() if item.text() == text)


def test_hide_preserves_geometry_and_refreshes_then_show_restores(widget_tray):
    window, controller = widget_tray
    geometry = window.geometry()
    controller.set_enabled(True)
    assert controller.tray.isVisible()
    assert controller.minimize() is True
    assert not window.isVisible()
    assert window.saved_position == geometry
    assert window.events == [("save", True)]
    assert window.refresh_timer.isActive()
    window.refresh_timer.timeout.emit()
    assert window.ticks == 1
    action(controller, "Refresh").trigger()
    assert window.refreshes == 1
    assert not window.isVisible()
    action(controller, "Show widget").trigger()
    assert window.isVisible()
    assert not window.isMinimized()
    assert window.geometry() == geometry
    assert not controller._probe.isActive()


@pytest.mark.parametrize("reason", [
    QSystemTrayIcon.ActivationReason.Trigger,
    QSystemTrayIcon.ActivationReason.DoubleClick,
])
def test_native_click_restores_hidden_window(widget_tray, reason):
    window, controller = widget_tray
    controller.set_enabled(True)
    assert controller.minimize()
    controller.tray.activated.emit(reason)
    assert window.isVisible()
    assert not window.isMinimized()


def test_context_activation_leaves_window_hidden(widget_tray):
    window, controller = widget_tray
    controller.set_enabled(True)
    assert controller.minimize()
    controller.tray.activated.emit(QSystemTrayIcon.ActivationReason.Context)
    assert not window.isVisible()


def test_settings_action_restores_before_opening_dialog(widget_tray):
    window, controller = widget_tray
    controller.set_enabled(True)
    assert controller.minimize()
    action(controller, "Settings").trigger()
    assert window.isVisible()
    assert window.events[-1] == ("settings", True)
    assert window.settings.isVisible()


def test_minimize_closes_existing_settings_dialog(widget_tray):
    window, controller = widget_tray
    window.open_settings()
    dialog = window.settings
    controller.set_enabled(True)
    assert controller.minimize()
    assert not dialog.isVisible()
    assert not window.isVisible()
    controller.restore()
    assert window.isVisible()
    action(controller, "Settings").trigger()
    assert window.settings.isVisible()


def test_refused_settings_close_does_not_hide_window(widget_tray):
    class RefusingDialog(QDialog):
        def closeEvent(self, event):
            event.ignore()

    window, controller = widget_tray
    window.settings = RefusingDialog(window)
    window.settings.show()
    controller.set_enabled(True)
    assert controller.minimize() is False
    assert window.isVisible()
    assert window.settings.isVisible()
    assert window.saved_position is None
    assert not controller._probe.isActive()


def test_disabled_tray_leaves_normal_minimize_to_caller(widget_tray):
    window, controller = widget_tray
    assert controller.minimize() is False
    assert window.isVisible()
    assert not controller.tray.isVisible()
    assert window.saved_position is None
    window.showMinimized()
    assert window.isMinimized()


def test_missing_native_tray_never_hides_window(widget_tray):
    window, controller = widget_tray
    FakeNativeTray.native_available = False
    controller.set_enabled(True)
    assert controller.available is False
    assert not controller.tray.isVisible()
    assert controller.minimize() is False
    assert window.isVisible()
    assert window.saved_position is None
    assert not controller._probe.isActive()
    window.showMinimized()
    assert window.isMinimized()


def test_native_tray_disappears_between_enable_and_minimize(widget_tray):
    window, controller = widget_tray
    controller.set_enabled(True)
    FakeNativeTray.native_available = False
    assert controller.minimize() is False
    assert window.isVisible()
    assert window.saved_position is None


def test_tray_disappears_during_geometry_save_before_hide(widget_tray, monkeypatch):
    window, controller = widget_tray
    save_position = window.save_position

    def save_then_lose_tray():
        save_position()
        FakeNativeTray.native_available = False

    monkeypatch.setattr(window, "save_position", save_then_lose_tray)
    controller.set_enabled(True)
    assert controller.minimize() is False
    assert window.isVisible()
    assert window.saved_position is not None
    assert not controller._probe.isActive()


def test_failed_tray_registration_does_not_hide_window(widget_tray):
    window, controller = widget_tray
    FakeNativeTray.registration_succeeds = False
    controller.set_enabled(True)
    assert controller.minimize() is False
    assert window.isVisible()
    assert window.saved_position is None


@pytest.mark.parametrize("failure", ["native", "icon"])
def test_hidden_window_recovers_when_native_tray_disappears(widget_tray, failure):
    window, controller = widget_tray
    controller.set_enabled(True)
    assert controller.minimize()
    assert controller._probe.isActive()
    if failure == "native":
        FakeNativeTray.native_available = False
    else:
        controller.tray.hide()
    controller._probe.timeout.emit()
    assert window.isVisible()
    assert not window.isMinimized()
    assert not controller.tray.isVisible()
    assert not controller._probe.isActive()
    assert window.refresh_timer.isActive()


def test_disabling_hidden_tray_restores_window_and_stops_probe(widget_tray):
    window, controller = widget_tray
    controller.set_enabled(True)
    assert controller.minimize()
    controller.set_enabled(False)
    assert window.isVisible()
    assert not controller.tray.isVisible()
    assert not controller._probe.isActive()
    assert controller.minimize() is False
    assert window.refresh_timer.isActive()


def test_rechecking_unavailable_tray_restores_hidden_window(widget_tray):
    window, controller = widget_tray
    controller.set_enabled(True)
    assert controller.minimize()
    FakeNativeTray.native_available = False
    controller.set_enabled(True)
    assert window.isVisible()
    assert not controller.tray.isVisible()


def test_tray_recovers_after_native_support_returns(widget_tray):
    window, controller = widget_tray
    FakeNativeTray.native_available = False
    controller.set_enabled(True)
    assert controller.minimize() is False
    FakeNativeTray.native_available = True
    assert controller.available is True
    assert controller.minimize() is True
    assert not window.isVisible()
    controller.restore()
    assert window.isVisible()


def test_quit_closes_hidden_window_and_its_lifecycle(widget_tray):
    window, controller = widget_tray
    controller.set_enabled(True)
    assert controller.minimize()
    action(controller, "Quit").trigger()
    assert window.closed
    assert not window.isVisible()
    assert not window.refresh_timer.isActive()
    assert not controller.tray.isVisible()
    assert not controller._probe.isActive()
    controller.tray.activated.emit(QSystemTrayIcon.ActivationReason.Trigger)
    assert not window.isVisible()


def test_controller_close_removes_tray_without_closing_window(widget_tray):
    window, controller = widget_tray
    controller.set_enabled(True)
    controller.close()
    assert window.isVisible()
    assert not window.closed
    assert window.refresh_timer.isActive()
    assert not controller.tray.isVisible()
    assert controller.minimize() is False
    controller.set_enabled(True)
    assert not controller.tray.isVisible()


def test_controller_close_while_hidden_does_not_reopen_window(widget_tray):
    window, controller = widget_tray
    controller.set_enabled(True)
    assert controller.minimize()
    controller.close()
    assert not window.isVisible()
    assert not window.closed
    assert not controller.tray.isVisible()
    assert not controller._probe.isActive()
    controller.tray.activated.emit(QSystemTrayIcon.ActivationReason.DoubleClick)
    action(controller, "Show widget").trigger()
    action(controller, "Settings").trigger()
    action(controller, "Refresh").trigger()
    action(controller, "Quit").trigger()
    assert not window.isVisible()
    assert not window.closed
    assert window.settings is None
    assert window.refreshes == 0


def test_minimize_also_works_without_optional_geometry_saver(qt_app, monkeypatch):
    monkeypatch.setattr(tray_module, "QSystemTrayIcon", FakeNativeTray)
    FakeNativeTray.native_available = True
    FakeNativeTray.registration_succeeds = True
    window = QWidget()
    window.show()
    controller = TrayController(window, QIcon())
    try:
        controller.set_enabled(True)
        assert controller.minimize() is True
        assert not window.isVisible()
        controller.restore()
        assert window.isVisible()
    finally:
        controller.close()
        window.close()
        window.deleteLater()
