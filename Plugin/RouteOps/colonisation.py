"""Colonisation supply planning.

Reads the player's current colony construction requirements straight from the
Elite Dangerous journal (the ``ColonisationConstructionDepot`` event), then for
each outstanding commodity finds the best place to buy it via Spansh
(spansh_client.find_commodity_sources), filtered by landing-pad size and ranked
by distance to the colony. The result is a "sourcing board": one row per
commodity with the outstanding amount, trips required at the player's cargo
capacity, and the nearest qualifying source stations.

Only the standard library plus spansh_client (stdlib urllib) are used.
"""

from __future__ import annotations

import glob
import json
import math
import os
from typing import Any, Callable

ProgressCallback = Callable[[str], None]

# Standard Elite Dangerous journal location on Windows.
DEFAULT_JOURNAL_DIR = os.path.join(
    os.path.expanduser("~"),
    "Saved Games",
    "Frontier Developments",
    "Elite Dangerous",
)

_SYSTEM_EVENTS = ('"event":"FSDJump"', '"event":"Location"', '"event":"Docked"', '"event":"CarrierJump"')


def _journal_files(journal_dir: str) -> list[str]:
    files = glob.glob(os.path.join(journal_dir, "Journal.*.log"))
    return sorted(files, key=lambda path: os.path.getmtime(path))


def read_latest_construction(journal_dir: str | None = None) -> dict[str, Any] | None:
    """Parse the most recent ColonisationConstructionDepot and its colony system.

    Returns ``{"system", "market_id", "progress", "complete", "needs": [...]}``
    where each need is ``{"name", "required", "provided", "outstanding",
    "payment"}`` for commodities that are not yet fully supplied. Returns None if
    no construction depot event is found.
    """
    journal_dir = journal_dir or DEFAULT_JOURNAL_DIR
    latest: dict[str, Any] | None = None
    latest_system: str | None = None
    last_system: str | None = None
    for path in _journal_files(journal_dir):
        try:
            with open(path, encoding="utf-8", errors="replace") as handle:
                for line in handle:
                    if any(marker in line for marker in _SYSTEM_EVENTS):
                        try:
                            star = json.loads(line).get("StarSystem")
                        except (ValueError, TypeError):
                            star = None
                        if star:
                            last_system = star
                    elif '"ColonisationConstructionDepot"' in line:
                        try:
                            event = json.loads(line)
                        except (ValueError, TypeError):
                            continue
                        latest = event
                        latest_system = last_system
        except OSError:
            continue

    if not latest:
        return None

    needs: list[dict[str, Any]] = []
    for resource in latest.get("ResourcesRequired", []) or []:
        if not isinstance(resource, dict):
            continue
        required = int(resource.get("RequiredAmount", 0) or 0)
        provided = int(resource.get("ProvidedAmount", 0) or 0)
        outstanding = required - provided
        if outstanding <= 0:
            continue
        needs.append(
            {
                "name": resource.get("Name_Localised") or resource.get("Name") or "?",
                "required": required,
                "provided": provided,
                "outstanding": outstanding,
                "payment": resource.get("Payment"),
            }
        )
    needs.sort(key=lambda item: item["outstanding"], reverse=True)
    return {
        "system": latest_system,
        "market_id": latest.get("MarketID"),
        "progress": latest.get("ConstructionProgress"),
        "complete": bool(latest.get("ConstructionComplete")),
        "needs": needs,
    }


def read_current_dock(journal_dir: str | None = None) -> tuple[str, str] | None:
    """Return the (system, station) of the most recent Docked event at a real market.

    Skips colonisation/construction ships and unlocalised token station names
    ("$EXT_PANEL_..."), which Spansh cannot resolve as a trade source.
    """
    journal_dir = journal_dir or DEFAULT_JOURNAL_DIR
    result: tuple[str, str] | None = None
    for path in _journal_files(journal_dir)[-10:]:
        try:
            with open(path, encoding="utf-8", errors="replace") as handle:
                for line in handle:
                    if '"event":"Docked"' not in line:
                        continue
                    try:
                        event = json.loads(line)
                    except (ValueError, TypeError):
                        continue
                    raw_name = str(event.get("StationName") or "")
                    name = str(event.get("StationName_Localised") or event.get("StationName") or "")
                    system = str(event.get("StarSystem") or "")
                    if raw_name.startswith("$") or "Colonisation" in raw_name or "Construction" in name:
                        continue
                    if system and name:
                        result = (system, name)
        except OSError:
            continue
    return result


def read_current_system(journal_dir: str | None = None) -> str | None:
    """Return the most recent StarSystem (FSDJump/CarrierJump/Location), for prefill."""
    journal_dir = journal_dir or DEFAULT_JOURNAL_DIR
    system: str | None = None
    for path in _journal_files(journal_dir)[-6:]:
        try:
            with open(path, encoding="utf-8", errors="replace") as handle:
                for line in handle:
                    if '"StarSystem"' not in line:
                        continue
                    if '"FSDJump"' in line or '"Location"' in line or '"CarrierJump"' in line:
                        try:
                            event = json.loads(line)
                        except (ValueError, TypeError):
                            continue
                        system = event.get("StarSystem") or system
        except OSError:
            continue
    return system


def read_cargo_capacity(journal_dir: str | None = None) -> int | None:
    """Return the current ship's CargoCapacity from the latest Loadout event."""
    journal_dir = journal_dir or DEFAULT_JOURNAL_DIR
    capacity: int | None = None
    for path in _journal_files(journal_dir)[-6:]:
        try:
            with open(path, encoding="utf-8", errors="replace") as handle:
                for line in handle:
                    if '"event":"Loadout"' not in line:
                        continue
                    try:
                        event = json.loads(line)
                    except (ValueError, TypeError):
                        continue
                    value = event.get("CargoCapacity")
                    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                        capacity = value
        except OSError:
            continue
    return capacity


