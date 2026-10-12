import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from dowidget.models import ProviderError
from dowidget import storage
from dowidget.storage import Config, ConfigStore, CredentialStore


SECRET = "fake-test-secret-never-a-real-key"


class FakeBackend:
    priority = 5

    def __init__(self, saved=None):
        self.saved = saved
        self.calls = []
        self.fail_get = False
        self.fail_set = False
        self.fail_delete = False

    def get_password(self, service, username):
        self.calls.append(("get", service, username))
        if self.fail_get:
            raise RuntimeError(SECRET)
        return self.saved

    def set_password(self, service, username, password):
        self.calls.append(("set", service, username))
        if self.fail_set:
            raise RuntimeError(SECRET)
        self.saved = password

    def delete_password(self, service, username):
        self.calls.append(("delete", service, username))
        if self.fail_delete:
            raise RuntimeError(SECRET)
        self.saved = None


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
def test_only_explicit_os_backends_are_discovered(monkeypatch, platform, module_name, class_name):
    calls = []
    backend = FakeBackend(SECRET)

    def import_module(name):
        calls.append(name)
        assert name == module_name
        return SimpleNamespace(**{class_name: lambda: backend})

    monkeypatch.setattr(storage.sys, "platform", platform)
    monkeypatch.setattr(storage.importlib, "import_module", import_module)
    store = CredentialStore()
    assert store.available
    assert calls == [module_name]
    assert backend.calls == []  # Constructor never reads a credential, including demo mode.
    assert store.get() == SECRET
    assert backend.calls == [("get", "DoWidget.DeepSeek", "api-key")]


@pytest.mark.parametrize("platform", ["darwin", "freebsd"])
def test_unsupported_platform_never_consults_a_backend(monkeypatch, platform):
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
    assert store.get() is None
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


def test_priority_failure_retains_backend_for_mandatory_delete(monkeypatch):
    class LockedBackend(FakeBackend):
        @property
        def priority(self):
            raise RuntimeError(SECRET)

    backend = LockedBackend(SECRET)
    backend.fail_get = True
    monkeypatch.setattr(storage.sys, "platform", "linux")
    monkeypatch.setattr(storage.importlib, "import_module", lambda name: SimpleNamespace(Keyring=lambda: backend))
    store = CredentialStore()
    assert not store.available
    with pytest.raises(ProviderError) as caught:
        store.connect(SECRET, persist=False)
    assert_safe(caught.value, store)
    assert store.get() == SECRET
    assert backend.calls == [("get", "DoWidget.DeepSeek", "api-key")]


def test_persistent_save_uses_exact_service_and_caches_session(backend):
    store = CredentialStore()
    store.connect(SECRET, persist=True)
    assert backend.saved == SECRET
    assert backend.calls == [("set", "DoWidget.DeepSeek", "api-key")]
    assert store.get() == SECRET
    assert len(backend.calls) == 1
    assert store.available
    assert SECRET not in store.status
    assert SECRET not in repr(store)


def test_session_connection_removes_previously_saved_key_first(backend):
    backend.saved = "previous-fake-key"
    store = CredentialStore()
    store.connect(SECRET, persist=False)
    assert backend.saved is None
    assert backend.calls == [
        ("get", "DoWidget.DeepSeek", "api-key"),
        ("delete", "DoWidget.DeepSeek", "api-key"),
    ]
    assert store.get() == SECRET


def test_session_connection_without_saved_key_does_not_delete(backend):
    store = CredentialStore()
    store.connect(SECRET, persist=False)
    assert backend.calls == [("get", "DoWidget.DeepSeek", "api-key")]


@pytest.mark.parametrize("failure", ["fail_get", "fail_delete"])
def test_session_delete_failure_never_promises_session_only(backend, failure):
    backend.saved = "previous-fake-key"
    setattr(backend, failure, True)
    store = CredentialStore()
    with pytest.raises(ProviderError) as caught:
        store.connect(SECRET, persist=False)
    assert_safe(caught.value, store)
    assert not store.available
    assert backend.saved == "previous-fake-key"
    assert store.get() == SECRET


def test_failed_save_preserves_memory_and_supports_explicit_session_retry(backend):
    backend.fail_set = True
    store = CredentialStore()
    with pytest.raises(ProviderError) as caught:
        store.connect(SECRET, persist=True)
    assert_safe(caught.value, store)
    assert not store.available
    assert store.get() == SECRET
    store.connect(SECRET, persist=False)
    assert store.available
    assert backend.saved is None


