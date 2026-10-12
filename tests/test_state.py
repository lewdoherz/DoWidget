from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from dowidget.models import Balance, ProviderError, Snapshot
from dowidget.state import ProviderState


NOW = datetime(2026, 10, 12, 12, 30, tzinfo=timezone.utc)
SNAPSHOT = Snapshot(balances=(Balance("USD", Decimal("12.34")),))


def test_initial_state_is_ready_for_setup_and_overlap_is_rejected():
    state = ProviderState()
    assert state.status == "setup_required"
    assert state.snapshot is None
    assert state.updated_at is None
    assert state.begin(100)
    assert state.busy
    assert not state.begin(100)
    assert not state.begin(100, manual=True)


def test_success_sets_utc_time_and_regular_refresh_interval():
    state = ProviderState()
    assert state.begin(10)
    local_time = NOW.astimezone(timezone(timedelta(hours=3)))
    state.succeed(SNAPSHOT, 10, local_time, 300)
    assert not state.busy
    assert state.status == "ready"
    assert state.snapshot is SNAPSHOT
    assert state.updated_at == NOW
    assert state.updated_at.tzinfo is timezone.utc
    assert state.failure_count == 0
    assert state.next_due == 310
    assert not state.begin(309.999)
    assert state.begin(310)


def test_naive_success_timestamp_is_explicitly_utc():
    state = ProviderState()
    state.succeed(SNAPSHOT, 1, NOW.replace(tzinfo=None), 300)
    assert state.updated_at == NOW
    assert state.updated_at.tzinfo is timezone.utc


def test_manual_refresh_bypasses_only_success_interval():
    state = ProviderState()
    state.succeed(SNAPSHOT, 10, NOW, 300)
    assert not state.begin(20)
    assert state.begin(20, manual=True)
    assert not state.begin(20, manual=True)
    state.fail(ProviderError("Service temporarily unavailable.", "network"), 20, 300)
    assert state.next_due == 320
    assert not state.begin(319, manual=True)
    assert state.begin(320, manual=True)


@pytest.mark.parametrize("kind", ["setup_required", "auth", "network", "rate_limit", "error"])
def test_first_failure_without_snapshot_preserves_error_kind(kind):
    state = ProviderState()
    error = ProviderError("Safe fixed message.", kind)
    state.begin(5)
    state.fail(error, 5, 5)
    assert not state.busy
    assert state.status == kind
    assert state.message == "Safe fixed message."
    assert state.snapshot is None
    assert state.updated_at is None
    assert state.failure_count == 1
    assert state.next_due == 35


def test_stale_snapshot_and_timestamp_survive_failure_then_recover():
    state = ProviderState()
    state.succeed(SNAPSHOT, 0, NOW, 60)
    assert state.begin(60)
    state.fail(ProviderError("Connection failed.", "network"), 60, 60)
    assert state.status == "stale"
    assert state.snapshot is SNAPSHOT
    assert state.updated_at == NOW
    assert state.message == "Connection failed."
    assert not state.begin(119, manual=True)
    assert state.begin(120)
    replacement = Snapshot(balances=(Balance("USD", Decimal("11.22")),))
    later = NOW + timedelta(minutes=2)
    state.succeed(replacement, 120, later, 60)
    assert state.snapshot is replacement
    assert state.updated_at == later
    assert state.status == "ready"
    assert state.message == ""
    assert state.failure_count == 0
    assert state.next_due == 180
    state.fail(ProviderError("Connection failed.", "network"), 180, 60)
    assert state.next_due == 240  # Success reset the exponential backoff.


@pytest.mark.parametrize("interval,expected", [(0, 30), (10, 30), (30, 30), (300, 300), (3600, 3600)])
def test_first_failure_waits_for_interval_or_thirty_seconds(interval, expected):
    state = ProviderState()
    state.fail(ProviderError("Connection failed.", "network"), 100, interval)
    assert state.next_due == 100 + expected


def test_exponential_backoff_is_bounded_and_manual_respects_every_cooldown():
    state = ProviderState()
    now = 100.0
    expected_delays = [300, 600, 1200, 2400, 3600, 3600, 3600, 3600, 3600]
    for count, expected in enumerate(expected_delays, 1):
        assert state.begin(now)
        state.fail(ProviderError("Connection failed.", "network"), now, 300)
        assert state.failure_count == count
        assert state.next_due == now + expected
        assert not state.begin(state.next_due - 0.01)
        assert not state.begin(state.next_due - 0.01, manual=True)
        now = state.next_due
    assert state.begin(now, manual=True)


@pytest.mark.parametrize("retry_after,expected", [(5, 30), (90, 90), (7200, 7200)])
def test_retry_after_is_minimum_even_above_backoff_cap(retry_after, expected):
    state = ProviderState()
    state.fail(ProviderError("Rate limit reached.", "rate_limit", retry_after), 100, 10)
    assert state.status == "rate_limit"
    assert state.next_due == 100 + expected
    assert not state.begin(state.next_due - 1, manual=True)
    assert state.begin(state.next_due)


@pytest.mark.parametrize("retry_after", [None, -1, 0, float("nan"), float("inf"), True, "secret"])
def test_invalid_retry_after_cannot_poison_monotonic_deadline(retry_after):
    state = ProviderState()
    state.fail(ProviderError("Rate limit reached.", "rate_limit", retry_after), 100, 60)
    assert state.next_due == 160
    assert state.message == "Rate limit reached."
    assert "secret" not in state.message


def test_rate_limit_preserves_stale_data_and_fixed_error_message():
    state = ProviderState()
    state.succeed(SNAPSHOT, 1, NOW, 60)
    state.fail(ProviderError("Rate limit reached. Try again later.", "rate_limit", 120), 2, 60)
    assert state.status == "stale"
    assert state.message == "Rate limit reached. Try again later."
    assert state.snapshot is SNAPSHOT
    assert state.updated_at == NOW
    assert state.next_due == 122


def test_reset_for_missing_provider_configuration_clears_all_history():
    state = ProviderState()
    state.succeed(SNAPSHOT, 1, NOW, 60)
    state.fail(ProviderError("Connection failed.", "network", 7200), 2, 60)
    state.busy = True
    state.reset()
    assert state == ProviderState()
    assert state.begin(3)  # No stale cooldown or overlap gate survives disconnect.


def test_reset_accepts_explicit_status_and_message():
    state = ProviderState(snapshot=SNAPSHOT, updated_at=NOW, busy=True, next_due=999, failure_count=10)
    state.reset(status="disabled", message="Provider disabled.")
    assert state.status == "disabled"
    assert state.message == "Provider disabled."
    assert state.snapshot is None
    assert state.updated_at is None
    assert not state.busy
    assert state.next_due == 0
    assert state.failure_count == 0


def test_wall_clock_changes_do_not_change_monotonic_refresh_gating():
    state = ProviderState()
    state.succeed(SNAPSHOT, 100, NOW - timedelta(days=1), 60)
    assert state.next_due == 160
    assert not state.begin(159)
    assert state.begin(160)
    state.succeed(SNAPSHOT, 160, NOW + timedelta(days=30), 60)
    assert state.next_due == 220
    assert not state.begin(219)
