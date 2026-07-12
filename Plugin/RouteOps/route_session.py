from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json
from typing import Any

from route_engine import RouteEngine
from route_models import Route


SESSION_VERSION = 1


@dataclass(frozen=True)
class RouteSessionDefinition:
    route_id: str
    route_name: str
    route_type: str
    source_path: str
    source_format: str
    schema_version: int
    fingerprint: str

    @classmethod
    def from_route(cls, route: Route) -> "RouteSessionDefinition":
        return cls(
            route_id=route.id,
            route_name=route.name,
            route_type=route.route_type,
            source_path=route.source_path,
            source_format=route.source_format,
            schema_version=route.schema_version,
            fingerprint=_route_fingerprint(route),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "routeId": self.route_id,
            "routeName": self.route_name,
            "routeType": self.route_type,
            "sourcePath": self.source_path,
            "sourceFormat": self.source_format,
            "schemaVersion": self.schema_version,
            "fingerprint": self.fingerprint,
        }


class RouteSession:
    """Owns mutable runtime progress for one compiled route definition."""

    def __init__(self, definition: RouteSessionDefinition, engine: RouteEngine) -> None:
        self.definition = definition
        self.engine = engine

    @classmethod
    def start(cls, compiled_route: Route, state: dict[str, Any] | None = None) -> "RouteSession":
        definition = RouteSessionDefinition.from_route(compiled_route)
        working_route = deepcopy(compiled_route)
        session = cls(definition, RouteEngine(working_route))
        if state:
            session.apply_state(state)
        return session

    @classmethod
    def attach(cls, engine: RouteEngine) -> "RouteSession":
        """Compatibility bridge for callers that still construct RouteEngine directly."""
        return cls(RouteSessionDefinition.from_route(engine.route), engine)

    @property
    def route(self) -> Route:
        return self.engine.route

    def apply_state(self, state: dict[str, Any]) -> bool:
        route_id = str(state.get("routeId") or state.get("route_id") or "")
        if route_id and route_id != self.definition.route_id:
            return False
        self.engine.apply_state(deepcopy(state))
        return True

    def snapshot(self) -> dict[str, Any]:
        state = self.engine.to_state()
        state["sessionVersion"] = SESSION_VERSION
        state["routeFingerprint"] = self.definition.fingerprint
        state["routeDefinition"] = self.definition.to_dict()
        return state


def _route_fingerprint(route: Route) -> str:
    payload = {
        "routeId": route.id,
        "routeType": route.route_type,
        "sourceFormat": route.source_format,
        "schemaVersion": route.schema_version,
        "stops": [
            {
                "id": stop.id,
                "system": stop.system,
                "body": stop.body,
                "stopType": stop.stop_type,
                "tasks": [
                    {
                        "id": task.id,
                        "taskType": task.task_type,
                        "target": task.target,
                        "quantityRequired": task.quantity_required,
                    }
                    for task in stop.tasks
                ],
            }
            for stop in route.stops
        ],
    }
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
