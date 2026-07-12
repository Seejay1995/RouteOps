from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from state_store import fallback_state_path_for, load_state, save_state, state_path_for


@dataclass(frozen=True)
class SessionStoragePaths:
    """Resolved primary and fallback locations for one route session."""

    primary: Path
    fallback: Path


class SessionStorage(Protocol):
    """Persistence boundary used by the EDDiscovery application adapter."""

    def paths_for(self, route_path: str) -> SessionStoragePaths:
        ...

    def load(self, route_path: str) -> dict[str, Any]:
        ...

    def save(self, route_path: str, state: dict[str, Any]) -> Path:
        ...


class FileSessionStorage:
    """File-backed session storage with a portable plugin-local fallback."""

    def __init__(self, fallback_dir: str | Path) -> None:
        self._fallback_dir = Path(fallback_dir).expanduser().resolve()

    @classmethod
    def for_plugin(
        cls,
        plugin_dir: str | Path,
        configured_root: str | Path | None = None,
    ) -> "FileSessionStorage":
        plugin_root = Path(plugin_dir).expanduser().resolve()
        if configured_root is None or not str(configured_root).strip():
            return cls(plugin_root / "State")

        configured = Path(str(configured_root).strip()).expanduser()
        if not configured.is_absolute():
            configured = plugin_root / configured
        return cls(configured)

    @property
    def fallback_dir(self) -> Path:
        return self._fallback_dir

    def paths_for(self, route_path: str) -> SessionStoragePaths:
        return SessionStoragePaths(
            primary=state_path_for(route_path),
            fallback=fallback_state_path_for(route_path, self._fallback_dir),
        )

    def load(self, route_path: str) -> dict[str, Any]:
        return load_state(route_path, self._fallback_dir)

    def save(self, route_path: str, state: dict[str, Any]) -> Path:
        return save_state(route_path, state, self._fallback_dir)
