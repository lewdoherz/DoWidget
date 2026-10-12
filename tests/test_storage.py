import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from dowidget import storage
from dowidget.connections import Connection, default_connections, new_connection_id
from dowidget.models import ProviderError
from dowidget.storage import Config, ConfigStore, CredentialStore


SECRET = "fake-test-secret-never-a-real-key"
OTHER_SECRET = "another-fake-key"
LEGACY_SLOT = ("DoWidget.DeepSeek", "api-key")


class FakeBackend:
    priority = 5

    def __init__(self):
        self.secrets = {}
        self.calls = []
        self.fail_get = False
        self.fail_set = False
        self.fail_delete = False

    def get_password(self, service, username):
        self.calls.append(("get", service, username))
        if self.fail_get:
            raise RuntimeError(SECRET)
        return self.secrets.get((service, username))

    def set_password(self, service, username, password):
        self.calls.append(("set", service, username))
        if self.fail_set:
            raise RuntimeError(SECRET)
        self.secrets[service, username] = password

    def delete_password(self, service, username):
        self.calls.append(("delete", service, username))
        if self.fail_delete:
            raise RuntimeError(SECRET)
        self.secrets.pop((service, username), None)


@pytest.fixture
def backend(monkeypatch):
    instance = FakeBackend()
    monkeypatch.setattr(storage.sys, "platform", "win32")
    monkeypatch.setattr(
        storage.importlib, "import_module",
        lambda name: SimpleNamespace(WinVaultKeyring=lambda: instance),
    )
    return instance


def assert_safe(error, store):
    assert isinstance(error, ProviderError)
    assert error.kind == "storage_unavailable"
    assert SECRET not in str(error)
    assert SECRET not in repr(error)
    assert SECRET not in store.status
    assert SECRET not in repr(store)
    assert error.__suppress_context__


@pytest.mark.parametrize("platform,module_name,class_name", [
    ("win32", "keyring.backends.Windows", "WinVaultKeyring"),
    ("linux", "keyring.backends.SecretService", "Keyring"),
])
def test_only_explicit_os_backends_and_no_constructor_reads(monkeypatch, platform, module_name, class_name):
    calls = []
    backend = FakeBackend()

    def import_module(name):
        calls.append(name)
        assert name == module_name
        return SimpleNamespace(**{class_name: lambda: backend})

    monkeypatch.setattr(storage.sys, "platform", platform)
    monkeypatch.setattr(storage.importlib, "import_module", import_module)
    store = CredentialStore()
    assert store.available
    assert calls == [module_name]
    assert backend.calls == []
    store.connect(SECRET, persist=True)
    assert store.get() == SECRET
    assert CredentialStore().get() == SECRET


@pytest.mark.parametrize("platform", ["darwin", "freebsd"])
def test_unsupported_platform_allows_session_without_backend(monkeypatch, platform):
    monkeypatch.setattr(storage.sys, "platform", platform)

    def forbidden_import(name):
        pytest.fail("Unsupported platforms must not discover a configured backend")

    monkeypatch.setattr(storage.importlib, "import_module", forbidden_import)
    store = CredentialStore()
    assert not store.available
    assert store.get() is None
    store.connect(SECRET, persist=False)
    assert store.get() == SECRET
    assert SECRET not in repr(store)
    with pytest.raises(ProviderError) as caught:
        store.connect(SECRET, persist=True)
    assert_safe(caught.value, store)
    store.disconnect()
    assert store.get() is None


@pytest.mark.parametrize("namespace", [
    SimpleNamespace(ChainerBackend=lambda: FakeBackend()),
    SimpleNamespace(PlaintextKeyring=lambda: FakeBackend()),
    SimpleNamespace(UnknownBackend=lambda: FakeBackend()),
])
def test_unrecognized_backend_is_not_used(monkeypatch, namespace):
    monkeypatch.setattr(storage.sys, "platform", "win32")
    monkeypatch.setattr(storage.importlib, "import_module", lambda name: namespace)
    store = CredentialStore()
    assert not store.available
    store.connect(SECRET, persist=False)
    assert store.get() == SECRET
    with pytest.raises(ProviderError) as caught:
        store.connect(SECRET, persist=True)
    assert_safe(caught.value, store)


