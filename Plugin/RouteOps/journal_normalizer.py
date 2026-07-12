from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class OrganicSaleRecord:
    genus: str = ""
    species: str = ""
    variant: str = ""
    value: int = 0
    bonus: int = 0


@dataclass
class JournalEvent:
    event_type: str
    event_id: str = ""
    timestamp: str = ""
    system: str = ""
    system_address: int | None = None
    body_name: str = ""
    body_id: int | None = None
    station: str = ""
    settlement: str = ""
    commodity: str = ""
    material: str = ""
    species: str = ""
    species_internal: str = ""
    genus: str = ""
    genus_internal: str = ""
    variant: str = ""
    variant_internal: str = ""
    scan_type: str = ""
    quantity: int = 1
    total: int | None = None
    biological_signal_count: int | None = None
    genuses: list[str] = field(default_factory=list)
    bio_data: list[OrganicSaleRecord] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def body(self) -> str:
        """Compatibility alias used by the v0.2 engine and tests."""
        return self.body_name


def _lookup(entry: dict[str, Any], *names: str) -> Any:
    lower = {str(key).casefold(): value for key, value in entry.items()}
    for name in names:
        if name.casefold() in lower:
            return lower[name.casefold()]
    return None


def _text(entry: dict[str, Any], *names: str) -> str:
    value = _lookup(entry, *names)
    return "" if value is None else str(value)


def _integer(entry: dict[str, Any], *names: str, default: int = 1) -> int:
    value = _lookup(entry, *names)
    try:
        return int(float(value)) if value not in {None, ""} else default
    except (TypeError, ValueError):
        return default


def _optional_integer(entry: dict[str, Any], *names: str) -> int | None:
    value = _lookup(entry, *names)
    if value in {None, ""}:
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _body_fields(entry: dict[str, Any]) -> tuple[str, int | None]:
    body_name = _text(entry, "BodyName", "Body_Localised", "BodyName_Localised")
    body_id = _optional_integer(entry, "BodyID", "BodyId")
    raw_body = _lookup(entry, "Body")
    if isinstance(raw_body, (int, float)) and not isinstance(raw_body, bool):
        if body_id is None:
            body_id = int(raw_body)
    elif raw_body is not None and not body_name:
        text = str(raw_body).strip()
        if text:
            try:
                numeric = int(float(text))
                if body_id is None:
                    body_id = numeric
            except (TypeError, ValueError):
                body_name = text
    return body_name, body_id


def _normalize_genuses(entry: dict[str, Any]) -> list[str]:
    result: list[str] = []
    raw = _lookup(entry, "Genuses", "Genera")
    if not isinstance(raw, list):
        return result
    for item in raw:
        if isinstance(item, dict):
            value = _text(item, "Genus_Localised", "Genus", "Name_Localised", "Name")
        else:
            value = str(item or "")
        value = value.strip()
        if value and value.casefold() not in {existing.casefold() for existing in result}:
            result.append(value)
    return result


def _biological_signal_count(entry: dict[str, Any]) -> int | None:
    direct = _optional_integer(entry, "BiologicalSignals", "BiologicalSignalCount")
    if direct is not None:
        return direct
    signals = _lookup(entry, "Signals")
    if not isinstance(signals, list):
        return None
    total = 0
    found = False
    for signal in signals:
        if not isinstance(signal, dict):
            continue
        signal_type = _text(signal, "Type_Localised", "Type", "SignalType").casefold()
        if "biological" not in signal_type:
            continue
        found = True
        total += max(0, _integer(signal, "Count", default=0))
    return total if found else None


def _normalize_bio_data(entry: dict[str, Any]) -> list[OrganicSaleRecord]:
    result: list[OrganicSaleRecord] = []
    raw = _lookup(entry, "BioData", "Biodata")
    if not isinstance(raw, list):
        return result
    for item in raw:
        if not isinstance(item, dict):
            continue
        result.append(
            OrganicSaleRecord(
                genus=_text(item, "Genus_Localised", "Genus"),
                species=_text(item, "Species_Localised", "Species"),
                variant=_text(item, "Variant_Localised", "Variant"),
                value=max(0, _integer(item, "Value", default=0)),
                bonus=max(0, _integer(item, "Bonus", default=0)),
            )
        )
    return result


def normalize_journal_event(entry: dict[str, Any]) -> JournalEvent:
    event_type = _text(entry, "EventTypeID", "EventTypeStr", "event", "Event").strip()
    species = _text(entry, "Species_Localised", "Species")
    genus = _text(entry, "Genus_Localised", "Genus")
    variant = _text(entry, "Variant_Localised", "Variant")
    commodity = _text(
        entry,
        "Type_Localised",
        "Commodity_Localised",
        "CargoType_Localised",
        "Type",
        "Commodity",
        "CargoType",
    )
    material = _text(entry, "Name_Localised", "Material_Localised", "Name", "Material")
    quantity = _integer(
        entry,
        "Count",
        "Quantity",
        "ItemsCollected",
        "ItemsDelivered",
        "Amount",
        default=1,
    )
    total = _optional_integer(
        entry,
        "Inventory",
        "Total",
        "TotalCount",
        "ItemsDelivered",
        "TotalItemsToDeliver",
    )
    body_name, body_id = _body_fields(entry)

    # CargoDepot's UpdateType determines whether its count represents loading or delivery.
    update_type = _text(entry, "UpdateType")
    if event_type.casefold() == "cargodepot":
        if update_type.casefold() in {"collect", "wingupdate", "deliver"}:
            commodity = commodity or _text(entry, "CargoType")

    return JournalEvent(
        event_type=event_type,
        event_id=_text(entry, "Id", "id", "JournalId", "JID"),
        timestamp=_text(entry, "timestamp", "TimeUTC"),
        system=_text(entry, "StarSystem", "SystemName", "System"),
        system_address=_optional_integer(entry, "SystemAddress"),
        body_name=body_name,
        body_id=body_id,
        station=_text(entry, "StationName", "Station", "Station_Localised"),
        settlement=_text(entry, "SettlementName", "Settlement", "NearestDestination"),
        commodity=commodity,
        material=material,
        species=species,
        species_internal=_text(entry, "Species"),
        genus=genus,
        genus_internal=_text(entry, "Genus"),
        variant=variant,
        variant_internal=_text(entry, "Variant"),
        scan_type=_text(entry, "ScanType"),
        quantity=max(0, quantity),
        total=total,
        biological_signal_count=_biological_signal_count(entry),
        genuses=_normalize_genuses(entry),
        bio_data=_normalize_bio_data(entry),
        raw=dict(entry),
    )
