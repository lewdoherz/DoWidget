from dataclasses import FrozenInstanceError
from uuid import UUID

import pytest

from dowidget.connections import (
    MAX_CONNECTIONS, Connection, Provider, default_connections,
    new_connection_id, serialize_connections, validate_connections,
)


def profile(**changes):
    return {"id": new_connection_id(), "provider": "deepseek", "name": "Personal", **changes}


def test_provider_ids_and_default_connections():
    assert {provider.value for provider in Provider} == {"deepseek", "codex", "claude", "gemini", "grok", "glm"}
    connections = default_connections()
    assert [(value.id, value.provider, value.enabled) for value in connections] == [
        ("deepseek-default", "deepseek", True), ("codex-default", "codex", False),
    ]
    connections.clear()
    assert len(default_connections()) == 2


def test_generated_ids_are_unique_canonical_uuids():
    ids = [new_connection_id() for _ in range(100)]
    assert len(set(ids)) == len(ids)
    assert all(str(UUID(value)) == value for value in ids)
    assert all(Connection(value, "claude", "Account").id == value for value in ids)


@pytest.mark.parametrize("connection_id", [
    "", "../escape", "..", "/absolute", "C:\\escape", "CON", "a/b", "a\\b",
    "claude-default", "DEEPSEEK-DEFAULT", " deepseek-default", None, 123,
])
def test_invalid_ids_cannot_be_paths(connection_id):
    with pytest.raises(ValueError, match="^Invalid connection metadata\\.$"):
        Connection(connection_id, "deepseek", "Name")


@pytest.mark.parametrize("values", [
    {"provider": "unknown"}, {"provider": None}, {"provider": []},
    {"id": "deepseek-default", "provider": "grok"},
    {"id": "codex-default", "provider": "deepseek"},
    {"name": ""}, {"name": " "}, {"name": "N" * 129}, {"name": None},
    {"name": "control\n"}, {"name": "nul\x00"}, {"model_label": "M" * 129},
    {"model_label": []}, {"source": "cookies"}, {"source": None},
    {"enabled": 1}, {"enabled": "false"}, {"remember": 0}, {"remember": None},
    {"options": None}, {"options": []}, {"options": {"path": "p" * 4097}},
    {"options": {"user_id": "u" * 129}}, {"options": {"team_id": "t" * 129}},
    {"options": {"path": "new\nline"}}, {"options": {"path": 12}},
    {"options": {"api_key": "must-not-be-retained"}},
    {"options": {"authorization": "must-not-be-retained"}},
    {"options": {"cookie": "must-not-be-retained"}},
    {"options": {"token": "must-not-be-retained"}},
    {"options": {"unknown": "ignored-is-not-safe"}},
])
def test_invalid_metadata_is_rejected_without_echoing_values(values):
    raw = profile(**values)
    with pytest.raises(ValueError) as caught:
        Connection(**raw)
    assert str(caught.value) == "Invalid connection metadata."
    assert validate_connections([raw]) == []


@pytest.mark.parametrize("provider", list(Provider))
@pytest.mark.parametrize("source", ["api", "local"])
def test_model_labels_and_sources_are_separate_metadata(provider, source):
    connection = Connection(
        new_connection_id(), provider, "Account", "Model display label", source,
        False, False, {"path": "C:\\usage\\account.json", "user_id": "user_123", "team_id": "team_123"},
    )
    assert validate_connections(serialize_connections([connection])) == [connection]
    assert connection.model_label == "Model display label"
    assert connection.source == source


def test_connection_is_frozen_and_detaches_supplied_options():
    options = {"path": "usage.json"}
    connection = Connection(new_connection_id(), "glm", "Personal", source="local", options=options)
    options["path"] = "other.json"
    assert connection.options == {"path": "usage.json"}
    with pytest.raises(FrozenInstanceError):
        connection.name = "Changed"


def test_serialization_only_keeps_nonsecret_fields_and_revalidates_options():
    raw = profile(api_key="secret-never-serialized", password="secret-never-serialized")
    parsed = validate_connections([raw])
    assert len(parsed) == 1
    serialized = serialize_connections(parsed)
    assert set(serialized[0]) == {"id", "provider", "name", "model_label", "source", "enabled", "remember", "options"}
    assert "secret-never-serialized" not in repr(serialized)
    parsed[0].options["api_key"] = "secret-never-serialized"
    assert serialize_connections(parsed) == []


def test_first_duplicate_wins_and_other_valid_profiles_survive():
    first = profile()
    second = profile(provider="grok", options={"team_id": "team_123"})
    profiles = [None, first, {**first, "name": "Duplicate"}, {}, second]
    result = validate_connections(profiles)
    assert [value.id for value in result] == [first["id"], second["id"]]
    assert result[0].name == first["name"]


def test_profiles_are_bounded_and_explicit_empty_stays_empty():
    profiles = [profile() for _ in range(MAX_CONNECTIONS + 5)]
    assert len(validate_connections(profiles)) == MAX_CONNECTIONS
    assert len(serialize_connections(profiles)) == MAX_CONNECTIONS
    assert validate_connections([]) == []
    assert serialize_connections([]) == []


@pytest.mark.parametrize("raw", [None, {}, "text", 1, True, (), [None, {}, []]])
def test_malformed_profile_container_is_empty(raw):
    assert validate_connections(raw) == []