def test_discovery_failure_is_safe_and_allows_session(monkeypatch):
    monkeypatch.setattr(storage.sys, "platform", "linux")

    def broken_import(name):
        raise RuntimeError(SECRET)

    monkeypatch.setattr(storage.importlib, "import_module", broken_import)
    store = CredentialStore()
    assert not store.available
    assert SECRET not in store.status
    store.connect(SECRET, persist=False)
    assert store.get() == SECRET


@pytest.mark.parametrize("priority", [0, -1, True, float("nan"), float("inf"), "unknown"])
def test_invalid_backend_priority_is_unavailable_without_reading(backend, priority):
    backend.priority = priority
    store = CredentialStore()
    assert not store.available
    assert backend.calls == []
    assert SECRET not in store.status


def test_priority_failure_retains_backend_for_mandatory_delete(monkeypatch):
    class LockedBackend(FakeBackend):
        @property
        def priority(self):
            raise RuntimeError(SECRET)

    backend = LockedBackend()
    backend.fail_get = True
    monkeypatch.setattr(storage.sys, "platform", "linux")
    monkeypatch.setattr(storage.importlib, "import_module", lambda name: SimpleNamespace(Keyring=lambda: backend))
    store = CredentialStore()
    assert not store.available
    with pytest.raises(ProviderError) as caught:
        store.connect(SECRET, persist=False)
    assert_safe(caught.value, store)
    assert store.get() == SECRET
    assert backend.calls


@pytest.mark.parametrize("provider", ["deepseek", "claude", "grok", "gemini", "glm", "codex"])
def test_two_connections_have_independent_persistence_and_removal(backend, provider):
    first_id, second_id = new_connection_id(), new_connection_id()
    first, second = CredentialStore(first_id, provider), CredentialStore(second_id, provider)
    first.connect(SECRET, persist=True)
    second.connect(OTHER_SECRET, persist=True)
    assert len(backend.secrets) == 2
    assert CredentialStore(first_id, provider).get() == SECRET
    assert CredentialStore(second_id, provider).get() == OTHER_SECRET
    first.disconnect()
    assert first.get() is None
    assert CredentialStore(first_id, provider).get() is None
    assert CredentialStore(second_id, provider).get() == OTHER_SECRET
    assert list(backend.secrets.values()) == [OTHER_SECRET]
    assert SECRET not in repr(first)


def test_session_key_replaces_only_its_own_persistent_key(backend):
    first_id, second_id = new_connection_id(), new_connection_id()
    first = CredentialStore(first_id, "deepseek")
    second = CredentialStore(second_id, "deepseek")
    first.connect(OTHER_SECRET, persist=True)
    second.connect(OTHER_SECRET, persist=True)
    first.connect(SECRET, persist=False)
    assert first.get() == SECRET
    assert CredentialStore(first_id, "deepseek").get() is None
    assert CredentialStore(second_id, "deepseek").get() == OTHER_SECRET
    assert list(backend.secrets.values()) == [OTHER_SECRET]


@pytest.mark.parametrize("failure", ["fail_get", "fail_delete"])
def test_session_delete_failure_retains_session_without_claiming_session_only(backend, failure):
    store = CredentialStore()
    store.connect(OTHER_SECRET, persist=True)
    setattr(backend, failure, True)
    with pytest.raises(ProviderError) as caught:
        store.connect(SECRET, persist=False)
    assert_safe(caught.value, store)
    assert not store.available
    assert OTHER_SECRET in backend.secrets.values()
    assert store.get() == SECRET


def test_failed_save_preserves_session_and_supports_session_retry(backend):
    backend.fail_set = True
    store = CredentialStore()
    with pytest.raises(ProviderError) as caught:
        store.connect(SECRET, persist=True)
    assert_safe(caught.value, store)
    assert store.get() == SECRET
    store.connect(SECRET, persist=False)
    assert store.available
    assert not backend.secrets


