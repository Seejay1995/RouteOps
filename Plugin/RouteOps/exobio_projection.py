from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from exobiology_catalog import DEFAULT_CATALOG
from exobio_taxonomy import (
    InclusionDecision,
    InclusionState,
    KnowledgeLevel,
    inclusion_decision,
    normalize_filter_ids,
    task_taxonomy,
)
from route_models import CompletionPolicy, ProgressStatus, Route, RouteStop, RouteTask, StopType, TaskStatus


@dataclass(frozen=True)
class TaskProjection:
    task_id: str
    taxonomy: Any
    decision: InclusionDecision
    knowledge_level: str
    value_exact: int | None
    value_min: int | None
    value_max: int | None
    sample_count: int
    sample_target: int
    required: bool
    complete: bool
    source: str

    @property
    def included(self) -> bool:
        return self.decision.included

    @property
    def excluded(self) -> bool:
        return self.decision.excluded

    @property
    def unresolved(self) -> bool:
        return self.decision.state == InclusionState.UNRESOLVED

    @property
    def active_exact_value(self) -> int:
        return int(self.value_exact or 0) if self.included else 0


@dataclass(frozen=True)
class BodyValueBreakdown:
    raw_exact: int = 0
    raw_min: int = 0
    raw_max: int = 0
    excluded_exact: int = 0
    excluded_min: int = 0
    excluded_max: int = 0
    active_exact: int = 0
    active_min: int = 0
    active_max: int = 0
    secured_active: int = 0
    in_progress_active: int = 0
    remaining_active: int = 0
    unknown_value_slots: int = 0


@dataclass(frozen=True)
class BodyProjection:
    stop_index: int
    stop_id: str
    tasks: tuple[TaskProjection, ...]
    included_task_ids: tuple[str, ...]
    excluded_task_ids: tuple[str, ...]
    unresolved_task_ids: tuple[str, ...]
    included_body: bool
    inclusion_state: str
    inclusion_reason: str
    unresolved_signal_count: int
    values: BodyValueBreakdown
    work_complete: bool

    @property
    def included_count(self) -> int:
        return len(self.included_task_ids)

    @property
    def excluded_count(self) -> int:
        return len(self.excluded_task_ids)

    @property
    def unresolved_count(self) -> int:
        return len(self.unresolved_task_ids) + self.unresolved_signal_count


@dataclass(frozen=True)
class RouteProjection:
    bodies: dict[str, BodyProjection] = field(default_factory=dict)
    active_indices: tuple[int, ...] = ()
    visible_indices: tuple[int, ...] = ()
    raw_exact_value: int = 0
    raw_min_value: int = 0
    raw_max_value: int = 0
    excluded_exact_value: int = 0
    excluded_min_value: int = 0
    excluded_max_value: int = 0
    active_exact_value: int = 0
    active_min_value: int = 0
    active_max_value: int = 0
    secured_active_value: int = 0
    in_progress_active_value: int = 0
    remaining_active_value: int = 0
    unknown_value_slots: int = 0

    def body_for(self, stop: RouteStop | None) -> BodyProjection | None:
        return self.bodies.get(stop.id) if stop else None

    def task_for(self, stop: RouteStop | None, task_id: str) -> TaskProjection | None:
        body = self.body_for(stop)
        if not body:
            return None
        return next((item for item in body.tasks if item.task_id == task_id), None)


def _task_value(task: RouteTask, taxonomy: Any) -> tuple[int | None, int | None, int | None]:
    if task.base_value is not None:
        exact = int(task.base_value)
        return exact, exact, exact
    if taxonomy.species_name:
        match = DEFAULT_CATALOG.resolve(taxonomy.species_name)
        if match:
            return match.base_value, match.base_value, match.base_value
    if taxonomy.genus_name:
        low, high = DEFAULT_CATALOG.value_range_for_genus(taxonomy.genus_name)
        return None, low, high
    return None, None, None


