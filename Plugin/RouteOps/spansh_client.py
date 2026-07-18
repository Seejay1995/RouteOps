"""Spansh route generation client (standard-library only).

RouteOps generates routes directly from the Spansh plotters
(https://spansh.co.uk) instead of requiring a manual export/import. Each plotter
is an asynchronous job: submit parameters, receive a job id, then poll a results
endpoint until it reports ``ok``. The completed result is flattened and handed to
the plugin's existing importers, so a generated route follows the exact same
compile/load/library path as a file the user opened.

Only the Python standard library is used (urllib), matching the plugin's existing
dependency footprint (pyzmq + stdlib). Network work is blocking, so callers should
run generation on a worker thread and load the resulting route on the main thread
(see routeops_kernel_app background pump).
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable

SPANSH_API = "https://spansh.co.uk/api"
USER_AGENT = "RouteOps-EDDiscovery-Plugin"

ProgressCallback = Callable[[str], None]


class SpanshError(Exception):
    """A recoverable Spansh generation failure with a user-facing message.

    ``status`` is the HTTP status when Spansh rejected the request (e.g. 400 for an
    unknown reference system), or None for network/other failures.
    """

    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


def _http_error(exc: "urllib.error.HTTPError") -> SpanshError:
    message = None
    try:
        body = json.load(exc)
        if isinstance(body, dict):
            message = body.get("error")
    except Exception:
        message = None
    return SpanshError(str(message) if message else f"Spansh rejected the request (HTTP {exc.code}).", status=exc.code)


def _post(path: str, params: dict[str, Any], timeout: float = 30.0) -> Any:
    data = urllib.parse.urlencode(params).encode("utf-8")
    request = urllib.request.Request(SPANSH_API + path, data=data, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        raise _http_error(exc) from exc
    except urllib.error.HTTPError as exc:
        raise _http_error(exc) from exc
    except (urllib.error.URLError, OSError) as exc:
        raise SpanshError(f"Could not reach Spansh: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise SpanshError("Spansh returned an unreadable response.") from exc


def _get(path: str, timeout: float = 30.0) -> Any:
    request = urllib.request.Request(SPANSH_API + path, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        raise _http_error(exc) from exc
    except (urllib.error.URLError, OSError) as exc:
        raise SpanshError(f"Could not reach Spansh: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise SpanshError("Spansh returned an unreadable response.") from exc


def _jpost(path: str, body: dict[str, Any], timeout: float = 30.0) -> Any:
    request = urllib.request.Request(
        SPANSH_API + path,
        data=json.dumps(body).encode("utf-8"),
        headers={"User-Agent": USER_AGENT, "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        raise _http_error(exc) from exc
    except (urllib.error.URLError, OSError) as exc:
        raise SpanshError(f"Could not reach Spansh: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise SpanshError("Spansh returned an unreadable response.") from exc


def find_nearest_trade_station(
    system: str, *, large_pad_only: bool = True, timeout: float = 30.0
) -> dict[str, Any] | None:
    """Find the nearest real market station to ``system`` (for a cargo-route start).

    Skips colonisation ships, fleet carriers and stations with no live market data.
    """
    filters: dict[str, Any] = {"market": {"value": True}}
    if large_pad_only:
        filters["has_large_pad"] = {"value": True}
    body = {
        "filters": filters,
        "reference_system": str(system).strip(),
        "sort": [{"distance": {"direction": "asc"}}],
        "size": 30,
    }
    try:
        data = _jpost("/stations/search", body, timeout=timeout)
    except SpanshError as exc:
        if getattr(exc, "status", None) == 400:  # bad request == unknown reference system
            raise SpanshError(
                f"Spansh has no data for '{system}' - the system may be unexplored. "
                "Enter a start system nearer populated space."
            ) from exc
        raise  # transient server errors (500/429/etc.) keep Spansh's own message
    for station in data.get("results", []) if isinstance(data, dict) else []:
        name = str(station.get("name") or "")
        stype = str(station.get("type") or "")
        if not station.get("has_market") or not station.get("updated_at"):
            continue  # no live market data (construction ships, unstocked carriers)
        if name.startswith("$") or "Colonisation Ship" in name or "Carrier" in stype or "Construction" in name:
            continue
        return {
            "system": station.get("system_name"),
            "station": name,
            "distance_ly": station.get("distance"),
            "distance_ls": station.get("distance_to_arrival"),
            "type": stype,
        }
    return None


def _await_job(
    submit_response: Any,
    *,
    poll_timeout: float,
    interval: float = 2.0,
    on_progress: ProgressCallback | None = None,
) -> Any:
    if not isinstance(submit_response, dict) or not submit_response.get("job"):
        error = submit_response.get("error") if isinstance(submit_response, dict) else None
        raise SpanshError(str(error or "Spansh did not accept the request."))
    job = submit_response["job"]
    deadline = time.monotonic() + poll_timeout
    polls = 0
    while time.monotonic() < deadline:
        time.sleep(interval)
        result = _get(f"/results/{job}")
        status = str(result.get("status", "")) if isinstance(result, dict) else ""
        if status == "ok":
            return result.get("result")
        if status in {"failed", "error"}:
            raise SpanshError(str(result.get("error") or "Spansh route job failed."))
        polls += 1
        if on_progress:
            on_progress(f"Spansh working ({status or 'queued'})... {polls * interval:.0f}s")
    raise SpanshError("Timed out waiting for the Spansh route.")


# --------------------------------------------------------------------------- #
# Exobiology (Expressway to Exomastery)
# --------------------------------------------------------------------------- #

def _flatten_exobiology(result: Any) -> list[dict[str, Any]]:
    """Flatten Spansh's nested systems->bodies->landmarks into importer rows.

    A Spansh "landmark" is one biological find: ``subtype`` = full species,
    ``type`` = genus, ``value`` = credits. spansh_exobiology_importer already
    understands these row keys.
    """
    rows: list[dict[str, Any]] = []
    for system in result or []:
        if not isinstance(system, dict):
            continue
        system_name = system.get("name")
        system_address = system.get("id64")
        for body in system.get("bodies") or []:
            if not isinstance(body, dict):
                continue
            landmarks = body.get("landmarks") or []
            common = {
                "system": system_name,
                "system_address": system_address,
                "body": body.get("name"),
                "body_id": body.get("id64"),
                "distance": body.get("distance_to_arrival"),
                "biological_signals": len(landmarks),
            }
            for landmark in landmarks:
                if not isinstance(landmark, dict):
                    continue
                rows.append(
                    {
                        **common,
                        "species": landmark.get("subtype"),
                        "genus": landmark.get("type"),
                        "value": landmark.get("value"),
                    }
                )
    return rows


def generate_exobiology(
    *,
    from_system: str,
    jump_range: float,
    radius: float,
    min_value: int = 0,
    max_results: int = 50,
    loop: bool = False,
    use_mapping_value: bool = True,
    name: str | None = None,
    poll_timeout: float = 180.0,
    on_progress: ProgressCallback | None = None,
) -> dict[str, Any]:
    """Generate an exobiology route and return a RouteOps route dict."""
    if not str(from_system).strip():
        raise SpanshError("A start system is required.")
    params = {
        "from": str(from_system).strip(),
        "range": jump_range,
        "radius": radius,
        "max_results": max_results,
        "min_value": min_value,
        "loop": 1 if loop else 0,
        "use_mapping_value": 1 if use_mapping_value else 0,
    }
    result = _await_job(
        _post("/exobiology/route", params), poll_timeout=poll_timeout, on_progress=on_progress
    )
    rows = _flatten_exobiology(result)
    if not rows:
        raise SpanshError("Spansh found no exobiology bodies for those parameters.")
    from spansh_exobiology_importer import rows_to_routeops_v3

    route = rows_to_routeops_v3(
        rows, name or f"Spansh Exobiology from {from_system}", "spansh-exobiology-api"
    )
    if not route:
        raise SpanshError("Could not convert the Spansh result into a RouteOps route.")
    return route


# --------------------------------------------------------------------------- #
# Commodity sourcing ("where do I buy X near here") for colonisation supply
# --------------------------------------------------------------------------- #

def find_commodity_sources(
    reference_system: str,
    commodity: str,
    amount: int,
    *,
    large_pad_only: bool = True,
    limit: int = 5,
    timeout: float = 25.0,
) -> list[dict[str, Any]]:
    """Return stations that SELL ``commodity``, NEAREST to ``reference_system`` first.

    Uses Spansh's ``/api/commodity/buy/{system}/{commodity}/{amount}`` endpoint.
    That endpoint is NOT distance-sorted (it ranks by a buy-deal heuristic), so we
    collect the qualifying stations and re-sort by distance ourselves — the whole
    point for colony hauling is to prefer the fewest-jump source. Each source
    carries buy price, supply, pad availability and distances.
    """
    path = (
        "/commodity/buy/"
        + urllib.parse.quote(str(reference_system))
        + "/"
        + urllib.parse.quote(str(commodity))
        + "/"
        + str(int(max(1, amount)))
    )
    data = _get(path, timeout=timeout)
    stations = data.get("results") if isinstance(data, dict) else data
    if not isinstance(stations, list):
        return []
    key = str(commodity).casefold()
    sources: list[dict[str, Any]] = []
    for station in stations:
        if not isinstance(station, dict):
            continue
        if large_pad_only and not station.get("has_large_pad"):
            continue
        buy_price = supply = None
        for entry in station.get("market") or []:
            if str(entry.get("commodity", "")).casefold() == key:
                buy_price = entry.get("buy_price")
                supply = entry.get("supply")
                break
        sources.append(
            {
                "station": station.get("name"),
                "system": station.get("system_name"),
                "distance_ly": station.get("distance"),
                "distance_ls": station.get("distance_to_arrival"),
                "large_pads": station.get("large_pads"),
                "is_planetary": station.get("is_planetary"),
                "buy_price": buy_price,
                "supply": supply,
                "market_updated_at": station.get("market_updated_at"),
            }
        )
        if len(sources) >= 100:
            break  # bound the candidate pool; plenty to pick the nearest from
    sources.sort(
        key=lambda s: s["distance_ly"] if isinstance(s.get("distance_ly"), (int, float)) else float("inf")
    )
    return sources[:limit]


# --------------------------------------------------------------------------- #
# Trade / cargo routes (Spansh trade planner)
# --------------------------------------------------------------------------- #

def _trade_route(params: dict[str, Any], poll_timeout: float, on_progress: ProgressCallback | None) -> list[dict[str, Any]]:
    result = _await_job(_post("/trade/route", params), poll_timeout=poll_timeout, on_progress=on_progress)
    if not isinstance(result, list) or not result:
        raise SpanshError("Spansh found no profitable cargo route for those parameters.")
    return result


def generate_trade(
    *,
    system: str,
    station: str = "",
    cargo: int = 720,
    max_hops: int = 5,
    large_pad_only: bool = True,
    max_hop_distance: float = 50.0,
    max_system_distance: float = 25.0,
    starting_capital: int = 100_000_000,
    allow_planetary: bool = True,
    unique: bool = True,
    poll_timeout: float = 180.0,
    on_progress: ProgressCallback | None = None,
) -> dict[str, Any]:
    """Generate a profit-optimised cargo route starting from wherever you are.

    Give a start ``system``; ``station`` is optional. If it is blank (or the given
    station has no market Spansh can trade from), RouteOps finds the nearest real
    market station and starts there — returning an ``approach`` describing the hop
    to that first station. Returns ``{hops, start_system, start_station, approach,
    from_system}``.
    """
    system = str(system).strip()
    station = str(station or "").strip()
    if not system:
        raise SpanshError("A start system is required for a cargo route.")
    params = {
        "max_hops": int(max_hops),
        "max_hop_distance": max_hop_distance,
        "max_system_distance": max_system_distance,
        "starting_capital": int(starting_capital),
        "max_cargo": int(cargo),
        "max_price_age": 1_000_000_000,
        "requires_large_pad": 1 if large_pad_only else 0,
        "allow_planetary": 1 if allow_planetary else 0,
        "unique": 1 if unique else 0,
        "permit": 0,
    }
    approach: dict[str, Any] | None = None

    def with_found() -> list[dict[str, Any]]:
        nonlocal approach, station
        if on_progress:
            on_progress("Finding nearest trading station...")
        found = find_nearest_trade_station(system, large_pad_only=large_pad_only)
        if not found:
            raise SpanshError(f"No large-pad trading station with a market found near {system}.")
        approach = found
        resolved_station = str(found["station"])
        route = _trade_route(
            {**params, "system": str(found["system"]), "station": resolved_station},
            poll_timeout, on_progress,
        )
        station = resolved_station
        return route

    if station:
        try:
            hops = _trade_route({**params, "system": system, "station": station}, poll_timeout, on_progress)
            start_system = system
        except SpanshError:
            # Given station isn't a market Spansh can trade from (e.g. a construction
            # ship) -> fall back to the nearest real market near the system.
            hops = with_found()
            start_system = str(approach["system"]) if approach else system
    else:
        hops = with_found()
        start_system = str(approach["system"]) if approach else system

    return {
        "hops": hops,
        "from_system": system,
        "start_system": start_system,
        "start_station": station,
        "approach": approach,
    }
