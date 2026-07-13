from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path, PureWindowsPath
from typing import Any, Iterable

from route_models import ProgressStatus, Route


LIBRARY_CONFIG_KEY = "route_library"
DEFAULT_LIMIT = 12


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _canonical_path(value: str | Path) -> str:
    return os.path.normcase(os.path.abspath(os.path.expanduser(str(value))))


def file_fingerprint(path: str | Path) -> str:
    """Return a stable SHA-256 fingerprint for one route source file."""

    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def route_completion(route: Route) -> float:
    """Return completed/skipped stop progress as a bounded percentage."""

    if not route.stops:
        return 0.0
    complete = sum(
        stop.status in {ProgressStatus.COMPLETE, ProgressStatus.SKIPPED}
        for stop in route.stops
    )
    return round((complete / len(route.stops)) * 100.0, 1)


@dataclass(frozen=True)
class RouteLibraryEntry:
    path: str
    name: str
    route_id: str
    route_type: str
    source_format: str
    system_count: int
    stop_count: int
    completion_percent: float
    last_system: str
    fingerprint: str
    last_opened_at: str
    available: bool = True
    recovered_from: str = ""

    @classmethod
    def from_route(
        cls,
        route: Route,
        source_path: str | Path | None = None,
        opened_at: str | None = None,
    ) -> "RouteLibraryEntry":
        path = Path(source_path or route.source_path).expanduser()
        systems = {stop.system.casefold() for stop in route.stops if stop.system}
        last_system = next(
            (
                stop.system
                for stop in reversed(route.stops)
                if stop.status in {ProgressStatus.CURRENT, ProgressStatus.COMPLETE, ProgressStatus.SKIPPED}
            ),
            "",
        )
        fingerprint = file_fingerprint(path) if path.is_file() else ""
        return cls(
            path=str(path.resolve()) if path.exists() else str(path),
            name=route.name or path.stem,
            route_id=route.id,
            route_type=route.route_type,
            source_format=route.source_format,
            system_count=len(systems),
            stop_count=len(route.stops),
            completion_percent=route_completion(route),
            last_system=last_system,
            fingerprint=fingerprint,
            last_opened_at=opened_at or _utc_now(),
            available=path.is_file(),
        )

    @classmethod
    def from_dict(cls, raw: Any) -> "RouteLibraryEntry | None":
        if not isinstance(raw, dict):
            return None
        path = str(raw.get("path", "") or "").strip()
        if not path:
            return None
        try:
            return cls(
                path=path,
                name=str(raw.get("name", "") or Path(path).stem),
                route_id=str(raw.get("routeId", raw.get("route_id", "")) or ""),
                route_type=str(raw.get("routeType", raw.get("route_type", "")) or ""),
                source_format=str(raw.get("sourceFormat", raw.get("source_format", "")) or ""),
                system_count=max(0, int(raw.get("systemCount", 0) or 0)),
                stop_count=max(0, int(raw.get("stopCount", 0) or 0)),
                completion_percent=max(0.0, min(100.0, float(raw.get("completionPercent", 0) or 0))),
                last_system=str(raw.get("lastSystem", "") or ""),
                fingerprint=str(raw.get("fingerprint", "") or ""),
                last_opened_at=str(raw.get("lastOpenedAt", "") or ""),
                available=bool(raw.get("available", True)),
                recovered_from=str(raw.get("recoveredFrom", "") or ""),
            )
        except (TypeError, ValueError):
            return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "name": self.name,
            "routeId": self.route_id,
            "routeType": self.route_type,
            "sourceFormat": self.source_format,
            "systemCount": self.system_count,
            "stopCount": self.stop_count,
            "completionPercent": self.completion_percent,
            "lastSystem": self.last_system,
            "fingerprint": self.fingerprint,
            "lastOpenedAt": self.last_opened_at,
            "available": self.available,
            "recoveredFrom": self.recovered_from,
        }

    @property
    def display_status(self) -> str:
        availability = "available" if self.available else "missing"
        return f"{self.completion_percent:.1f}% complete | {availability}"