def _project_task(task: RouteTask, excluded_genus_ids: set[str]) -> TaskProjection:
    taxonomy = task_taxonomy(task)
    decision = inclusion_decision(task, excluded_genus_ids)
    if task.status == TaskStatus.SKIPPED:
        decision = InclusionDecision(InclusionState.EXCLUDED, "user-skip")
    exact, low, high = _task_value(task, taxonomy)
    source = str(task.metadata.get("source") or task.metadata.get("knowledgeSource") or "route")
    return TaskProjection(
        task_id=task.id,
        taxonomy=taxonomy,
        decision=decision,
        knowledge_level=taxonomy.knowledge_level,
        value_exact=exact,
        value_min=low,
        value_max=high,
        sample_count=min(task.quantity_completed, task.quantity_required),
        sample_target=task.quantity_required,
        required=task.required and task.status != TaskStatus.SKIPPED,
        complete=task.complete,
        source=source,
    )


def _unresolved_signal_count(stop: RouteStop, task_projections: list[TaskProjection]) -> int:
    expected = int(stop.biological_signal_count or 0)
    if expected <= 0:
        return 0
    return max(0, expected - len(task_projections))


def _body_values(tasks: list[TaskProjection], unresolved_signals: int) -> BodyValueBreakdown:
    raw_exact = raw_min = raw_max = 0
    excluded_exact = excluded_min = excluded_max = 0
    active_exact = active_min = active_max = 0
    secured = in_progress = remaining = 0
    unknown = unresolved_signals

    for task in tasks:
        if task.value_exact is not None:
            raw_exact += task.value_exact
            raw_min += task.value_exact
            raw_max += task.value_exact
        elif task.value_min is not None or task.value_max is not None:
            raw_min += int(task.value_min or 0)
            raw_max += int(task.value_max or task.value_min or 0)
        else:
            unknown += 1

        if task.excluded:
            if task.value_exact is not None:
                excluded_exact += task.value_exact
                excluded_min += task.value_exact
                excluded_max += task.value_exact
            else:
                excluded_min += int(task.value_min or 0)
                excluded_max += int(task.value_max or task.value_min or 0)
            continue

        if task.value_exact is not None:
            active_exact += task.value_exact
            active_min += task.value_exact
            active_max += task.value_exact
            if task.complete:
                secured += task.value_exact
            elif task.sample_count > 0:
                in_progress += task.value_exact
            else:
                remaining += task.value_exact
        else:
            active_min += int(task.value_min or 0)
            active_max += int(task.value_max or task.value_min or 0)

    return BodyValueBreakdown(
        raw_exact=raw_exact,
        raw_min=raw_min,
        raw_max=raw_max,
        excluded_exact=excluded_exact,
        excluded_min=excluded_min,
        excluded_max=excluded_max,
        active_exact=active_exact,
        active_min=active_min,
        active_max=active_max,
        secured_active=secured,
        in_progress_active=in_progress,
        remaining_active=remaining,
        unknown_value_slots=unknown,
    )


def _body_complete(stop: RouteStop, tasks: list[TaskProjection], unresolved_signals: int) -> bool:
    if stop.stop_type != StopType.EXOBIOLOGY:
        required = stop.required_tasks
        return bool(required) and all(task.complete for task in required)
    if stop.completion_policy == CompletionPolicy.MANUAL:
        return False
    included_required = [task for task in tasks if task.included and task.required]
    unresolved = unresolved_signals + sum(1 for task in tasks if task.unresolved and task.required)
    if unresolved > 0:
        return False
    if stop.completion_policy == CompletionPolicy.ANY_TARGET:
        return any(task.complete for task in included_required)
    if not included_required:
        return False
    if not all(task.complete for task in included_required):
        return False
    if stop.completion_policy == CompletionPolicy.ALL_SIGNALS:
        return True
    return True


