"""Cargo (trade) route rendering for the CARGOGRID view.

Turns the hop list from spansh_client.generate_trade into grid rows:
Hop | Commodity | Buy at | Sell at | Ly | Profit | Cumulative, with human-readable
credit values and a full buy/sell/jump tooltip per hop. Standard library only.
"""

from __future__ import annotations

from typing import Any


def _cr(value: Any) -> str:
    """Human-readable credits: 16,212,810 -> '16.2M', 49,185 -> '49k'."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return "-"
    v = int(round(value))
    if abs(v) >= 1_000_000:
        return f"{v / 1_000_000:.2f}M"
    if abs(v) >= 1_000:
        return f"{v / 1_000:.0f}k"
    return str(v)


def _fmt(value: Any, suffix: str = "") -> str:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return "?"
    return f"{int(round(value)):,}{suffix}"


def _ly(value: Any) -> dict[str, Any]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return {"type": "text", "value": ""}
    return {"type": "text", "value": str(int(round(value)))}


def _hops(result: Any) -> list[dict[str, Any]]:
    return result.get("hops", []) if isinstance(result, dict) else (result or [])


def total_profit(result: Any) -> int:
    return sum(int(hop.get("total_profit") or 0) for hop in _hops(result))


def total_distance(result: Any) -> int:
    return int(round(sum(float(hop.get("distance") or 0) for hop in _hops(result))))


def route_to_rows(result: Any) -> list[dict[str, Any]]:
    hops = _hops(result)
    approach = result.get("approach") if isinstance(result, dict) else None
    from_system = result.get("from_system") if isinstance(result, dict) else None
    rows: list[dict[str, Any]] = []

    # Prepend a "travel to your first buy station" row when the start market is in a
    # different system than where you are.
    if approach and approach.get("system") and approach.get("system") != from_system:
        to_text = f"{approach.get('system')} / {approach.get('station')}"
        tip = (
            "Travel to your first buy station:\r\n"
            f"{to_text}  [{_fmt(approach.get('distance_ly'), ' ly')}, "
            f"{_fmt(approach.get('distance_ls'), ' ls')}]"
        )
        rows.append({
            "row": -2,
            "cells": [
                {"type": "text", "value": ">"},
                {"type": "text", "value": "(travel to start)", "tooltip": tip},
                {"type": "text", "value": str(from_system or "you"), "tooltip": tip},
                {"type": "text", "value": to_text, "tooltip": tip},
                _ly(approach.get("distance_ly")),
                {"type": "text", "value": ""},
                {"type": "text", "value": ""},
            ],
        })

    cumulative = 0
    for index, hop in enumerate(hops, start=1):
        commodities = hop.get("commodities") or []
        first = commodities[0] if commodities else {}
        name = first.get("name", "?")
        amount = first.get("amount")
        source = hop.get("source") or {}
        destination = hop.get("destination") or {}
        buy = (first.get("source_commodity") or {}).get("buy_price")
        sell = (first.get("destination_commodity") or {}).get("sell_price")
        profit = int(hop.get("total_profit") or 0)
        cumulative += profit
        commodity_text = name + (f"  x{amount}" if amount else "")
        from_text = f"{source.get('system')} / {source.get('station')}"
        to_text = f"{destination.get('system')} / {destination.get('station')}"
        per_ton = (profit / amount) if amount else None
        extra = f"\r\n(+{len(commodities) - 1} more commodity on this hop)" if len(commodities) > 1 else ""
        tip = "\r\n".join([
            f"Hop {index}: {commodity_text}",
            f"Buy  {from_text}  ({_fmt(source.get('distance_to_arrival'), ' ls')})  @ {_fmt(buy, ' cr')}",
            f"Sell {to_text}  ({_fmt(destination.get('distance_to_arrival'), ' ls')})  @ {_fmt(sell, ' cr')}",
            f"Jump {_fmt(hop.get('distance'), ' ly')}  |  profit {_fmt(profit, ' cr')}"
            + (f"  ({_fmt(per_ton, ' cr/t')})" if per_ton else ""),
        ]) + extra
        rows.append({
            "row": -2,
            "cells": [
                {"type": "text", "value": str(index)},
                {"type": "text", "value": commodity_text, "tooltip": tip},
                {"type": "text", "value": from_text, "tooltip": tip},
                {"type": "text", "value": to_text, "tooltip": tip},
                _ly(hop.get("distance")),
                {"type": "text", "value": _cr(profit), "tooltip": tip},
                {"type": "text", "value": _cr(cumulative), "tooltip": tip},
            ],
        })
    return rows
