from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from exobiology_catalog import DEFAULT_CATALOG, normalize_organic_name
from route_models import (
    CompletionPolicy,
    Route,
    RouteMode,
    RouteSettings,
    RouteStop,
    RouteTask,
    StopType,
)
from spansh_exobiology_importer import load_exobiology_csv, normalize_exobiology_payload
from specializations import (
    SPECIALIZATIONS,
    canonical_route_mode,
    canonical_stop_type,
    canonical_task_type,
)
from trade_csv_importer import import_edd_route_csv


class RouteImportError(ValueError):
    pass


@dataclass
class ImportResult:
    route: Route | None
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


_TASK_STOP_TYPES = {
    "scanstar": StopType.EXPLORATION,
    "scanbody": StopType.EXPLORATION,
    "mapbody": StopType.EXPLORATION,
    "scanorganic": StopType.EXOBIOLOGY,
    "scanspecies": StopType.EXOBIOLOGY,
    "samplespecies": StopType.EXOBIOLOGY,
    "collectmaterial": StopType.MATERIALS,
    "reachinventoryquantity": StopType.MATERIALS,
    "buycommodity": StopType.TRADE,
    "sellcommodity": StopType.TRADE,
    "loadcommodity": StopType.CARGO,
    "collectcargo": StopType.CARGO,
    "delivercommodity": StopType.CARGO,
    "unloadcommodity": StopType.CARGO,
    "dockatstation": StopType.DOCK,
    "landonbody": StopType.LAND,
}


_VALID_COMPLETION_POLICIES = {
    CompletionPolicy.LISTED_TARGETS,
    CompletionPolicy.ALL_SIGNALS,
    CompletionPolicy.MANUAL,
    CompletionPolicy.ANY_TARGET,
}


def _first(mapping: dict[str, Any], *keys: str, default: Any = None) -> Any:
    lower = {str(key).casefold(): value for key, value in mapping.items()}
    for key in keys:
        if key.casefold() in lower:
            return lower[key.casefold()]
    return default


