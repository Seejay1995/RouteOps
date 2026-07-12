from __future__ import annotations

import csv
import hashlib
import io
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from route_models import Route, RouteMode, RouteSettings, RouteStop, RouteTask, StopType


@dataclass(frozen=True)
class TradeCommodity:
    name: str
    amount: int
    profit: int | None = None


@dataclass
class ParsedRouteRow:
    source_index: int
    system: str
    note: str = ""
    station: str = ""
    final_station: str = ""
    buys: list[TradeCommodity] = field(default_factory=list)
    cumulative_profit: int | None = None


_HEADER_SYSTEM = {
    "system",
    "systemname",
    "starsystem",
    "star",
    "name",
}
_HEADER_NOTE = {
    "note",
    "notes",
    "information",
    "info",
    "details",
    "description",
    "instructions",
}

_STATION_RE = re.compile(r"^\s*Station\s*:\s*(?P<station>.+?)\s*$", re.IGNORECASE)
_FINAL_RE = re.compile(
    r"^\s*Fly\s+to\s+(?P<station>.+?)\s+and\s+sell\s+all\s*$",
    re.IGNORECASE,
)
_BUY_RE = re.compile(
    r"^\s*(?P<commodity>.+?)\s+buy\s+(?P<amount>[\d,]+)\s+profit\s+(?P<profit>[-+]?\s*[\d,]+)\s*$",
    re.IGNORECASE,
)
_PROFIT_RE = re.compile(
    r"^\s*Profit\s+so\s+far\s*:\s*(?P<profit>[-+]?\s*[\d,]+)\s*$",
    re.IGNORECASE,
)


def _normalise_header(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.casefold())


def _slug(value: str) -> str:
    result = re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")
    return result or "item"


def _parse_integer(value: str) -> int:
    compact = value.replace(",", "").replace(" ", "").strip()
    return int(compact)


def _decode_csv(path: Path) -> str:
    raw = path.read_bytes()
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        return raw.decode("utf-16")
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _detect_dialect(text: str) -> csv.Dialect:
    sample = text[:16384]
    try:
        return csv.Sniffer().sniff(sample, delimiters=",;\t|")
    except csv.Error:
        class Fallback(csv.excel):
            delimiter = "\t" if sample.count("\t") > sample.count(",") else ";" if sample.count(";") > sample.count(",") else ","

        return Fallback()


def _find_columns(header: list[str]) -> tuple[int, int]:
    normalised = [_normalise_header(item) for item in header]
    system_index = next((i for i, name in enumerate(normalised) if name in _HEADER_SYSTEM), 0)
    note_index = next((i for i, name in enumerate(normalised) if name in _HEADER_NOTE), 1 if len(header) > 1 else -1)
    return system_index, note_index


def _looks_like_header(row: list[str]) -> bool:
    if not row:
        return False
    normalised = [_normalise_header(item) for item in row[:3]]
    return any(name in _HEADER_SYSTEM or name in _HEADER_NOTE for name in normalised)


def _parse_note(source_index: int, system: str, note: str) -> ParsedRouteRow:
    parsed = ParsedRouteRow(source_index=source_index, system=system, note=note)
    for raw_line in note.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = raw_line.strip()
        if not line:
            continue
        match = _STATION_RE.match(line)
        if match:
            parsed.station = match.group("station").strip()
            continue
        match = _FINAL_RE.match(line)
        if match:
            parsed.final_station = match.group("station").strip()
            continue
        match = _BUY_RE.match(line)
        if match:
            try:
                parsed.buys.append(
                    TradeCommodity(
                        name=match.group("commodity").strip(),
                        amount=max(1, _parse_integer(match.group("amount"))),
                        profit=_parse_integer(match.group("profit")),
                    )
                )
            except ValueError:
                pass
            continue
        match = _PROFIT_RE.match(line)
        if match:
            try:
                parsed.cumulative_profit = _parse_integer(match.group("profit"))
            except ValueError:
                pass
    return parsed


def _read_rows(path: Path) -> tuple[list[ParsedRouteRow], list[str], list[str]]:
    warnings: list[str] = []
    errors: list[str] = []
    try:
        text = _decode_csv(path)
    except OSError as exc:
        return [], warnings, [f"Could not read route CSV: {exc}"]

    try:
        reader = csv.reader(io.StringIO(text, newline=""), _detect_dialect(text))
        raw_rows = [list(row) for row in reader]
    except csv.Error as exc:
        return [], warnings, [f"Invalid route CSV: {exc}"]

    raw_rows = [row for row in raw_rows if any(str(cell).strip() for cell in row)]
    if not raw_rows:
        return [], warnings, ["The route CSV contains no rows."]

    if _looks_like_header(raw_rows[0]):
        header = raw_rows.pop(0)
        system_index, note_index = _find_columns(header)
    else:
        header = []
        system_index, note_index = 0, 1
        warnings.append("The CSV had no recognised header; RouteOps used columns 1 and 2 as System and Notes.")

    parsed_rows: list[ParsedRouteRow] = []
    for source_index, row in enumerate(raw_rows, start=2 if header else 1):
        system = row[system_index].strip() if system_index < len(row) else ""
        if not system:
            warnings.append(f"Ignored CSV row {source_index} because it has no system name.")
            continue
        note = row[note_index].strip() if note_index >= 0 and note_index < len(row) else ""
        parsed_rows.append(_parse_note(source_index, system, note))

    if not parsed_rows:
        errors.append("The route CSV contains no usable system rows.")
    return parsed_rows, warnings, errors


def _task(
    stop_id: str,
    suffix: str,
    task_type: str,
    label: str,
    target: str,
    quantity: int = 1,
    metadata: dict[str, Any] | None = None,
) -> RouteTask:
    return RouteTask(
        id=f"{stop_id}-{suffix}",
        task_type=task_type,
        label=label,
        required=True,
        target=target,
        quantity_required=max(1, quantity),
        metadata=dict(metadata or {}),
    )


