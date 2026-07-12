from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

from route_models import ProgressStatus, Route, RouteStop, StopType, TaskStatus


class GuidanceMode:
    CONFIRM = "confirm"
    AUTO_COPY = "auto-copy"
    AUTO_ADVANCE = "auto-advance"

    ALL = (CONFIRM, AUTO_COPY, AUTO_ADVANCE)


class BodyOrderMode:
    ROUTE = "route"
    NEAREST = "nearest"
    VALUE = "value"
    MANUAL = "manual"

    ALL = (ROUTE, NEAREST, VALUE, MANUAL)


class NavigationTargetType:
    SYSTEM = "system"
    BODY = "body"
    SURFACE_SEARCH = "surface-search"
    NONE = "none"


class NavigationTargetState:
    SELECTED = "selected"
    COPIED = "copied"
    REACHED = "reached"
    SUPERSEDED = "superseded"


class ManifestCompleteness:
    EXACT = "exact"
    BODIES = "bodies-known"
    SYSTEM_ONLY = "system-only"
    LIVE = "live"


class SkipScope:
    TARGET_BODY = "target-body"
    SPECIES_BODY = "species-body"
    SPECIES_ROUTE = "species-route"
    GENUS_ROUTE = "genus-route"
    BODY = "body"


SKIP_REASONS = (
    "too-difficult",
    "low-value",
    "terrain",
    "too-far",
    "already-sampled",
    "time-limit",
    "preference",
    "other",
)

SKIP_REASON_LABELS = {
    "too-difficult": "Too difficult to locate",
    "low-value": "Low value",
    "terrain": "Terrain unsuitable",
    "too-far": "Too far from arrival",
    "already-sampled": "Already sampled previously",
    "time-limit": "Time limit",
    "preference": "User preference",
    "other": "Other",
}

DIFFICULTIES = ("unknown", "easy", "normal", "hard", "very-hard")


@dataclass
class NavigationTarget:
    target_type: str = NavigationTargetType.NONE
    system_key: str = ""
    system_name: str = ""
    stop_id: str = ""
    body_name: str = ""
    source: str = "route-order"
    state: str = NavigationTargetState.SELECTED
    copied_at: str = ""
    reached_at: str = ""

    @property
    def text(self) -> str:
        if self.target_type in {NavigationTargetType.BODY, NavigationTargetType.SURFACE_SEARCH}:
            return self.body_name
        if self.target_type == NavigationTargetType.SYSTEM:
            return self.system_name
        return ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "targetType": self.target_type,
            "systemKey": self.system_key,
            "systemName": self.system_name,
            "stopId": self.stop_id,
            "bodyName": self.body_name,
            "source": self.source,
            "state": self.state,
            "copiedAt": self.copied_at,
            "reachedAt": self.reached_at,
        }

    @classmethod
    def from_dict(cls, raw: Any) -> "NavigationTarget":
        if not isinstance(raw, dict):
            return cls()
        return cls(
            target_type=str(raw.get("targetType") or NavigationTargetType.NONE),
            system_key=str(raw.get("systemKey") or ""),
            system_name=str(raw.get("systemName") or ""),
            stop_id=str(raw.get("stopId") or ""),
            body_name=str(raw.get("bodyName") or ""),
            source=str(raw.get("source") or "route-order"),
            state=str(raw.get("state") or NavigationTargetState.SELECTED),
            copied_at=str(raw.get("copiedAt") or ""),
            reached_at=str(raw.get("reachedAt") or ""),
        )