def _boolean(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    return str(value).strip().casefold() in {"1", "true", "yes", "on", "required"}



def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        values = [part.strip() for part in re.split(r"[,;|]", value)]
    elif isinstance(value, (list, tuple, set)):
        values = [str(part).strip() for part in value]
    else:
        values = [str(value).strip()]
    result: list[str] = []
    seen: set[str] = set()
    for item in values:
        key = item.casefold()
        if item and key not in seen:
            seen.add(key)
            result.append(item)
    return result

def _integer(value: Any, default: int = 1) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _optional_integer(value: Any) -> int | None:
    if value in {None, ""}:
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _optional_float(value: Any) -> float | None:
    if value in {None, ""}:
        return None
    try:
        return float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def _slug(value: str) -> str:
    compact = re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")
    return compact or "route"


def _completion_policy(value: Any, default: str = CompletionPolicy.LISTED_TARGETS) -> str:
    normalized = str(value or default).strip().casefold()
    return normalized if normalized in _VALID_COMPLETION_POLICIES else default


def _infer_stop_type(raw: dict[str, Any], tasks: list[RouteTask]) -> str:
    explicit = str(_first(raw, "stopType", "activity", "specialization", default="") or "")
    if explicit:
        return canonical_stop_type(explicit)
    legacy_type = str(_first(raw, "type", default="") or "")
    if legacy_type and legacy_type.casefold() in SPECIALIZATIONS:
        return canonical_stop_type(legacy_type)
    inferred: set[str] = set()
    for task in tasks:
        inferred_type = _TASK_STOP_TYPES.get(task.task_type.casefold())
        if inferred_type:
            inferred.add(inferred_type)
    if len(inferred) == 1:
        return inferred.pop()
    if len(inferred) > 1:
        return StopType.CHECKLIST
    if _first(raw, "station", "stationName", default=""):
        return StopType.DOCK
    if _first(raw, "body", "bodyName", default=""):
        return StopType.LAND
    return StopType.WAYPOINT


def _default_label(task_type: str, target: str) -> str:
    names = {
        "visitSystem": "Visit system",
        "scanStar": "Scan star",
        "scanBody": "Scan body",
        "mapBody": "Map body",
        "visitBody": "Visit body",
        "landOnBody": "Land on body",
        "dockAtStation": "Dock at station",
        "scanOrganic": "Scan organism",
        "scanSpecies": "Scan species",
        "sampleSpecies": "Sample species",
        "collectMaterial": "Collect material",
        "reachInventoryQuantity": "Reach inventory quantity",
        "buyCommodity": "Buy commodity",
        "sellCommodity": "Sell commodity",
        "loadCommodity": "Load cargo",
        "collectCargo": "Collect cargo",
        "deliverCommodity": "Deliver cargo",
        "unloadCommodity": "Unload cargo",
        "manualChecklist": "Manual task",
    }
    base = names.get(task_type, task_type)
    return f"{base}: {target}" if target else base


def _task_from_json(raw: dict[str, Any], stop_id: str, index: int, warnings: list[str]) -> RouteTask:
    task_type = canonical_task_type(str(_first(raw, "type", "taskType", default="manualChecklist")))
    genus = str(_first(raw, "genus", "genusName", default="") or "").strip()
    species = str(_first(raw, "species", "speciesName", default="") or "").strip()
    variant = str(_first(raw, "variant", "variantName", default="") or "").strip()
    target = str(
        _first(
            raw,
            "target",
            "material",
            "commodity",
            "species",
            "genus",
            "body",
            "station",
            default="",
        )
        or ""
    ).strip()
    if task_type.casefold() in {"scanorganic", "scanspecies", "samplespecies"}:
        target = variant or species or genus or target
        quantity_default = 3
    else:
        quantity_default = 1
    quantity = max(
        1,
        _integer(
            _first(
                raw,
                "quantityRequired",
                "targetQuantity",
                "quantity",
                "desiredGain",
                "samplesRequired",
                default=quantity_default,
            ),
            quantity_default,
        ),
    )
    required_raw = _first(raw, "required", default=None)
    optional = _boolean(_first(raw, "optional", default=False), False)
    required = _boolean(required_raw, True) if required_raw is not None else not optional
    task_id = str(_first(raw, "id", default=f"{stop_id}-task-{index + 1}") or f"{stop_id}-task-{index + 1}")
    if task_type != "manualChecklist" and not target and task_type not in {"visitSystem", "scanStar"}:
        warnings.append(f"Task {task_id} ({task_type}) has no target and may match any related journal event.")

    metadata = dict(raw)
    base_value = _optional_integer(_first(raw, "baseValue", "estimatedValue", default=None))
    colony_range = _optional_integer(_first(raw, "colonyRangeMeters", "colonyRange", default=None))
    if task_type.casefold() in {"scanorganic", "scanspecies", "samplespecies"}:
        match = DEFAULT_CATALOG.resolve(variant, species, target)
        if match:
            species = species or match.name
            genus = genus or match.genus
            base_value = base_value if base_value is not None else match.base_value
            colony_range = colony_range if colony_range is not None else match.colony_range_m
            metadata.setdefault("estimatedValue", match.base_value)
            metadata.setdefault("baseValue", match.base_value)
            if match.colony_range_m is not None:
                metadata.setdefault("colonyRangeMeters", match.colony_range_m)
        elif genus and colony_range is None:
            colony_range = DEFAULT_CATALOG.colony_range_for_genus(genus)
            if colony_range is not None:
                metadata.setdefault("colonyRangeMeters", colony_range)

    label = str(_first(raw, "label", "title", "name", default="") or "").strip()
    return RouteTask(
        id=task_id,
        task_type=task_type,
        label=label or _default_label(task_type, target),
        required=required,
        target=target,
        quantity_required=quantity,
        metadata=metadata,
        genus=genus,
        species=species,
        variant=variant,
        base_value=base_value,
        colony_range_m=colony_range,
        first_logged_status=str(_first(raw, "firstLoggedStatus", default="unknown") or "unknown"),
        discovered_dynamically=_boolean(_first(raw, "discoveredDynamically", default=False)),
        genus_id=str(_first(raw, "genusId", default="") or ""),
        species_id=str(_first(raw, "speciesId", default="") or ""),
        variant_id=str(_first(raw, "variantId", default="") or ""),
        knowledge_level=str(_first(raw, "knowledgeLevel", default="unknown") or "unknown"),
        manual_inclusion=str(_first(raw, "manualInclusion", default="default") or "default"),
        sample_stage=str(_first(raw, "sampleStage", default="") or ""),
        sample_event_ids=_string_list(_first(raw, "sampleEventIds", default=[])),
        search_difficulty=str(_first(raw, "searchDifficulty", default="unknown") or "unknown"),
        search_started_at=str(_first(raw, "searchStartedAt", default="") or ""),
        search_elapsed_seconds=max(0, _integer(_first(raw, "searchElapsedSeconds", default=0), 0)),
    )


def _finalize_exobiology_stop(stop: RouteStop) -> None:
    if stop.stop_type != StopType.EXOBIOLOGY:
        return
    stop.auto_complete_on_arrival = False
    if not stop.completion_policy:
        stop.completion_policy = CompletionPolicy.LISTED_TARGETS
    for task in stop.tasks:
        if not task.is_organic:
            continue
        identity = task.variant or task.species or task.genus or task.target or task.id
        task.organism_key = f"{stop.body_key}:{normalize_organic_name(identity)}"


def _stop_from_json(raw: Any, index: int, warnings: list[str], source_format: str) -> RouteStop:
    if isinstance(raw, str):
        system = raw.strip()
        if not system:
            raise RouteImportError(f"Stop {index + 1} is empty")
        return RouteStop(
            id=f"stop-{index + 1}",
            sequence=index + 1,
            system=system,
            stop_type=StopType.WAYPOINT,
            auto_complete_on_arrival=True,
        )
    if not isinstance(raw, dict):
        raise RouteImportError(f"Stop {index + 1} is not a system name or object")

    system = str(
        _first(raw, "system", "System", "starSystem", "StarSystem", "systemName", default="") or ""
    ).strip()
    if not system and not _first(raw, "label", "title", default=""):
        system = str(_first(raw, "name", default="") or "").strip()
    if not system:
        raise RouteImportError(f"Stop {index + 1} has no system name")

    stop_id = str(_first(raw, "id", default=f"stop-{index + 1}") or f"stop-{index + 1}")
    tasks_raw = _first(raw, "tasks", "objectives", "organisms", default=[])
    tasks: list[RouteTask] = []
    if tasks_raw is None:
        tasks_raw = []
    if not isinstance(tasks_raw, list):
        warnings.append(f"Stop {stop_id} tasks are not a list; tasks were ignored.")
    else:
        for task_index, task_raw in enumerate(tasks_raw):
            if isinstance(task_raw, dict):
                organic_raw = dict(task_raw)
                if "organisms" in {str(key).casefold() for key in raw} and not _first(organic_raw, "type", "taskType"):
                    organic_raw["type"] = "scanOrganic"
                tasks.append(_task_from_json(organic_raw, stop_id, task_index, warnings))
            elif isinstance(task_raw, str):
                tasks.append(
                    RouteTask(
                        id=f"{stop_id}-task-{task_index + 1}",
                        task_type="manualChecklist",
                        label=task_raw,
                        target=task_raw,
                    )
                )
            else:
                warnings.append(f"Stop {stop_id} task {task_index + 1} was ignored because it is not an object or string.")

    stop_type = _infer_stop_type(raw, tasks)
    explicit_auto = _first(raw, "autoCompleteOnArrival", default=None)
    if explicit_auto is not None:
        auto_complete = _boolean(explicit_auto)
    else:
        auto_complete = bool(SPECIALIZATIONS.get(stop_type, {}).get("default_auto_complete", False)) and not tasks
        if source_format == "edd-expedition":
            auto_complete = True

    label = str(_first(raw, "label", "title", default="") or "").strip()
    biological_signals = _optional_integer(_first(raw, "biologicalSignals", "biologicalSignalCount", default=None))
    completion_default = CompletionPolicy.ALL_SIGNALS if biological_signals and not tasks else CompletionPolicy.LISTED_TARGETS
    stop = RouteStop(
        id=stop_id,
        sequence=max(1, _integer(_first(raw, "sequence", default=index + 1), index + 1)),
        system=system,
        label=label,
        stop_type=stop_type,
        body=str(_first(raw, "body", "bodyName", default="") or "").strip(),
        station=str(_first(raw, "station", "stationName", default="") or "").strip(),
        settlement=str(_first(raw, "settlement", "settlementName", default="") or "").strip(),
        notes=str(_first(raw, "notes", "description", default="") or "").strip(),
        instructions=str(_first(raw, "instructions", "directions", default="") or "").strip(),
        tasks=tasks,
        auto_complete_on_arrival=auto_complete,
        metadata=dict(raw),
        system_address=_optional_integer(_first(raw, "systemAddress", default=None)),
        body_id=_optional_integer(_first(raw, "bodyId", "bodyID", default=None)),
        parent_system_key=str(_first(raw, "parentSystemKey", default="") or ""),
        system_sequence=max(0, _integer(_first(raw, "systemSequence", default=0), 0)),
        body_sequence=max(0, _integer(_first(raw, "bodySequence", default=0), 0)),
        completion_policy=_completion_policy(_first(raw, "completionPolicy", default=completion_default), completion_default),
        biological_signal_count=biological_signals,
        known_genus_count=_optional_integer(_first(raw, "knownGenusCount", default=None)),
        distance_from_arrival_ls=_optional_float(_first(raw, "distanceFromArrivalLs", "distanceFromArrival", "distanceToArrival", default=None)),
        manifest_source=str(_first(raw, "manifestSource", "sourceProvider", default=source_format) or source_format),
        manifest_completeness=str(_first(raw, "manifestCompleteness", default="") or ""),
        manual_order=max(0, _integer(_first(raw, "manualOrder", default=0), 0)),
        priority_score=float(_first(raw, "priorityScore", default=0) or 0),
    )
    stop.parent_system_key = stop.parent_system_key or (
        str(stop.system_address) if stop.system_address is not None else stop.system.casefold()
    )
    _finalize_exobiology_stop(stop)
    return stop


def _flatten_v3_systems(raw: dict[str, Any], warnings: list[str]) -> list[dict[str, Any]]:
    flattened: list[dict[str, Any]] = []
    systems = raw.get("systems")
    if not isinstance(systems, list):
        return flattened
    sequence = 1
    settings = raw.get("settings") if isinstance(raw.get("settings"), dict) else {}
    default_policy = _completion_policy(settings.get("defaultCompletionPolicy"), CompletionPolicy.LISTED_TARGETS)
    for system_index, system_raw in enumerate(systems):
        if not isinstance(system_raw, dict):
            warnings.append(f"System {system_index + 1} was ignored because it is not an object.")
            continue
        system_name = str(_first(system_raw, "system", "name", "starSystem", default="") or "").strip()
        if not system_name:
            warnings.append(f"System {system_index + 1} was ignored because it has no system name.")
            continue
        system_id = str(_first(system_raw, "id", default=f"system-{system_index + 1}") or f"system-{system_index + 1}")
        system_address = _optional_integer(_first(system_raw, "systemAddress", default=None))
        bodies = _first(system_raw, "bodies", default=[])
        if not isinstance(bodies, list) or not bodies:
            flattened.append(
                {
                    "id": system_id,
                    "sequence": sequence,
                    "system": system_name,
                    "systemAddress": system_address,
                    "stopType": "exobiology",
                    "completionPolicy": "manual",
                    "systemSequence": system_index + 1,
                    "bodySequence": 0,
                    "label": str(_first(system_raw, "label", default="") or ""),
                    "notes": str(_first(system_raw, "notes", default="") or ""),
                }
            )
            sequence += 1
            continue
        for body_index, body_raw in enumerate(bodies):
            if not isinstance(body_raw, dict):
                warnings.append(f"Body {body_index + 1} in {system_name} was ignored because it is not an object.")
                continue
            body_name = str(_first(body_raw, "body", "bodyName", "name", default="") or "").strip()
            body_id = _optional_integer(_first(body_raw, "bodyId", "bodyID", default=None))
            body_key = str(_first(body_raw, "id", default=f"{system_id}-body-{body_id if body_id is not None else body_index + 1}") or "")
            organisms = _first(body_raw, "organisms", "tasks", default=[])
            if not isinstance(organisms, list):
                organisms = []
            completion_policy = _completion_policy(
                _first(body_raw, "completionPolicy", default=_first(system_raw, "completionPolicy", default=default_policy)),
                default_policy,
            )
            flattened.append(
                {
                    "id": body_key,
                    "sequence": sequence,
                    "system": system_name,
                    "systemAddress": system_address,
                    "body": body_name,
                    "bodyId": body_id,
                    "stopType": "exobiology",
                    "label": str(_first(body_raw, "label", default="") or ""),
                    "notes": str(_first(body_raw, "notes", default="") or ""),
                    "instructions": str(_first(body_raw, "instructions", default="") or ""),
                    "biologicalSignals": _first(body_raw, "biologicalSignals", "biologicalSignalCount", default=None),
                    "completionPolicy": completion_policy,
                    "systemSequence": system_index + 1,
                    "bodySequence": body_index + 1,
                    "parentSystemKey": str(system_address) if system_address is not None else system_name.casefold(),
                    "distanceFromArrivalLs": _first(body_raw, "distanceFromArrivalLs", "distanceFromArrival", "distanceToArrival", default=None),
                    "manifestSource": _first(body_raw, "manifestSource", "sourceProvider", default=_first(system_raw, "manifestSource", "sourceProvider", default=raw.get("sourceFormatOverride", "routeops"))),
                    "manifestCompleteness": _first(body_raw, "manifestCompleteness", default=("exact" if organisms else "bodies-known")),
                    "manualOrder": _first(body_raw, "manualOrder", default=body_index + 1),
                    "priorityScore": _first(body_raw, "priorityScore", default=0),
                    "organisms": organisms,
                }
            )
            sequence += 1
    return flattened


def _settings_from_json(raw: dict[str, Any]) -> RouteSettings:
    settings_raw = _first(raw, "settings", default={})
    if not isinstance(settings_raw, dict):
        settings_raw = {}
    auto_copy = str(_first(settings_raw, "autoCopyMode", default="smart-target") or "smart-target")
    if auto_copy not in {"off", "next-system", "system-only", "current-target", "smart-target", "manual-only"}:
        auto_copy = "smart-target"
    return RouteSettings(
        auto_copy_mode=auto_copy,
        auto_advance=_boolean(_first(settings_raw, "autoAdvance", default=True), True),
        complete_waypoint_on_arrival=_boolean(_first(settings_raw, "completeWaypointOnArrival", default=True), True),
        clipboard_retry_count=max(1, _integer(_first(settings_raw, "clipboardRetryCount", default=6), 6)),
        clipboard_retry_delay_ms=max(10, _integer(_first(settings_raw, "clipboardRetryDelayMs", default=75), 75)),
        add_unplanned_organisms=_boolean(_first(settings_raw, "addUnplannedOrganisms", default=True), True),
        default_completion_policy=_completion_policy(
            _first(settings_raw, "defaultCompletionPolicy", default=CompletionPolicy.LISTED_TARGETS),
            CompletionPolicy.LISTED_TARGETS,
        ),
        show_first_logged_potential=_boolean(_first(settings_raw, "showFirstLoggedPotential", default=True), True),
        excluded_organism_genera=_string_list(_first(settings_raw, "excludedOrganismGenera", default=[])),
        show_excluded_organisms=_boolean(_first(settings_raw, "showExcludedOrganisms", default=True), True),
        hide_empty_bodies=_boolean(_first(settings_raw, "hideEmptyBodies", default=True), True),
        hide_empty_systems=_boolean(_first(settings_raw, "hideEmptySystems", default=True), True),
        route_view_mode=str(_first(settings_raw, "routeViewMode", default="active") or "active").casefold(),
        guidance_mode=str(_first(settings_raw, "guidanceMode", default=("auto-advance" if _boolean(_first(settings_raw, "autoAdvance", default=True), True) else "confirm")) or "auto-advance").casefold(),
        body_order_mode=str(_first(settings_raw, "bodyOrderMode", default="route") or "route").casefold(),
        default_skip_reason=str(_first(settings_raw, "defaultSkipReason", default="too-difficult") or "too-difficult").casefold(),
    )


def _infer_mode_from_name(name: str) -> str:
    words = set(re.findall(r"[a-z0-9]+", name.casefold()))
    if {"trade", "trading", "market"} & words:
        return RouteMode.TRADE
    if {"exo", "exobiology", "biology", "organic"} & words:
        return RouteMode.EXOBIOLOGY
    if {"materials", "material", "mats", "raw"} & words:
        return RouteMode.MATERIALS
    if {"cargo", "tritium", "haul", "hauling"} & words:
        return RouteMode.CARGO
    if {"carrier", "fleetcarrier"} & words:
        return RouteMode.CARRIER
    if {"exploration", "explore", "survey"} & words:
        return RouteMode.EXPLORATION
    return RouteMode.WAYPOINT


def infer_route_mode(stops: list[RouteStop]) -> str:
    modes = {stop.stop_type for stop in stops}
    if not modes:
        return RouteMode.WAYPOINT
    if len(modes) == 1:
        only = next(iter(modes))
        if only in {
            StopType.WAYPOINT,
            StopType.EXPLORATION,
            StopType.EXOBIOLOGY,
            StopType.MATERIALS,
            StopType.TRADE,
            StopType.CARGO,
            StopType.CARRIER,
        }:
            return only
    return RouteMode.MIXED


def import_route(path: str | Path) -> ImportResult:
    source_path = Path(path).expanduser().resolve()
    warnings: list[str] = []
    errors: list[str] = []

    name = source_path.stem
    if source_path.suffix.casefold() in {".csv", ".tsv"}:
        raw = load_exobiology_csv(source_path)
        if raw is None:
            route, warnings, errors = import_edd_route_csv(source_path)
            return ImportResult(route, warnings, errors)
    else:
        try:
            raw = json.loads(source_path.read_text(encoding="utf-8-sig"))
        except OSError as exc:
            return ImportResult(None, warnings, [f"Could not read route: {exc}"])
        except json.JSONDecodeError as exc:
            return ImportResult(None, warnings, [f"Invalid JSON at line {exc.lineno}, column {exc.colno}: {exc.msg}"])
        normalized = normalize_exobiology_payload(raw, name)
        if normalized is not None:
            raw = normalized

    source_format = "unknown"
    schema_version = 1
    stops_raw: list[Any]
    explicit_id = ""
    route_mode = ""
    settings = RouteSettings()
    metadata: dict[str, Any] = {}

    if isinstance(raw, list):
        stops_raw = raw
        source_format = "system-list"
    elif isinstance(raw, dict):
        metadata = dict(raw)
        name = str(_first(raw, "Name", "name", default=name) or name)
        explicit_id = str(_first(raw, "id", "routeId", default="") or "")
        schema_version = max(1, _integer(_first(raw, "schemaVersion", default=1), 1))
        route_mode = canonical_route_mode(str(_first(raw, "routeMode", "routeType", default="") or "")) if _first(raw, "routeMode", "routeType", default="") else ""
        settings = _settings_from_json(raw)

        # Lowercase `systems` is the RouteOps v3 hierarchy. EDDiscovery exports
        # uppercase `Systems`, which remains the legacy flat system list.
        if schema_version >= 3 and isinstance(raw.get("systems"), list):
            stops_raw = _flatten_v3_systems(raw, warnings)
            source_format = str(raw.get("sourceFormatOverride") or "routeops-v3")
            route_mode = route_mode or RouteMode.EXOBIOLOGY
        elif isinstance(raw.get("Systems"), list):
            stops_raw = raw["Systems"]
            source_format = "edd-expedition"
            schema_version = 1
        else:
            stops = _first(raw, "stops", default=None)
            waypoints = _first(raw, "waypoints", default=None)
            if isinstance(stops, list):
                stops_raw = stops
                source_format = "routeops-v2" if schema_version >= 2 else "routeops-v1"
            elif isinstance(waypoints, list):
                stops_raw = waypoints
                source_format = "waypoints"
            else:
                errors.append("JSON must contain EDDiscovery 'Systems', RouteOps 'systems', 'stops', or 'waypoints'.")
                return ImportResult(None, warnings, errors)
    else:
        return ImportResult(None, warnings, ["The JSON root must be an object or array."])

    stops: list[RouteStop] = []
    for index, item in enumerate(stops_raw):
        if isinstance(item, str) and not item.strip():
            warnings.append(f"Ignored empty stop {index + 1}.")
            continue
        try:
            stops.append(_stop_from_json(item, index, warnings, source_format))
        except RouteImportError as exc:
            errors.append(str(exc))

    if errors:
        return ImportResult(None, warnings, errors)
    if not stops:
        return ImportResult(None, warnings, ["The route contains no usable systems."])

    seen_stop_ids: dict[str, int] = {}
    seen_task_ids: set[str] = set()
    for stop in stops:
        original_stop_id = stop.id
        count = seen_stop_ids.get(original_stop_id, 0) + 1
        seen_stop_ids[original_stop_id] = count
        if count > 1:
            candidate = f"{original_stop_id}-{count}"
            while candidate in seen_stop_ids:
                count += 1
                candidate = f"{original_stop_id}-{count}"
            stop.id = candidate
            seen_stop_ids[candidate] = 1
            warnings.append(f"Duplicate stop ID '{original_stop_id}' was renamed to '{stop.id}'.")
        for task in stop.tasks:
            if task.id in seen_task_ids:
                original_task_id = task.id
                candidate = f"{stop.id}-{original_task_id}"
                suffix = 2
                while candidate in seen_task_ids:
                    candidate = f"{stop.id}-{original_task_id}-{suffix}"
                    suffix += 1
                task.id = candidate
                warnings.append(f"Duplicate task ID '{original_task_id}' was renamed to '{task.id}'.")
            seen_task_ids.add(task.id)
        _finalize_exobiology_stop(stop)

    if not route_mode:
        route_mode = infer_route_mode(stops)
    if source_format == "edd-expedition":
        route_mode = _infer_mode_from_name(name)
        settings.complete_waypoint_on_arrival = route_mode == RouteMode.WAYPOINT
        if route_mode != RouteMode.WAYPOINT:
            for stop in stops:
                stop.stop_type = route_mode
                stop.auto_complete_on_arrival = False
                if route_mode == RouteMode.EXOBIOLOGY:
                    stop.completion_policy = CompletionPolicy.MANUAL
                    stop.metadata["systemPlaceholder"] = not bool(stop.body)
                    stop.metadata["dynamicBodyDiscovery"] = True
                    _finalize_exobiology_stop(stop)
        if route_mode == RouteMode.TRADE:
            warnings.append(
                "EDDiscovery expedition JSON contains only system names. Trade Router stations, commodities, quantities, and buy/sell instructions were not exported. Export the Trade Router grid with its Excel/CSV button and load that CSV into RouteOps."
            )
            metadata["tradeDataMissing"] = True
            for stop in stops:
                stop.metadata["tradeDataMissing"] = True

    if source_format in {"edd-expedition", "system-list", "waypoints", "routeops-v1"}:
        fingerprint = "\n".join(stop.system.casefold() for stop in stops)
    else:
        fingerprint = "\n".join(
            f"{stop.system.casefold()}|{stop.body.casefold()}|{stop.stop_type}|{stop.id}" for stop in stops
        )
    route_id = explicit_id or f"{_slug(name)}-{hashlib.sha1(fingerprint.encode('utf-8')).hexdigest()[:10]}"
    route = Route(
        id=route_id,
        name=name,
        route_type=route_mode,
        source_format=source_format,
        stops=stops,
        source_path=str(source_path),
        schema_version=max(3, schema_version) if source_format in {"routeops-v3", "routeops-v5", "spansh-exobiology-json", "spansh-exobiology-csv"} else (max(2, schema_version) if source_format.startswith("routeops") else schema_version),
        settings=settings,
        metadata=metadata,
    )
    route.metadata.setdefault("catalogVersion", DEFAULT_CATALOG.version)
    return ImportResult(route, warnings, errors)


def load_route(path: str | Path) -> Route:
    result = import_route(path)
    if result.route is None or result.errors:
        raise RouteImportError("\n".join(result.errors or ["Route import failed."]))
    result.route.metadata["importWarnings"] = list(result.warnings)
    return result.route