def _build_trade_route(path: Path, rows: list[ParsedRouteRow], warnings: list[str]) -> Route:
    stops: list[RouteStop] = []
    incoming: list[TradeCommodity] = []

    for route_index, row in enumerate(rows, start=1):
        stop_id = f"stop-{route_index}"
        station = row.station or row.final_station
        tasks: list[RouteTask] = []

        if station:
            tasks.append(
                _task(
                    stop_id,
                    "dock",
                    "dockAtStation",
                    f"Dock at {station}",
                    station,
                    metadata={"source": "edd-trade-router-csv"},
                )
            )
        elif incoming or row.buys:
            warnings.append(
                f"Trade CSV row {row.source_index} ({row.system}) has commodities but no station name."
            )

        for item_index, commodity in enumerate(incoming, start=1):
            tasks.append(
                _task(
                    stop_id,
                    f"sell-{item_index}-{_slug(commodity.name)}",
                    "sellCommodity",
                    f"Sell {commodity.amount} {commodity.name}",
                    commodity.name,
                    commodity.amount,
                    metadata={
                        "action": "sell",
                        "quantity": commodity.amount,
                        "source": "edd-trade-router-csv",
                    },
                )
            )

        for item_index, commodity in enumerate(row.buys, start=1):
            tasks.append(
                _task(
                    stop_id,
                    f"buy-{item_index}-{_slug(commodity.name)}",
                    "buyCommodity",
                    f"Buy {commodity.amount} {commodity.name}",
                    commodity.name,
                    commodity.amount,
                    metadata={
                        "action": "buy",
                        "quantity": commodity.amount,
                        "expectedProfit": commodity.profit,
                        "source": "edd-trade-router-csv",
                    },
                )
            )

        if incoming and row.buys:
            instructions = "Dock, sell the incoming cargo, then buy the listed cargo for the next leg."
        elif incoming:
            instructions = "Dock and sell the incoming cargo."
        elif row.buys:
            instructions = "Dock and buy the listed cargo for the next leg."
        else:
            instructions = "Review this Trade Router stop manually."
            tasks.append(
                _task(
                    stop_id,
                    "manual-review",
                    "manualChecklist",
                    "Review Trade Router instructions",
                    row.note or row.system,
                )
            )
            warnings.append(
                f"Trade CSV row {row.source_index} ({row.system}) did not contain recognised trade instructions."
            )

        stops.append(
            RouteStop(
                id=stop_id,
                sequence=route_index,
                system=row.system,
                stop_type=StopType.TRADE,
                station=station,
                notes=row.note,
                instructions=instructions,
                tasks=tasks,
                auto_complete_on_arrival=False,
                metadata={
                    "sourceRow": row.source_index,
                    "cumulativeProfit": row.cumulative_profit,
                    "tradeImport": True,
                    "inferDockFromMarket": True,
                },
            )
        )
        incoming = list(row.buys)

    first_station = rows[0].station or rows[0].final_station
    name = f"{rows[0].system} @ {first_station} (Trade)" if first_station else f"{path.stem} (Trade)"
    fingerprint = "\n".join(
        f"{stop.system.casefold()}|{stop.station.casefold()}|"
        + ",".join(f"{task.task_type}:{task.target}:{task.quantity_required}" for task in stop.tasks)
        for stop in stops
    )
    route_id = f"{_slug(name)}-{hashlib.sha1(fingerprint.encode('utf-8')).hexdigest()[:10]}"
    return Route(
        id=route_id,
        name=name,
        route_type=RouteMode.TRADE,
        source_format="edd-trade-router-csv",
        stops=stops,
        source_path=str(path),
        schema_version=2,
        settings=RouteSettings(
            auto_copy_mode="current-target",
            auto_advance=True,
            complete_waypoint_on_arrival=False,
        ),
        metadata={
            "source": "EDDiscovery Trade Router CSV",
            "tradeTasksRecovered": True,
        },
    )


def _build_generic_route(path: Path, rows: list[ParsedRouteRow], warnings: list[str]) -> Route:
    stops = [
        RouteStop(
            id=f"stop-{index}",
            sequence=index,
            system=row.system,
            stop_type=StopType.WAYPOINT,
            notes=row.note,
            auto_complete_on_arrival=True,
            metadata={"sourceRow": row.source_index},
        )
        for index, row in enumerate(rows, start=1)
    ]
    fingerprint = "\n".join(stop.system.casefold() for stop in stops)
    name = path.stem.replace("_", " ").strip() or "EDDiscovery Route"
    route_id = f"{_slug(name)}-{hashlib.sha1(fingerprint.encode('utf-8')).hexdigest()[:10]}"
    warnings.append(
        "No EDDiscovery Trade Router instructions were found, so the CSV was imported as waypoints."
    )
    return Route(
        id=route_id,
        name=name,
        route_type=RouteMode.WAYPOINT,
        source_format="edd-route-csv",
        stops=stops,
        source_path=str(path),
        schema_version=2,
        settings=RouteSettings(),
        metadata={"source": "EDDiscovery Route CSV"},
    )


def import_edd_route_csv(path: str | Path) -> tuple[Route | None, list[str], list[str]]:
    source_path = Path(path).expanduser().resolve()
    rows, warnings, errors = _read_rows(source_path)
    if errors:
        return None, warnings, errors

    trade_detected = any(row.station or row.final_station or row.buys for row in rows)
    route = _build_trade_route(source_path, rows, warnings) if trade_detected else _build_generic_route(source_path, rows, warnings)
    return route, warnings, errors