def test_get_failure_is_safe_and_can_recover(backend):
    CredentialStore().connect(SECRET, persist=True)
    store = CredentialStore()
    backend.fail_get = True
    assert store.get() is None
    assert not store.available
    assert SECRET not in store.status
    backend.fail_get = False
    assert store.get() == SECRET
    assert store.available


def test_disconnect_failure_retains_session_and_can_be_retried(backend):
    store = CredentialStore()
    store.connect(SECRET, persist=True)
    backend.fail_delete = True
    with pytest.raises(ProviderError) as caught:
        store.disconnect()
    assert_safe(caught.value, store)
    assert store.get() == SECRET
    assert SECRET in backend.secrets.values()
    backend.fail_delete = False
    store.disconnect()
    assert store.get() is None
    assert not backend.secrets


def test_default_deepseek_migrates_legacy_only_on_get_without_data_loss(backend):
    backend.secrets[LEGACY_SLOT] = SECRET
    store = CredentialStore()
    assert backend.calls == []
    assert store.get() == SECRET
    assert LEGACY_SLOT not in backend.secrets
    assert list(backend.secrets.values()) == [SECRET]
    operations = [call[0] for call in backend.calls]
    assert operations.index("set") < operations.index("delete")
    assert CredentialStore().get() == SECRET


@pytest.mark.parametrize("failure", ["fail_set", "fail_delete"])
def test_migration_failure_keeps_legacy_and_usable_session(backend, failure):
    backend.secrets[LEGACY_SLOT] = SECRET
    setattr(backend, failure, True)
    store = CredentialStore()
    assert store.get() == SECRET
    assert backend.secrets[LEGACY_SLOT] == SECRET
    assert SECRET not in store.status
    assert not store.available
    if failure == "fail_set":
        assert len(backend.secrets) == 1
        assert not any(call[0] == "delete" for call in backend.calls)
    else:
        assert len(backend.secrets) == 2


def test_new_saved_key_wins_over_legacy_and_disconnect_clears_both(backend):
    store = CredentialStore()
    store.connect(OTHER_SECRET, persist=True)
    backend.secrets[LEGACY_SLOT] = SECRET
    assert CredentialStore().get() == OTHER_SECRET
    store.disconnect()
    assert not backend.secrets
    assert CredentialStore().get() is None


def test_other_connections_do_not_read_or_delete_legacy(backend):
    backend.secrets[LEGACY_SLOT] = SECRET
    store = CredentialStore(new_connection_id(), "deepseek")
    assert store.get() is None
    store.connect(OTHER_SECRET, persist=True)
    store.disconnect()
    assert backend.secrets == {LEGACY_SLOT: SECRET}
    assert all(call[1:] != LEGACY_SLOT for call in backend.calls)


def test_session_only_default_removes_unmigrated_legacy(backend):
    backend.secrets[LEGACY_SLOT] = OTHER_SECRET
    store = CredentialStore()
    store.connect(SECRET, persist=False)
    assert not backend.secrets
    assert store.get() == SECRET
    assert CredentialStore().get() is None


@pytest.mark.parametrize("connection_id,provider", [
    ("../other", "deepseek"), ("deepseek-default", "claude"),
    (new_connection_id(), "unknown"), (None, "deepseek"),
])
def test_invalid_credential_identity_fails_without_backend_access(backend, connection_id, provider):
    with pytest.raises(ValueError):
        CredentialStore(connection_id, provider)
    assert backend.calls == []


def test_config_missing_and_malformed_defaults(tmp_path):
    path = tmp_path / "settings.json"
    store = ConfigStore(path)
    assert store.load() == Config()
    for data in ("{invalid", "null", "[]", '"text"', '{"api_key":"' + SECRET + '"}'):
        path.write_text(data, encoding="utf-8")
        assert store.load() == Config()
    path.write_bytes(b"\xff\xfe")
    assert store.load() == Config()