def build_route_projection(route: Route) -> RouteProjection:
    excluded = normalize_filter_ids(route.settings.excluded_organism_genera)
    bodies: dict[str, BodyProjection] = {}
    active_indices: list[int] = []
    visible_indices: list[int] = []
    totals = {
        "raw_exact": 0,
        "raw_min": 0,
        "raw_max": 0,
        "excluded_exact": 0,
        "excluded_min": 0,
        "excluded_max": 0,
        "active_exact": 0,
        "active_min": 0,
        "active_max": 0,
        "secured": 0,
        "in_progress": 0,
        "remaining": 0,
        "unknown": 0,
    }

    for index, stop in enumerate(route.stops):
        if stop.stop_type != StopType.EXOBIOLOGY:
            included_body = True
            body = BodyProjection(
                stop_index=index,
                stop_id=stop.id,
                tasks=(),
                included_task_ids=(),
                excluded_task_ids=(),
                unresolved_task_ids=(),
                included_body=True,
                inclusion_state=InclusionState.INCLUDED,
                inclusion_reason="non-exobiology",
                unresolved_signal_count=0,
                values=BodyValueBreakdown(),
                work_complete=stop.work_complete,
            )
        else:
            organic = [task for task in stop.tasks if task.is_organic or bool(task.metadata.get("unresolvedSlot", False))]
            task_projections = [_project_task(task, excluded) for task in organic]
            unresolved_signals = _unresolved_signal_count(stop, task_projections)
            included = [item for item in task_projections if item.included]
            excluded_tasks = [item for item in task_projections if item.excluded]
            unresolved = [item for item in task_projections if item.unresolved]

            no_biology_known = not task_projections and stop.biological_signal_count is None
            has_active_work = bool(included or unresolved or unresolved_signals or no_biology_known)
            manual_body_override = str(stop.metadata.get("manualInclusion", "default") or "default").casefold()
            if manual_body_override == "include":
                has_active_work = True
                body_state = InclusionState.MANUAL_INCLUDED
                reason = "manual-include"
            elif manual_body_override == "exclude":
                has_active_work = False
                body_state = InclusionState.MANUAL_EXCLUDED
                reason = "manual-exclude"
            elif has_active_work:
                body_state = InclusionState.UNRESOLVED if (unresolved or unresolved_signals or no_biology_known) else InclusionState.INCLUDED
                reason = "included-work" if body_state == InclusionState.INCLUDED else "unresolved-work"
            else:
                body_state = InclusionState.EXCLUDED
                reason = "all-organisms-filtered"

            values = _body_values(task_projections, unresolved_signals)
            body = BodyProjection(
                stop_index=index,
                stop_id=stop.id,
                tasks=tuple(task_projections),
                included_task_ids=tuple(item.task_id for item in included),
                excluded_task_ids=tuple(item.task_id for item in excluded_tasks),
                unresolved_task_ids=tuple(item.task_id for item in unresolved),
                included_body=has_active_work,
                inclusion_state=body_state,
                inclusion_reason=reason,
                unresolved_signal_count=unresolved_signals,
                values=values,
                work_complete=_body_complete(stop, task_projections, unresolved_signals),
            )
            for key, value in (
                ("raw_exact", values.raw_exact),
                ("raw_min", values.raw_min),
                ("raw_max", values.raw_max),
                ("excluded_exact", values.excluded_exact),
                ("excluded_min", values.excluded_min),
                ("excluded_max", values.excluded_max),
                ("active_exact", values.active_exact),
                ("active_min", values.active_min),
                ("active_max", values.active_max),
                ("secured", values.secured_active),
                ("in_progress", values.in_progress_active),
                ("remaining", values.remaining_active),
                ("unknown", values.unknown_value_slots),
            ):
                totals[key] += value

        bodies[stop.id] = body
        if body.included_body:
            active_indices.append(index)
        if route.settings.route_view_mode == "all" or body.included_body:
            visible_indices.append(index)

    return RouteProjection(
        bodies=bodies,
        active_indices=tuple(active_indices),
        visible_indices=tuple(visible_indices),
        raw_exact_value=totals["raw_exact"],
        raw_min_value=totals["raw_min"],
        raw_max_value=totals["raw_max"],
        excluded_exact_value=totals["excluded_exact"],
        excluded_min_value=totals["excluded_min"],
        excluded_max_value=totals["excluded_max"],
        active_exact_value=totals["active_exact"],
        active_min_value=totals["active_min"],
        active_max_value=totals["active_max"],
        secured_active_value=totals["secured"],
        in_progress_active_value=totals["in_progress"],
        remaining_active_value=totals["remaining"],
        unknown_value_slots=totals["unknown"],
    )
