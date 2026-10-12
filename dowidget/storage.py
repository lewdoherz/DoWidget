"""Nonsecret preferences and explicitly allowlisted OS credential storage."""
from dataclasses import dataclass
import importlib
import json
import math
import os
from pathlib import Path
import sys
import tempfile

from .models import ProviderError


_SERVICE = "DoWidget.DeepSeek"
_USERNAME = "api-key"
_UNAVAILABLE = "Secure credential storage is unavailable; use this session only."
_SESSION = "Session only; the API key is not saved."
_SAVED = "API key saved securely in the operating system keyring."
_SAVE_FAILED = "The API key could not be saved securely; it remains available for this session."
_REMOVE_FAILED = "The saved API key could not be removed; the session credential was retained."
_READ_FAILED = "The saved API key could not be read; secure storage is unavailable."


def _discover_backend():
    """Do not consult keyring configuration, chainers, or third-party backends."""
    if sys.platform == "win32":
        module_name, class_name = "keyring.backends.Windows", "WinVaultKeyring"
    elif sys.platform.startswith("linux"):
        module_name, class_name = "keyring.backends.SecretService", "Keyring"
    else:
        return None
    try:
        return getattr(importlib.import_module(module_name), class_name)()
    except Exception:
        # Import, desktop bus, and OS API failures must never escape with details.
        return None


class CredentialStore:
    """Keep session secrets out of repr, config, and backend error messages."""

    def __init__(self):
        self._backend = _discover_backend()
        self._session_key: str | None = None
        self.available = False
        if self._backend is not None:
            try:
                priority = self._backend.priority
                self.available = (
                    not isinstance(priority, bool) and math.isfinite(priority) and priority > 0
                )
            except Exception:
                # Retain the allowlisted backend so a later delete is attempted,
                # rather than silently claiming a previous key was removed.
                pass
        self.status = "Secure credential storage is available." if self.available else _UNAVAILABLE

    def get(self) -> str | None:
        if self._session_key is not None:
            return self._session_key
        if self._backend is None:
            return None
        try:
            key = self._backend.get_password(_SERVICE, _USERNAME)
        except Exception:
            self.available = False
            self.status = _READ_FAILED
            return None
        self.available = True
        if isinstance(key, str) and key:
            self._session_key = key
            self.status = _SAVED
            return key
        return None

    def _remove_saved(self) -> None:
        if self._backend is None:
            return
        try:
            # Missing credentials are success; a generic PasswordDeleteError is
            # not, because backends also use it for genuine deletion failures.
            if self._backend.get_password(_SERVICE, _USERNAME) is not None:
                self._backend.delete_password(_SERVICE, _USERNAME)
        except Exception:
            self.available = False
            self.status = _REMOVE_FAILED
            raise ProviderError(_REMOVE_FAILED, "storage_unavailable") from None
        self.available = True

    def connect(self, key: str, persist: bool) -> str:
        # A failed OS operation must not discard the caller's usable session key.
        self._session_key = key
        if not persist:
            self._remove_saved()
            self.status = _SESSION if self._backend is not None else _SESSION + " Secure storage is unavailable."
            return self.status
        if self._backend is None:
            self.status = _SAVE_FAILED
            raise ProviderError(_SAVE_FAILED, "storage_unavailable") from None
        try:
            self._backend.set_password(_SERVICE, _USERNAME, key)
        except Exception:
            self.available = False
            self.status = _SAVE_FAILED
            raise ProviderError(_SAVE_FAILED, "storage_unavailable") from None
        self.available = True
        self.status = _SAVED
        return self.status

    def disconnect(self) -> None:
        self._remove_saved()
        self._session_key = None
        self.status = (
            "Saved and session credentials removed."
            if self._backend is not None
            else "Session credential cleared; secure storage is unavailable."
        )


@dataclass
class Config:
    interval_minutes: int = 5
    auto_refresh: bool = True
    always_on_top: bool = False
    codex_enabled: bool = False
    x: int | None = None
    y: int | None = None
    width: int = 380
    height: int = 560
    compact_width: int = 320
    compact_height: int = 190
    view: str = "detailed"
    minimize_to_tray: bool = False


def _validated_config(values: dict) -> Config:
    defaults = Config()
    interval = values.get("interval_minutes")
    if type(interval) is int and 1 <= interval <= 1440:
        defaults.interval_minutes = interval
    for field in ("auto_refresh", "always_on_top", "codex_enabled", "minimize_to_tray"):
        value = values.get(field)
        if type(value) is bool:
            setattr(defaults, field, value)
    for field in ("x", "y"):
        value = values.get(field)
        if type(value) is int and -100_000 <= value <= 100_000:
            setattr(defaults, field, value)
    for field, minimum in (
        ("width", 340), ("height", 280),
        ("compact_width", 260), ("compact_height", 130),
    ):
        value = values.get(field)
        if type(value) is int and minimum <= value <= 10_000:
            setattr(defaults, field, value)
    view = values.get("view")
    if type(view) is str and view in ("compact", "detailed"):
        defaults.view = view
    return defaults


class ConfigStore:
    def __init__(self, path: Path):
        self.path = Path(path)

    def load(self) -> Config:
        try:
            with self.path.open("r", encoding="utf-8") as stream:
                values = json.load(stream)
        except (OSError, ValueError, RecursionError):
            return Config()
        return _validated_config(values) if isinstance(values, dict) else Config()

    def save(self, config: Config) -> None:
        # Whitelist both input and output; additional attributes are never saved.
        fields = (
            "interval_minutes", "auto_refresh", "always_on_top", "codex_enabled",
            "x", "y", "width", "height", "compact_width", "compact_height", "view",
            "minimize_to_tray",
        )
        validated = _validated_config({field: getattr(config, field, None) for field in fields})
        values = {field: getattr(validated, field) for field in fields}
        temporary: Path | None = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=self.path.parent,
                prefix=self.path.name + ".", suffix=".tmp", delete=False,
            ) as stream:
                temporary = Path(stream.name)
                json.dump(values, stream, indent=2)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
        except (OSError, ValueError, TypeError):
            raise ProviderError("Settings could not be saved.", "storage_unavailable") from None
        finally:
            if temporary is not None:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    pass