class RouteLibrary:
    """Bounded recent-route library stored in EDDiscovery plugin config."""

    def __init__(self, entries: Iterable[RouteLibraryEntry] = (), limit: int = DEFAULT_LIMIT) -> None:
        self.limit = max(1, int(limit))
        self._entries = list(entries)[: self.limit]

    @classmethod
    def from_config(cls, config: dict[str, Any], limit: int = DEFAULT_LIMIT) -> "RouteLibrary":
        raw = config.get(LIBRARY_CONFIG_KEY, [])
        entries: list[RouteLibraryEntry] = []
        if isinstance(raw, list):
            for item in raw:
                entry = RouteLibraryEntry.from_dict(item)
                if entry is not None:
                    entries.append(entry)
        return cls(entries, limit=limit)

    @property
    def entries(self) -> tuple[RouteLibraryEntry, ...]:
        return tuple(self._entries)

    def save_to_config(self, config: dict[str, Any]) -> None:
        config[LIBRARY_CONFIG_KEY] = [entry.to_dict() for entry in self._entries]

    def record(self, route: Route, source_path: str | Path | None = None) -> RouteLibraryEntry:
        entry = RouteLibraryEntry.from_route(route, source_path)
        key = self._entry_key(entry)
        retained = [item for item in self._entries if self._entry_key(item) != key]
        self._entries = [entry, *retained][: self.limit]
        return entry

    def most_recent(self, available_only: bool = True) -> RouteLibraryEntry | None:
        for entry in self._entries:
            if not available_only or entry.available:
                return entry
        return None

    def refresh_availability(
        self,
        search_roots: Iterable[str | Path] = (),
        drive_roots: Iterable[str | Path] | None = None,
    ) -> tuple[RouteLibraryEntry, ...]:
        refreshed = [
            self._resolve_entry(entry, search_roots=search_roots, drive_roots=drive_roots)
            for entry in self._entries
        ]
        self._entries = refreshed
        return tuple(refreshed)

    def render_text(self) -> str:
        lines = ["ROUTE LIBRARY"]
        if not self._entries:
            lines.append("No recent routes have been recorded.")
            return "\r\n".join(lines)
        for index, entry in enumerate(self._entries, start=1):
            marker = "OK" if entry.available else "MISSING"
            lines.append(
                f"{index}. [{marker}] {entry.name} | {entry.route_type or 'route'} | "
                f"{entry.system_count} systems | {entry.completion_percent:.1f}%"
            )
            lines.append(f"   {entry.path}")
            if entry.last_system:
                lines.append(f"   Last system: {entry.last_system}")
            if entry.recovered_from:
                lines.append(f"   Recovered from: {entry.recovered_from}")
        return "\r\n".join(lines)

    @staticmethod
    def _entry_key(entry: RouteLibraryEntry) -> str:
        if entry.fingerprint:
            return f"fingerprint:{entry.fingerprint}"
        if entry.route_id:
            return f"route:{entry.route_id}"
        return f"path:{_canonical_path(entry.path)}"

    def _resolve_entry(
        self,
        entry: RouteLibraryEntry,
        search_roots: Iterable[str | Path],
        drive_roots: Iterable[str | Path] | None,
    ) -> RouteLibraryEntry:
        original = Path(entry.path).expanduser()
        if self._matches(original, entry.fingerprint):
            return replace(entry, path=str(original.resolve()), available=True, recovered_from="")

        for candidate in self._candidate_paths(original, search_roots, drive_roots):
            if self._matches(candidate, entry.fingerprint):
                return replace(
                    entry,
                    path=str(candidate.resolve()),
                    available=True,
                    recovered_from=entry.path,
                )
        return replace(entry, available=False)

    @staticmethod
    def _matches(path: Path, fingerprint: str) -> bool:
        if not path.is_file():
            return False
        if not fingerprint:
            return True
        try:
            return file_fingerprint(path) == fingerprint
        except OSError:
            return False

    @staticmethod
    def _candidate_paths(
        original: Path,
        search_roots: Iterable[str | Path],
        drive_roots: Iterable[str | Path] | None,
    ) -> Iterable[Path]:
        seen: set[str] = set()

        def yield_once(candidate: Path) -> Iterable[Path]:
            key = _canonical_path(candidate)
            if key not in seen:
                seen.add(key)
                yield candidate

        for root in search_roots:
            base = Path(root).expanduser()
            yield from yield_once(base / original.name)
            yield from yield_once(base / "Routes" / original.name)

        windows_path = PureWindowsPath(str(original))
        relative_parts = windows_path.parts[1:] if windows_path.drive else windows_path.parts
        roots = drive_roots if drive_roots is not None else RouteLibrary._available_windows_drives()
        for root in roots:
            drive = Path(root)
            if relative_parts:
                yield from yield_once(drive.joinpath(*relative_parts))
            yield from yield_once(drive / original.name)

    @staticmethod
    def _available_windows_drives() -> tuple[Path, ...]:
        if os.name != "nt":
            return ()
        drives: list[Path] = []
        for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
            root = Path(f"{letter}:\\")
            if root.exists():
                drives.append(root)
        return tuple(drives)