@pytest.mark.parametrize("interval", [0, 1441, -5, True, 1.0, "5", None])
def test_config_invalid_interval_defaults(tmp_path, interval):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"interval_minutes": interval}), encoding="utf-8")
    assert ConfigStore(path).load().interval_minutes == 5


@pytest.mark.parametrize("interval", [1, 5, 1440])
def test_config_valid_interval_boundaries(tmp_path, interval):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"interval_minutes": interval}), encoding="utf-8")
    assert ConfigStore(path).load().interval_minutes == interval


@pytest.mark.parametrize("value", [0, 1, "false", "true", None, []])
def test_config_requires_actual_booleans(tmp_path, value):
    path = tmp_path / "settings.json"
    fields = ("auto_refresh", "always_on_top", "codex_enabled", "minimize_to_tray")
    path.write_text(json.dumps({field: value for field in fields}), encoding="utf-8")
    assert ConfigStore(path).load() == Config()


@pytest.mark.parametrize("value", [True, 1.5, "10", 100001, -100001, None])
def test_config_invalid_coordinates_default(tmp_path, value):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"x": value, "y": value}), encoding="utf-8")
    config = ConfigStore(path).load()
    assert config.x is None and config.y is None


@pytest.mark.parametrize("codex_enabled", [True, False])
def test_old_config_migrates_connections_and_preserves_behavior(tmp_path, codex_enabled):
    path = tmp_path / "settings.json"
    values = {
        "interval_minutes": 12, "auto_refresh": False, "always_on_top": True,
        "codex_enabled": codex_enabled, "x": -40, "y": 20,
        "width": 500, "height": 600, "compact_width": 300, "compact_height": 180,
        "view": "compact", "minimize_to_tray": True,
    }
    path.write_text(json.dumps(values), encoding="utf-8")
    config = ConfigStore(path).load()
    connections = default_connections()
    connections[1] = replace(connections[1], enabled=codex_enabled)
    assert config == Config(
        interval_minutes=12, auto_refresh=False, always_on_top=True,
        connections=connections, x=-40, y=20, width=500, height=600,
        compact_width=300, compact_height=180, view="compact", minimize_to_tray=True,
    )
    ConfigStore(path).save(config)
    assert "codex_enabled" not in json.loads(path.read_text(encoding="utf-8"))


@pytest.mark.parametrize("field,minimum", [
    ("width", 340), ("height", 280), ("compact_width", 260), ("compact_height", 130),
])
@pytest.mark.parametrize("boundary", ["minimum", "maximum"])
def test_config_valid_dimension_boundaries(tmp_path, field, minimum, boundary):
    value = minimum if boundary == "minimum" else 10_000
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({field: value}), encoding="utf-8")
    assert getattr(ConfigStore(path).load(), field) == value


@pytest.mark.parametrize("field,minimum", [
    ("width", 340), ("height", 280), ("compact_width", 260), ("compact_height", 130),
])
@pytest.mark.parametrize("value", [True, False, 400.0, "400", None, [], 0, -1, 10_001, "below"])
def test_config_invalid_dimensions_default(tmp_path, field, minimum, value):
    value = minimum - 1 if value == "below" else value
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({field: value}), encoding="utf-8")
    assert getattr(ConfigStore(path).load(), field) == getattr(Config(), field)


@pytest.mark.parametrize("view", ["Compact", "other", "", 1, True, None, [], {}])
def test_config_invalid_view_defaults(tmp_path, view):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"view": view}), encoding="utf-8")
    assert ConfigStore(path).load().view == "detailed"