def build_sourcing_board(
    construction: dict[str, Any],
    *,
    cargo_capacity: int = 720,
    large_pad_only: bool = True,
    sources_per_commodity: int = 3,
    on_progress: ProgressCallback | None = None,
) -> list[dict[str, Any]]:
    """For each outstanding need, attach the best qualifying source stations.

    Each board row is the original need plus ``trips`` (loads at ``cargo_capacity``)
    and ``sources`` (nearest large-pad-qualifying stations selling it).
    """
    import spansh_client as sc

    reference = construction.get("system")
    if not reference:
        raise sc.SpanshError("Could not determine the colony system from the journal.")
    needs = construction.get("needs") or []
    board: list[dict[str, Any]] = []
    for index, need in enumerate(needs, start=1):
        if on_progress:
            on_progress(f"Sourcing {need['name']} ({index}/{len(needs)})...")
        # Ask for a hold's worth, not the whole need: no single station stocks
        # tens of thousands of units, and the run is multi-trip regardless. This
        # finds the nearest qualifying sellers; their real supply is reported.
        probe_amount = min(need["outstanding"], cargo_capacity) if cargo_capacity else need["outstanding"]
        try:
            sources = sc.find_commodity_sources(
                reference,
                need["name"],
                probe_amount,
                large_pad_only=large_pad_only,
                limit=sources_per_commodity,
            )
        except sc.SpanshError:
            sources = []
        trips = math.ceil(need["outstanding"] / cargo_capacity) if cargo_capacity else None
        board.append({**need, "trips": trips, "sources": sources})
    return board


def _fmt_int(value: Any, suffix: str = "") -> str:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return "?"
    return f"{int(round(value)):,}{suffix}"


def _numcell(value: Any) -> dict[str, Any]:
    # Plain (comma-free) integer string so the DGV's Numeric columns sort correctly.
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return {"type": "text", "value": ""}
    return {"type": "text", "value": str(int(round(value)))}


def _source_tooltip(row: dict[str, Any]) -> str:
    lines = [row["name"]]
    trips = row.get("trips")
    lines.append(f"Need {_fmt_int(row['outstanding'])}" + (f"  (~{trips} trips)" if trips else ""))
    sources = row.get("sources") or []
    if not sources:
        lines.append("No qualifying large-pad source found near the colony.")
    for source in sources:
        lines.append(
            f"{source.get('system')} / {source.get('station')}  "
            f"[{_fmt_int(source.get('distance_ly'), ' ly')}, {_fmt_int(source.get('distance_ls'), ' ls')}, "
            f"buy {_fmt_int(source.get('buy_price'), ' cr')}, supply {_fmt_int(source.get('supply'))}]"
        )
    return "\r\n".join(lines)


def board_to_rows(board: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert a sourcing board into a COLGRID changelist (Commodity, Need, Trips,
    Best Source, Dist ly, Buy CR, Supply) with a full-detail tooltip per row."""
    rows: list[dict[str, Any]] = []
    for row in board:
        sources = row.get("sources") or []
        best = sources[0] if sources else None
        tip = _source_tooltip(row)
        if best:
            source_text = f"{best.get('system')} / {best.get('station')}"
            distance, buy, supply = best.get("distance_ly"), best.get("buy_price"), best.get("supply")
        else:
            source_text, distance, buy, supply = "(no large-pad source)", None, None, None
        rows.append(
            {
                "row": -2,
                "cells": [
                    {"type": "text", "value": row["name"], "tooltip": tip},
                    _numcell(row.get("outstanding")),
                    _numcell(row.get("trips")),
                    {"type": "text", "value": source_text, "tooltip": tip},
                    _numcell(distance),
                    _numcell(buy),
                    _numcell(supply),
                ],
            }
        )
    return rows


def format_board_text(construction: dict[str, Any], board: list[dict[str, Any]]) -> str:
    """Render the sourcing board as plain text for the DETAIL rich-text pane."""
    lines: list[str] = []
    system = construction.get("system") or "?"
    progress = construction.get("progress")
    header = f"COLONISATION SUPPLY - {system}"
    if isinstance(progress, (int, float)):
        header += f"   (construction {progress * 100:.0f}%)"
    lines.append(header)
    lines.append(f"{len(board)} commodities outstanding. Best large-pad source per commodity, nearest first.")
    lines.append("")
    for row in board:
        head = f"{row['name']}  -  need {_fmt_int(row['outstanding'])}"
        if row.get("trips"):
            head += f"  (~{row['trips']} trips)"
        lines.append(head)
        sources = row.get("sources") or []
        if not sources:
            lines.append("   (no qualifying large-pad source found near the colony)")
        for source in sources:
            dly = _fmt_int(source.get("distance_ly"), " ly")
            dls = _fmt_int(source.get("distance_ls"), " ls")
            price = _fmt_int(source.get("buy_price"), " cr")
            supply = _fmt_int(source.get("supply"))
            pads = source.get("large_pads")
            pad = f"{pads}xL" if isinstance(pads, int) else "L"
            lines.append(
                f"   -> {source.get('system')} / {source.get('station')}"
                f"  [{dly}, {dls}, {pad}, buy {price}, supply {supply}]"
            )
        lines.append("")
    return "\r\n".join(lines)
