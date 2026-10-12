"""Connection management; keys stay masked and are never prefilled."""
from dataclasses import replace
from html import escape
import time

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QFileDialog, QFormLayout,
    QHBoxLayout, QLineEdit, QListWidget, QListWidgetItem, QPushButton,
    QScrollArea, QSpinBox, QVBoxLayout, QWidget,
)

from .catalog import PROVIDERS, connection_title, product_title
from .connections import Connection, new_connection_id
from .models import ProviderError
from .ui_helpers import label


class AddConnection(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("Add account / API connection")
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.provider = QComboBox()
        for identifier, info in PROVIDERS.items():
            self.provider.addItem(info[0], identifier)
        form.addRow("Company / product", self.provider)
        self.source = QComboBox()
        self.source.addItem("Automatic documented integration", "api")
        self.source.addItem("Explicit local usage JSON file", "local")
        form.addRow("Usage source", self.source)
        self.name = QLineEdit()
        self.name.setMaxLength(80)
        self.name.setPlaceholderText("For example: Personal, Work, Project A")
        form.addRow("Connection name", self.name)
        layout.addLayout(form)
        self.help = label("", "muted")
        layout.addWidget(self.help)
        self.provider.currentIndexChanged.connect(self.provider_changed)
        self.source.currentIndexChanged.connect(self.update_help)
        self.provider_changed()
        buttons = QHBoxLayout()
        add, cancel = QPushButton("Add connection"), QPushButton("Cancel")
        buttons.addWidget(add)
        buttons.addWidget(cancel)
        add.clicked.connect(self.accept)
        cancel.clicked.connect(self.reject)
        layout.addLayout(buttons)
        self.setMinimumWidth(420)

    def provider_changed(self):
        self.source.setCurrentIndex(1 if self.provider.currentData() in ("gemini", "glm") else 0)
        self.update_help()

    def update_help(self):
        identifier = self.provider.currentData()
        text = PROVIDERS[identifier][4]
        if self.source.currentData() == "local":
            text = "Select your own JSON snapshot after adding the connection. File observations are explicitly labeled local, with their original timestamps. No API key is needed. " + text
        self.help.setText(text)

    def connection(self):
        provider = self.provider.currentData()
        return Connection(id=new_connection_id(), provider=provider,
                          name=self.name.text().strip() or PROVIDERS[provider][0],
                          source=self.source.currentData(), enabled=provider != "codex" or self.source.currentData() == "local")


class Settings(QDialog):
    def __init__(self, window):
        super().__init__(window)
        self.owner = window
        self.selected_id = None
        self._list_signature = None
        self.setWindowTitle("DoWidget settings")
        self.setMinimumWidth(440)
        self.resize(510, min(850, QApplication.primaryScreen().availableGeometry().height() - 80))
        outer = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        layout = QVBoxLayout(content)
        scroll.setWidget(content)
        outer.addWidget(scroll)
        layout.addWidget(label("Accounts / API connections", "title"))
        layout.addWidget(label("Add multiple connections for the same provider. Different keys on one account/team/project can share the same quota; values are never added together. Model labels are display-only, not model-specific allowances.", "muted"))
        self.connections = QListWidget()
        self.connections.setMinimumHeight(100)
        self.connections.setMaximumHeight(160)
        self.connections.currentItemChanged.connect(self.selection_changed)
        layout.addWidget(self.connections)
        self.add_button = QPushButton("Add account / API connection")
        self.add_button.clicked.connect(self.add_connection)
        layout.addWidget(self.add_button)
        self.product = label("", "title")
        self.help = label("", "muted")
        layout.addWidget(self.product)
        layout.addWidget(self.help)
        self.official = QPushButton("Open official usage / setup page")
        self.official.clicked.connect(self.open_official)
        layout.addWidget(self.official)
        form = QFormLayout()
        self.name = QLineEdit()
        self.name.setMaxLength(80)
        form.addRow("Connection name", self.name)
        self.model = QLineEdit()
        self.model.setMaxLength(120)
        self.model.setPlaceholderText("Optional display label only")
        form.addRow("Model label", self.model)
        self.enabled = QCheckBox("Monitor this connection")
        form.addRow(self.enabled)
        self.scope = QLineEdit()
        self.scope.setMaxLength(120)
        self.scope_label = label("Member / team ID")
        form.addRow(self.scope_label, self.scope)
        self.path = QLineEdit()
        self.path_label = label("Usage JSON file")
        path_row = QWidget()
        path_layout = QHBoxLayout(path_row)
        path_layout.setContentsMargins(0, 0, 0, 0)
        path_layout.addWidget(self.path, 1)
        self.browse = QPushButton("Browse…")
        self.browse.clicked.connect(self.browse_file)
        path_layout.addWidget(self.browse)
        self.path_row = path_row
        form.addRow(self.path_label, path_row)
        layout.addLayout(form)
        self.save_connection_button = QPushButton("Save connection")
        self.save_connection_button.clicked.connect(self.save_connection)
        layout.addWidget(self.save_connection_button)
        self.key = QLineEdit()
        self.key.setEchoMode(QLineEdit.EchoMode.Password)
        self.key.setPlaceholderText("Enter new key; existing keys are never displayed")
        layout.addWidget(self.key)
        self.persist = QCheckBox("Remember in operating system credential store")
        layout.addWidget(self.persist)
        self.storage_info = label("", "muted")
        layout.addWidget(self.storage_info)
        buttons = QHBoxLayout()
        self.connect = QPushButton("Connect / replace key")
        self.disconnect = QPushButton("Disconnect")
        self.remove = QPushButton("Remove connection")
        self.connect.clicked.connect(self.connect_selected)
        self.disconnect.clicked.connect(lambda: self.disconnect_selected(False))
        self.remove.clicked.connect(lambda: self.disconnect_selected(True))
        for button in (self.connect, self.disconnect, self.remove):
            buttons.addWidget(button)
        layout.addLayout(buttons)
        layout.addWidget(label("Disconnect removes this connection's saved and session credentials. Unchecking Monitor only stops its refreshes. Removing a connection also disconnects it.", "muted"))
        layout.addWidget(label("Codex extra credits and resets", "title"))
        layout.addWidget(label("DoWidget never generates tasks, buys credits or consumes banked quota resets. It cannot change OpenAI account spending permissions. OpenAI says banked resets require your explicit confirmation; scheduled/global resets are different. Business owners/admins manage additional credit usage limits in Billing; automatic reload controls purchases, not consumption of an existing credit balance. Review the controls for your plan and do not confirm extra usage or banked resets if you want to stop at included limits.", "muted"))
        billing = QPushButton("Open OpenAI Business billing / spend controls")
        billing.clicked.connect(lambda: QDesktopServices.openUrl(QUrl("https://chatgpt.com/admin/billing")))
        layout.addWidget(billing)
        layout.addWidget(label("Widget behavior", "title"))
        behavior = QFormLayout()
        self.interval = QSpinBox()
        self.interval.setRange(1, 1440)
        self.interval.setSuffix(" minutes")
        self.interval.setValue(window.config.interval_minutes)
        behavior.addRow("Refresh interval", self.interval)
        self.auto = QCheckBox("Automatically refresh")
        self.auto.setChecked(window.config.auto_refresh)
        behavior.addRow(self.auto)
        self.top = QCheckBox("Always on top")
        self.top.setChecked(window.config.always_on_top)
        behavior.addRow(self.top)
        self.minimize_tray = QCheckBox("Minimize to system tray")
        self.minimize_tray.setChecked(window.config.minimize_to_tray)
        behavior.addRow(self.minimize_tray)
        layout.addLayout(behavior)
        layout.addWidget(label("Tray click restores the widget. Without a usable tray, ordinary taskbar minimization is used. Failed refreshes retain stale data and respect backoff. Local snapshots older than the interval remain stale until their source file is updated.", "muted"))
        self.info = label("", "warning")
        layout.addWidget(self.info)
        apply = QPushButton("Save behavior")
        apply.clicked.connect(self.save_behavior)
        layout.addWidget(apply)
        close = QPushButton("Close settings")
        close.clicked.connect(self.accept)
        layout.addWidget(close)
        self.update_controls()

    def account(self):
        return self.owner.runtime.accounts.get(self.selected_id)

    def update_controls(self):
        accounts = self.owner.runtime.accounts
        signature = tuple((identifier, account.connection) for identifier, account in accounts.items())
        if signature != self._list_signature:
            selected = self.selected_id
            self.connections.blockSignals(True)
            self.connections.clear()
            for identifier, account in accounts.items():
                item = QListWidgetItem(connection_title(account.connection))
                item.setData(Qt.ItemDataRole.UserRole, identifier)
                item.setToolTip("<qt>" + escape(connection_title(account.connection)) + "</qt>")
                self.connections.addItem(item)
                if identifier == selected:
                    self.connections.setCurrentItem(item)
            if self.connections.currentRow() < 0 and self.connections.count():
                self.connections.setCurrentRow(0)
            self.connections.blockSignals(False)
            self._list_signature = signature
            self.selection_changed(self.connections.currentItem(), None)
        account = self.account()
        idle = bool(account and not account.state.busy and not self.owner.demo)
        self.add_button.setEnabled(not self.owner.demo)
        for control in (self.name, self.model, self.enabled, self.scope, self.path, self.browse,
                        self.save_connection_button, self.disconnect, self.remove):
            control.setEnabled(idle)
        self.connect.setEnabled(idle and account.connection.source == "api" and account.connection.provider in ("deepseek", "claude", "grok", "codex") if account else False)
        self.key.setEnabled(idle)
        self.persist.setEnabled(idle and account.credentials.available if account else False)
        self.official.setEnabled(bool(account))
        self.storage_info.setText(account.credentials.status if account else "Add a connection first.")
        self.info.setText(self.owner.notice.text())

    def selection_changed(self, current, previous):
        self.selected_id = current.data(Qt.ItemDataRole.UserRole) if current else None
        self.key.clear()
        account = self.account()
        if not account:
            self.product.setText("No connection selected")
            self.help.setText("Add a connection to choose a provider and usage source.")
            return
        connection = account.connection
        self.product.setText(product_title(connection))
        self.help.setText(PROVIDERS[connection.provider][4] if connection.source == "api" else "Explicit local data, not a live API reading. See README for the JSON schema. " + PROVIDERS[connection.provider][4])
        self.name.setText(connection.name)
        self.model.setText(connection.model_label)
        self.enabled.setChecked(connection.enabled)
        scope_key = "user_id" if connection.provider == "claude" else "team_id"
        self.scope.setText(connection.options.get(scope_key, ""))
        self.scope_label.setText("Enterprise member user_ ID" if connection.provider == "claude" else "xAI team ID")
        scope_visible = connection.source == "api" and connection.provider in ("claude", "grok")
        self.scope.setVisible(scope_visible)
        self.scope_label.setVisible(scope_visible)
        self.path.setText(connection.options.get("path", ""))
        for control in (self.path_label, self.path_row):
            control.setVisible(connection.source == "local")
        secret_source = connection.source == "api" and connection.provider in ("deepseek", "claude", "grok")
        self.key.setVisible(secret_source)
        self.persist.setVisible(secret_source or connection.provider == "codex" and connection.source == "api")
        self.persist.setChecked(connection.remember and account.credentials.available)
        self.connect.setText("Sign in with ChatGPT" if connection.provider == "codex" else "Connect / replace key")
        self.connect.setVisible(connection.source == "api" and connection.provider in ("deepseek", "claude", "grok", "codex"))
        # A selection change is not necessarily accompanied by a backend event.
        idle = not account.state.busy and not self.owner.demo
        for control in (self.connect, self.disconnect, self.remove, self.save_connection_button, self.name, self.model, self.enabled, self.scope, self.path, self.browse, self.key):
            control.setEnabled(idle)
        self.persist.setEnabled(idle and account.credentials.available)
        self.storage_info.setText(account.credentials.status)

    def guard(self, function):
        try:
            function()
        except ProviderError as error:
            self.info.setText(str(error))
        except (ValueError, TypeError):
            self.info.setText("Invalid connection settings. Check the name and source fields.")

    def add_connection(self):
        dialog = AddConnection(self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            def add():
                connection = dialog.connection()
                self.owner.runtime.add(connection)
                for row in range(self.connections.count()):
                    if self.connections.item(row).data(Qt.ItemDataRole.UserRole) == connection.id:
                        self.connections.setCurrentRow(row)
                        break
            self.guard(add)

    def edited_connection(self):
        connection = self.account().connection
        options = {}
        if connection.source == "local":
            options["path"] = self.path.text().strip()
        elif connection.provider in ("claude", "grok"):
            options["user_id" if connection.provider == "claude" else "team_id"] = self.scope.text().strip()
        return replace(connection, name=self.name.text().strip(), model_label=self.model.text().strip(),
                       enabled=self.enabled.isChecked(), options=options)

    def save_connection(self):
        def save():
            connection = self.edited_connection()
            self.owner.runtime.update(connection)
            self.owner.runtime.refresh(True, connection.id)
        self.guard(save)

    def connect_selected(self):
        def connect():
            connection = self.edited_connection()
            key, remember = self.key.text(), self.persist.isChecked()
            self.owner.runtime.update(connection)
            if connection.provider == "codex":
                self.owner.runtime.login(connection.id, remember)
            else:
                self.owner.runtime.connect_key(connection.id, key, remember)
                self.key.clear()
        self.guard(connect)

    def disconnect_selected(self, remove):
        if self.account():
            self.guard(lambda: self.owner.runtime.disconnect(self.selected_id, remove))

    def browse_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "Select your own usage snapshot", "", "Usage snapshots (*.json)")
        if path:
            self.path.setText(path)

    def open_official(self):
        if self.account():
            QDesktopServices.openUrl(QUrl(PROVIDERS[self.account().connection.provider][3]))

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
            for account in w.runtime.accounts.values():
                if account.state.status in ("ready", "stale") and not account.state.failure_count:
                    account.state.next_due = now + w.config.interval_minutes * 60
            self.info.setText("Behavior saved.")
