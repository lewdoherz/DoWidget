"""Read only an explicitly selected, bounded usage snapshot, never credentials."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import json
import os
from pathlib import Path
import re
import stat
import unicodedata

from .models import Balance, ProviderError, Snapshot, UsageWindow, remaining_percentage


MAX_BODY = 256 * 1024
MAX_ROWS = 32
MAX_NUMBER_LENGTH = 160
MAX_EXPONENT = 100
PROVIDERS = frozenset({"deepseek", "codex", "claude", "gemini", "grok", "glm"})
_ROOT_FIELDS = {"provider", "product", "observed_at", "demo", "balances", "windows", "note"}
_NUMBER = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?\Z")
_CURRENCY = re.compile(r"[A-Za-z][A-Za-z0-9]{0,15}\Z")
_INVALID = "Local usage file has an invalid snapshot format."


def _invalid():
    raise ProviderError(_INVALID, "setup_required") from None


def _object(value, allowed, required=()):
    if not isinstance(value, dict) or not set(value) <= allowed or not set(required) <= set(value):
        _invalid()
    return value


def _text(value, limit):
    if (not isinstance(value, str) or not value.strip() or len(value) > limit
            or any(unicodedata.category(char).startswith("C") or char in "<>" for char in value)):
        _invalid()
    return value


def _timestamp(value):
    if not isinstance(value, str) or len(value) > 64 or "T" not in value:
        _invalid()
    try:
        result = datetime.fromisoformat(value)
        if result.tzinfo is None or result.utcoffset() is None:
            _invalid()
        # Ensure conversion itself is representable, even near datetime's bounds.
        result.astimezone(timezone.utc)
        return result
    except (ValueError, OverflowError):
        _invalid()


def _number(value, *, optional=False):
    if value is None and optional:
        return None
    if not isinstance(value, str) or len(value) > MAX_NUMBER_LENGTH:
        _invalid()
    if not _NUMBER.fullmatch(value):
        if optional:
            return None
        _invalid()
    try:
        number = Decimal(value)
    except InvalidOperation:
        _invalid()
    # Bound both the encoded exponent and the effective magnitude. This also
    # bounds downstream fixed-point display for tiny values and large balances.
    if not number.is_finite() or abs(number.as_tuple().exponent) > MAX_EXPONENT or abs(number.adjusted()) > MAX_EXPONENT:
        _invalid()
    return number


def _rows(value):
    if not isinstance(value, list) or len(value) > MAX_ROWS:
        _invalid()
    return value


def _balance(row):
    _object(row, {"currency", "total", "granted", "topped_up"}, {"currency", "total"})
    currency = row["currency"]
    if not isinstance(currency, str) or not _CURRENCY.fullmatch(currency):
        _invalid()
    return Balance(currency, _number(row["total"]),
                   _number(row["granted"]) if "granted" in row else None,
                   _number(row["topped_up"]) if "topped_up" in row else None)


def _window(row):
    _object(row, {"name", "used_percent", "used", "total", "resets_at"}, {"name"})
    if "used_percent" in row and ("used" in row or "total" in row):
        _invalid()
    name = _text(row["name"], 120)
    remaining = remaining_percentage(
        used_percent=_number(row.get("used_percent"), optional=True),
        used=_number(row.get("used"), optional=True),
        total=_number(row.get("total"), optional=True),
    )
    reset = _timestamp(row["resets_at"]) if row.get("resets_at") is not None else None
    return UsageWindow(name, remaining, reset)


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            _invalid()
        result[key] = value
    return result


def _reject_number(_value):
    # All quantities are decimal strings; reject JSON numbers before conversion.
    _invalid()


class LocalUsageProvider:
    def __init__(self, provider: str):
        if provider not in PROVIDERS:
            raise ProviderError("Local usage provider is not supported.", "setup_required") from None
        self.provider = provider

    def fetch(self, path: str) -> Snapshot:
        if not isinstance(path, str) or not path:
            raise ProviderError("Select a local usage snapshot file.", "setup_required") from None
        try:
            selected = Path(path)
            if not stat.S_ISREG(selected.stat().st_mode):
                raise ProviderError("Select a regular local usage snapshot file.", "setup_required")
            with selected.open("rb") as stream:
                if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                    raise ProviderError("Select a regular local usage snapshot file.", "setup_required")
                body = stream.read(MAX_BODY + 1)
        except (OSError, ValueError):
            raise ProviderError("Local usage snapshot file could not be read.", "setup_required") from None
        if len(body) > MAX_BODY:
            raise ProviderError("Local usage snapshot file exceeds the size limit.", "setup_required") from None
        try:
            data = json.loads(body.decode("utf-8"), object_pairs_hook=_pairs,
                              parse_int=_reject_number, parse_float=_reject_number,
                              parse_constant=_reject_number)
        except (UnicodeError, ValueError, RecursionError):
            _invalid()
        _object(data, _ROOT_FIELDS, {"provider", "product", "observed_at"})
        if data["provider"] != self.provider:
            raise ProviderError("Local usage snapshot provider does not match the connection.", "setup_required") from None
        product = _text(data["product"], 120)
        observed_at = _timestamp(data["observed_at"])
        if observed_at > datetime.now(timezone.utc) + timedelta(minutes=5):
            raise ProviderError("Local usage snapshot observation time is in the future.", "setup_required") from None
        demo = data.get("demo", False)
        if not isinstance(demo, bool):
            _invalid()
        balances = tuple(_balance(row) for row in _rows(data.get("balances", [])))
        windows = tuple(_window(row) for row in _rows(data.get("windows", [])))
        if not balances and not windows:
            _invalid()
        note = f"Local snapshot · {product}"
        if "note" in data:
            supplied_note = data["note"]
            if supplied_note != "":
                note += f" · {_text(supplied_note, 500)}"
        return Snapshot(balances=balances, windows=windows, note=note,
                        demo=demo, observed_at=observed_at)
