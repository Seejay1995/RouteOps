from __future__ import annotations

from route_models import RouteMode, StopType


SPECIALIZATIONS: dict[str, dict[str, object]] = {
    StopType.WAYPOINT: {
        "display_name": "Waypoint",
        "default_auto_complete": True,
        "copy_target": "system",
        "supported_tasks": {"visitSystem", "manualChecklist"},
    },
    StopType.EXPLORATION: {
        "display_name": "Exploration",
        "default_auto_complete": False,
        "copy_target": "system",
        "supported_tasks": {
            "visitSystem",
            "scanStar",
            "scanBody",
            "mapBody",
            "visitBody",
            "landOnBody",
            "dockAtStation",
            "manualChecklist",
        },
    },
    StopType.EXOBIOLOGY: {
        "display_name": "Exobiology",
        "default_auto_complete": False,
        "copy_target": "system",
        "supported_tasks": {
            "scanOrganic",
            "scanSpecies",
            "sampleSpecies",
            "visitBody",
            "landOnBody",
            "manualChecklist",
        },
    },
    StopType.MATERIALS: {
        "display_name": "Materials",
        "default_auto_complete": False,
        "copy_target": "system",
        "supported_tasks": {
            "collectMaterial",
            "reachInventoryQuantity",
            "material",
            "visitBody",
            "landOnBody",
            "manualChecklist",
        },
    },
    StopType.TRADE: {
        "display_name": "Trade",
        "default_auto_complete": False,
        "copy_target": "system",
        "supported_tasks": {
            "dockAtStation",
            "buyCommodity",
            "sellCommodity",
            "manualChecklist",
        },
    },
    StopType.CARGO: {
        "display_name": "Cargo",
        "default_auto_complete": False,
        "copy_target": "system",
        "supported_tasks": {
            "dockAtStation",
            "loadCommodity",
            "collectCargo",
            "deliverCommodity",
            "unloadCommodity",
            "manualChecklist",
        },
    },
    StopType.CARRIER: {
        "display_name": "Carrier",
        "default_auto_complete": False,
        "copy_target": "system",
        "supported_tasks": {
            "dockAtStation",
            "loadCommodity",
            "deliverCommodity",
            "manualChecklist",
        },
    },
    StopType.DOCK: {
        "display_name": "Docking",
        "default_auto_complete": False,
        "copy_target": "system",
        "supported_tasks": {"dockAtStation", "manualChecklist"},
    },
    StopType.LAND: {
        "display_name": "Landing",
        "default_auto_complete": False,
        "copy_target": "system",
        "supported_tasks": {"visitBody", "landOnBody", "manualChecklist"},
    },
    StopType.CHECKLIST: {
        "display_name": "Checklist",
        "default_auto_complete": False,
        "copy_target": "system",
        "supported_tasks": {"manualChecklist"},
    },
}


TASK_TYPE_ALIASES = {
    "visit": "visitSystem",
    "visitsystem": "visitSystem",
    "waypoint": "visitSystem",
    "scanstar": "scanStar",
    "scanbody": "scanBody",
    "mapbody": "mapBody",
    "visitbody": "visitBody",
    "landonbody": "landOnBody",
    "dock": "dockAtStation",
    "dockatstation": "dockAtStation",
    "scanorganic": "scanOrganic",
    "scanspecies": "scanSpecies",
    "samplespecies": "sampleSpecies",
    "collectmaterial": "collectMaterial",
    "reachinventoryquantity": "reachInventoryQuantity",
    "material": "collectMaterial",
    "buycommodity": "buyCommodity",
    "sellcommodity": "sellCommodity",
    "loadcommodity": "loadCommodity",
    "collectcargo": "collectCargo",
    "delivercommodity": "deliverCommodity",
    "unloadcommodity": "unloadCommodity",
    "manualconfirmation": "manualChecklist",
    "manualchecklist": "manualChecklist",
    "checklist": "manualChecklist",
}


ROUTE_MODE_ALIASES = {
    "expedition": RouteMode.WAYPOINT,
    "waypoints": RouteMode.WAYPOINT,
    "waypoint": RouteMode.WAYPOINT,
    "exploration": RouteMode.EXPLORATION,
    "exo": RouteMode.EXOBIOLOGY,
    "exobiology": RouteMode.EXOBIOLOGY,
    "material": RouteMode.MATERIALS,
    "materials": RouteMode.MATERIALS,
    "rawmaterials": RouteMode.MATERIALS,
    "trade": RouteMode.TRADE,
    "cargo": RouteMode.CARGO,
    "carrier": RouteMode.CARRIER,
    "mixed": RouteMode.MIXED,
}


STOP_TYPE_ALIASES = {
    "expedition": StopType.WAYPOINT,
    "waypoints": StopType.WAYPOINT,
    "waypoint": StopType.WAYPOINT,
    "explore": StopType.EXPLORATION,
    "exploration": StopType.EXPLORATION,
    "exo": StopType.EXOBIOLOGY,
    "exobiology": StopType.EXOBIOLOGY,
    "material": StopType.MATERIALS,
    "materials": StopType.MATERIALS,
    "rawmaterials": StopType.MATERIALS,
    "trade": StopType.TRADE,
    "cargo": StopType.CARGO,
    "carrier": StopType.CARRIER,
    "dock": StopType.DOCK,
    "land": StopType.LAND,
    "checklist": StopType.CHECKLIST,
}


def canonical_task_type(value: str) -> str:
    compact = value.strip().replace("_", "").replace("-", "").casefold()
    return TASK_TYPE_ALIASES.get(compact, value.strip() or "manualChecklist")


def canonical_route_mode(value: str) -> str:
    return ROUTE_MODE_ALIASES.get(value.strip().casefold(), value.strip().casefold() or RouteMode.WAYPOINT)


def canonical_stop_type(value: str) -> str:
    return STOP_TYPE_ALIASES.get(value.strip().casefold(), value.strip().casefold() or StopType.WAYPOINT)


def display_name(stop_type: str) -> str:
    info = SPECIALIZATIONS.get(stop_type, SPECIALIZATIONS[StopType.CHECKLIST])
    return str(info["display_name"])
