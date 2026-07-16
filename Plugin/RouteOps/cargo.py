"""Cargo (trade) route rendering for the CARGOGRID view.

Turns the hop list from spansh_client.generate_trade into grid rows:
Hop | Commodity | From | To | Dist ly | Buy | Sell | Profit, each with a
full buy/sell/jump tooltip. Standard library only.
"""

from __future__ import annotations

from typing import Any


def _num(value: Any) -> dict[str, Any]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return {"type": "text", "value": ""}
    return {"type": "text", "value": str(int(round(value)))}


def _fmt(value: Any, suffix: str = "") -> str:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return "?"
    return f"{int(round(value)):,}{suffix}"


def _hops(result: Any) -> list[dict[str, Any]]:
    return result.get("hops", []) if isinstance(result, dict) else (result or [])


def total_profit(result: Any) -> int:
    return sum(int(hop.get("total_profit") or 0) for hop in _hops(result))


def route_to_rows(result: Any) -> list[dict[str, Any]]:
    hops = _hops(result)
    approach = result.get("approach") if isinstance(result, dict) else None
    from_system = result.get("from_system") if isinstance(result, dict) else None
    rows: list[dict[str, Any]] = []
    # Prepend a "travel to your first buy station" row when the start market is
    # in a different system than where you are.
    if approach and approach.get("system") and approach.get("system") != from_system:
        to_text = f"{approach.get('system')} / {approach.get('station')}"
        tip = (
            "Travel to your first buy station:\r\n"
            f"{to_text}  [{_fmt(approach.get('distance_ly'), ' ly')}, {_fmt(approach.get('distance_ls'), ' ls')}]"
        )
        rows.append(
            {
                "row": -2,
                "cells": [
                    {"type": "text", "value": ">"},
                    {"type": "text", "value": "(go to start)", "tooltip": tip},
                    {"type": "text", "value": str(from_system or "you"), "tooltip": tip},
                    {"type": "text", "value": to_text, "tooltip": tip},
                    _num(approach.get("distance_ly")),
                    {"type": "text", "value": ""},
                    {"type": "text", "value": ""},
                    {"type": "text", "value": ""},
                ],
            }
        )
    for index, hop in enumerate(hops, start=1):
        commodities = hop.get("commodities") or []
        first = commodities[0] if commodities else {}
        name = first.get("name", "?")
        amount = first.get("amount")
        source = hop.get("source") or {}
        destination = hop.get("destination") or {}
        buy = (first.get("source_commodity") or {}).get("buy_price")
        sell = (first.get("destination_commodity") or {}).get("sell_price")
        profit = hop.get("total_profit")
        commodity_text = name + (f" x{amount}" if amount else "")
        from_text = f"{source.get('system')} / {source.get('station')}"
        to_text = f"{destination.get('system')} / {destination.get('station')}"
        extra = ""
        if len(commodities) > 1:
            extra = f"\r\n(+{len(commodities) - 1} more commodity on this hop)"
        tip = "\r\n".join(
            [
                f"Hop {index}: {commodity_text}",
                f"Buy at {from_text} ({_fmt(source.get('distance_to_arrival'), ' ls')}) for {_fmt(buy, ' cr')}",
                f"Sell at {to_text} ({_fmt(destination.get('distance_to_arrival'), ' ls')}) for {_fmt(sell, ' cr')}",
                f"Jump {_fmt(hop.get('distance'), ' ly')}  |  hop profit {_fmt(profit, ' cr')}",
            ]
        ) + extra
        rows.append(
            {
                "row": -2,
                "cells": [
                    {"type": "text", "value": str(index)},
                    {"type": "text", "value": commodity_text, "tooltip": tip},
                    {"type": "text", "value": from_text, "tooltip": tip},
                    {"type": "text", "value": to_text, "tooltip": tip},
                    _num(hop.get("distance")),
                    _num(buy),
                    _num(sell),
                    _num(profit),
                ],
            }
        )
    return rows
