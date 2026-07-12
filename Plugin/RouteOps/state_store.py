from __future__ import annotations

import hashlib
import json
import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any


DEFAULT_FALLBACK_DIR = Path(__file__).resolve().parent / "State"


def state_path_for(route_path: str) -> Path:
    path = Path(route_path)
    return path.with_name(path.name + ".routeops.state.json")


def fallback_state_path_for(route_path: str, fallback_dir: str | Path | None = None) -> Path:
    folder = Path(fallback_dir) if fallback_dir else DEFAULT_FALLBACK_DIR
    route = Path(route_path).expanduser().resolve()
    digest = hashlib.sha1(str(route).casefold().encode("utf-8")).hexdigest()[:12]
    safe_stem = "".join(character if character.isalnum() or character in "-_" else "-" for character in route.stem)
    return folder / f"{safe_stem}-{digest}.routeops.state.json"


def _candidate_paths(route_path: str, fallback_dir: str | Path | None = None) -> list[Path]:
    return [state_path_for(route_path), fallback_state_path_for(route_path, fallback_dir)]


def _backup_corrupt(path: Path) -> None:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    destination = path.with_name(path.name + f".corrupt-{stamp}")
    try:
        shutil.move(str(path), str(destination))
    except OSError:
        pass


def _migrate_state(value: dict[str, Any]) -> dict[str, Any]:
    version = int(value.get("stateVersion", 1) or 1)
    if version >= 6:
        return value
    migrated = dict(value)
    migrated["stateVersion"] = 6
    migrated["routeId"] = value.get("routeId") or value.get("route_id", "")
    migrated["currentStopId"] = value.get("currentStopId", "")
    migrated["selectedStopId"] = value.get("selectedStopId", "")
    migrated["autoAdvance"] = value.get("autoAdvance", value.get("auto_advance", True))
    migrated.setdefault("selectedTaskId", "")
    migrated.setdefault("selectedSystemKey", "")
    migrated.setdefault("navigationTarget", {})
    migrated.setdefault("guidanceMode", "auto-advance" if migrated.get("autoAdvance", migrated.get("auto_advance", True)) else "confirm")
    migrated.setdefault("bodyOrderMode", "route")
    migrated.setdefault("pendingSkip", None)
    migrated.setdefault("skipDecisions", [])
    migrated.setdefault("currentLocation", {})
    migrated.setdefault("salesLedger", [])
    migrated.setdefault(
        "filterProfile",
        {
            "excludedGenusIds": migrated.get("excludedOrganismGenera", []),
            "showExcludedOrganisms": True,
            "hideEmptyBodies": True,
            "hideEmptySystems": True,
            "routeViewMode": "active",
            "guidanceMode": "auto-advance",
            "bodyOrderMode": "route",
            "defaultSkipReason": "too-difficult",
        },
    )
    return migrated


def load_state(route_path: str, fallback_dir: str | Path | None = None) -> dict[str, Any]:
    existing = [path for path in _candidate_paths(route_path, fallback_dir) if path.exists()]
    existing.sort(key=lambda path: path.stat().st_mtime, reverse=True)
    for path in existing:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(value, dict):
                return _migrate_state(value)
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            _backup_corrupt(path)
    return {}


def _atomic_write(destination: Path, state: dict[str, Any]) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + ".tmp")
    temporary.write_text(
        json.dumps(state, indent=2, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )
    os.replace(temporary, destination)


def save_state(
    route_path: str,
    state: dict[str, Any],
    fallback_dir: str | Path | None = None,
) -> Path:
    primary = state_path_for(route_path)
    try:
        _atomic_write(primary, state)
        return primary
    except OSError:
        fallback = fallback_state_path_for(route_path, fallback_dir)
        _atomic_write(fallback, state)
        return fallback