@dataclass
class SkipDecision:
    id: str
    system_key: str
    system_name: str
    stop_id: str
    body_name: str
    task_id: str
    genus_id: str
    species_id: str
    variant_id: str
    organism_name: str
    certainty: str
    scope: str
    reason: str
    note: str
    value_removed: int
    body_value_before: int
    body_value_after: int
    body_removed_from_route: bool
    system_removed_from_route: bool
    created_at: str
    reversed_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "systemKey": self.system_key,
            "systemName": self.system_name,
            "stopId": self.stop_id,
            "bodyName": self.body_name,
            "taskId": self.task_id,
            "genusId": self.genus_id,
            "speciesId": self.species_id,
            "variantId": self.variant_id,
            "organismName": self.organism_name,
            "certainty": self.certainty,
            "scope": self.scope,
            "reason": self.reason,
            "note": self.note,
            "valueRemoved": self.value_removed,
            "bodyValueBefore": self.body_value_before,
            "bodyValueAfter": self.body_value_after,
            "bodyRemovedFromRoute": self.body_removed_from_route,
            "systemRemovedFromRoute": self.system_removed_from_route,
            "createdAt": self.created_at,
            "reversedAt": self.reversed_at,
        }

    @classmethod
    def from_dict(cls, raw: Any) -> "SkipDecision | None":
        if not isinstance(raw, dict) or not raw.get("id"):
            return None
        return cls(
            id=str(raw.get("id")),
            system_key=str(raw.get("systemKey") or ""),
            system_name=str(raw.get("systemName") or ""),
            stop_id=str(raw.get("stopId") or ""),
            body_name=str(raw.get("bodyName") or ""),
            task_id=str(raw.get("taskId") or ""),
            genus_id=str(raw.get("genusId") or ""),
            species_id=str(raw.get("speciesId") or ""),
            variant_id=str(raw.get("variantId") or ""),
            organism_name=str(raw.get("organismName") or ""),
            certainty=str(raw.get("certainty") or "unknown"),
            scope=str(raw.get("scope") or SkipScope.TARGET_BODY),
            reason=str(raw.get("reason") or "other"),
            note=str(raw.get("note") or ""),
            value_removed=int(raw.get("valueRemoved", 0) or 0),
            body_value_before=int(raw.get("bodyValueBefore", 0) or 0),
            body_value_after=int(raw.get("bodyValueAfter", 0) or 0),
            body_removed_from_route=bool(raw.get("bodyRemovedFromRoute", False)),
            system_removed_from_route=bool(raw.get("systemRemovedFromRoute", False)),
            created_at=str(raw.get("createdAt") or ""),
            reversed_at=str(raw.get("reversedAt") or ""),
        )


@dataclass(frozen=True)
class BodyPlan:
    route_index: int
    stop_id: str
    system_key: str
    system_name: str
    body_name: str
    body_id: int | None
    sequence: int
    distance_from_arrival_ls: float | None
    biological_signals: int | None
    included_targets: int
    excluded_targets: int
    unresolved_targets: int
    completed_targets: int
    sample_current: int
    sample_total: int
    active_value: int
    active_value_min: int
    active_value_max: int
    raw_value: int
    excluded_value: int
    included: bool
    complete: bool
    skipped: bool
    manifest_completeness: str
    manifest_source: str


@dataclass(frozen=True)
class SystemPlan:
    key: str
    name: str
    system_address: int | None
    sequence: int
    bodies: tuple[BodyPlan, ...]
    active_body_count: int
    complete_body_count: int
    target_count: int
    completed_target_count: int
    active_value: int
    excluded_value: int
    raw_value: int
    manifest_completeness: str

    @property
    def active_bodies(self) -> tuple[BodyPlan, ...]:
        return tuple(body for body in self.bodies if body.included and not body.complete and not body.skipped)


@dataclass(frozen=True)
class NavigationSnapshot:
    systems: tuple[SystemPlan, ...] = ()
    by_key: dict[str, SystemPlan] = field(default_factory=dict)
    body_by_stop_id: dict[str, BodyPlan] = field(default_factory=dict)

    def system(self, key: str) -> SystemPlan | None:
        return self.by_key.get(key)

    def body(self, stop_id: str) -> BodyPlan | None:
        return self.body_by_stop_id.get(stop_id)


def system_key_for(stop: RouteStop) -> str:
    return stop.parent_system_key or (str(stop.system_address) if stop.system_address is not None else stop.system.casefold())


def _manifest_rank(value: str) -> int:
    return {
        ManifestCompleteness.SYSTEM_ONLY: 0,
        ManifestCompleteness.LIVE: 1,
        ManifestCompleteness.BODIES: 2,
        ManifestCompleteness.EXACT: 3,
    }.get(value, 0)


def _system_manifest(values: Iterable[str]) -> str:
    values = list(values)
    if not values:
        return ManifestCompleteness.SYSTEM_ONLY
    return min(values, key=_manifest_rank)


def _order_bodies(bodies: list[BodyPlan], mode: str) -> list[BodyPlan]:
    if mode == BodyOrderMode.NEAREST:
        return sorted(
            bodies,
            key=lambda body: (
                body.distance_from_arrival_ls is None,
                body.distance_from_arrival_ls if body.distance_from_arrival_ls is not None else float("inf"),
                body.sequence,
                body.route_index,
            ),
        )
    if mode == BodyOrderMode.VALUE:
        return sorted(bodies, key=lambda body: (-body.active_value_max, body.sequence, body.route_index))
    if mode == BodyOrderMode.MANUAL:
        return sorted(bodies, key=lambda body: (body.sequence, body.route_index))
    return sorted(bodies, key=lambda body: (body.sequence, body.route_index))


