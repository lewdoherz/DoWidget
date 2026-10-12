from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
import time

import pytest
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from dowidget.connections import Connection, new_connection_id
from dowidget.models import ProviderError
from dowidget.runtime import Runtime
from dowidget.storage import Config, ConfigStore


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr("dowidget.storage._discover_backend", lambda: None)
    config = Config(connections=[])
    store = ConfigStore(tmp_path / "settings.json")
    def save():
        store.save(config)
        return True
    engine = Runtime(config, tmp_path, save)
    yield engine, app, store
    engine.shutdown()
    app.processEvents()


def write_usage(path, provider, used, *, observed=None):
    path.write_text(json.dumps({"provider": provider, "product": "Synthetic regression source",
        "observed_at": (observed or datetime.now(timezone.utc)).isoformat(), "demo": True,
        "windows": [{"name": "5h", "used_percent": used}, {"name": "Week", "used_percent": None}]}), encoding="utf-8")


def settle(engine, app):
    deadline = time.monotonic() + 5
    while any(account.state.busy for account in engine.accounts.values()) and time.monotonic() < deadline:
        app.processEvents()
        QTest.qWait(5)
    assert not any(account.state.busy for account in engine.accounts.values())


def local(engine, path, provider="codex", name="Account", enabled=True):
    connection = Connection(new_connection_id(), provider, name, source="local", enabled=enabled,
                            options={"path": str(path)})
    engine.add(connection)
    return connection


def test_two_same_provider_accounts_keep_windows_failures_and_removal_independent(runtime, tmp_path):
    engine, app, store = runtime
    first, second = tmp_path / "first.json", tmp_path / "second.json"
    write_usage(first, "codex", "27")
    write_usage(second, "codex", "80")
    a, b = local(engine, first, name="Personal"), local(engine, second, name="Work")
    engine.refresh(True)
    settle(engine, app)
    sa, sb = engine.accounts[a.id].state, engine.accounts[b.id].state
    assert sa.snapshot.windows[0].remaining == Decimal("73")
    assert sb.snapshot.windows[0].remaining == Decimal("20")
    assert sa.snapshot.windows[1].remaining is None and sb.snapshot.windows[1].remaining is None
    original, timestamp = sa.snapshot, sa.updated_at
    first.write_text("not JSON", encoding="utf-8")
    write_usage(second, "codex", "90")
    engine.refresh(True)
    settle(engine, app)
    assert sa.status == "stale" and sa.snapshot is original and sa.updated_at == timestamp
    assert sb.status == "ready" and sb.snapshot.windows[0].remaining == Decimal("10")
    engine.disconnect(a.id, remove=True)
    assert a.id not in engine.accounts
    assert engine.accounts[b.id].state is sb and sb.status == "ready"
    assert [profile.id for profile in store.load().connections] == [b.id]


def test_rereading_old_local_data_does_not_make_it_fresh_and_new_observation_recovers(runtime, tmp_path):
    engine, app, _ = runtime
    path = tmp_path / "usage.json"
    observed = datetime.now(timezone.utc) - timedelta(hours=2)
    write_usage(path, "glm", "25", observed=observed)
    connection = local(engine, path, "glm")
    engine.refresh(True)
    settle(engine, app)
    state = engine.accounts[connection.id].state
    assert state.status == "stale" and state.updated_at == observed
    engine.refresh(True)
    settle(engine, app)
    assert state.status == "stale" and state.updated_at == observed
    write_usage(path, "glm", "30")
    engine.refresh(True)
    settle(engine, app)
    assert state.status == "ready" and state.updated_at > observed
    assert state.snapshot.windows[0].remaining == Decimal("70")


def test_local_observations_expire_even_with_automatic_refresh_disabled(runtime, tmp_path):
    engine, app, _ = runtime
    path = tmp_path / "usage.json"
    write_usage(path, "gemini", "40")
    connection = local(engine, path, "gemini")
    engine.config.auto_refresh = False
    engine.refresh(True)
    settle(engine, app)
    state = engine.accounts[connection.id].state
    original_time = state.updated_at
    state.snapshot = replace(state.snapshot, observed_at=datetime.now(timezone.utc) - timedelta(minutes=6))
    engine.expire_local()
    assert state.status == "stale" and state.updated_at == original_time
    assert state.snapshot.windows[0].remaining == Decimal("60")


def test_busy_connection_cannot_be_reconfigured_or_removed_and_refresh_does_not_overlap(runtime, tmp_path, monkeypatch):
    engine, app, _ = runtime
    path = tmp_path / "usage.json"
    write_usage(path, "gemini", "40")
    connection = local(engine, path, "gemini")
    account = engine.accounts[connection.id]
    account.state.busy = True
    with pytest.raises(ProviderError):
        engine.update(replace(connection, name="Changed"))
    with pytest.raises(ProviderError):
        engine.disconnect(connection.id, True)
    engine.refresh(True)
    assert account.connection.name == "Account" and account.state.snapshot is None
    account.state.busy = False
    engine.refresh(True)
    settle(engine, app)
    assert account.state.snapshot.windows[0].remaining == Decimal("60")


@pytest.mark.parametrize("provider", ["gemini", "glm"])
def test_unsupported_automatic_sources_never_claim_an_allowance(runtime, provider):
    engine, app, _ = runtime
    connection = Connection(new_connection_id(), provider, "Needs source")
    engine.add(connection)
    engine.refresh(True)
    state = engine.accounts[connection.id].state
    assert state.status == "unavailable" and state.snapshot is None
    assert not state.busy


def test_removing_every_connection_stays_empty_after_restart(runtime, tmp_path):
    engine, app, store = runtime
    path = tmp_path / "usage.json"
    write_usage(path, "gemini", "40")
    connection = local(engine, path, "gemini")
    engine.disconnect(connection.id, True)
    restored = Runtime(store.load(), tmp_path, lambda: True)
    try:
        assert restored.accounts == {}
    finally:
        restored.shutdown()
