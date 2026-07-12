from __future__ import annotations

import csv
from collections import OrderedDict
from pathlib import Path
from typing import Any


_SYSTEM_KEYS = (
    "system", "system name", "system_name", "star system", "star_system", "star system name",
)
_BODY_KEYS = (
    "body", "body name", "body_name", "planet", "planet name", "planet_name", "landmark name", "landmark_name",
)
_SPECIES_KEYS = (
    "species", "species name", "species_name", "organism", "organism name", "biology", "landmark subtype", "landmark_subtype", "subtype",
)
_GENUS_KEYS = ("genus", "genus name", "genus_name")
_VALUE_KEYS = ("value", "estimated value", "estimated_value", "landmark value", "landmark_value", "credits", "base value", "base_value")
_SYSTEM_ADDRESS_KEYS = ("system address", "system_address", "systemaddress", "id64", "system id64", "system_id64")
_BODY_ID_KEYS = ("body id", "body_id", "bodyid")
_SIGNAL_KEYS = ("biological signals", "biological_signals", "biological signal count", "bio signals", "bio_signals")
_DISTANCE_KEYS = ("distance from arrival", "distance_from_arrival", "distance from arrival ls", "distance_from_arrival_ls", "distance to arrival", "distance_to_arrival", "distance")
_VARIANT_KEYS = ("variant", "variant name", "variant_name", "landmark variant", "landmark_variant")


def _normalized_map(row: dict[str, Any]) -> dict[str, Any]:
    return {str(key).strip().casefold(): value for key, value in row.items()}


def _first(row: dict[str, Any], keys: tuple[str, ...], default: Any = None) -> Any:
    values = _normalized_map(row)
    for key in keys:
        if key in values and values[key] not in {None, ""}:
            return values[key]
    return default


def _text(value: Any) -> str:
    return str(value or "").strip()


def _integer(value: Any) -> int | None:
    if value in {None, ""}:
        return None
    try:
        return int(float(str(value).replace(",", "").strip()))
    except (TypeError, ValueError):
        return None


def _extract_rows(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if not isinstance(payload, dict):
        return []
    for key in ("results", "route", "data", "bodies", "landmarks"):
        value = payload.get(key)
        if isinstance(value, list):
            return [row for row in value if isinstance(row, dict)]
    return []


def looks_like_exobiology_rows(rows: list[dict[str, Any]]) -> bool:
    for row in rows[:25]:
        system = _text(_first(row, _SYSTEM_KEYS))
        body = _text(_first(row, _BODY_KEYS))
        organic = _text(_first(row, _SPECIES_KEYS)) or _text(_first(row, _GENUS_KEYS))
        value = _integer(_first(row, _VALUE_KEYS))
        if system and body and (organic or value is not None):
            return True
    return False


def rows_to_routeops_v3(rows: list[dict[str, Any]], name: str, source_format: str) -> dict[str, Any] | None:
    if not looks_like_exobiology_rows(rows):
        return None

    systems: OrderedDict[str, dict[str, Any]] = OrderedDict()
    for row_index, row in enumerate(rows):
        system_name = _text(_first(row, _SYSTEM_KEYS))
        body_name = _text(_first(row, _BODY_KEYS))
        if not system_name or not body_name:
            continue
        system_address = _integer(_first(row, _SYSTEM_ADDRESS_KEYS))
        body_id = _integer(_first(row, _BODY_ID_KEYS))
        system_key = str(system_address) if system_address is not None else system_name.casefold()
        system = systems.setdefault(
            system_key,
            {
                "id": f"spansh-system-{len(systems) + 1}",
                "system": system_name,
                "systemAddress": system_address,
                "bodies": OrderedDict(),
            },
        )
        body_key = str(body_id) if body_id is not None else body_name.casefold()
        body = system["bodies"].setdefault(
            body_key,
            {
                "id": f"{system['id']}-body-{len(system['bodies']) + 1}",
                "body": body_name,
                "bodyId": body_id,
                "biologicalSignals": _integer(_first(row, _SIGNAL_KEYS)),
                "completionPolicy": "listed-targets",
                "distanceFromArrivalLs": _integer(_first(row, _DISTANCE_KEYS)),
                "manifestSource": source_format,
                "manifestCompleteness": "exact",
                "providerOrder": row_index + 1,
                "organisms": [],
            },
        )
        species = _text(_first(row, _SPECIES_KEYS))
        genus = _text(_first(row, _GENUS_KEYS))
        variant = _text(_first(row, _VARIANT_KEYS))
        value = _integer(_first(row, _VALUE_KEYS))
        if not species and not genus:
            continue
        identity = (variant or species or genus).casefold()
        existing = next(
            (
                organism
                for organism in body["organisms"]
                if _text(organism.get("variant") or organism.get("species") or organism.get("genus")).casefold() == identity
            ),
            None,
        )
        if existing is None:
            organism: dict[str, Any] = {
                "id": f"{body['id']}-organism-{len(body['organisms']) + 1}",
                "type": "scanOrganic",
                "genus": genus,
                "species": species,
                "variant": variant,
                "knowledgeLevel": "confirmed" if species or variant else "genus-confirmed",
                "source": source_format,
                "providerOrder": row_index + 1,
                "rawSourceRow": dict(row),
                "samplesRequired": 3,
                "required": True,
            }
            if value is not None:
                organism["baseValue"] = value
                organism["estimatedValue"] = value
            body["organisms"].append(organism)
        elif value is not None and not existing.get("baseValue"):
            existing["baseValue"] = value
            existing["estimatedValue"] = value

    normalized_systems: list[dict[str, Any]] = []
    for system in systems.values():
        system["bodies"] = list(system["bodies"].values())
        normalized_systems.append(system)
    if not normalized_systems:
        return None
    return {
        "schemaVersion": 5,
        "name": name,
        "routeMode": "exobiology",
        "sourceFormatOverride": source_format,
        "settings": {
            "autoAdvance": True,
            "autoCopyMode": "smart-target",
            "guidanceMode": "confirm",
            "bodyOrderMode": "route",
            "addUnplannedOrganisms": True,
            "defaultCompletionPolicy": "listed-targets",
            "showFirstLoggedPotential": True,
        },
        "systems": normalized_systems,
    }


def normalize_exobiology_payload(payload: Any, name: str, source_format: str = "spansh-exobiology-json") -> dict[str, Any] | None:
    return rows_to_routeops_v3(_extract_rows(payload), name, source_format)


def load_exobiology_csv(path: str | Path) -> dict[str, Any] | None:
    source_path = Path(path)
    delimiter = "\t" if source_path.suffix.casefold() == ".tsv" else ","
    try:
        with source_path.open("r", encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle, delimiter=delimiter))
    except (OSError, csv.Error):
        return None
    return rows_to_routeops_v3(rows, source_path.stem, "spansh-exobiology-csv")
