"""Validated, nonsecret account metadata; credentials live in OS storage only."""
from dataclasses import dataclass, field
from enum import StrEnum
from uuid import UUID, uuid4


class Provider(StrEnum):
    DEEPSEEK = "deepseek"
    CODEX = "codex"
    CLAUDE = "claude"
    GEMINI = "gemini"
    GROK = "grok"
    GLM = "glm"


MAX_CONNECTIONS = 100
_DEFAULT_IDS = {"deepseek-default": "deepseek", "codex-default": "codex"}
_OPTION_LIMITS = {"path": 4096, "user_id": 128, "team_id": 128}
_FIELDS = ("id", "provider", "name", "model_label", "source", "enabled", "remember", "options")


def new_connection_id() -> str:
    return str(uuid4())


def valid_connection_id(value: object, provider: str) -> bool:
    if not isinstance(value, str):
        return False
    if value in _DEFAULT_IDS:
        return _DEFAULT_IDS[value] == provider
    try:
        return str(UUID(value)) == value
    except (ValueError, AttributeError):
        return False


def _text(value: object, limit: int, *, required: bool = False) -> bool:
    return (
        isinstance(value, str) and len(value) <= limit
        and (not required or bool(value.strip()))
        and all(ord(char) >= 32 and ord(char) != 127 for char in value)
    )


@dataclass(frozen=True)
class Connection:
    id: str
    provider: str
    name: str
    model_label: str = ""
    source: str = "api"
    enabled: bool = True
    remember: bool = True
    options: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if (
            not isinstance(self.provider, str) or self.provider not in Provider._value2member_map_
            or not valid_connection_id(self.id, self.provider)
            or not _text(self.name, 128, required=True)
            or not _text(self.model_label, 128)
            or self.source not in ("api", "local")
            or type(self.enabled) is not bool or type(self.remember) is not bool
            or type(self.options) is not dict
            or any(
                key not in _OPTION_LIMITS or not _text(value, _OPTION_LIMITS[key])
                for key, value in self.options.items()
            )
        ):
            raise ValueError("Invalid connection metadata.")
        # Detach mutable caller input; source options never contain credential fields.
        object.__setattr__(self, "options", dict(self.options))


def default_connections() -> list[Connection]:
    return [
        Connection("deepseek-default", "deepseek", "DeepSeek"),
        Connection("codex-default", "codex", "Codex", enabled=False),
    ]


def validate_connections(values: object) -> list[Connection]:
    """Keep the first valid occurrence; malformed explicit profiles never add defaults."""
    if type(values) is not list:
        return []
    result: list[Connection] = []
    seen: set[str] = set()
    for value in values[:MAX_CONNECTIONS]:
        if isinstance(value, Connection):
            # Revalidate even frozen instances: their options dictionaries can be mutated.
            value = {name: getattr(value, name) for name in _FIELDS}
        if type(value) is not dict:
            continue
        try:
            connection = Connection(**{name: value[name] for name in _FIELDS if name in value})
        except (TypeError, ValueError):
            continue
        if connection.id not in seen:
            seen.add(connection.id)
            result.append(connection)
    return result


def serialize_connections(values: object) -> list[dict]:
    return [
        {name: getattr(connection, name) for name in _FIELDS}
        for connection in validate_connections(values)
    ]
