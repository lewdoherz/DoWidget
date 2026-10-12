"""Explicit local files only: no network, credentials, CLI, or generation."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
from unittest.mock import patch

import pytest

from dowidget.local_usage import LocalUsageProvider, MAX_BODY, MAX_ROWS
from dowidget.models import ProviderError


OBSERVED = "2020-01-02T03:04:05+03:00"


def payload(provider="gemini"):
    return {"provider": provider, "product": "Manually recorded AI Studio limits",
            "observed_at": OBSERVED,
            "windows": [{"name": "Requests per minute", "used": "2", "total": "10"},
                        {"name": "Tokens per minute", "used_percent": "37.5"}]}


def fetch(tmp_path, data=None, provider="gemini", *, body=None):
    selected = tmp_path / "usage.json"
    selected.write_bytes(body if body is not None else json.dumps(data if data is not None else payload(provider)).encode())
    return LocalUsageProvider(provider).fetch(str(selected))


@pytest.mark.parametrize("provider", ["deepseek", "codex", "claude", "gemini", "grok", "glm"])
def test_all_providers_and_independent_windows(tmp_path, provider):
    snapshot = fetch(tmp_path, provider=provider)
    assert [window.name for window in snapshot.windows] == ["Requests per minute", "Tokens per minute"]
    assert [window.remaining for window in snapshot.windows] == [Decimal("80"), Decimal("62.5")]
    assert snapshot.observed_at == datetime.fromisoformat(OBSERVED)
    assert snapshot.observed_at.isoformat() == OBSERVED
    assert not snapshot.demo
    assert not snapshot.metrics


def test_exact_balances_and_currency_labels(tmp_path):
    data = payload()
    data["balances"] = [
        {"currency": "USD", "total": "123456789.12345678901234567890123456789",
         "granted": "0.00000000000000000001", "topped_up": "10.50"},
        {"currency": "CNY", "total": "3.00"},
        {"currency": "XTS", "total": "-0.10"},
    ]
    snapshot = fetch(tmp_path, data)
    assert [balance.currency for balance in snapshot.balances] == ["USD", "CNY", "XTS"]
    assert snapshot.balances[0].total == Decimal(data["balances"][0]["total"])
    assert snapshot.balances[0].granted == Decimal("0.00000000000000000001")
    assert snapshot.balances[0].topped_up.as_tuple().exponent == -2
    assert snapshot.balances[1].total.as_tuple().exponent == -2
    assert snapshot.balances[1].granted is None
    assert snapshot.balances[2].total == Decimal("-0.10")


@pytest.mark.parametrize("window,remaining", [
    ({"name": "Unknown"}, None),
    ({"name": "Unknown", "used_percent": None}, None),
    ({"name": "Unknown", "used_percent": "NaN"}, None),
    ({"name": "Unknown", "used_percent": "Infinity"}, None),
    ({"name": "Unknown", "used_percent": "not measured"}, None),
    ({"name": "Unknown", "used": "2"}, None),
    ({"name": "Unknown", "total": "10"}, None),
    ({"name": "Unknown", "used": "-1", "total": "10"}, None),
    ({"name": "Unknown", "used": "1", "total": "0"}, None),
    ({"name": "Unknown", "used": "1", "total": "-10"}, None),
    ({"name": "Clamp", "used_percent": "-10"}, Decimal("100")),
    ({"name": "Clamp", "used_percent": "110"}, Decimal("0")),
    ({"name": "Clamp", "used": "11", "total": "10"}, Decimal("0")),
    ({"name": "Zero", "used": "0", "total": "10"}, Decimal("100")),
])
def test_missing_invalid_and_clamped_percentages(tmp_path, window, remaining):
    data = payload()
    data["windows"] = [window, {"name": "Independent", "used_percent": "25"}]
    snapshot = fetch(tmp_path, data)
    assert snapshot.windows[0].remaining == remaining
    assert snapshot.windows[1].remaining == Decimal("75")


def test_demo_note_and_reset(tmp_path):
    data = payload()
    data.update(demo=True, note="Demo data, not live account usage")
    data["windows"][0]["resets_at"] = "2020-01-02T04:00:00Z"
    snapshot = fetch(tmp_path, data)
    assert snapshot.demo
    assert snapshot.windows[0].resets_at == datetime(2020, 1, 2, 4, tzinfo=timezone.utc)
    assert snapshot.windows[1].resets_at is None


@pytest.mark.parametrize("value", ["2020-01-02T03:04:05", "2020-01-02", "nonsense", None,
                                    "9999-12-31T23:59:59-23:00", "x" * 65])
@pytest.mark.parametrize("field", ["observed_at", "resets_at"])
def test_timezone_and_invalid_timestamps(tmp_path, value, field):
    data = payload()
    if field == "observed_at":
        data[field] = value
    else:
        data["windows"][0][field] = value
    if field == "resets_at" and value is None:
        assert fetch(tmp_path, data).windows[0].resets_at is None
    else:
        with pytest.raises(ProviderError):
            fetch(tmp_path, data)


def test_future_time_grace_and_stale_time_preserved(tmp_path):
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    with patch("dowidget.local_usage.datetime") as clock:
        clock.fromisoformat.side_effect = datetime.fromisoformat
        clock.now.return_value = now
        data = payload()
        data["observed_at"] = (now + timedelta(minutes=5)).isoformat()
        assert fetch(tmp_path, data).observed_at == now + timedelta(minutes=5)
        data["observed_at"] = (now + timedelta(minutes=5, seconds=1)).isoformat()
        with pytest.raises(ProviderError, match="observation time is in the future"):
            fetch(tmp_path, data)
        data["observed_at"] = OBSERVED
        assert fetch(tmp_path, data).observed_at == datetime.fromisoformat(OBSERVED)


def test_provider_mismatch_and_unsupported_provider(tmp_path):
    with pytest.raises(ProviderError, match="does not match"):
        fetch(tmp_path, payload("glm"))
    with pytest.raises(ProviderError, match="not supported"):
        LocalUsageProvider("unknown")


@pytest.mark.parametrize("field", ["provider", "product", "observed_at"])
def test_required_metadata(tmp_path, field):
    data = payload()
    del data[field]
    with pytest.raises(ProviderError):
        fetch(tmp_path, data)


@pytest.mark.parametrize("change", [
    {"product": ""}, {"product": " "}, {"product": "x" * 121},
    {"product": "<b>Live</b>"}, {"note": "SECRET\n"}, {"note": "x" * 501},
    {"note": "\u202eHidden"}, {"demo": "false"}, {"demo": 0},
    {"balances": [] , "windows": []}, {"windows": {}}, {"balances": None},
    {"windows": [{"name": ""}]}, {"windows": [{"name": "X", "remaining": "100"}]},
    {"windows": [{"name": "X", "used_percent": "2", "used": "1"}]},
    {"windows": [{"name": "X", "used_percent": True}]},
    {"windows": [{"name": "X", "used_percent": 25}]},
    {"balances": [{"currency": "USD"}]},
    {"balances": [{"currency": "USD", "total": "NaN"}]},
    {"balances": [{"currency": "USD", "total": None}]},
    {"balances": [{"currency": "USD", "total": "1", "granted": "bad"}]},
    {"balances": [{"currency": "<USD>", "total": "1"}]},
    {"balances": [{"currency": "USD", "total": "1", "api_key": "SECRET"}]},
    {"windows": [{"name": "X", "access_token": "SECRET"}]},
    {"windows": [{"name": "X"}] * (MAX_ROWS + 1)},
    {"balances": [{"currency": "USD", "total": "1"}] * (MAX_ROWS + 1)},
    {"api_key": "SECRET"}, {"credentials": {"token": "SECRET"}},
    {"metrics": []},
])
def test_strict_schema_and_credential_rejection(tmp_path, change):
    data = payload()
    data.update(change)
    with pytest.raises(ProviderError) as caught:
        fetch(tmp_path, data)
    assert "SECRET" not in str(caught.value)
    assert caught.value.kind == "setup_required"


@pytest.mark.parametrize("value", ["1" * 161, "1e101", "1e-101", "9" * 102,
                                    "1e999999999999999999999999999999999999"])
@pytest.mark.parametrize("field", ["balance", "percent", "used", "total"])
def test_number_length_and_exponent_bounds(tmp_path, value, field):
    data = payload()
    if field == "balance":
        data["balances"] = [{"currency": "USD", "total": value}]
    elif field == "percent":
        data["windows"] = [{"name": "X", "used_percent": value}]
    else:
        data["windows"] = [{"name": "X", "used": "1", "total": "10", field: value}]
    with pytest.raises(ProviderError):
        fetch(tmp_path, data)


@pytest.mark.parametrize("body", [b"SECRET", b"\xff", b"{}", b"[]", b"null",
                                  b'{"provider":"gemini","provider":"glm"}',
                                  b'{"api_key":"SECRET"}', b'{"value":NaN}',
                                  b'{"value":' + b"9" * 10000 + b"}",
                                  b"[" * 2000 + b"]" * 2000,
                                  b"x" * (MAX_BODY + 1)],
                         ids=["not-json", "invalid-utf8", "empty-object", "array", "null",
                              "duplicate-provider", "credential-file", "nonfinite",
                              "large-json-number", "deep-nesting", "oversized"])
def test_malformed_bounded_body_and_safe_errors(tmp_path, body):
    with pytest.raises(ProviderError) as caught:
        fetch(tmp_path, body=body)
    assert "SECRET" not in str(caught.value)
    assert str(tmp_path) not in str(caught.value)
    assert caught.value.__cause__ is None


def test_body_at_limit_is_accepted(tmp_path):
    body = json.dumps(payload()).encode()
    snapshot = fetch(tmp_path, body=body + b" " * (MAX_BODY - len(body)))
    assert [window.remaining for window in snapshot.windows] == [Decimal("80"), Decimal("62.5")]


@pytest.mark.parametrize("path", ["", "missing-SECRET.json", "nul\x00SECRET"])
def test_safe_file_errors(path):
    with pytest.raises(ProviderError) as caught:
        LocalUsageProvider("gemini").fetch(path)
    assert "SECRET" not in str(caught.value)
    assert caught.value.__cause__ is None


def test_directory_rejected(tmp_path):
    with pytest.raises(ProviderError, match="regular"):
        LocalUsageProvider("gemini").fetch(str(tmp_path))


def test_unreadable_file_error_redacted(tmp_path):
    selected = tmp_path / "SECRET.json"
    selected.write_text(json.dumps(payload()), encoding="utf-8")
    with patch("dowidget.local_usage.Path.open", side_effect=PermissionError("SECRET")):
        with pytest.raises(ProviderError) as caught:
            LocalUsageProvider("gemini").fetch(str(selected))
    assert str(caught.value) == "Local usage snapshot file could not be read."
    assert caught.value.__cause__ is None
