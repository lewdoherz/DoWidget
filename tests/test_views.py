from datetime import datetime, timezone
from decimal import Decimal

import pytest
from PySide6.QtWidgets import QApplication

from dowidget.app import CompactCard, compact_window_name, provider_tooltip
from dowidget.models import Balance, ProviderError, Snapshot
from dowidget.providers import parse_codex_limits
from dowidget.state import ProviderState


@pytest.fixture(scope="module")
def qt_app():
    app = QApplication.instance() or QApplication([])
    yield app


def ready(snapshot):
    state = ProviderState()
    state.succeed(snapshot, 0, datetime(2026, 10, 12, tzinfo=timezone.utc), 300)
    return state


def test_compact_preserves_multiple_currencies_and_decimal_precision(qt_app):
    state = ready(Snapshot(balances=(Balance("CNY", Decimal("24.8400")),
                                    Balance("USD", Decimal("0.123456789123456789")))))
    card = CompactCard("deepseek", "DeepSeek")
    card.render(state)
    assert "CNY 24.8400" in card.value.text()
    assert "USD 0.123456789123456789" in card.value.text()
    card.close()


def test_compact_displays_both_source_windows_and_keeps_unknown_unknown(qt_app):
    snapshot = parse_codex_limits({"rateLimits": {"limitId": "codex", "primary": {
        "usedPercent": 27, "windowDurationMins": 300, "resetsAt": 1730947200},
        "secondary": {"windowDurationMins": 10080}}})
    state = ready(snapshot)
    card = CompactCard("openai", "Codex")
    card.render(state)
    assert "5h: 73.0%" in card.value.text()
    assert "Week: Unknown" in card.value.text()
    assert "Week: 0" not in card.value.text()
    assert "Week: 100" not in card.value.text()
    assert "Resets:" in card.toolTip()
    card.close()


def test_identical_window_durations_remain_distinguishable(qt_app):
    snapshot = parse_codex_limits({"rateLimits": {"limitId": "codex", "primary": {
        "usedPercent": 10, "windowDurationMins": 300}, "secondary": {
        "usedPercent": 20, "windowDurationMins": 300}}})
    card = CompactCard("openai", "Codex")
    card.render(ready(snapshot))
    assert "primary" in card.value.text() and "90.0%" in card.value.text()
    assert "secondary" in card.value.text() and "80.0%" in card.value.text()
    card.close()


def test_compact_retains_stale_balance_and_success_time_during_retry(qt_app):
    state = ready(Snapshot(balances=(Balance("CNY", Decimal("24.84")),)))
    timestamp = state.updated_at
    state.fail(ProviderError("Connection failed.", "network"), 1, 300)
    state.busy = True
    card = CompactCard("deepseek", "DeepSeek")
    card.render(state)
    assert "CNY 24.84" in card.value.text()
    assert "stale" in card.indicator.accessibleName().lower()
    assert "Connection failed." in card.toolTip()
    assert state.updated_at == timestamp
    assert "Last successful update:" in card.toolTip()
    card.close()


def test_missing_and_error_states_never_fabricate_a_percentage(qt_app):
    state = ProviderState()
    card = CompactCard("openai", "Codex")
    card.render(state)
    assert "%" not in card.value.text()
    state.fail(ProviderError("Service unavailable.", "unavailable"), 0, 300)
    card.render(state)
    assert "%" not in card.value.text()
    assert "Service unavailable." in card.toolTip()
    assert card.indicator.accessibleName() == "Unavailable"
    card.close()


def test_provider_tooltip_escapes_source_labels():
    snapshot = parse_codex_limits({"rateLimits": {"limitId": "codex", "limitName": "<b>untrusted</b>",
                                                  "primary": {"usedPercent": 25}}})
    tooltip = provider_tooltip(ready(snapshot))
    assert "<b>untrusted</b>" not in tooltip
    assert "&lt;b&gt;untrusted&lt;/b&gt;" in tooltip


@pytest.mark.parametrize("name,expected", [
    ("codex · primary (5 hour)", "5h"),
    ("codex · secondary (1 week)", "Week"),
    ("codex · primary (15 minute)", "15m"),
    ("Review · primary (5 hour)", "Review 5h"),
    ("codex · secondary", "secondary"),
])
def test_compact_window_labels_keep_source_duration_or_slot(name, expected):
    assert compact_window_name(name) == expected