def build_navigation_snapshot(route: Route, projection: Any, body_order_mode: str = BodyOrderMode.ROUTE) -> NavigationSnapshot:
    grouped: dict[str, list[BodyPlan]] = {}
    system_meta: dict[str, tuple[str, int | None, int]] = {}
    body_lookup: dict[str, BodyPlan] = {}

    for index, stop in enumerate(route.stops):
        body_projection = projection.body_for(stop)
        if body_projection:
            included_targets = body_projection.included_count
            excluded_targets = body_projection.excluded_count
            unresolved_targets = body_projection.unresolved_count
            completed_targets = sum(1 for task in body_projection.tasks if task.included and task.complete)
            sample_current = sum(task.sample_count for task in body_projection.tasks if task.included)
            sample_total = sum(task.sample_target for task in body_projection.tasks if task.included)
            active_value = body_projection.values.active_exact
            active_min = body_projection.values.active_min
            active_max = body_projection.values.active_max
            raw_value = body_projection.values.raw_exact
            excluded_value = body_projection.values.excluded_exact
            included = body_projection.included_body
            complete = bool(body_projection.work_complete or stop.status == ProgressStatus.COMPLETE)
        else:
            required = [task for task in stop.tasks if task.required and task.status != TaskStatus.SKIPPED]
            included_targets = len(required)
            excluded_targets = 0
            unresolved_targets = 0
            completed_targets = sum(1 for task in required if task.complete)
            sample_current = sum(task.quantity_completed for task in required)
            sample_total = sum(task.quantity_required for task in required)
            active_value = active_min = active_max = raw_value = excluded_value = 0
            included = index in projection.active_indices
            complete = stop.status == ProgressStatus.COMPLETE

        completeness = str(stop.manifest_completeness or stop.metadata.get("manifestCompleteness") or "")
        if not completeness:
            if stop.body and stop.tasks and all(task.species or task.variant for task in stop.organic_tasks):
                completeness = ManifestCompleteness.EXACT
            elif stop.body:
                completeness = ManifestCompleteness.BODIES
            elif stop.metadata.get("discoveredDynamically"):
                completeness = ManifestCompleteness.LIVE
            else:
                completeness = ManifestCompleteness.SYSTEM_ONLY
        source = str(stop.manifest_source or stop.metadata.get("manifestSource") or route.source_format)
        sequence = int(stop.manual_order or stop.body_sequence or stop.sequence or index + 1)
        plan = BodyPlan(
            route_index=index,
            stop_id=stop.id,
            system_key=system_key_for(stop),
            system_name=stop.system,
            body_name=stop.body,
            body_id=stop.body_id,
            sequence=sequence,
            distance_from_arrival_ls=stop.distance_from_arrival_ls,
            biological_signals=stop.biological_signal_count,
            included_targets=included_targets,
            excluded_targets=excluded_targets,
            unresolved_targets=unresolved_targets,
            completed_targets=completed_targets,
            sample_current=sample_current,
            sample_total=sample_total,
            active_value=active_value,
            active_value_min=active_min,
            active_value_max=active_max,
            raw_value=raw_value,
            excluded_value=excluded_value,
            included=included,
            complete=complete,
            skipped=stop.status == ProgressStatus.SKIPPED,
            manifest_completeness=completeness,
            manifest_source=source,
        )
        grouped.setdefault(plan.system_key, []).append(plan)
        system_meta.setdefault(plan.system_key, (stop.system, stop.system_address, stop.system_sequence or stop.sequence or index + 1))
        body_lookup[stop.id] = plan

    systems: list[SystemPlan] = []
    for key, bodies in grouped.items():
        ordered = _order_bodies(bodies, body_order_mode)
        name, address, sequence = system_meta[key]
        systems.append(
            SystemPlan(
                key=key,
                name=name,
                system_address=address,
                sequence=int(sequence),
                bodies=tuple(ordered),
                active_body_count=sum(1 for body in ordered if body.included and not body.complete and not body.skipped),
                complete_body_count=sum(1 for body in ordered if body.complete),
                target_count=sum(body.included_targets for body in ordered if body.included),
                completed_target_count=sum(body.completed_targets for body in ordered if body.included),
                active_value=sum(body.active_value for body in ordered if body.included),
                excluded_value=sum(body.excluded_value for body in ordered),
                raw_value=sum(body.raw_value for body in ordered),
                manifest_completeness=_system_manifest(body.manifest_completeness for body in ordered),
            )
        )
    systems.sort(key=lambda system: (system.sequence, system.name.casefold()))
    return NavigationSnapshot(
        systems=tuple(systems),
        by_key={system.key: system for system in systems},
        body_by_stop_id=body_lookup,
    )
