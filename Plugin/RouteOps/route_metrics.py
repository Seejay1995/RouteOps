from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from route_models import ProgressStatus, Route, TaskStatus

if TYPE_CHECKING:
    from exobio_projection import RouteProjection


@dataclass
class RouteMetrics:
    total_stops: int
    complete_stops: int
    skipped_stops: int
    remaining_stops: int
    required_tasks: int
    completed_tasks: int
    estimated_value: int
    delivered_quantity: int
    collected_materials: int
    planned_base_value: int = 0
    secured_base_value: int = 0
    remaining_base_value: int = 0
    potential_first_logged_value: int = 0
    actual_sold_value: int = 0
    actual_sale_bonus: int = 0
    unknown_value_organisms: int = 0
    unallocated_sale_entries: int = 0
    completed_organisms: int = 0
    total_organisms: int = 0
    completed_samples: int = 0
    total_samples: int = 0
    raw_base_value: int = 0
    raw_min_value: int = 0
    raw_max_value: int = 0
    excluded_base_value: int = 0
    excluded_min_value: int = 0
    excluded_max_value: int = 0
    active_base_value: int = 0
    active_min_value: int = 0
    active_max_value: int = 0
    in_progress_base_value: int = 0
    filtered_stops: int = 0


def calculate_route_metrics(route: Route, projection: "RouteProjection | None" = None) -> RouteMetrics:
    if projection is None:
        from exobio_projection import build_route_projection

        projection = build_route_projection(route)

    active_indices = set(projection.active_indices)
    complete_stops = sum(
        1
        for index, stop in enumerate(route.stops)
        if index in active_indices and stop.status == ProgressStatus.COMPLETE
    )
    skipped_stops = sum(
        1
        for index, stop in enumerate(route.stops)
        if index in active_indices and stop.status == ProgressStatus.SKIPPED
    )
    filtered_stops = sum(1 for index in range(len(route.stops)) if index not in active_indices)
    required_tasks = 0
    completed_tasks = 0
    estimated_value = 0
    delivered_quantity = 0
    collected_materials = 0
    actual_value = 0
    actual_bonus = 0
    completed_organisms = 0
    total_organisms = 0
    completed_samples = 0
    total_samples = 0

    for stop in route.stops:
        body = projection.body_for(stop)
        projected_tasks = {item.task_id: item for item in body.tasks} if body else {}
        for task in stop.tasks:
            projected = projected_tasks.get(task.id)
            if task.is_organic:
                actual_value += int(task.actual_value or 0)
                actual_bonus += int(task.actual_bonus or 0)
                if not projected or not projected.included:
                    continue
                total_organisms += 1
                completed_samples += min(task.quantity_completed, task.quantity_required)
                total_samples += task.quantity_required
                if task.complete:
                    completed_organisms += 1
                if projected.required:
                    required_tasks += 1
                    if task.complete:
                        completed_tasks += 1
                continue

            if task.required:
                required_tasks += 1
                if task.status == TaskStatus.COMPLETE or task.complete:
                    completed_tasks += 1
            kind = task.task_type.casefold()
            try:
                estimated_value += int(task.metadata.get("expectedProfit", task.metadata.get("estimatedValue", 0)) or 0)
            except (TypeError, ValueError):
                pass
            if kind in {"delivercommodity", "sellcommodity", "unloadcommodity"}:
                delivered_quantity += task.quantity_completed
            if kind in {"collectmaterial", "reachinventoryquantity", "material"}:
                collected_materials += task.quantity_completed

    ledger = route.metadata.get("salesLedger", [])
    unallocated = 0
    if isinstance(ledger, list):
        for item in ledger:
            if not isinstance(item, dict) or bool(item.get("allocated", False)):
                continue
            unallocated += 1
            try:
                actual_value += int(item.get("value", 0) or 0)
                actual_bonus += int(item.get("bonus", 0) or 0)
            except (TypeError, ValueError):
                continue

    active_total = len(active_indices)
    estimated_value += projection.active_exact_value
    return RouteMetrics(
        total_stops=active_total,
        complete_stops=complete_stops,
        skipped_stops=skipped_stops,
        remaining_stops=max(0, active_total - complete_stops - skipped_stops),
        required_tasks=required_tasks,
        completed_tasks=completed_tasks,
        estimated_value=estimated_value,
        delivered_quantity=delivered_quantity,
        collected_materials=collected_materials,
        planned_base_value=projection.active_exact_value,
        secured_base_value=projection.secured_active_value,
        remaining_base_value=projection.remaining_active_value,
        potential_first_logged_value=projection.active_max_value * 5,
        actual_sold_value=actual_value,
        actual_sale_bonus=actual_bonus,
        unknown_value_organisms=projection.unknown_value_slots,
        unallocated_sale_entries=unallocated,
        completed_organisms=completed_organisms,
        total_organisms=total_organisms,
        completed_samples=completed_samples,
        total_samples=total_samples,
        raw_base_value=projection.raw_exact_value,
        raw_min_value=projection.raw_min_value,
        raw_max_value=projection.raw_max_value,
        excluded_base_value=projection.excluded_exact_value,
        excluded_min_value=projection.excluded_min_value,
        excluded_max_value=projection.excluded_max_value,
        active_base_value=projection.active_exact_value,
        active_min_value=projection.active_min_value,
        active_max_value=projection.active_max_value,
        in_progress_base_value=projection.in_progress_active_value,
        filtered_stops=filtered_stops,
    )
