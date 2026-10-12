"""Optional native tray access without stopping the widget's refresh lifecycle."""
from PySide6.QtCore import QObject, QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QMenu, QSystemTrayIcon, QWidget


class TrayController(QObject):
    """Hide only while a native tray can provide a route back to the widget."""

    def __init__(self, window: QWidget, icon: QIcon):
        super().__init__(window)
        self.window = window
        self._enabled = False
        self._hidden = False
        self._closed = False
        self.menu = QMenu(window)
        self.menu.addAction("Show widget", self.restore)
        self.menu.addAction("Refresh", self._refresh)
        self.menu.addAction("Settings", self._settings)
        self.menu.addSeparator()
        self.menu.addAction("Quit", self._quit)
        self.tray = QSystemTrayIcon(icon, self)
        self.tray.setToolTip("DoWidget")
        self.tray.setContextMenu(self.menu)
        self.tray.activated.connect(self._activated)
        self._probe = QTimer(self)
        self._probe.setInterval(2000)
        self._probe.timeout.connect(self._check_tray)

    @property
    def available(self) -> bool:
        return QSystemTrayIcon.isSystemTrayAvailable()

    def set_enabled(self, enabled: bool) -> None:
        if self._closed:
            return
        self._enabled = enabled
        if enabled and self.available:
            self.tray.show()
        else:
            if self._hidden:
                self.restore()
            self.tray.hide()

    def minimize(self) -> bool:
        if self._closed or not self._enabled or not self.available:
            if self._hidden:
                self.restore()
            return False
        self.tray.show()
        if not self.tray.isVisible():
            if self._hidden:
                self.restore()
            return False
        if self._hidden:
            return True
        # Settings is a child dialog: close it before hiding its owner rather
        # than leaving a modal or orphaned dialog with no accessible parent.
        settings = getattr(self.window, "settings", None)
        if settings is not None and settings.isVisible() and not settings.close():
            return False
        save_position = getattr(self.window, "save_position", None)
        if save_position is not None:
            save_position()
        # Closing a dialog can enter application callbacks; check again before
        # removing the only ordinary route back to the window.
        if not self.available or not self.tray.isVisible():
            return False
        self._hidden = True
        self.window.hide()
        self._probe.start()
        return True

    def restore(self) -> None:
        if self._closed:
            return
        self._probe.stop()
        self._hidden = False
        self.window.showNormal()
        self.window.raise_()
        self.window.activateWindow()

    def close(self) -> None:
        """Remove tray resources; the window owns its own shutdown and close."""
        self._closed = True
        self._enabled = False
        self._hidden = False
        self._probe.stop()
        self.menu.hide()
        self.tray.hide()

    def _check_tray(self) -> None:
        if self._hidden and (not self.available or not self.tray.isVisible()):
            self.restore()
            self.tray.hide()

    def _activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            self.restore()

    def _refresh(self) -> None:
        if not self._closed:
            self.window.refresh(True)

    def _settings(self) -> None:
        if not self._closed:
            self.restore()
            self.window.open_settings()

    def _quit(self) -> None:
        if not self._closed:
            self.window.close()
