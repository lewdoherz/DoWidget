"""Independent account sessions and bounded work; no generation or billing mutations."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
import time

from PySide6.QtCore import QObject, Qt, Signal

from .catalog import PROVIDERS
from .connections import Connection
from .extra_providers import ClaudeProvider, GrokProvider
from .local_usage import LocalUsageProvider
from .models import ProviderError
from .providers import CodexProvider, DeepSeekProvider
from .state import ProviderState
from .storage import CredentialStore


@dataclass
class Account:
    connection: Connection
    credentials: CredentialStore
    state: ProviderState = field(default_factory=ProviderState)
    adapter: object = field(default=None, repr=False)
    secret: str | None = field(default=None, repr=False)
    persistent: bool = False
    operation: str = ""


class Runtime(QObject):
    changed = Signal()
    notice = Signal(str)
    finished = Signal(str, str, object, object)

    def __init__(self, config, data_dir, save, parent=None, demo=False):
        super().__init__(parent)
        self.config, self.data_dir, self.save, self.demo = config, Path(data_dir), save, demo
        self.closing = False
        self.accounts = {}
        self.executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="DoWidget")
        self.finished.connect(self.completed, Qt.ConnectionType.QueuedConnection)
        for connection in config.connections:
            self.accounts[connection.id] = self.create_account(connection)

    def create_account(self, connection):
        credentials = CredentialStore(connection.id, connection.provider)
        account = Account(connection, credentials)
        if connection.source == "local":
            account.adapter = LocalUsageProvider(connection.provider)
        elif connection.provider == "codex":
            account.persistent = connection.remember and credentials.available
            home = self.data_dir / "codex" if connection.id == "codex-default" else self.data_dir / "codex-connections" / connection.id
            account.adapter = CodexProvider(home, persistent=account.persistent)
        elif connection.provider in ("deepseek", "claude", "grok"):
            account.adapter = {"deepseek": DeepSeekProvider, "claude": ClaudeProvider, "grok": GrokProvider}[connection.provider]()
            if not self.demo and connection.enabled:
                account.secret = credentials.get()
        self.reset_account(account)
        return account

    def reset_account(self, account):
        connection = account.connection
        if not connection.enabled:
            account.state.reset("disconnected", "Enable or connect this account in Settings.")
        elif account.adapter is None:
            account.state.reset("unavailable", PROVIDERS[connection.provider][4])
        else:
            account.state.reset(message=PROVIDERS[connection.provider][4] if connection.source == "api" else "Select your own usage JSON file in Settings. Local observations are not live API readings.")

    def idle(self, account):
        if self.demo:
            raise ProviderError("Connections cannot be changed in demo mode.", "unavailable")
        if account.state.busy:
            raise ProviderError("Wait for this connection's current operation to finish.", "busy")

    def replace_connection(self, connection):
        previous = self.config.connections
        self.config.connections = [connection if item.id == connection.id else item for item in previous]
        if not self.save():
            self.config.connections = previous
            raise ProviderError("Connection settings could not be saved.", "storage_unavailable")
        self.accounts[connection.id].connection = connection

    def add(self, connection):
        if self.demo:
            raise ProviderError("Connections cannot be changed in demo mode.", "unavailable")
        if len(self.accounts) >= 100 or connection.id in self.accounts:
            raise ProviderError("Cannot add this connection.", "setup_required")
        previous = self.config.connections
        self.config.connections = previous + [connection]
        if not self.save():
            self.config.connections = previous
            raise ProviderError("Connection settings could not be saved.", "storage_unavailable")
        self.accounts[connection.id] = self.create_account(connection)
        self.changed.emit()

    def update(self, connection):
        account = self.accounts[connection.id]
        self.idle(account)
        if connection.provider != account.connection.provider or connection.source != account.connection.source:
            raise ProviderError("Add a separate connection to change provider or source.", "setup_required")
        self.replace_connection(connection)
        self.reset_account(account)
        self.changed.emit()

    def connect_key(self, connection_id, key, remember):
        account = self.accounts[connection_id]
        self.idle(account)
        if account.connection.source != "api" or account.connection.provider not in ("deepseek", "claude", "grok"):
            raise ProviderError("This source does not use an API key.", "setup_required")
        if not key.strip():
            raise ProviderError("Enter a key first.", "setup_required")
        status = account.credentials.connect(key.strip(), remember)
        account.secret = key.strip()
        self.replace_connection(replace(account.connection, enabled=True, remember=remember))
        self.reset_account(account)
        self.notice.emit(status)
        self.refresh(True, connection_id)

    def submit(self, account, operation, function):
        account.state.busy = True
        account.operation = operation
        connection_id = account.connection.id
        future = self.executor.submit(function)

        def complete(done):
            if self.closing:
                return
            try:
                result, error = done.result(), None
            except ProviderError as failure:
                result, error = None, failure
            except Exception:
                result, error = None, ProviderError("Operation failed. Please retry.")
            if not self.closing:
                self.finished.emit(connection_id, operation, result, error)
        future.add_done_callback(complete)

    def refresh(self, manual=False, connection_id=None):
        if self.demo or self.closing:
            return
        now, started, changed = time.monotonic(), False, False
        accounts = [self.accounts[connection_id]] if connection_id else list(self.accounts.values())
        for account in accounts:
            connection = account.connection
            if not connection.enabled or account.adapter is None:
                continue
            if connection.source == "api" and connection.provider in ("deepseek", "claude", "grok") and not account.secret:
                message = "Connect this account's key in Settings. " + account.credentials.status
                if account.state.message != message:
                    account.state.reset(message=message)
                    changed = True
                continue
            if not account.state.begin(now, manual):
                continue
            if connection.source == "local":
                path = connection.options.get("path", "")
                function = lambda a=account, p=path: a.adapter.fetch(p)
            elif connection.provider == "codex":
                function = account.adapter.fetch
            elif connection.provider == "deepseek":
                function = lambda a=account, k=account.secret: a.adapter.fetch(k)
            else:
                function = lambda a=account, k=account.secret, options=dict(connection.options): a.adapter.fetch(k, options)
            self.submit(account, "refresh", function)
            started = True
        if manual:
            self.notice.emit("Refreshing…" if started else "No refresh started: connect or configure a source in Settings, or wait for the request / retry cooldown.")
        if started or changed or manual:
            self.changed.emit()

    def login(self, connection_id, remember):
        account = self.accounts[connection_id]
        self.idle(account)
        if account.connection.provider != "codex" or account.connection.source != "api":
            raise ProviderError("Select a Codex subscription connection.", "setup_required")
        if any(other.state.busy and other.operation == "login" for other in self.accounts.values()):
            raise ProviderError("Finish the current Codex browser sign-in before starting another.", "busy")
        wanted = bool(remember and account.credentials.available)
        self.replace_connection(replace(account.connection, remember=wanted))
        self.notice.emit("Complete the official sign-in in your browser. Sign-in expires after three minutes.")

        def sign_in():
            if wanted != account.persistent:
                account.adapter.logout()
                account.adapter.close()
                if self.closing:
                    raise ProviderError("Sign-in cancelled.")
                account.adapter = CodexProvider(account.adapter.home, persistent=wanted)
                account.persistent = wanted
            account.adapter.login()
        self.submit(account, "login", sign_in)
        self.changed.emit()

    def disconnect(self, connection_id, remove=False):
        account = self.accounts[connection_id]
        self.idle(account)
        if account.connection.provider == "codex" and account.connection.source == "api":
            self.submit(account, "remove" if remove else "logout", account.adapter.logout)
            self.changed.emit()
        else:
            if account.connection.source == "api" and account.connection.provider in ("deepseek", "claude", "grok"):
                account.credentials.disconnect()
            account.secret = None
            self.disconnected(account, remove)

    def disconnected(self, account, remove):
        connection = account.connection
        if remove:
            previous = self.config.connections
            self.config.connections = [item for item in previous if item.id != connection.id]
            if not self.save():
                self.config.connections = previous
                account.connection = replace(connection, enabled=False)
                account.state.reset("disconnected", "Credential disconnected, but connection removal could not be saved.")
                self.notice.emit("Credential disconnected, but connection removal could not be saved.")
                self.changed.emit()
                return
            if isinstance(account.adapter, CodexProvider):
                account.adapter.close()
            del self.accounts[connection.id]
        else:
            disabled = replace(connection, enabled=False)
            try:
                self.replace_connection(disabled)
            except ProviderError:
                account.connection = disabled
                self.reset_account(account)
                self.changed.emit()
                raise
            self.reset_account(account)
        self.notice.emit("Connection removed." if remove else "DoWidget connection disconnected.")
        self.changed.emit()

    def completed(self, connection_id, operation, result, error):
        if self.closing or connection_id not in self.accounts:
            return
        account = self.accounts[connection_id]
        now, interval = time.monotonic(), self.config.interval_minutes * 60
        try:
            if error:
                account.state.fail(error, now, interval)
                self.notice.emit(str(error))
            elif operation == "login":
                self.replace_connection(replace(account.connection, enabled=True))
                self.reset_account(account)
                self.refresh(True, connection_id)
            elif operation in ("logout", "remove"):
                account.state.busy = False
                self.disconnected(account, operation == "remove")
            else:
                wall = datetime.now(timezone.utc)
                observed = result.observed_at or wall
                account.state.succeed(result, now, observed, interval)
                if account.connection.source == "local" and result.observed_at and (wall - observed).total_seconds() > interval:
                    account.state.status = "stale"
                    account.state.message = "Local source observation is older than the refresh interval. Update the selected file; rereading it does not make its data fresh."
                self.notice.emit("")
        except ProviderError as failure:
            account.state.fail(failure, now, interval)
            self.notice.emit(str(failure))
        self.changed.emit()

    def expire_local(self):
        wall, changed = datetime.now(timezone.utc), False
        for account in self.accounts.values():
            snapshot = account.state.snapshot
            if (account.connection.source == "local" and snapshot and snapshot.observed_at
                    and account.state.status == "ready"
                    and (wall - snapshot.observed_at).total_seconds() > self.config.interval_minutes * 60):
                account.state.status = "stale"
                account.state.message = "Local source observation is older than the refresh interval. Update the selected file; rereading it does not make its data fresh."
                changed = True
        if changed:
            self.changed.emit()

    def shutdown(self):
        self.closing = True
        for account in self.accounts.values():
            if isinstance(account.adapter, CodexProvider):
                account.adapter.close()
        self.executor.shutdown(wait=False, cancel_futures=True)