def test_get_failure_is_safe_and_can_recover(backend):
    backend.saved = SECRET
    backend.fail_get = True
    store = CredentialStore()
    assert store.get() is None
    assert not store.available
    assert SECRET not in store.status
    backend.fail_get = False
    assert store.get() == SECRET
    assert store.available


def test_disconnect_removes_both_saved_and_session_key(backend):
    store = CredentialStore()
    store.connect(SECRET, persist=True)
    store.disconnect()
    assert backend.saved is None
    assert store.get() is None


def test_disconnect_failure_retains_key_and_can_be_retried(backend):
    store = CredentialStore()
    store.connect(SECRET, persist=True)
    backend.fail_delete = True
    with pytest.raises(ProviderError) as caught:
        store.disconnect()
    assert_safe(caught.value, store)
    assert not store.available
    assert store.get() == SECRET
    assert backend.saved == SECRET
    backend.fail_delete = False
    store.disconnect()
    assert store.get() is None
    assert backend.saved is None
    assert store.available


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


def test_old_config_migrates_with_default_window_preferences(tmp_path):
    path = tmp_path / "settings.json"
    values = {
        "interval_minutes": 12, "auto_refresh": False, "always_on_top": True,
        "codex_enabled": True, "x": -40, "y": 20,
    }
    path.write_text(json.dumps(values), encoding="utf-8")
    config = ConfigStore(path).load()
    assert config == Config(12, False, True, True, -40, 20)
    assert (config.width, config.height) == (380, 560)
    assert (config.compact_width, config.compact_height) == (320, 190)
    assert config.view == "detailed"
    assert config.minimize_to_tray is False


@pytest.mark.parametrize("field,minimum", [
    ("width", 340), ("height", 280),
    ("compact_width", 260), ("compact_height", 130),
])
@pytest.mark.parametrize("boundary", ["minimum", "maximum"])
def test_config_valid_dimension_boundaries(tmp_path, field, minimum, boundary):
    value = minimum if boundary == "minimum" else 10_000
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({field: value}), encoding="utf-8")
    assert getattr(ConfigStore(path).load(), field) == value


@pytest.mark.parametrize("field,minimum", [
    ("width", 340), ("height", 280),
    ("compact_width", 260), ("compact_height", 130),
])
@pytest.mark.parametrize("value", [True, False, 400.0, "400", None, [], 0, -1, 10_001, "below"])
def test_config_invalid_dimensions_default(tmp_path, field, minimum, value):
    value = minimum - 1 if value == "below" else value
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({field: value}), encoding="utf-8")
    assert getattr(ConfigStore(path).load(), field) == getattr(Config(), field)


@pytest.mark.parametrize("view", ["compact", "detailed"])
def test_config_valid_view(tmp_path, view):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"view": view}), encoding="utf-8")
    assert ConfigStore(path).load().view == view


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
    config = Config(
        1440, False, True, True, -100000, 100000, 700, 900, 350, 200, view,
        minimize_to_tray,
    )
    config.api_key = SECRET
    replacements = []
    real_replace = storage.os.replace

    def capture_replace(source, target):
        assert source != target
        assert Path(source).parent == path.parent
        data = json.loads(Path(source).read_text(encoding="utf-8"))
        assert set(data) == {
            "interval_minutes", "auto_refresh", "always_on_top", "codex_enabled",
            "x", "y", "width", "height", "compact_width", "compact_height", "view",
            "minimize_to_tray",
        }
        replacements.append((source, target))
        return real_replace(source, target)

    monkeypatch.setattr(storage.os, "replace", capture_replace)
    store.save(config)
    assert replacements
    assert store.load() == config
    assert SECRET not in path.read_text(encoding="utf-8")
    assert not list(path.parent.glob("*.tmp"))


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


@pytest.mark.parametrize("priority", [0, -1, True, float("nan"), float("inf"), "unknown"])
def test_invalid_backend_priority_is_unavailable_without_reading_secrets(backend, priority):
    backend.priority = priority
    store = CredentialStore()
    assert not store.available
    assert backend.calls == []
    assert SECRET not in store.status


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
