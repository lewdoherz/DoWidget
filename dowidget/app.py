"""Native desktop surface; provider work stays off the GUI thread."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from html import escape
from pathlib import Path
import re
import sys
import time

from PySide6.QtCore import QEvent, QObject, QPoint, QSize, QStandardPaths, Qt, QTimer, Signal
from PySide6.QtGui import QCloseEvent, QColor, QFont, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QDialog, QFormLayout, QFrame, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QScrollArea, QSpinBox,
    QSizePolicy, QStackedWidget, QVBoxLayout, QWidget,
)

from .icons import app_icon, control_icon
from .models import Balance, ProviderError, Snapshot, UsageWindow
from .providers import CodexProvider, DeepSeekProvider
from .state import ProviderState
from .storage import ConfigStore, CredentialStore
from .window import EdgeResize
from .tray import TrayController


STYLE = """
QWidget { background: #161c27; color: #e8eef8; font-size: 13px; }
QWidget#widgetShell { background: rgba(22, 28, 39, 24); }
QWidget#providerContent, QWidget#providerStack, QWidget#providerViewport, QScrollArea#providerScroll { background: transparent; border: none; }
QPushButton#compactControl { background: transparent; border: none; border-radius: 4px; padding: 2px; }
QPushButton#compactControl:hover { background: rgba(75, 96, 128, 140); }
QPushButton#compactControl:pressed { background: rgba(75, 96, 128, 200); }
QPushButton#compactControl:disabled { background: transparent; }
QFrame#card { background: #222c3b; border: 1px solid #35445b; border-radius: 10px; }
QFrame#card QLabel { background: transparent; border: none; }
QLabel#title { font-size: 17px; font-weight: 600; }
QLabel#amount { font-size: 23px; font-weight: 600; color: #95dfcb; }
QLabel#muted { color: #b5c3d8; }
QLabel#compactAmount { font-size: 16px; font-weight: 600; color: #95dfcb; }
QFrame#compactCard { background: #222c3b; border: 1px solid #35445b; border-radius: 6px; }
QFrame#compactCard QLabel { background: transparent; border: none; }
QLabel#warning { color: #ffd28a; }
QPushButton { background: #304159; border: 1px solid #4b6080; border-radius: 5px; padding: 6px 10px; }
QPushButton:hover { background: #405777; }
QPushButton:disabled { color: #8996aa; background: #232d3d; }
QLineEdit, QSpinBox { background: #222c3b; padding: 6px; border: 1px solid #4b6080; border-radius: 4px; }
QCheckBox { spacing: 8px; }
QScrollArea { border: none; }
"""


def label(text, name="", wrap=True):
    result = QLabel(text)
    result.setTextFormat(Qt.TextFormat.PlainText)
    result.setWordWrap(wrap)
    result.setObjectName(name)
    return result


def local_time(value):
    return value.astimezone().strftime("%b %d, %H:%M %z")


def connection_status(state):
    status = "Connected" if state.status == "ready" else state.status.replace("_", " ").capitalize()
    if state.busy:
        status = "Updating · stale" if state.status == "stale" else "Updating"
    if state.snapshot and state.snapshot.demo:
        status = "DEMO · " + status
    return status


def compact_window_name(name):
    """Shorten only adapter-defined duration labels; preserve unfamiliar labels."""
    match = re.fullmatch(r"(.+) · (primary|secondary) \((\d+(?:\.\d+)?) (minute|hour|day|week)\)", name)
    if match:
        bucket, slot, value, unit = match.groups()
        duration = "Week" if value == "1" and unit == "week" else value + {"minute": "m", "hour": "h", "day": "d", "week": "w"}[unit]
        return duration if bucket.lower() == "codex" else f"{bucket} {duration}"
    if name == "Codex · 5-hour window":
        return "5h"
    if name == "Codex · weekly window":
        return "Week"
    return name.removeprefix("codex · ").removeprefix("Codex · ")


def provider_tooltip(state, title=""):
    lines = ([title] if title else []) + [connection_status(state)]
    if state.message:
        lines.append(state.message)
    snapshot = state.snapshot
    if snapshot:
        for balance in snapshot.balances:
            lines.append(f"Total: {balance.currency} {balance.total:f}")
            if balance.granted is not None:
                lines.append(f"Granted: {balance.currency} {balance.granted:f}")
            if balance.topped_up is not None:
                lines.append(f"Topped up: {balance.currency} {balance.topped_up:f}")
        for window in snapshot.windows:
            value = "Unknown" if window.remaining is None else f"{window.remaining:.1f}% remaining"
            lines.append(f"{window.name}: {value}")
            if window.resets_at:
                lines.append(f"Resets: {local_time(window.resets_at)}")
        if snapshot.note:
            lines.append(snapshot.note)
    lines.append("Last successful update: " + (local_time(state.updated_at) if state.updated_at else "Never"))
    # Qt detects rich-text tooltips. Escape upstream labels before showing them.
    return "<qt>" + "<br>".join(escape(line) for line in lines) + "</qt>"


class Jobs(QObject):
    finished = Signal(str, object, object)

    def __init__(self, parent):
        super().__init__(parent)
        self.executors = {key: ThreadPoolExecutor(max_workers=1, thread_name_prefix=key)
                          for key in ("deepseek", "codex")}

    def submit(self, key, operation, function):
        future = self.executors[key].submit(function)

        def complete(done):
            try:
                self.finished.emit(operation, done.result(), None)
            except ProviderError as error:
                self.finished.emit(operation, None, error)
            except Exception:
                self.finished.emit(operation, None, ProviderError("Operation failed. Please retry."))
        future.add_done_callback(complete)

    def shutdown(self):
        for executor in self.executors.values():
            executor.shutdown(wait=False, cancel_futures=True)


class DragHeader(QLabel):
    """Explicit drag target; ordinary controls remain clickable."""
    def __init__(self, window):
        super().__init__("DoWidget", window)
        self.setObjectName("title")
        self.setCursor(Qt.CursorShape.SizeAllCursor)
        self.setToolTip("Drag the header to move; drag an edge or corner to resize.")
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.offset = None

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            handle = self.window().windowHandle()
            if handle and handle.startSystemMove():
                return
            self.offset = event.globalPosition().toPoint() - self.window().pos()

    def mouseMoveEvent(self, event):
        if self.offset is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.window().move(event.globalPosition().toPoint() - self.offset)

    def mouseReleaseEvent(self, event):
        self.offset = None
        self.window().save_position()


class ProviderCard(QFrame):
    def __init__(self, title):
        super().__init__()
        self.setObjectName("card")
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(14, 12, 14, 12)
        self.layout.setSpacing(7)
        self.layout.addWidget(label(title, "title"))
        self.content = QVBoxLayout()
        self.layout.addLayout(self.content)

    def render(self, state):
        while self.content.count():
            item = self.content.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        snapshot = state.snapshot
        status = connection_status(state)
        self.content.addWidget(label(status, "warning" if state.status == "stale" or snapshot and snapshot.demo else "muted"))
        if snapshot:
            for balance in snapshot.balances:
                self.content.addWidget(label(f"{balance.currency} {format(balance.total, 'f')}", "amount"))
                self.content.addWidget(label("Total available balance", "muted"))
                parts = []
                if balance.granted is not None:
                    parts.append(f"Granted {balance.currency} {format(balance.granted, 'f')}")
                if balance.topped_up is not None:
                    parts.append(f"Topped up {balance.currency} {format(balance.topped_up, 'f')}")
                if parts:
                    self.content.addWidget(label(" · ".join(parts), "muted"))
            for window in snapshot.windows:
                self.content.addWidget(label(window.name, "muted"))
                amount = "Unknown allowance" if window.remaining is None else f"{window.remaining:.1f}% remaining"
                self.content.addWidget(label(amount, "amount"))
                if window.resets_at:
                    self.content.addWidget(label(f"Resets {local_time(window.resets_at)}", "muted"))
            if snapshot.note:
                self.content.addWidget(label(snapshot.note, "muted"))
        else:
            self.content.addWidget(label("—", "amount"))
        if state.message:
            self.content.addWidget(label(state.message, "warning"))
        updated = local_time(state.updated_at) if state.updated_at else "Never"
        self.content.addWidget(label(f"Last success: {updated}", "muted"))


class CompactCard(QFrame):
    def __init__(self, provider, title):
        super().__init__()
        self.title = title
        self.setObjectName("compactCard")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(7, 5, 7, 5)
        layout.setSpacing(8)
        logo = label("", wrap=False)
        logo.setFixedSize(34, 34)
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        # Original marks are neither recolored nor distorted. A neutral tile
        # keeps an official dark OpenAI mark legible on the dark widget.
        logo.setStyleSheet("background: #ffffff; border-radius: 4px;")
        pixmap = QPixmap(str(Path(__file__).parent / "assets" / f"{provider}.png"))
        logo.setPixmap(pixmap.scaled(28, 28, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        logo.setAccessibleName(title)
        layout.addWidget(logo)
        self.value = label("—", "compactAmount")
        self.value.setMinimumWidth(0)
        self.value.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        layout.addWidget(self.value, 1)
        self.indicator = label("?", wrap=False)
        self.indicator.setFixedWidth(16)
        self.indicator.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.indicator)

    def render(self, state):
        snapshot = state.snapshot
        values = []
        if snapshot:
            values.extend(f"{balance.currency} {balance.total:f}" for balance in snapshot.balances)
            names = [compact_window_name(window.name) for window in snapshot.windows]
            values.extend(f"{name if names.count(name) == 1 else window.name}: " +
                          ("Unknown" if window.remaining is None else f"{window.remaining:.1f}%")
                          for name, window in zip(names, snapshot.windows))
        self.value.setText(" · ".join(values) if values else "—")
        self.value.setAccessibleName(self.title + ": " + self.value.text())
        status = connection_status(state)
        if state.status == "stale":
            mark, color = "!", "#ffd28a"
        elif snapshot and snapshot.demo:
            mark, color = "D", "#ffd28a"
        elif state.busy:
            mark, color = "↻", "#b5c3d8"
        elif state.status == "ready":
            mark, color = "●", "#95dfcb"
        elif state.status == "setup_required":
            mark, color = "?", "#b5c3d8"
        else:
            mark, color = "!", "#ff9c9c"
        self.indicator.setText(mark)
        self.indicator.setStyleSheet(f"color: {color}; font-weight: 600;")
        self.indicator.setAccessibleName(status)
        tooltip = provider_tooltip(state, self.title)
        self.setToolTip(tooltip)
        self.value.setToolTip(tooltip)
        self.indicator.setToolTip(tooltip)


class Settings(QDialog):
    def __init__(self, window):
        super().__init__(window)
        self.owner = window
        self.setWindowTitle("DoWidget settings")
        self.setMinimumWidth(430)
        self.resize(450, min(800, QApplication.primaryScreen().availableGeometry().height() - 80))
        outer = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        layout = QVBoxLayout(content)
        scroll.setWidget(content)
        outer.addWidget(scroll)
        layout.addWidget(label("DeepSeek API balance", "title"))
        layout.addWidget(label("Enter your own API key. Keys are masked and never saved in the configuration file.", "muted"))
        self.key = QLineEdit()
        self.key.setEchoMode(QLineEdit.EchoMode.Password)
        self.key.setPlaceholderText("Enter new DeepSeek API key")
        layout.addWidget(self.key)
        self.persist = QCheckBox("Remember in operating system credential store")
        self.persist.setChecked(window.credentials.available)
        self.persist.setEnabled(window.credentials.available)
        layout.addWidget(self.persist)
        self.storage_info = label(window.credentials.status, "muted")
        layout.addWidget(self.storage_info)
        buttons = QHBoxLayout()
        self.connect = QPushButton("Connect / replace key")
        self.disconnect = QPushButton("Disconnect DeepSeek")
        buttons.addWidget(self.connect)
        buttons.addWidget(self.disconnect)
        layout.addLayout(buttons)
        self.connect.clicked.connect(self.connect_deepseek)
        self.disconnect.clicked.connect(self.disconnect_deepseek)
        layout.addWidget(label("Codex subscription allowance", "title"))
        layout.addWidget(label("Requires the official Codex CLI and a ChatGPT subscription sign-in. DoWidget uses its own isolated sign-in, not credentials from other apps. This is not general ChatGPT message usage or OpenAI API billing.", "muted"))
        layout.addWidget(label("The app-server command is documented as experimental and not supported for production workloads. DoWidget uses stdio and stable account methods, not experimental API opt-in. This caveat concerns integration support—not the subscription or the accuracy of service-reported percentages. CLI/API changes may require a DoWidget update.", "warning"))
        layout.addWidget(label("Sign-in uses the OS credential store when available; otherwise it lasts only for this session. No browser cookies are collected.", "muted"))
        self.codex_persist = QCheckBox("Remember Codex sign-in in OS credential store")
        self.codex_persist.setChecked(window.credentials.available)
        self.codex_persist.setEnabled(window.credentials.available)
        layout.addWidget(self.codex_persist)
        buttons = QHBoxLayout()
        self.login = QPushButton("Sign in with ChatGPT")
        self.logout = QPushButton("Disconnect Codex")
        buttons.addWidget(self.login)
        buttons.addWidget(self.logout)
        layout.addLayout(buttons)
        self.login.clicked.connect(window.login_codex)
        self.logout.clicked.connect(window.logout_codex)
        layout.addWidget(label("Widget behavior", "title"))
        form = QFormLayout()
        self.interval = QSpinBox()
        self.interval.setRange(1, 1440)
        self.interval.setSuffix(" minutes")
        self.interval.setValue(window.config.interval_minutes)
        form.addRow("Refresh interval", self.interval)
        self.auto = QCheckBox("Automatically refresh")
        self.auto.setChecked(window.config.auto_refresh)
        form.addRow(self.auto)
        self.top = QCheckBox("Always on top")
        self.top.setChecked(window.config.always_on_top)
        form.addRow(self.top)
        self.minimize_tray = QCheckBox("Minimize to system tray")
        self.minimize_tray.setChecked(window.config.minimize_to_tray)
        form.addRow(self.minimize_tray)
        form.addRow(label("Tray click restores the widget; its menu has Show, Refresh, Settings, and Quit. If no tray is available, normal taskbar minimization is used.", "muted"))
        layout.addLayout(form)
        layout.addWidget(label("Failed requests retain the last value as stale. Automatic and manual refresh respect failure backoff.", "muted"))
        self.info = label("", "warning")
        layout.addWidget(self.info)
        apply = QPushButton("Save behavior")
        apply.clicked.connect(self.save_behavior)
        layout.addWidget(apply)
        close = QPushButton("Close settings")
        close.clicked.connect(self.accept)
        layout.addWidget(close)
        self.update_controls()

    def update_controls(self):
        w = self.owner
        self.connect.setEnabled(not w.states["deepseek"].busy and not w.demo)
        self.disconnect.setEnabled(not w.states["deepseek"].busy and not w.demo)
        self.login.setEnabled(not w.states["codex"].busy and not w.demo)
        self.logout.setEnabled(not w.states["codex"].busy and not w.demo)
        self.storage_info.setText(w.credentials.status)
        self.info.setText(w.notice.text())

    def connect_deepseek(self):
        key = self.key.text().strip()
        if not key:
            self.info.setText("Enter an API key first.")
            return
        try:
            status = self.owner.credentials.connect(key, self.persist.isChecked())
            self.owner.key = key
            self.key.clear()
            self.owner.states["deepseek"].reset()
            self.owner.notice.setText(status)
            self.owner.refresh(True)
        except ProviderError as error:
            self.storage_info.setText(self.owner.credentials.status)
            self.info.setText(f"{error} Uncheck Remember to try session-only storage.")

    def disconnect_deepseek(self):
        try:
            self.owner.credentials.disconnect()
            self.owner.key = None
            self.owner.states["deepseek"].reset(message="Connect your API key in settings.")
            self.owner.notice.setText("DeepSeek disconnected.")
            self.owner.render()
        except ProviderError as error:
            self.info.setText(str(error))

    def save_behavior(self):
        w = self.owner
        w.config.interval_minutes = self.interval.value()
        w.config.auto_refresh = self.auto.isChecked()
        w.config.always_on_top = self.top.isChecked()
        w.config.minimize_to_tray = self.minimize_tray.isChecked()
        if w.save_config():
            w.tray.set_enabled(w.config.minimize_to_tray)
            w.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, w.config.always_on_top)
            w.show()
            now = time.monotonic()
            for state in w.states.values():
                if state.status == "ready":
                    state.next_due = now + w.config.interval_minutes * 60
            self.info.setText("Behavior saved.")


class Widget(QWidget):
    def __init__(self, data_dir: Path, demo=False):
        super().__init__()
        self._geometry_ready = False
        self._changing_view = False
        self.demo = demo
        self.setWindowTitle("DoWidget" + (" — DEMO" if demo else ""))
        self.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint)
        self.setObjectName("widgetShell")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        self.setWindowIcon(app_icon())
        self.data_dir = data_dir
        self.config_store = ConfigStore(data_dir / "settings.json")
        self.config = self.config_store.load()
        self.geometry_timer = QTimer(self)
        self.geometry_timer.setSingleShot(True)
        self.geometry_timer.setInterval(300)
        self.geometry_timer.timeout.connect(self.save_position)
        self.credentials = CredentialStore()
        self.key = None if demo else self.credentials.get()
        self.deepseek = DeepSeekProvider()
        self.codex = CodexProvider(data_dir / "codex", persistent=self.credentials.available)
        self.codex_persistent = self.credentials.available
        self.states = {"deepseek": ProviderState(), "codex": ProviderState()}
        self.states["deepseek"].reset(message="Connect your API key in settings.")
        self.states["codex"].reset(message="Install the official Codex CLI, then sign in through settings. General ChatGPT message limits are not supplied by this integration.")
        self.jobs = Jobs(self)
        self.jobs.finished.connect(self.completed)
        self.settings = None
        self.closing = False
        outer = QVBoxLayout(self)
        outer.setContentsMargins(6, 6, 6, 6)
        self.body = QFrame(self)
        self.body.setObjectName("widgetBody")
        outer.addWidget(self.body)
        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(6, 6, 6, 6)
        self.body_layout.setSpacing(4)
        root = self.body_layout
        header = QHBoxLayout()
        header.setSpacing(5)
        self.header = DragHeader(self)
        header.addWidget(self.header, 1)
        self.view_button = QPushButton("Compact")
        self.view_button.setAccessibleName("Switch to Compact view")
        self.view_button.clicked.connect(self.toggle_view)
        header.addWidget(self.view_button)
        self.minimize_button = QPushButton("−")
        self.minimize_button.setAccessibleName("Minimize DoWidget")
        self.minimize_button.setToolTip("Minimize")
        self.minimize_button.setFixedWidth(26)
        self.minimize_button.clicked.connect(self.minimize)
        header.addWidget(self.minimize_button)
        self.close_button = QPushButton("×")
        self.close_button.setAccessibleName("Close DoWidget")
        self.close_button.setToolTip("Close")
        self.close_button.setFixedWidth(26)
        self.close_button.clicked.connect(self.close)
        header.addWidget(self.close_button)
        root.addLayout(header)
        self.view_stack = QStackedWidget()
        self.view_stack.setObjectName("providerStack")
        self.cards = {"deepseek": ProviderCard("DeepSeek · API balance"),
                      "codex": ProviderCard("Codex · subscription")}
        self.compact_cards = {"deepseek": CompactCard("deepseek", "DeepSeek · API balance"),
                              "codex": CompactCard("openai", "Codex · subscription")}
        for card_set in (self.cards, self.compact_cards):
            scroll = QScrollArea()
            scroll.setObjectName("providerScroll")
            scroll.viewport().setObjectName("providerViewport")
            scroll.setWidgetResizable(True)
            scroll.setMinimumSize(0, 0)
            content = QWidget()
            content.setObjectName("providerContent")
            cards = QVBoxLayout(content)
            cards.setContentsMargins(0, 0, 0, 0)
            cards.setSpacing(5)
            for card in card_set.values():
                cards.addWidget(card)
            cards.addStretch()
            scroll.setWidget(content)
            self.view_stack.addWidget(scroll)
        root.addWidget(self.view_stack, 1)
        self.notice = label("DEMO ONLY · no account requests or credential reads" if demo else "", "warning")
        root.addWidget(self.notice)
        self.footer = QHBoxLayout()
        self.footer.setSpacing(4)
        self.footer.addStretch(0)
        row = self.footer
        self.refresh_button = QPushButton("Refresh")
        self.refresh_button.setAccessibleName("Refresh account usage")
        self.refresh_button.setToolTip("Refresh account usage")
        self.refresh_button.clicked.connect(lambda: self.refresh(True))
        row.addWidget(self.refresh_button)
        self.settings_button = QPushButton("Settings")
        self.settings_button.setAccessibleName("Settings")
        self.settings_button.setToolTip("Settings")
        self.settings_button.clicked.connect(self.open_settings)
        row.addWidget(self.settings_button)
        self.notice_indicator = label("!", "warning", wrap=False)
        self.notice_indicator.setFixedWidth(16)
        row.addWidget(self.notice_indicator)
        root.addLayout(row)
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, self.config.always_on_top)
        self.apply_view()
        self.restore_position()
        if demo:
            self.seed_demo()
        self.render()
        self.edge_resize = EdgeResize(self)
        self._geometry_ready = True
        self.timer = QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self.tick)
        self.timer.start()
        self.tray = TrayController(self, self.windowIcon())
        self.tray.set_enabled(self.config.minimize_to_tray)
        if not demo:
            QTimer.singleShot(0, lambda: self.refresh(True))

    def restore_position(self):
        screens = QApplication.screens()
        if self.config.x is not None and self.config.y is not None:
            target = QPoint(self.config.x, self.config.y)
            for screen in screens:
                area = screen.availableGeometry()
                if area.contains(target):
                    self.move(max(area.left(), min(target.x(), area.right() - self.width() + 1)),
                              max(area.top(), min(target.y(), area.bottom() - self.height() + 1)))
                    return
        area = QApplication.primaryScreen().availableGeometry()
        self.move(area.right() - self.width() - 24, area.top() + 40)

    def remember_size(self):
        if self.config.view == "compact":
            self.config.compact_width, self.config.compact_height = self.width(), self.height()
        else:
            self.config.width, self.config.height = self.width(), self.height()

    def apply_view(self):
        self._changing_view = True
        compact = self.config.view == "compact"
        self.view_stack.setCurrentIndex(1 if compact else 0)
        self.setMinimumSize(260, 130) if compact else self.setMinimumSize(340, 280)
        width = self.config.compact_width if compact else self.config.width
        height = self.config.compact_height if compact else self.config.height
        area = self.screen().availableGeometry()
        self.configure_button(self.view_button, "Compact", "expand", compact, 22, 20)
        self.configure_button(self.minimize_button, "−", "minimize", compact, 22, 20)
        self.configure_button(self.close_button, "×", "close", compact, 22, 20)
        self.configure_button(self.refresh_button, "Refresh", "refresh", compact, 28, 24)
        self.configure_button(self.settings_button, "Settings", "settings", compact, 28, 24)
        self.footer.setStretch(0, 1 if compact else 0)
        self.footer.setStretch(1, 0 if compact else 1)
        self.footer.setStretch(2, 0 if compact else 1)
        self.header.setFixedHeight(20 if compact else 30)
        self.header.setStyleSheet("background: transparent;" + ("font-size: 11px; color: #b5c3d8;" if compact else ""))
        self.body.setStyleSheet("QFrame#widgetBody { background: " +
                               ("rgba(22, 28, 39, 218)" if compact else "#161c27") +
                               "; border: 1px solid #35445b; border-radius: 8px; }")
        self.view_button.setAccessibleName("Switch to " + ("Detailed" if compact else "Compact") + " view")
        self.view_button.setToolTip(self.view_button.accessibleName())
        self.header.setText(("DEMO" if self.demo else "⋮⋮") if compact else "DoWidget" + (" · DEMO" if self.demo else ""))
        self.notice.setVisible(not compact and bool(self.notice.text()))
        self.resize(min(width, area.width()), min(height, area.height()))
        self._changing_view = False

    @staticmethod
    def configure_button(button, text, icon, compact, width, height):
        button.setObjectName("compactControl" if compact else "")
        button.setText("" if compact else text)
        button.setIcon(control_icon(icon) if compact else QIcon())
        button.setIconSize(QSize(16, 16) if height == 20 else QSize(20, 20))
        if compact:
            button.setFixedSize(width, height)
        else:
            button.setMinimumSize(0, 0)
            button.setMaximumSize(16777215, 16777215)
            if icon in ("minimize", "close"):
                button.setFixedWidth(26)
        button.style().unpolish(button)
        button.style().polish(button)

    def toggle_view(self):
        self.geometry_timer.stop()
        self.remember_size()
        self.config.x, self.config.y = self.x(), self.y()
        self.config.view = "detailed" if self.config.view == "compact" else "compact"
        self.apply_view()
        self.restore_position()
        self.save_position()
        self.render()

    def update_notice(self):
        compact = self.config.view == "compact"
        self.notice.setVisible(not compact and bool(self.notice.text()))
        self.notice_indicator.setVisible(compact and not self.demo and bool(self.notice.text()))
        self.notice_indicator.setToolTip("<qt>" + escape(self.notice.text()) + "</qt>")
        self.notice_indicator.setAccessibleName(self.notice.text())

    def moveEvent(self, event):
        super().moveEvent(event)
        if self._geometry_ready and not self._changing_view:
            self.geometry_timer.start()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._geometry_ready and not self._changing_view:
            self.geometry_timer.start()

    def paintEvent(self, event):
        # Nonzero alpha keeps transparent resize margins hit-testable on Windows.
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(22, 28, 39, 24))

    def minimize(self):
        if not self.tray.minimize():
            self.save_position()
            self.showMinimized()

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.Type.WindowStateChange and self.isMinimized() and hasattr(self, "tray"):
            QTimer.singleShot(0, self.minimize_from_window_state)

    def minimize_from_window_state(self):
        if not self.closing and self.isMinimized() and self.config.minimize_to_tray:
            self.tray.minimize()

    def seed_demo(self):
        now = datetime.now(timezone.utc)
        self.states["deepseek"].succeed(Snapshot(balances=(Balance("CNY", Decimal("123.4567"), Decimal("3.4567"), Decimal("120")),), demo=True), time.monotonic(), now, 300)
        self.states["codex"].succeed(Snapshot(windows=(UsageWindow("Codex · 5-hour window", Decimal("72.5"), now + timedelta(hours=2)), UsageWindow("Codex · weekly window", Decimal("41"), now + timedelta(days=3))), note="Illustrative values only", demo=True), time.monotonic(), now, 300)

    def tick(self):
        if self.config.auto_refresh and not self.demo:
            self.refresh(False)

    def refresh(self, manual=False):
        if self.demo:
            self.seed_demo()
            self.render()
            return
        now = time.monotonic()
        started = False
        if self.key and self.states["deepseek"].begin(now, manual):
            key = self.key
            self.jobs.submit("deepseek", "deepseek", lambda: self.deepseek.fetch(key))
            started = True
        if self.config.codex_enabled and self.states["codex"].begin(now, manual):
            self.jobs.submit("codex", "codex", self.codex.fetch)
            started = True
        if manual:
            self.notice.setText("Refreshing…" if started else "No refresh started: connect in settings, or wait for the active request / retry cooldown.")
        if started or manual:
            self.render()

    def login_codex(self):
        state = self.states["codex"]
        if state.busy or self.demo:
            return
        persistent = self.settings.codex_persist.isChecked() if self.settings else self.credentials.available
        state.busy = True
        self.notice.setText("Complete the official sign-in in your browser. Sign-in expires after three minutes.")
        def sign_in():
            if persistent != self.codex_persistent:
                self.codex.logout()
                self.codex.close()
                if self.closing:
                    raise ProviderError("Sign-in cancelled.")
                self.codex = CodexProvider(self.data_dir / "codex", persistent=persistent)
                self.codex_persistent = persistent
            self.codex.login()
        self.jobs.submit("codex", "login", sign_in)
        self.render()

    def logout_codex(self):
        state = self.states["codex"]
        if state.busy or self.demo:
            return
        state.busy = True
        self.jobs.submit("codex", "logout", self.codex.logout)
        self.render()

    def completed(self, operation, result, error):
        if self.closing:
            return
        key = operation if operation in self.states else "codex"
        state = self.states[key]
        now = time.monotonic()
        if error:
            state.fail(error, now, self.config.interval_minutes * 60)
            self.notice.setText(str(error))
        elif operation == "login":
            self.config.codex_enabled = True
            self.save_config()
            state.reset()
            self.notice.setText("Codex signed in. Retrieving subscription usage…")
            self.refresh(True)
        elif operation == "logout":
            self.config.codex_enabled = False
            self.save_config()
            state.reset(message="Codex disconnected. Sign in through settings to reconnect.")
            self.notice.setText("DoWidget's Codex sign-in disconnected.")
        else:
            state.succeed(result, now, datetime.now(timezone.utc), self.config.interval_minutes * 60)
            self.notice.setText("")
        self.render()

    def render(self):
        card_set = self.compact_cards if self.config.view == "compact" else self.cards
        for key, card in card_set.items():
            card.render(self.states[key])
        self.update_notice()
        self.refresh_button.setEnabled(not any(state.busy for state in self.states.values()))
        if self.settings:
            self.settings.update_controls()

    def open_settings(self):
        if self.settings:
            self.settings.raise_()
            self.settings.activateWindow()
            return
        self.settings = Settings(self)
        self.settings.finished.connect(self.settings_closed)
        self.settings.show()

    def settings_closed(self):
        self.settings.deleteLater()
        self.settings = None

    def save_config(self):
        if self.demo:
            return True
        try:
            self.config_store.save(self.config)
            return True
        except ProviderError as error:
            self.notice.setText(str(error))
            self.update_notice()
            return False

    def save_position(self):
        self.geometry_timer.stop()
        self.remember_size()
        self.config.x, self.config.y = self.x(), self.y()
        self.save_config()

    def closeEvent(self, event: QCloseEvent):
        self.closing = True
        self.timer.stop()
        self.geometry_timer.stop()
        self.save_position()
        self.codex.close()
        self.tray.close()
        self.jobs.shutdown()
        event.accept()


def main():
    parser = argparse.ArgumentParser(description="DoWidget floating desktop usage widget")
    parser.add_argument("--demo", action="store_true", help="Clearly labeled offline preview; never accesses account credentials")
    args = parser.parse_args()
    app = QApplication(sys.argv[:1])
    app.setApplicationName("DoWidget")
    app.setOrganizationName("DoWidget")
    app.setWindowIcon(app_icon())
    app.setFont(QFont("Segoe UI" if sys.platform == "win32" else "Sans Serif", 10))
    app.setStyleSheet(STYLE)
    data_dir = Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppLocalDataLocation))
    window = Widget(data_dir, demo=args.demo)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