@pytest.mark.parametrize("view", ["compact", "detailed"])
@pytest.mark.parametrize("minimize_to_tray", [False, True])
def test_config_roundtrip_whitelist_and_atomic_replace(tmp_path, monkeypatch, view, minimize_to_tray):
    path = tmp_path / "nested" / "settings.json"
    store = ConfigStore(path)
    connection = Connection(new_connection_id(), "claude", "Work", "Claude", options={"user_id": "user_work"})
    config = Config(
        interval_minutes=1440, auto_refresh=False, always_on_top=True,
        connections=[connection], x=-100000, y=100000, width=700, height=900,
        compact_width=350, compact_height=200, view=view, minimize_to_tray=minimize_to_tray,
    )
    config.api_key = SECRET
    replacements = []
    real_replace = storage.os.replace

    def capture_replace(source, target):
        assert source != target
        assert Path(source).parent == path.parent
        replacements.append((source, target))
        return real_replace(source, target)

    monkeypatch.setattr(storage.os, "replace", capture_replace)
    store.save(config)
    assert replacements
    assert store.load() == config
    assert SECRET not in path.read_text(encoding="utf-8")
    assert not list(path.parent.glob("*.tmp"))


@pytest.mark.parametrize("profiles", [[], None, {}, "bad", [None, {}, {"api_key": SECRET}]])
def test_explicit_empty_or_malformed_profiles_never_recreate_cards(tmp_path, profiles):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"connections": profiles, "codex_enabled": True}), encoding="utf-8")
    store = ConfigStore(path)
    config = store.load()
    assert config.connections == []
    store.save(config)
    assert store.load().connections == []
    assert json.loads(path.read_text(encoding="utf-8"))["connections"] == []


def test_config_duplicate_and_secret_option_profiles_are_safe(tmp_path):
    path = tmp_path / "settings.json"
    connection_id = new_connection_id()
    valid = {"id": connection_id, "provider": "deepseek", "name": "First", "api_key": SECRET}
    duplicate = {**valid, "name": "Second"}
    secret_options = {"id": new_connection_id(), "provider": "grok", "name": "Secret", "options": {"api_key": SECRET}}
    path.write_text(json.dumps({"connections": [valid, duplicate, secret_options]}), encoding="utf-8")
    store = ConfigStore(path)
    config = store.load()
    assert config.connections == [Connection(connection_id, "deepseek", "First")]
    assert SECRET not in repr(config)
    store.save(config)
    assert SECRET not in path.read_text(encoding="utf-8")


def test_config_save_validates_fields_and_excludes_extra_secrets(tmp_path):
    path = tmp_path / "settings.json"
    config = Config(
        interval_minutes=True, auto_refresh=SECRET, x=10**20,
        width=True, height=279, compact_width="320", compact_height=10_001,
        view="unknown", minimize_to_tray=1,
    )
    config.api_key = SECRET
    ConfigStore(path).save(config)
    assert ConfigStore(path).load() == Config()
    assert SECRET not in path.read_text(encoding="utf-8")


def test_config_save_failure_is_safe_and_preserves_previous_file(tmp_path, monkeypatch):
    path = tmp_path / "settings.json"
    path.write_text('{"interval_minutes": 12}', encoding="utf-8")
    original = path.read_bytes()

    def failed_replace(source, target):
        raise OSError(SECRET)

    monkeypatch.setattr(storage.os, "replace", failed_replace)
    with pytest.raises(ProviderError) as caught:
        ConfigStore(path).save(Config())
    assert SECRET not in repr(caught.value)
    assert caught.value.__suppress_context__
    assert path.read_bytes() == original
    assert not list(tmp_path.glob("*.tmp"))


def test_config_read_os_failure_returns_safe_defaults(tmp_path, monkeypatch):
    def broken_open(self, *args, **kwargs):
        raise PermissionError(SECRET)

    monkeypatch.setattr(Path, "open", broken_open)
    assert ConfigStore(tmp_path / "settings.json").load() == Config()


def test_config_write_failure_cleans_temporary_file(tmp_path, monkeypatch):
    def failed_sync(descriptor):
        raise OSError(SECRET)

    monkeypatch.setattr(storage.os, "fsync", failed_sync)
    with pytest.raises(ProviderError) as caught:
        ConfigStore(tmp_path / "settings.json").save(Config())
    assert SECRET not in repr(caught.value)
    assert not list(tmp_path.glob("*.tmp"))
    assert not (tmp_path / "settings.json").exists()
