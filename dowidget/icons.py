"""DoWidget's original application mark and compact toolbar icons."""

from pathlib import Path

from PySide6.QtGui import QIcon


_ASSETS = Path(__file__).with_name("assets")
_CONTROL_FILES = {
    "refresh": "refresh.png",
    "settings": "settings.png",
    "expand": "expand.png",
    "minimize": "minimize.png",
    "close": "close.png",
}


def app_icon() -> QIcon:
    """Return the application's own mark, not a provider logo."""
    return QIcon(str(_ASSETS / "dowidget.png"))


def control_icon(name: str) -> QIcon:
    """Return an outlined toolbar icon; reject unknown control names."""
    filename = _CONTROL_FILES.get(name)
    if filename is None:
        raise ValueError(f"Unknown control icon: {name!r}")
    return QIcon(str(_ASSETS / filename))
