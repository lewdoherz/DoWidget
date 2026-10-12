"""Native desktop surface; provider work stays off the GUI thread."""
import argparse
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from html import escape
from pathlib import Path
import re
import sys
import time

from PySide6.QtCore import QEvent, QPoint, QSize, QStandardPaths, Qt, QTimer
from PySide6.QtGui import QCloseEvent, QColor, QFont, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (
    QApplication, QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea,
    QSizePolicy, QStackedWidget, QVBoxLayout, QWidget,
)

from .icons import app_icon, control_icon
from .catalog import PROVIDERS, connection_caption, connection_title
from .connections import Connection, new_connection_id
from .models import Balance, MoneyMetric, ProviderError, Snapshot, UsageWindow
from .runtime import Runtime
from .settings import Settings
from .storage import ConfigStore
from .ui_helpers import label, metric_text
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
QLineEdit, QSpinBox, QComboBox, QListWidget { background: #222c3b; padding: 6px; border: 1px solid #4b6080; border-radius: 4px; }
QCheckBox { spacing: 8px; }
QScrollArea { border: none; }
"""




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
    if name.startswith("Claude Enterprise "):
        period = name.removeprefix("Claude Enterprise ")
        for value, short in (("monthly", "Month"), ("weekly", "Week"), ("daily", "Day")):
            if period == value or period.startswith(value + " ("):
                return short + " spend cap" + period.removeprefix(value)
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
        for metric in snapshot.metrics:
            lines.append(metric.label + ": " + metric_text(metric))
        if snapshot.note:
            lines.append(snapshot.note)
    lines.append("Last successful update: " + (local_time(state.updated_at) if state.updated_at else "Never"))
    # Qt detects rich-text tooltips. Escape upstream labels before showing them.
    return "<qt>" + "<br>".join(escape(line) for line in lines) + "</qt>"




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
            for metric in snapshot.metrics:
                self.content.addWidget(label(metric.label, "muted"))
                self.content.addWidget(label(metric_text(metric), "amount"))
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
    def __init__(self, provider, title, caption=""):
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
        values_layout = QVBoxLayout()
        values_layout.setContentsMargins(0, 0, 0, 0)
        values_layout.setSpacing(1)
        if caption:
            self.caption = label(caption, "muted")
            self.caption.setMinimumWidth(0)
            self.caption.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
            self.caption.setStyleSheet("font-size: 11px;")
            values_layout.addWidget(self.caption)
        self.value = label("—", "compactAmount")
        self.value.setMinimumWidth(0)
        self.value.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        values_layout.addWidget(self.value)
        layout.addLayout(values_layout, 1)
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
            if not snapshot.windows:
                values.extend(metric.label + ": " + metric_text(metric) for metric in snapshot.metrics)
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
        if demo:
            for provider in ("deepseek", "claude", "gemini", "grok", "glm"):
                self.config.connections.append(Connection(new_connection_id(), provider,
                    PROVIDERS[provider][0] + " DEMO", source="local" if provider in ("gemini", "glm") else "api"))
        self.runtime = Runtime(self.config, data_dir, self.save_config, self, demo=demo)
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
        self.cards, self.compact_cards = {}, {}
        self.card_layouts = []
        self._card_signature = None
        for _ in range(2):
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
            self.card_layouts.append(cards)
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
        self.runtime.changed.connect(self.render)
        self.runtime.notice.connect(self.set_notice)
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
        for index, account in enumerate(self.runtime.accounts.values()):
            provider = account.connection.provider
            if provider in ("deepseek", "grok"):
                snapshot = Snapshot(balances=(Balance("CNY" if provider == "deepseek" else "USD",
                    Decimal("123.4567") if index == 0 else Decimal("24.8400")),), demo=True)
            else:
                snapshot = Snapshot(windows=(
                    UsageWindow("Codex · 5-hour window" if provider == "codex" else "Monthly" if provider == "claude" else "5h",
                                Decimal("72.5"), now + timedelta(hours=2)),
                    UsageWindow("Codex · weekly window" if provider == "codex" else "Week",
                                None if provider == "gemini" else Decimal("41"), now + timedelta(days=3))),
                    note="Illustrative values only; not live account data.", demo=True,
                    metrics=(MoneyMetric("Monthly spend-cap remaining", "USD", Decimal("24.875")),) if provider == "claude" else ())
            account.state.succeed(snapshot, time.monotonic(), now, 300)

    def tick(self):
        if not self.demo:
            self.runtime.expire_local()
        if self.config.auto_refresh and not self.demo:
            self.refresh(False)

    def refresh(self, manual=False):
        if self.demo:
            self.seed_demo()
            self.render()
        else:
            self.runtime.refresh(manual)

    def set_notice(self, text):
        self.notice.setText(text)
        self.update_notice()
        if self.settings:
            self.settings.update_controls()

    def rebuild_cards(self):
        signature = tuple(account.connection for account in self.runtime.accounts.values())
        if signature == self._card_signature:
            return
        self._card_signature = signature
        for layout in self.card_layouts:
            while layout.count():
                item = layout.takeAt(0)
                if item.widget():
                    item.widget().deleteLater()
        self.cards, self.compact_cards = {}, {}
        for identifier, account in self.runtime.accounts.items():
            connection = account.connection
            title = connection_title(connection)
            card = ProviderCard(title)
            if connection.model_label:
                card.layout.insertWidget(1, label("Model label: " + connection.model_label + " (display only)", "muted"))
            self.cards[identifier] = card
            self.compact_cards[identifier] = CompactCard(PROVIDERS[connection.provider][2], title,
                                                        connection_caption(connection))
            self.card_layouts[0].addWidget(card)
            self.card_layouts[1].addWidget(self.compact_cards[identifier])
        if not self.cards:
            for layout in self.card_layouts:
                layout.addWidget(label("No connections. Open Settings to add an account or API source.", "muted"))
        for layout in self.card_layouts:
            layout.addStretch()

    def render(self):
        self.rebuild_cards()
        card_set = self.compact_cards if self.config.view == "compact" else self.cards
        for key, card in card_set.items():
            card.render(self.runtime.accounts[key].state)
        self.update_notice()
        self.refresh_button.setEnabled(not any(account.state.busy for account in self.runtime.accounts.values()))
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
        self.runtime.shutdown()
        self.tray.close()
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
