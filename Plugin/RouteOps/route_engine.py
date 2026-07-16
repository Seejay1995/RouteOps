from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from typing import Any

from exobiology_catalog import DEFAULT_CATALOG, normalize_organic_name
from exobio_projection import BodyProjection, RouteProjection, build_route_projection
from exobio_taxonomy import (
    InclusionState,
    KnowledgeLevel,
    canonical_genus_id,
    display_genus_name,
    task_taxonomy,
)
from journal_normalizer import JournalEvent, OrganicSaleRecord, normalize_journal_event
from navigation_model import (
    BodyOrderMode,
    DIFFICULTIES,
    GuidanceMode,
    NavigationSnapshot,
    NavigationTarget,
    NavigationTargetState,
    NavigationTargetType,
    SKIP_REASON_LABELS,
    SKIP_REASONS,
    SkipDecision,
    SkipScope,
    build_navigation_snapshot,
    system_key_for,
)
from route_metrics import RouteMetrics, calculate_route_metrics
from route_models import (
    CompletionPolicy,
    OperationPhase,
    ProgressStatus,
    Route,
    RouteMode,
    RouteStop,
    RouteTask,
    StopType,
    TaskStatus,
)


_FINAL_STOP_STATES = {ProgressStatus.COMPLETE, ProgressStatus.SKIPPED}
_ORGANIC_TASK_TYPES = {"scanorganic", "scanspecies", "samplespecies"}


class RouteEngine:
    def __init__(self, route: Route, auto_advance: bool | None = None) -> None:
        self.route = route
        self.current_index = 0
        self.selected_index = 0
        self.selected_task_id = ""
        self.paused = False
        self.auto_advance = route.settings.auto_advance if auto_advance is None else auto_advance
        self.current_location: dict[str, Any] = {
            "system": "",
            "systemAddress": None,
            "body": "",
            "bodyId": None,
            "station": "",
            "settlement": "",
        }
        ledger = route.metadata.get("salesLedger", [])
        self.sales_ledger: list[dict[str, Any]] = list(ledger) if isinstance(ledger, list) else []
        self.last_event_ids: list[str] = []
        self.recent_exobio_events: list[dict[str, Any]] = []
        self.guidance_mode = route.settings.guidance_mode if route.settings.guidance_mode in GuidanceMode.ALL else (GuidanceMode.AUTO_ADVANCE if self.auto_advance else GuidanceMode.CONFIRM)
        self.auto_advance = self.guidance_mode == GuidanceMode.AUTO_ADVANCE
        self.body_order_mode = route.settings.body_order_mode if route.settings.body_order_mode in BodyOrderMode.ALL else BodyOrderMode.ROUTE
        self.selected_system_key = ""
        self.navigation_target = NavigationTarget()
        self.pending_skip: dict[str, Any] | None = None
        raw_decisions = route.metadata.get("skipDecisions", [])
        self.skip_decisions: list[SkipDecision] = [
            decision for decision in (SkipDecision.from_dict(item) for item in raw_decisions if isinstance(raw_decisions, list)) if decision is not None
        ]
        self._repair_legacy_filter_mutations()
        self._refresh_taxonomy()
        self.projection: RouteProjection = build_route_projection(self.route)
        self.navigation: NavigationSnapshot = build_navigation_snapshot(self.route, self.projection, self.body_order_mode)
        unfinished = self._active_unfinished_indices()
        if self.route.stops and (0 not in self.projection.active_indices or self.route.stops[0].status in _FINAL_STOP_STATES):
            self.current_index = unfinished[0] if unfinished else len(self.route.stops)
            self.selected_index = min(self.current_index, max(0, len(self.route.stops) - 1))
        self._select_current()
        self._ensure_selected_task()
        if self.current_stop:
            self.selected_system_key = system_key_for(self.current_stop)
        elif self.navigation.systems:
            self.selected_system_key = self.navigation.systems[0].key
        self._set_navigation_target_for_current(source="route-order")

    @property
    def complete(self) -> bool:
        return self.current_index >= len(self.route.stops) or not self._active_unfinished_indices()

    @property
    def current_stop(self) -> RouteStop | None:
        if self.current_index >= len(self.route.stops):
            return None
        if self.current_index not in self.projection.active_indices:
            return None
        stop = self.route.stops[self.current_index]
        return None if stop.status in _FINAL_STOP_STATES else stop

    @property
    def selected_stop(self) -> RouteStop | None:
        if 0 <= self.selected_index < len(self.route.stops):
            return self.route.stops[self.selected_index]
        return self.current_stop

    def body_projection(self, stop: RouteStop | None = None) -> BodyProjection | None:
        return self.projection.body_for(stop or self.selected_stop)

    def task_projection(self, task: RouteTask | None = None, stop: RouteStop | None = None):
        selected_stop = stop or self.selected_stop
        selected_task = task or self.selected_task
        if not selected_stop or not selected_task:
            return None
        return self.projection.task_for(selected_stop, selected_task.id)

    def is_stop_filtered(self, stop: RouteStop) -> bool:
        body = self.projection.body_for(stop)
        return bool(body and not body.included_body)

    @property
    def visible_stop_indices(self) -> list[int]:
        return list(self.projection.visible_indices)

    @property
    def visible_stops(self) -> list[RouteStop]:
        return [self.route.stops[index] for index in self.visible_stop_indices]

    @property
    def system_plans(self):
        return list(self.navigation.systems)

    @property
    def selected_system(self):
        system = self.navigation.system(self.selected_system_key)
        if system:
            return system
        if self.current_stop:
            return self.navigation.system(system_key_for(self.current_stop))
        return self.navigation.systems[0] if self.navigation.systems else None

    @property
    def selected_system_body_plans(self):
        system = self.selected_system
        if not system:
            return []
        if self.route.settings.route_view_mode == "all":
            return list(system.bodies)
        return [body for body in system.bodies if body.included]

    @property
    def current_system(self):
        if self.current_stop:
            return self.navigation.system(system_key_for(self.current_stop))
        return None

    def select_system(self, visible_index: int) -> list[dict[str, Any]]:
        systems = self.system_plans
        if not systems:
            return []
        visible_index = max(0, min(int(visible_index), len(systems) - 1))
        system = systems[visible_index]
        self.selected_system_key = system.key
        bodies = self.selected_system_body_plans
        if bodies and not any(body.route_index == self.selected_index for body in bodies):
            self.selected_index = bodies[0].route_index
            self.selected_task_id = ""
            self._ensure_selected_task()
        return [{
            "type": "system_selected",
            "system": system.name,
            "bodies": len(system.bodies),
            "activeBodies": system.active_body_count,
        }]

    def select_system_body(self, visible_index: int) -> list[dict[str, Any]]:
        bodies = self.selected_system_body_plans
        if not bodies:
            return []
        visible_index = max(0, min(int(visible_index), len(bodies) - 1))
        body = bodies[visible_index]
        self.selected_index = body.route_index
        self.selected_task_id = ""
        self._ensure_selected_task()
        stop = self.selected_stop
        return [{
            "type": "body_inspected",
            "system": stop.system if stop else body.system_name,
            "body": stop.body if stop else body.body_name,
        }]

    def select_current_system(self) -> None:
        if self.current_stop:
            self.selected_system_key = system_key_for(self.current_stop)

    def cycle_guidance_mode(self) -> list[dict[str, Any]]:
        current = GuidanceMode.ALL.index(self.guidance_mode) if self.guidance_mode in GuidanceMode.ALL else 0
        self.guidance_mode = GuidanceMode.ALL[(current + 1) % len(GuidanceMode.ALL)]
        self.route.settings.guidance_mode = self.guidance_mode
        self.auto_advance = self.guidance_mode == GuidanceMode.AUTO_ADVANCE
        return [{"type": "message", "message": f"Guidance mode: {self.guidance_mode}."}]

    def cycle_body_order_mode(self) -> list[dict[str, Any]]:
        current = BodyOrderMode.ALL.index(self.body_order_mode) if self.body_order_mode in BodyOrderMode.ALL else 0
        self.body_order_mode = BodyOrderMode.ALL[(current + 1) % len(BodyOrderMode.ALL)]
        self.route.settings.body_order_mode = self.body_order_mode
        self.navigation = build_navigation_snapshot(self.route, self.projection, self.body_order_mode)
        return [{"type": "message", "message": f"Body order: {self.body_order_mode}."}]

    def cycle_skip_reason(self) -> list[dict[str, Any]]:
        current = self.route.settings.default_skip_reason
        index = SKIP_REASONS.index(current) if current in SKIP_REASONS else 0
        self.route.settings.default_skip_reason = SKIP_REASONS[(index + 1) % len(SKIP_REASONS)]
        return [{
            "type": "message",
            "message": f"Skip reason: {SKIP_REASON_LABELS[self.route.settings.default_skip_reason]}.",
        }]

    def cycle_selected_difficulty(self) -> list[dict[str, Any]]:
        task = self.selected_task
        if not task:
            return [{"type": "message", "message": "No organism is selected."}]
        current = task.search_difficulty if task.search_difficulty in DIFFICULTIES else "unknown"
        task.search_difficulty = DIFFICULTIES[(DIFFICULTIES.index(current) + 1) % len(DIFFICULTIES)]
        return [{
            "type": "message",
            "message": f"{task.display_organism or task.label} difficulty: {task.search_difficulty}.",
        }]

    def set_selected_difficulty(self, value: str) -> list[dict[str, Any]]:
        task = self.selected_task
        if not task:
            return [{"type": "message", "message": "No organism is selected."}]
        if value not in DIFFICULTIES:
            return [{"type": "message", "message": f"Unknown difficulty: {value}."}]
        task.search_difficulty = value
        return [{
            "type": "message",
            "message": f"{task.display_organism or task.label} difficulty: {value}.",
        }]

    def set_default_skip_reason(self, value: str) -> list[dict[str, Any]]:
        if value not in SKIP_REASONS:
            return [{"type": "message", "message": f"Unknown skip reason: {value}."}]
        self.route.settings.default_skip_reason = value
        return [{
            "type": "message",
            "message": f"Skip reason: {SKIP_REASON_LABELS[value]}.",
        }]

    def visible_tasks(self, stop: RouteStop | None = None) -> list[RouteTask]:
        stop = stop or self.selected_stop
        if not stop:
            return []
        body = self.projection.body_for(stop)
        if not body or stop.stop_type != StopType.EXOBIOLOGY:
            return list(stop.tasks)
        by_id = {item.task_id: item for item in body.tasks}
        result: list[RouteTask] = []
        for task in stop.tasks:
            projected = by_id.get(task.id)
            if projected and projected.excluded and not self.route.settings.show_excluded_organisms:
                continue
            result.append(task)
        return result

    @property
    def selected_task(self) -> RouteTask | None:
        visible = self.visible_tasks()
        if self.selected_task_id:
            task = next((item for item in visible if item.id == self.selected_task_id), None)
            if task:
                return task
        return visible[0] if visible else None

    @property
    def next_stop(self) -> RouteStop | None:
        unfinished = self._active_unfinished_indices()
        after = [index for index in unfinished if index > self.current_index]
        target = min(after) if after else (min(unfinished) if unfinished else None)
        return self.route.stops[target] if target is not None else None

    def _active_unfinished_indices(self) -> list[int]:
        return [
            index
            for index in self.projection.active_indices
            if self.route.stops[index].status not in _FINAL_STOP_STATES
        ]

    def _rebuild_projection(self, repair_current: bool = True) -> None:
        self._refresh_taxonomy()
        self.projection = build_route_projection(self.route)
        self.navigation = build_navigation_snapshot(self.route, self.projection, self.body_order_mode)
        if not repair_current:
            return
        unfinished = self._active_unfinished_indices()
        if self.current_index not in unfinished:
            self.current_index = unfinished[0] if unfinished else len(self.route.stops)
        if self.route.settings.route_view_mode != "all" and self.selected_index not in self.projection.visible_indices:
            self.selected_index = self.current_index if self.current_index < len(self.route.stops) else (self.projection.visible_indices[0] if self.projection.visible_indices else 0)
        self._select_current()
        self._ensure_selected_task()
        if self.current_stop:
            self.selected_system_key = self.selected_system_key or system_key_for(self.current_stop)
        elif self.navigation.systems and not self.selected_system_key:
            self.selected_system_key = self.navigation.systems[0].key
        self._set_navigation_target_for_current(source="projection-rebuild")

    def _repair_legacy_filter_mutations(self) -> None:
        """Undo v0.3 filter mutations before building the non-destructive projection."""
        for stop in self.route.stops:
            if bool(stop.metadata.get("filteredOutByGenus", False)):
                previous_status = stop.metadata.pop("filterPreviousStatus", ProgressStatus.PENDING)
                previous_phase = stop.metadata.pop("filterPreviousPhase", OperationPhase.EN_ROUTE)
                stop.status = str(previous_status)
                stop.operation_phase = str(previous_phase)
                stop.metadata.pop("filteredOutByGenus", None)
            for task in stop.tasks:
                if not bool(task.metadata.get("filteredOut", False)):
                    continue
                previous_status = task.metadata.pop("filterPreviousStatus", None)
                previous_required = task.metadata.pop("filterPreviousRequired", None)
                if previous_status:
                    task.status = str(previous_status)
                elif task.quantity_completed >= task.quantity_required:
                    task.status = TaskStatus.COMPLETE
                elif task.quantity_completed > 0:
                    task.status = TaskStatus.IN_PROGRESS
                else:
                    task.status = TaskStatus.PENDING
                if previous_required is not None:
                    task.required = bool(previous_required)
                task.metadata.pop("filteredOut", None)

    def _refresh_taxonomy(self) -> None:
        for stop in self.route.stops:
            for task in stop.tasks:
                if not (task.is_organic or bool(task.metadata.get("unresolvedSlot", False))):
                    continue
                resolution = task_taxonomy(task)
                task.genus_id = resolution.genus_id
                task.species_id = resolution.species_id
                task.variant_id = resolution.variant_id
                task.knowledge_level = resolution.knowledge_level
                if resolution.genus_name and not task.genus:
                    task.genus = resolution.genus_name
                if resolution.species_name and not task.species:
                    task.species = resolution.species_name
                task.metadata["taxonomyConfidence"] = resolution.confidence
                task.metadata["taxonomyMatchedFrom"] = resolution.matched_from
                task.metadata["canonicalGenusId"] = resolution.genus_id

    def _select_current(self) -> None:
        for index, stop in enumerate(self.route.stops):
            if index == self.current_index and index < len(self.route.stops):
                if stop.status not in _FINAL_STOP_STATES:
                    stop.status = ProgressStatus.CURRENT
            elif stop.status == ProgressStatus.CURRENT:
                stop.status = ProgressStatus.PENDING
        if self.complete:
            self.selected_index = min(self.selected_index, max(0, len(self.route.stops) - 1))
        else:
            self.selected_index = max(0, min(self.selected_index, len(self.route.stops) - 1))

    def _ensure_selected_task(self) -> None:
        stop = self.selected_stop
        if not stop or not stop.tasks:
            self.selected_task_id = ""
            return
        visible = self.visible_tasks(stop)
        if not visible:
            self.selected_task_id = ""
            return
        if not any(task.id == self.selected_task_id for task in visible):
            incomplete = next((task for task in visible if not task.complete and task.status != TaskStatus.SKIPPED), None)
            self.selected_task_id = (incomplete or visible[0]).id

    def route_metrics(self) -> RouteMetrics:
        self.route.metadata["salesLedger"] = list(self.sales_ledger)
        self._rebuild_projection(repair_current=False)
        return calculate_route_metrics(self.route, self.projection)

    @property
    def exobiology_mode_active(self) -> bool:
        return self.route.route_type == RouteMode.EXOBIOLOGY or any(
            stop.stop_type == StopType.EXOBIOLOGY for stop in self.route.stops
        )

    def enable_exobiology_mode(self) -> list[dict[str, Any]]:
        self.route.metadata["forceExobiologyMode"] = True
        self.route.metadata.setdefault("originalRouteType", self.route.route_type)
        self.route.route_type = RouteMode.EXOBIOLOGY
        converted = 0
        reset = 0
        for stop in self.route.stops:
            can_convert = (
                stop.stop_type == StopType.WAYPOINT
                and not stop.tasks
                and not stop.station
                and not stop.settlement
            )
            if can_convert:
                stop.metadata.setdefault("originalStopType", stop.stop_type)
                stop.metadata.setdefault("originalAutoCompleteOnArrival", stop.auto_complete_on_arrival)
                stop.stop_type = StopType.EXOBIOLOGY
                stop.auto_complete_on_arrival = False
                stop.completion_policy = CompletionPolicy.MANUAL
                stop.metadata["systemPlaceholder"] = not bool(stop.body)
                stop.metadata["dynamicBodyDiscovery"] = True
                converted += 1
            if stop.stop_type == StopType.EXOBIOLOGY:
                stop.auto_complete_on_arrival = False
                if not stop.body:
                    stop.metadata["systemPlaceholder"] = True
                    stop.metadata["dynamicBodyDiscovery"] = True
                if self._false_arrival_completion(stop):
                    stop.status = ProgressStatus.PENDING
                    stop.operation_phase = OperationPhase.IN_SYSTEM if stop.arrived else OperationPhase.EN_ROUTE
                    stop.metadata.pop("completionSource", None)
                    reset += 1
        self._rebuild_projection(repair_current=True)
        self.selected_index = min(self.current_index, max(0, len(self.route.stops) - 1))
        self.selected_task_id = ""
        self._select_current()
        self._ensure_selected_task()
        return [{
            "type": "message",
            "message": f"Exobiology mode enabled. {converted} system stops converted; {reset} false arrival completions reopened.",
        }]

    def is_genus_excluded(self, genus: str) -> bool:
        key = canonical_genus_id(genus)
        return bool(key) and key in {
            canonical_genus_id(item)
            for item in self.route.settings.excluded_organism_genera
            if canonical_genus_id(item)
        }

    def toggle_genus_filter(self, genus: str) -> list[dict[str, Any]]:
        return self.set_genus_excluded(genus, not self.is_genus_excluded(genus))

    def set_genus_excluded(self, genus: str, excluded: bool) -> list[dict[str, Any]]:
        genus_id = canonical_genus_id(genus) or normalize_organic_name(genus)
        existing = [
            item
            for item in self.route.settings.excluded_organism_genera
            if (canonical_genus_id(item) or normalize_organic_name(item)) != genus_id
        ]
        if excluded:
            existing.append(display_genus_name(genus_id, genus))
        self.route.settings.excluded_organism_genera = existing
        previous_current = self.current_index
        self._rebuild_projection(repair_current=True)
        filtered_tasks = sum(body.excluded_count for body in self.projection.bodies.values())
        filtered_bodies = sum(1 for body in self.projection.bodies.values() if not body.included_body)
        state = "excluded" if excluded else "included"
        action = {
            "type": "message",
            "message": (
                f"{display_genus_name(genus_id, genus)} is now {state}. "
                f"Excluded organisms: {filtered_tasks}; excluded bodies: {filtered_bodies}. "
                "Raw scan progress is preserved and route values were recalculated."
            ),
        }
        actions = [action]
        if previous_current != self.current_index and self.current_stop:
            actions.append({
                "type": "advanced",
                "system": self.current_stop.system,
                "body": self.current_stop.body,
            })
        return actions

    def toggle_show_excluded(self) -> list[dict[str, Any]]:
        self.route.settings.show_excluded_organisms = not self.route.settings.show_excluded_organisms
        self._rebuild_projection(repair_current=False)
        self._ensure_selected_task()
        state = "shown" if self.route.settings.show_excluded_organisms else "hidden"
        return [{"type": "message", "message": f"Excluded organisms are now {state} in the species workspace."}]

    def toggle_route_view(self) -> list[dict[str, Any]]:
        self.route.settings.route_view_mode = "all" if self.route.settings.route_view_mode != "all" else "active"
        self._rebuild_projection(repair_current=False)
        mode = "All Bodies" if self.route.settings.route_view_mode == "all" else "Active Bodies"
        return [{"type": "message", "message": f"Route view: {mode}. Navigation still uses active bodies only."}]

    def set_selected_task_inclusion(self, mode: str) -> list[dict[str, Any]]:
        task = self.selected_task
        if not task:
            return [{"type": "message", "message": "No organism is selected."}]
        mode = mode.casefold()
        if mode not in {"default", "include", "exclude"}:
            mode = "default"
        task.manual_inclusion = mode
        self._rebuild_projection(repair_current=True)
        label = task.display_organism or task.label
        wording = {"default": "uses route filters", "include": "is manually included", "exclude": "is manually excluded"}[mode]
        return [{"type": "message", "message": f"{label} {wording}. Body and route values were recalculated."}]

    def set_selected_body_inclusion(self, mode: str) -> list[dict[str, Any]]:
        stop = self.selected_stop
        if not stop:
            return [{"type": "message", "message": "No body is selected."}]
        mode = mode.casefold()
        stop.metadata["manualInclusion"] = mode if mode in {"include", "exclude"} else "default"
        self._rebuild_projection(repair_current=True)
        wording = {"default": "uses route filters", "include": "is manually included", "exclude": "is manually excluded"}.get(mode, "uses route filters")
        return [{"type": "message", "message": f"{stop.body or stop.system} {wording}."}]

    @staticmethod
    def _false_arrival_completion(stop: RouteStop) -> bool:
        if stop.stop_type != StopType.EXOBIOLOGY or stop.status != ProgressStatus.COMPLETE:
            return False
        if str(stop.metadata.get("completionSource", "")) in {"manual", "journal"}:
            return False
        return not any(task.is_organic and task.complete for task in stop.tasks)

    def stop_progress(self, stop: RouteStop) -> tuple[int, int]:
        required = stop.required_tasks
        if required:
            return sum(1 for task in required if task.complete), len(required)
        return (1, 1) if stop.status == ProgressStatus.COMPLETE else (0, 0)

    def sample_progress(self, stop: RouteStop, include_excluded: bool = False) -> tuple[int, int]:
        body = self.projection.body_for(stop)
        if not body:
            return (0, 0)
        tasks = list(body.tasks) if include_excluded else [item for item in body.tasks if item.included]
        if not tasks:
            return (0, 0)
        return (
            sum(min(item.sample_count, item.sample_target) for item in tasks),
            sum(item.sample_target for item in tasks),
        )

    def _already_in_system(self, stop: RouteStop) -> bool:
        location_system = str(self.current_location.get("system") or "")
        address = self.current_location.get("systemAddress")
        if stop.system_address is not None and address is not None:
            try:
                return int(address) == int(stop.system_address)
            except (TypeError, ValueError):
                pass
        return _same_name(location_system, stop.system)

    def _set_navigation_target_for_current(self, source: str = "auto-selected") -> None:
        stop = self.current_stop
        if not stop:
            self.navigation_target = NavigationTarget()
            return
        target_type = NavigationTargetType.SYSTEM
        body_name = ""
        if stop.stop_type == StopType.EXOBIOLOGY and stop.body and self._already_in_system(stop):
            target_type = NavigationTargetType.BODY
            body_name = stop.body
        previous = self.navigation_target
        same_identity = previous.stop_id == stop.id and previous.target_type == target_type
        self.navigation_target = NavigationTarget(
            target_type=target_type,
            system_key=system_key_for(stop),
            system_name=stop.system,
            stop_id=stop.id,
            body_name=body_name,
            source=source,
            state=previous.state if same_identity else NavigationTargetState.SELECTED,
            copied_at=previous.copied_at if same_identity else "",
            reached_at=previous.reached_at if same_identity else "",
        )

    def mark_navigation_copied(self) -> None:
        if not self.navigation_target.text:
            return
        self.navigation_target.state = NavigationTargetState.COPIED
        self.navigation_target.copied_at = datetime.now(timezone.utc).isoformat()

    def navigation_text(self) -> str:
        self._set_navigation_target_for_current(source=self.navigation_target.source or "route-order")
        return self.navigation_target.text

    def navigation_label(self) -> str:
        if self.navigation_target.target_type == NavigationTargetType.BODY:
            return "Body"
        if self.navigation_target.target_type == NavigationTargetType.SYSTEM:
            return "System"
        return "Target"

    def _navigation_order_indices(self) -> list[int]:
        result: list[int] = []
        for system in self.navigation.systems:
            for body in system.bodies:
                stop = self.route.stops[body.route_index]
                if not body.included or stop.status in _FINAL_STOP_STATES:
                    continue
                result.append(body.route_index)
        return result

    def choose_selected_body(self) -> list[dict[str, Any]]:
        stop = self.selected_stop
        if not stop:
            return [{"type": "message", "message": "No body is selected."}]
        if self.selected_index not in self.projection.active_indices:
            return [{"type": "message", "message": f"{stop.body or stop.system} is not in active navigation."}]
        target = self._activate_index(self.selected_index)
        if not target:
            return []
        self.selected_system_key = system_key_for(target)
        self._set_navigation_target_for_current(source="user-selected")
        return [{
            "type": "navigation_target",
            "system": target.system,
            "body": target.body,
            "targetType": self.navigation_target.target_type,
            "text": self.navigation_target.text,
        }]

    def next_navigation_target(self) -> list[dict[str, Any]]:
        order = self._navigation_order_indices()
        if not order:
            return []
        if self.current_index in order:
            target_pos = (order.index(self.current_index) + 1) % len(order)
        else:
            target_pos = 0
        target = self._activate_index(order[target_pos])
        if not target:
            return []
        self.selected_system_key = system_key_for(target)
        self._set_navigation_target_for_current(source="user-next")
        return [{
            "type": "navigation_target",
            "system": target.system,
            "body": target.body,
            "targetType": self.navigation_target.target_type,
            "text": self.navigation_target.text,
        }]

    def previous_navigation_target(self) -> list[dict[str, Any]]:
        order = self._navigation_order_indices()
        if not order:
            return []
        if self.current_index in order:
            target_pos = (order.index(self.current_index) - 1) % len(order)
        else:
            target_pos = 0
        target = self._activate_index(order[target_pos])
        if not target:
            return []
        self.selected_system_key = system_key_for(target)
        self._set_navigation_target_for_current(source="user-previous")
        return [{
            "type": "navigation_target",
            "system": target.system,
            "body": target.body,
            "targetType": self.navigation_target.target_type,
            "text": self.navigation_target.text,
        }]

    def copy_system(self, selected: bool = False) -> str:
        stop = self.selected_stop if selected else self.current_stop
        return stop.system if stop else ""

    def copy_secondary(self, selected: bool = False) -> str:
        stop = self.selected_stop if selected else self.current_stop
        return stop.secondary_target if stop else ""

    def copy_text(self, mode: str = "smart-target") -> str:
        mode = mode.casefold()
        if mode in {"next-system", "system-only"}:
            stop = self.current_stop
            return stop.system if stop else ""
        return self.navigation_text()

    def select_stop(self, index: int) -> list[dict[str, Any]]:
        if not self.route.stops:
            return []
        self.selected_index = max(0, min(int(index), len(self.route.stops) - 1))
        self.selected_task_id = ""
        self._ensure_selected_task()
        stop = self.selected_stop
        return [
            {
                "type": "row_selected",
                "index": self.selected_index,
                "system": stop.system if stop else "",
                "body": stop.body if stop else "",
            }
        ]

    def select_visible_stop(self, visible_index: int) -> list[dict[str, Any]]:
        indices = self.visible_stop_indices
        if not indices:
            return []
        visible_index = max(0, min(int(visible_index), len(indices) - 1))
        return self.select_stop(indices[visible_index])

    def select_task(self, index: int) -> list[dict[str, Any]]:
        visible = self.visible_tasks()
        if not visible:
            return []
        index = max(0, min(int(index), len(visible) - 1))
        task = visible[index]
        self.selected_task_id = task.id
        return [{"type": "task_selected", "task": task.id, "label": task.label}]

    def jump_to(self, index: int | None = None) -> list[dict[str, Any]]:
        if not self.route.stops:
            return []
        target = self.selected_index if index is None else int(index)
        target = max(0, min(target, len(self.route.stops) - 1))
        if target not in self.projection.active_indices:
            selected = self.route.stops[target]
            return [{"type": "message", "message": f"{selected.body or selected.system} is excluded from active navigation. Include the body or change filters first."}]
        target_stop = self._activate_index(target)
        if not target_stop:
            return []
        copy_target = self.copy_text("smart-target")
        return [
            {"type": "jumped", "system": target_stop.system, "body": target_stop.body},
            {"type": "copy", "text": copy_target, "targetType": "body" if copy_target == target_stop.body else "system"},
        ]

    def reopen_stop(self, index: int | None = None) -> list[dict[str, Any]]:
        if not self.route.stops:
            return []
        target = self.selected_index if index is None else int(index)
        target = max(0, min(target, len(self.route.stops) - 1))
        stop = self.route.stops[target]
        stop.status = ProgressStatus.PENDING
        if stop.operation_phase in {OperationPhase.COMPLETE, OperationPhase.SKIPPED}:
            stop.operation_phase = OperationPhase.IN_SYSTEM if stop.arrived else OperationPhase.EN_ROUTE
        return self.jump_to(target) + [{"type": "reopened", "system": stop.system, "body": stop.body}]

    def reset_stop(self, index: int | None = None) -> list[dict[str, Any]]:
        if not self.route.stops:
            return []
        target = self.selected_index if index is None else int(index)
        target = max(0, min(target, len(self.route.stops) - 1))
        stop = self.route.stops[target]
        stop.reset()
        if target == self.current_index:
            stop.status = ProgressStatus.CURRENT
        self.selected_task_id = ""
        self._ensure_selected_task()
        return [{"type": "reset", "system": stop.system, "body": stop.body}]

    def complete_selected_task(self) -> list[dict[str, Any]]:
        stop = self.selected_stop
        if not stop:
            return []
        task = self.selected_task
        body = self.projection.body_for(stop)
        included_ids = set(body.included_task_ids) if body else {item.id for item in stop.tasks}
        if task is None or task.complete:
            task = next((item for item in stop.tasks if item.id in included_ids and item.required and not item.complete and item.status != TaskStatus.SKIPPED), None)
        if task is None:
            task = next((item for item in stop.tasks if item.id in included_ids and not item.complete and item.status != TaskStatus.SKIPPED), None)
        if task is None:
            return [{"type": "message", "message": "No incomplete task is selected."}]
        task.add_progress(task.quantity_required, absolute=True)
        self._rebuild_projection(repair_current=False)
        actions = [_task_action(task)]
        if self.selected_index == self.current_index:
            self._rebuild_projection(repair_current=True)
        actions.extend(self._evaluate_current_stop())
        return actions

    def preview_selected_task_skip(self, reason: str | None = None, scope: str = SkipScope.TARGET_BODY) -> list[dict[str, Any]]:
        stop = self.selected_stop
        task = self.selected_task
        if not stop or not task:
            return [{"type": "message", "message": "Select an organism before previewing a skip."}]
        projected = self.task_projection(task, stop)
        body = self.body_projection(stop)
        reason = reason if reason in SKIP_REASONS else self.route.settings.default_skip_reason
        value_removed = int((projected.value_exact if projected else None) or (projected.value_max if projected else None) or task.base_value or 0)
        body_before = int(body.values.active_exact if body else 0)
        body_after = max(0, body_before - value_removed) if projected and projected.included else body_before
        body_removed = bool(body and projected and projected.included and body.included_count <= 1 and body.unresolved_count == 0)
        system = self.navigation.system(system_key_for(stop))
        other_active = 0
        if system:
            other_active = sum(
                1 for candidate in system.bodies
                if candidate.stop_id != stop.id and candidate.included and not candidate.complete and not candidate.skipped
            )
        system_removed = body_removed and other_active == 0
        certainty = task.knowledge_level or (projected.knowledge_level if projected else "unknown")
        self.pending_skip = {
            "systemKey": system_key_for(stop),
            "systemName": stop.system,
            "stopId": stop.id,
            "bodyName": stop.body,
            "taskId": task.id,
            "organismName": task.display_organism or task.label,
            "genusId": task.genus_id,
            "speciesId": task.species_id,
            "variantId": task.variant_id,
            "certainty": certainty,
            "scope": scope,
            "reason": reason,
            "valueRemoved": value_removed,
            "bodyValueBefore": body_before,
            "bodyValueAfter": body_after,
            "bodyRemovedFromRoute": body_removed,
            "systemRemovedFromRoute": system_removed,
            "progress": f"{task.quantity_completed}/{task.quantity_required}",
        }
        return [{
            "type": "skip_preview",
            "system": stop.system,
            "body": stop.body,
            "organism": self.pending_skip["organismName"],
            "reason": SKIP_REASON_LABELS.get(reason, reason),
            "bodyRemoved": body_removed,
            "systemRemoved": system_removed,
            "valueRemoved": value_removed,
        }]

    def cancel_pending_skip(self) -> list[dict[str, Any]]:
        if not self.pending_skip:
            return [{"type": "message", "message": "No skip preview is active."}]
        organism = str(self.pending_skip.get("organismName") or "target")
        self.pending_skip = None
        return [{"type": "message", "message": f"Skip cancelled for {organism}."}]

    def confirm_pending_skip(self) -> list[dict[str, Any]]:
        pending = self.pending_skip
        if not pending:
            return [{"type": "message", "message": "Preview a species skip before confirming it."}]
        stop = next((item for item in self.route.stops if item.id == pending.get("stopId")), None)
        task = next((item for item in stop.tasks if item.id == pending.get("taskId")), None) if stop else None
        if not stop or not task:
            self.pending_skip = None
            return [{"type": "message", "message": "The skip target is no longer available."}]
        decision_id = f"skip-{uuid.uuid4().hex[:12]}"
        created_at = datetime.now(timezone.utc).isoformat()
        decision = SkipDecision(
            id=decision_id,
            system_key=str(pending.get("systemKey") or system_key_for(stop)),
            system_name=stop.system,
            stop_id=stop.id,
            body_name=stop.body,
            task_id=task.id,
            genus_id=task.genus_id,
            species_id=task.species_id,
            variant_id=task.variant_id,
            organism_name=str(pending.get("organismName") or task.display_organism or task.label),
            certainty=str(pending.get("certainty") or task.knowledge_level or "unknown"),
            scope=str(pending.get("scope") or SkipScope.TARGET_BODY),
            reason=str(pending.get("reason") or "other"),
            note="",
            value_removed=int(pending.get("valueRemoved", 0) or 0),
            body_value_before=int(pending.get("bodyValueBefore", 0) or 0),
            body_value_after=int(pending.get("bodyValueAfter", 0) or 0),
            body_removed_from_route=bool(pending.get("bodyRemovedFromRoute", False)),
            system_removed_from_route=bool(pending.get("systemRemovedFromRoute", False)),
            created_at=created_at,
        )
        task.status = TaskStatus.SKIPPED
        task.metadata["skipDecisionId"] = decision_id
        task.metadata["skipReason"] = decision.reason
        task.metadata["skipScope"] = decision.scope
        self.skip_decisions.append(decision)
        self.route.metadata["skipDecisions"] = [item.to_dict() for item in self.skip_decisions]
        self.pending_skip = None
        was_current = self.current_stop is not None and self.current_stop.id == stop.id
        self._rebuild_projection(repair_current=True)
        actions: list[dict[str, Any]] = [{
            "type": "task_skipped",
            "task": task.id,
            "label": task.display_organism or task.label,
            "system": stop.system,
            "body": stop.body,
            "reason": SKIP_REASON_LABELS.get(decision.reason, decision.reason),
            "valueRemoved": decision.value_removed,
            "bodyRemoved": decision.body_removed_from_route,
        }]
        if was_current and self.current_stop and self.current_stop.id != stop.id:
            actions.append({
                "type": "navigation_target",
                "system": self.current_stop.system,
                "body": self.current_stop.body,
                "targetType": self.navigation_target.target_type,
                "text": self.navigation_target.text,
            })
        elif was_current:
            actions.extend(self._evaluate_current_stop())
        return actions

    def skip_selected_task(self) -> list[dict[str, Any]]:
        """Compatibility immediate skip; the v0.5 UI uses preview/confirm instead."""
        task = self.selected_task
        stop = self.selected_stop
        if not task or not stop:
            return [{"type": "message", "message": "No task is selected."}]
        task.status = TaskStatus.SKIPPED
        task.metadata.setdefault("skipReason", self.route.settings.default_skip_reason)
        task.metadata.setdefault("skipScope", SkipScope.TARGET_BODY)
        self._rebuild_projection(repair_current=True)
        actions = [{"type": "task_skipped", "task": task.id, "label": task.label, "system": stop.system, "body": stop.body}]
        if self.selected_index == self.current_index:
            actions.extend(self._evaluate_current_stop())
        return actions

    def undo_last_skip(self) -> list[dict[str, Any]]:
        decision = next((item for item in reversed(self.skip_decisions) if not item.reversed_at), None)
        if not decision:
            return [{"type": "message", "message": "No reversible species skip was found."}]
        stop = next((item for item in self.route.stops if item.id == decision.stop_id), None)
        task = next((item for item in stop.tasks if item.id == decision.task_id), None) if stop else None
        if not task:
            return [{"type": "message", "message": "The last skipped organism is not present in this route."}]
        task.status = TaskStatus.IN_PROGRESS if task.quantity_completed > 0 else TaskStatus.PENDING
        task.metadata.pop("skipDecisionId", None)
        task.metadata.pop("skipReason", None)
        task.metadata.pop("skipScope", None)
        decision.reversed_at = datetime.now(timezone.utc).isoformat()
        self.route.metadata["skipDecisions"] = [item.to_dict() for item in self.skip_decisions]
        self._rebuild_projection(repair_current=True)
        return [{
            "type": "task_reopened",
            "task": task.id,
            "label": task.display_organism or task.label,
            "system": stop.system if stop else decision.system_name,
            "body": stop.body if stop else decision.body_name,
        }]

    def reopen_selected_task(self) -> list[dict[str, Any]]:
        task = self.selected_task
        if not task:
            return [{"type": "message", "message": "No task is selected."}]
        task.status = TaskStatus.IN_PROGRESS if task.quantity_completed > 0 else TaskStatus.PENDING
        if task.quantity_completed >= task.quantity_required:
            task.quantity_completed = max(0, task.quantity_required - 1)
            task.status = TaskStatus.IN_PROGRESS
        self._rebuild_projection(repair_current=False)
        return [{"type": "task_reopened", "task": task.id, "label": task.label}]

    def complete_current(self, manual: bool = True) -> list[dict[str, Any]]:
        stop = self.current_stop
        if not stop:
            return []
        stop.status = ProgressStatus.COMPLETE
        stop.operation_phase = OperationPhase.COMPLETE
        stop.metadata["completionSource"] = "manual" if manual else "journal"
        actions: list[dict[str, Any]] = [
            {"type": "stop_completed", "system": stop.system, "body": stop.body, "manual": manual}
        ]
        actions.extend(self._advance(stop))
        return actions

    def skip_current(self) -> list[dict[str, Any]]:
        stop = self.current_stop
        if not stop:
            return []
        stop.status = ProgressStatus.SKIPPED
        stop.operation_phase = OperationPhase.SKIPPED
        stop.metadata["completionSource"] = "manual-skip"
        actions: list[dict[str, Any]] = [{"type": "stop_skipped", "system": stop.system, "body": stop.body}]
        actions.extend(self._advance(stop))
        return actions

    def previous(self) -> list[dict[str, Any]]:
        candidates = [index for index in self.projection.active_indices if index < self.current_index]
        if not candidates:
            return []
        target = max(candidates)
        previous = self._activate_index(target)
        if not previous:
            return []
        copy_target = self.copy_text("smart-target")
        return [
            {"type": "selected", "system": previous.system, "body": previous.body},
            {"type": "copy", "text": copy_target, "targetType": "body" if copy_target == previous.body else "system"},
        ]

    def _activate_index(self, index: int) -> RouteStop | None:
        if not (0 <= index < len(self.route.stops)) or index not in self.projection.active_indices:
            return None
        current = self.current_stop
        if current and current.status in {ProgressStatus.CURRENT, ProgressStatus.READY} and self.current_index != index:
            current.status = ProgressStatus.PENDING
        self.current_index = index
        self.selected_index = index
        target = self.current_stop
        if target:
            target.status = ProgressStatus.CURRENT
        self._select_current()
        self.selected_task_id = ""
        self._ensure_selected_task()
        if target:
            self.selected_system_key = system_key_for(target)
            self._set_navigation_target_for_current(source="activated")
        return target

    def _advance(self, completed_stop: RouteStop) -> list[dict[str, Any]]:
        target_index = self._next_index_after_completion(completed_stop)
        if target_index is None:
            self.current_index = len(self.route.stops)
            self._select_current()
            return [{"type": "route_complete"}]
        candidate = self._activate_index(target_index)
        if not candidate:
            return [{"type": "route_complete"}]
        same_system = _same_stop_system(completed_stop, candidate)
        copy_target = candidate.body if same_system and candidate.body else candidate.system
        return [
            {"type": "advanced", "system": candidate.system, "body": candidate.body},
            {"type": "copy", "text": copy_target, "targetType": "body" if copy_target == candidate.body else "system"},
        ]

    def _next_index_after_completion(self, completed_stop: RouteStop) -> int | None:
        order = self._navigation_order_indices()
        if not order:
            return None
        same_system = [
            index for index in order
            if _same_stop_system(completed_stop, self.route.stops[index])
        ]
        if same_system:
            return same_system[0]
        return order[0]

    def hydrate_journal_knowledge(self, entry: dict[str, Any]) -> list[dict[str, Any]]:
        """Use historical journal events to enrich body/species knowledge only.

        Historical data must not mark the current route's sampling work complete.
        """
        event = normalize_journal_event(entry)
        event_type = event.event_type.casefold()
        if event_type not in {"saasignalsfound", "scanorganic"}:
            return []
        created = self._ensure_exobio_body_stop(event)
        if created is not None and created.get("created"):
            self._rebuild_projection(repair_current=False)
        resolved = self._resolve_exobio_body(event)
        if resolved is None:
            return []
        stop = self.route.stops[resolved]
        actions: list[dict[str, Any]] = []
        if event_type == "saasignalsfound":
            self._handle_saa_signals(stop, event, actions)
        else:
            task, ambiguous = self._match_organic_task(stop, event)
            if ambiguous:
                return []
            if task is None and self.route.settings.add_unplanned_organisms:
                task = self._create_dynamic_organic_task(stop, event)
                actions.append({"type": "organism_added", "task": task.id, "label": task.label})
            if task is not None:
                self._enrich_task_from_event(stop, task, event)
                task.metadata["knowledgeSource"] = "journal-history"
                self._reconcile_unresolved_slots(stop)
                self._rebuild_projection(repair_current=False)
        return actions

    def handle_journal(self, entry: dict[str, Any]) -> list[dict[str, Any]]:
        event = normalize_journal_event(entry)
        event_key = self._event_key(event)
        if event_key and event_key in self.last_event_ids:
            return []
        if event_key:
            self.last_event_ids.append(event_key)
            self.last_event_ids = self.last_event_ids[-300:]

        actions: list[dict[str, Any]] = []
        self._update_location(event)
        event_type = event.event_type.casefold()
        if event_type in {"saasignalsfound", "scanorganic", "approachbody", "supercruiseexit", "touchdown", "leavebody", "sellorganicdata"}:
            self.recent_exobio_events.append(dict(entry))
            self.recent_exobio_events = self.recent_exobio_events[-200:]

        if event_type == "sellorganicdata":
            self._handle_organic_sale(event, actions)
            self._rebuild_projection(repair_current=False)
            return actions

        if event_type in {"fsdjump", "carrierjump", "location"}:
            exobio_candidates = self._unfinished_exobio_stops_in_system(event)
            if exobio_candidates:
                for index in exobio_candidates:
                    candidate = self.route.stops[index]
                    candidate.arrived = True
                    if candidate.operation_phase == OperationPhase.EN_ROUTE:
                        candidate.operation_phase = OperationPhase.IN_SYSTEM
                active_candidates = [index for index in exobio_candidates if index in self.projection.active_indices]
                current_candidate = (
                    self.current_index
                    if self.current_index in active_candidates
                    else (active_candidates[0] if active_candidates else None)
                )
                stop = self._activate_index(current_candidate) if current_candidate is not None else None
                actions.append({
                    "type": "arrived",
                    "system": (stop.system if stop else event.system),
                    "body": (stop.body if stop else ""),
                })
                return actions

        stop = self.current_stop

        if event_type in {"approachbody", "supercruiseexit", "touchdown", "disembark", "saasignalsfound", "scanorganic", "leavebody"}:
            created = self._ensure_exobio_body_stop(event)
            if created is not None and created.get("created"):
                actions.append({
                    "type": "body_added",
                    "system": created.get("system", ""),
                    "body": created.get("body", ""),
                })
                self._rebuild_projection(repair_current=False)
            resolved = self._resolve_exobio_body(event)
            if resolved is not None:
                resolved_stop = self.route.stops[resolved]
                resolved_body = self.projection.body_for(resolved_stop)
                if resolved_body and resolved_body.included_body:
                    if resolved != self.current_index:
                        stop = self._activate_index(resolved) or resolved_stop
                        actions.append({"type": "body_selected", "system": stop.system, "body": stop.body})
                    else:
                        stop = self.current_stop or resolved_stop
                else:
                    # Filtered bodies still receive observations and sample progress,
                    # but they never become active navigation targets.
                    stop = resolved_stop
            if stop is None:
                return actions
        elif stop is None:
            return actions

        if event_type in {"fsdjump", "carrierjump", "location"}:
            if _event_matches_system(event, stop):
                stop.arrived = True
                if stop.status != ProgressStatus.READY:
                    stop.status = ProgressStatus.CURRENT
                actions.append({"type": "arrived", "system": stop.system, "body": stop.body})
                self._progress_tasks(stop, {"visitsystem"}, event.system, 1, actions)
                if stop.auto_complete_on_arrival and not stop.required_tasks and self.route.settings.complete_waypoint_on_arrival:
                    if self.auto_advance and not self.paused:
                        actions.extend(self.complete_current(manual=False))
                    else:
                        stop.status = ProgressStatus.READY
                        actions.append({"type": "stop_ready"})
                    return actions

        elif event_type == "docked":
            target = event.station or event.settlement
            self._progress_tasks(stop, {"dockatstation"}, target, 1, actions)
            if stop.stop_type == StopType.DOCK and not stop.tasks and _matches_optional(target, stop.station or stop.settlement):
                actions.extend(self._complete_or_ready())
                return actions

        elif event_type == "approachbody":
            if stop.stop_type == StopType.EXOBIOLOGY:
                stop.arrived = True
                stop.operation_phase = OperationPhase.APPROACHING
            self._progress_tasks(stop, {"visitbody"}, event.body, 1, actions)

        elif event_type == "supercruiseexit":
            if stop.stop_type == StopType.EXOBIOLOGY:
                stop.arrived = True
                stop.operation_phase = OperationPhase.NEAR_BODY
            self._progress_tasks(stop, {"visitbody"}, event.body, 1, actions)

        elif event_type == "touchdown":
            if stop.stop_type == StopType.EXOBIOLOGY:
                stop.arrived = True
                stop.operation_phase = OperationPhase.LANDED
            self._progress_tasks(stop, {"visitbody", "landonbody"}, event.body, 1, actions)
            if stop.stop_type == StopType.LAND and not stop.tasks and _matches_optional(event.body, stop.body):
                actions.extend(self._complete_or_ready())
                return actions

        elif event_type == "disembark":
            if stop.stop_type == StopType.EXOBIOLOGY:
                stop.arrived = True
                stop.operation_phase = OperationPhase.LANDED

        elif event_type == "leavebody":
            if stop.stop_type == StopType.EXOBIOLOGY and stop.status not in _FINAL_STOP_STATES:
                stop.operation_phase = OperationPhase.IN_SYSTEM

        elif event_type == "scan":
            body = event.body or str(entry.get("BodyName") or "")
            if entry.get("StarType"):
                self._progress_tasks(stop, {"scanstar"}, body or stop.system, 1, actions)
            self._progress_tasks(stop, {"scanbody"}, body, 1, actions)

        elif event_type == "saascancomplete":
            self._progress_tasks(stop, {"mapbody"}, event.body, 1, actions)

        elif event_type == "saasignalsfound" and stop.stop_type == StopType.EXOBIOLOGY:
            self._handle_saa_signals(stop, event, actions)

        elif event_type == "scanorganic":
            self._handle_scan_organic(stop, event, actions)

        elif event_type in {"materialcollected", "materialtrade"}:
            self._handle_material(stop, event, actions)

        elif event_type in {"marketbuy", "collectcargo"}:
            progress_before = len(actions)
            self._progress_tasks(stop, {"buycommodity", "loadcommodity", "collectcargo"}, event.commodity, event.quantity or 1, actions)
            if len(actions) > progress_before and stop.metadata.get("inferDockFromMarket"):
                self._progress_tasks(stop, {"dockatstation"}, stop.station or stop.settlement, 1, actions)

        elif event_type in {"marketsell", "ejectcargo"}:
            progress_before = len(actions)
            self._progress_tasks(stop, {"sellcommodity", "delivercommodity", "unloadcommodity"}, event.commodity, event.quantity or 1, actions)
            if len(actions) > progress_before and stop.metadata.get("inferDockFromMarket"):
                self._progress_tasks(stop, {"dockatstation"}, stop.station or stop.settlement, 1, actions)

        elif event_type == "cargodepot":
            update_type = str(event.raw.get("UpdateType") or "").casefold()
            if update_type in {"collect", "wingupdate"}:
                self._progress_tasks(stop, {"loadcommodity", "collectcargo", "buycommodity"}, event.commodity, event.quantity or 1, actions)
            if update_type in {"deliver", "wingupdate"}:
                self._progress_tasks(stop, {"delivercommodity", "unloadcommodity", "sellcommodity"}, event.commodity, event.quantity or 1, actions)

        # Every journal-driven progress update changes the calculated work state.
        # Rebuild before evaluating completion so trade, materials, cargo, and
        # exobiology all consume the same current projection.
        self._rebuild_projection(repair_current=False)
        actions.extend(self._evaluate_current_stop())
        return actions

    def _unfinished_exobio_stops_in_system(self, event: JournalEvent) -> list[int]:
        result: list[int] = []
        for index, stop in enumerate(self.route.stops):
            if stop.stop_type != StopType.EXOBIOLOGY or stop.status in _FINAL_STOP_STATES:
                continue
            if _event_matches_system(event, stop):
                result.append(index)
        return result

    def _ensure_exobio_body_stop(self, event: JournalEvent) -> dict[str, Any] | None:
        if not event.body and event.body_id is None:
            return None
        same_system = [
            index
            for index, stop in enumerate(self.route.stops)
            if stop.stop_type == StopType.EXOBIOLOGY and _event_matches_system(event, stop)
        ]
        if not same_system and event.system_address is not None:
            same_system = [
                index
                for index, stop in enumerate(self.route.stops)
                if stop.stop_type == StopType.EXOBIOLOGY
                and stop.system_address is not None
                and int(stop.system_address) == int(event.system_address)
            ]
        if not same_system:
            return None

        for index in same_system:
            stop = self.route.stops[index]
            id_matches = event.body_id is not None and stop.body_id is not None and int(event.body_id) == int(stop.body_id)
            name_matches = bool(event.body and stop.body and _same_name(event.body, stop.body))
            if id_matches or name_matches:
                return {"index": index, "created": False, "system": stop.system, "body": stop.body}

        placeholders = [
            index
            for index in same_system
            if not self.route.stops[index].body
            and bool(self.route.stops[index].metadata.get("dynamicBodyDiscovery", False))
        ]
        if placeholders:
            index = placeholders[0]
            stop = self.route.stops[index]
            stop.body = event.body or f"{stop.system} body {event.body_id}"
            stop.body_id = event.body_id
            stop.system_address = event.system_address if event.system_address is not None else stop.system_address
            stop.metadata["systemPlaceholder"] = False
            stop.metadata["boundFromJournal"] = True
            stop.manifest_source = "live-journal"
            stop.manifest_completeness = "live"
            stop.completion_policy = (
                CompletionPolicy.ALL_SIGNALS
                if event.biological_signal_count
                else CompletionPolicy.MANUAL
            )
            stop.auto_complete_on_arrival = False
            stop.status = ProgressStatus.CURRENT
            stop.operation_phase = OperationPhase.IN_SYSTEM
            return {"index": index, "created": True, "system": stop.system, "body": stop.body}

        if not any(bool(self.route.stops[index].metadata.get("dynamicBodyDiscovery", False)) for index in same_system):
            return None

        base = self.route.stops[same_system[0]]
        body_name = event.body or f"{base.system} body {event.body_id}"
        body_token = str(event.body_id) if event.body_id is not None else _slug(body_name)
        base_id = f"{base.id}-body-{body_token}"
        existing_ids = {stop.id for stop in self.route.stops}
        stop_id = base_id
        suffix = 2
        while stop_id in existing_ids:
            stop_id = f"{base_id}-{suffix}"
            suffix += 1
        body_sequence = max((self.route.stops[index].body_sequence for index in same_system), default=0) + 1
        new_stop = RouteStop(
            id=stop_id,
            sequence=len(self.route.stops) + 1,
            system=base.system,
            stop_type=StopType.EXOBIOLOGY,
            body=body_name,
            auto_complete_on_arrival=False,
            metadata={
                "dynamicBodyDiscovery": True,
                "discoveredDynamically": True,
                "source": "journal-body",
            },
            system_address=event.system_address if event.system_address is not None else base.system_address,
            body_id=event.body_id,
            parent_system_key=base.parent_system_key,
            system_sequence=base.system_sequence,
            body_sequence=body_sequence,
            operation_phase=OperationPhase.IN_SYSTEM,
            completion_policy=(
                CompletionPolicy.ALL_SIGNALS
                if event.biological_signal_count
                else CompletionPolicy.MANUAL
            ),
            biological_signal_count=event.biological_signal_count,
            manifest_source="live-journal",
            manifest_completeness="live",
            manual_order=body_sequence,
        )
        insert_index = max(same_system) + 1
        if insert_index <= self.current_index:
            self.current_index += 1
        if insert_index <= self.selected_index:
            self.selected_index += 1
        self.route.stops.insert(insert_index, new_stop)
        for sequence, stop in enumerate(self.route.stops, start=1):
            stop.sequence = sequence
        return {"index": insert_index, "created": True, "system": new_stop.system, "body": new_stop.body}

    def _resolve_exobio_body(self, event: JournalEvent) -> int | None:
        candidates = self._unfinished_exobio_stops_in_system(event)
        if not candidates:
            # Some body events omit the system name but retain SystemAddress.
            for index, stop in enumerate(self.route.stops):
                if stop.stop_type == StopType.EXOBIOLOGY and stop.status not in _FINAL_STOP_STATES:
                    if event.system_address is not None and stop.system_address is not None and int(event.system_address) == int(stop.system_address):
                        candidates.append(index)
        if not candidates:
            return None

        if event.body_id is not None:
            exact_id = [index for index in candidates if self.route.stops[index].body_id is not None and int(self.route.stops[index].body_id) == int(event.body_id)]
            if len(exact_id) == 1:
                return exact_id[0]
            if len(exact_id) > 1 and event.body:
                exact_name = [index for index in exact_id if _same_name(self.route.stops[index].body, event.body)]
                return exact_name[0] if len(exact_name) == 1 else None

        if event.body:
            exact_name = [index for index in candidates if _same_name(self.route.stops[index].body, event.body)]
            if len(exact_name) == 1:
                return exact_name[0]

        if self.current_index in candidates:
            current = self.route.stops[self.current_index]
            if not event.body and event.body_id is None:
                return self.current_index
            if event.body_id is not None and current.body_id is None and len(candidates) == 1:
                return self.current_index
        return candidates[0] if len(candidates) == 1 else None

    def _update_location(self, event: JournalEvent) -> None:
        if event.system:
            self.current_location["system"] = event.system
        if event.system_address is not None:
            self.current_location["systemAddress"] = event.system_address
        if event.body:
            self.current_location["body"] = event.body
        if event.body_id is not None:
            self.current_location["bodyId"] = event.body_id
        if event.station:
            self.current_location["station"] = event.station
        if event.settlement:
            self.current_location["settlement"] = event.settlement

    def _handle_saa_signals(self, stop: RouteStop, event: JournalEvent, actions: list[dict[str, Any]]) -> None:
        if event.biological_signal_count is not None:
            stop.biological_signal_count = event.biological_signal_count
            if bool(stop.metadata.get("dynamicBodyDiscovery", False)):
                stop.completion_policy = CompletionPolicy.ALL_SIGNALS
        if event.genuses:
            stop.known_genus_count = len(event.genuses)
        for raw_genus in event.genuses:
            genus_id = canonical_genus_id(raw_genus)
            display_genus = display_genus_name(genus_id, raw_genus)
            existing = next(
                (
                    task
                    for task in stop.organic_tasks
                    if not task.species
                    and (task.genus_id == genus_id if genus_id else normalize_organic_name(task.genus or task.target) == normalize_organic_name(raw_genus))
                ),
                None,
            )
            if existing:
                existing.genus = existing.genus or display_genus
                existing.genus_id = genus_id
                existing.knowledge_level = KnowledgeLevel.GENUS_CONFIRMED
                existing.metadata.setdefault("rawGenus", raw_genus)
                existing.metadata.setdefault("source", "SAASignalsFound")
                continue
            task_id = self._unique_task_id(stop, f"{stop.id}-{_slug(display_genus)}")
            colony_range = DEFAULT_CATALOG.colony_range_for_genus(display_genus)
            task = RouteTask(
                id=task_id,
                task_type="scanOrganic",
                label=f"{display_genus} — species unresolved",
                required=(
                    stop.completion_policy == CompletionPolicy.ALL_SIGNALS
                    or bool(stop.metadata.get("dynamicBodyDiscovery", False))
                ),
                target=display_genus,
                quantity_required=3,
                metadata={
                    "source": "SAASignalsFound",
                    "rawGenus": raw_genus,
                    "genusInternal": raw_genus if raw_genus.startswith("$") else "",
                    "colonyRangeMeters": colony_range,
                },
                genus=display_genus,
                genus_id=genus_id,
                knowledge_level=KnowledgeLevel.GENUS_CONFIRMED,
                organism_key=f"{stop.body_key}:{genus_id or normalize_organic_name(raw_genus)}",
                colony_range_m=colony_range,
                discovered_dynamically=True,
            )
            stop.tasks.append(task)
            actions.append({"type": "organism_added", "task": task.id, "label": task.label})
        self._reconcile_unresolved_slots(stop, actions)
        self._rebuild_projection(repair_current=True)
        self._ensure_selected_task()

    def _reconcile_unresolved_slots(self, stop: RouteStop, actions: list[dict[str, Any]] | None = None) -> None:
        expected = int(stop.biological_signal_count or 0)
        if expected <= 0:
            return
        organic = list(stop.organic_tasks)
        placeholders = [task for task in organic if bool(task.metadata.get("unresolvedSlot", False))]
        classified = [task for task in organic if not bool(task.metadata.get("unresolvedSlot", False))]
        desired = max(0, expected - len(classified))
        while len(placeholders) < desired:
            number = len(placeholders) + 1
            task = RouteTask(
                id=self._unique_task_id(stop, f"{stop.id}-unknown-signal-{number}"),
                task_type="scanOrganic",
                label=f"Unknown biological signal {len(classified) + number}",
                required=stop.completion_policy == CompletionPolicy.ALL_SIGNALS,
                target="Unknown biological signal",
                quantity_required=3,
                metadata={"source": "SAASignalsFound", "unresolvedSlot": True},
                knowledge_level=KnowledgeLevel.UNKNOWN,
                organism_key=f"{stop.body_key}:unknown-{number}",
                discovered_dynamically=True,
            )
            stop.tasks.append(task)
            placeholders.append(task)
            if actions is not None:
                actions.append({"type": "organism_added", "task": task.id, "label": task.label})
        removable = [task for task in placeholders[desired:] if task.quantity_completed == 0]
        if removable:
            remove_ids = {task.id for task in removable}
            stop.tasks[:] = [task for task in stop.tasks if task.id not in remove_ids]

    def _handle_scan_organic(self, stop: RouteStop, event: JournalEvent, actions: list[dict[str, Any]]) -> None:
        if stop.stop_type != StopType.EXOBIOLOGY:
            return
        stop.arrived = True
        stop.operation_phase = OperationPhase.SAMPLING
        task, ambiguous = self._match_organic_task(stop, event)
        if ambiguous:
            actions.append({"type": "message", "message": f"Organic scan was not applied because multiple tasks match {event.variant or event.species or event.genus}."})
            return
        if task is None and self.route.settings.add_unplanned_organisms:
            task = self._create_dynamic_organic_task(stop, event)
            actions.append({"type": "organism_added", "task": task.id, "label": task.label})
        if task is None:
            actions.append({"type": "message", "message": f"Unmatched organic scan on {stop.body or stop.system}: {event.variant or event.species or event.genus}."})
            return

        self._enrich_task_from_event(stop, task, event)
        event_key = self._event_key(event)
        if event_key and event_key in task.sample_event_ids:
            return
        if event_key:
            task.sample_event_ids.append(event_key)
            task.sample_event_ids = task.sample_event_ids[-20:]
        scan_stage = event.scan_type.casefold()
        task.sample_stage = scan_stage
        was_skipped = task.status == TaskStatus.SKIPPED
        if scan_stage == "analyse":
            task.add_progress(task.quantity_required, absolute=True)
        elif scan_stage == "sample":
            task.add_progress(min(task.quantity_required, 2), absolute=True)
        elif scan_stage == "log":
            task.add_progress(1, absolute=True)
        else:
            task.add_progress(1)
        if was_skipped:
            task.status = TaskStatus.SKIPPED
        self._reconcile_unresolved_slots(stop)
        self._rebuild_projection(repair_current=True)
        projected = self.projection.task_for(stop, task.id)
        self.selected_task_id = task.id
        actions.append(_task_action(task))
        if projected and projected.excluded:
            actions.append({
                "type": "message",
                "message": (
                    f"Recorded {task.display_organism} at {task.quantity_completed}/{task.quantity_required}. "
                    f"It remains excluded from active progress and value by the {projected.decision.matched_filter or 'organism'} filter."
                ),
            })

    def _match_organic_task(self, stop: RouteStop, event: JournalEvent) -> tuple[RouteTask | None, bool]:
        candidates = list(stop.organic_tasks)
        if not candidates:
            return None, False
        event_resolution = task_taxonomy(
            RouteTask(
                id="event",
                task_type="scanOrganic",
                genus=event.genus or event.genus_internal,
                species=event.species or event.species_internal,
                variant=event.variant or event.variant_internal,
                target=event.variant or event.species or event.genus,
                metadata={
                    "genusInternal": event.genus_internal,
                    "speciesInternal": event.species_internal,
                    "variantInternal": event.variant_internal,
                },
            )
        )
        variant = normalize_organic_name(event.variant or event.variant_internal)
        species = normalize_organic_name(event.species or event.species_internal)
        genus_id = event_resolution.genus_id
        genus = normalize_organic_name(event.genus or event.genus_internal)

        tiers: list[list[RouteTask]] = []
        if variant:
            tiers.append([task for task in candidates if normalize_organic_name(task.variant or task.target) == variant])
        if event_resolution.species_id:
            tiers.append([task for task in candidates if task.species_id == event_resolution.species_id])
        if species:
            tiers.append([task for task in candidates if normalize_organic_name(task.species or task.target) == species])
        if genus_id:
            tiers.append([task for task in candidates if task.genus_id == genus_id and not task.species_id])
        elif genus:
            tiers.append([task for task in candidates if normalize_organic_name(task.genus or task.target) == genus and not task.species])
        observed = event.variant or event.species or event.genus
        if observed:
            tiers.append([task for task in candidates if task.target and _contains_either(observed, task.target)])
        for matches in tiers:
            unique = {task.id: task for task in matches}
            if len(unique) == 1:
                return next(iter(unique.values())), False
            if len(unique) > 1:
                return None, True

        unresolved = [task for task in candidates if bool(task.metadata.get("unresolvedSlot", False))]
        if len(unresolved) == 1:
            return unresolved[0], False
        return None, False

    def _create_dynamic_organic_task(self, stop: RouteStop, event: JournalEvent) -> RouteTask:
        genus = event.genus or event.genus_internal
        species = event.species or event.species_internal
        variant = event.variant or event.variant_internal
        target = variant or species or genus or "Unknown organism"
        match = DEFAULT_CATALOG.resolve(variant, species)
        genus_id = canonical_genus_id(genus, species, variant)
        task_id = self._unique_task_id(stop, f"{stop.id}-{_slug(target)}")
        task = RouteTask(
            id=task_id,
            task_type="scanOrganic",
            label=match.name if match else target,
            required=(
                stop.completion_policy == CompletionPolicy.ALL_SIGNALS
                or bool(stop.metadata.get("dynamicBodyDiscovery", False))
            ),
            target=match.name if match else target,
            quantity_required=3,
            metadata={
                "source": "ScanOrganic",
                "discoveredDynamically": True,
                "genusInternal": event.genus_internal,
                "speciesInternal": event.species_internal,
                "variantInternal": event.variant_internal,
            },
            genus=event.genus or (match.genus if match else display_genus_name(genus_id, genus)),
            species=event.species or (match.name if match else species),
            variant=event.variant or variant,
            genus_id=genus_id,
            species_id=normalize_organic_name(match.name if match else species).replace(" ", "-") if (match or species) else "",
            variant_id=normalize_organic_name(variant).replace(" ", "-") if variant else "",
            knowledge_level=KnowledgeLevel.CONFIRMED if (species or variant or match) else KnowledgeLevel.GENUS_CONFIRMED,
            organism_key=f"{stop.body_key}:{normalize_organic_name(variant or species or genus or target)}",
            base_value=match.base_value if match else None,
            colony_range_m=match.colony_range_m if match else DEFAULT_CATALOG.colony_range_for_genus(genus),
            discovered_dynamically=True,
        )
        if task.base_value is not None:
            task.metadata["estimatedValue"] = task.base_value
            task.metadata["baseValue"] = task.base_value
        if task.colony_range_m is not None:
            task.metadata["colonyRangeMeters"] = task.colony_range_m
        stop.tasks.append(task)
        return task

    def _enrich_task_from_event(self, stop: RouteStop, task: RouteTask, event: JournalEvent) -> None:
        task.metadata.pop("unresolvedSlot", None)
        task.metadata["source"] = "ScanOrganic"
        task.metadata["genusInternal"] = event.genus_internal
        task.metadata["speciesInternal"] = event.species_internal
        task.metadata["variantInternal"] = event.variant_internal
        if event.genus:
            task.genus = event.genus
        elif event.genus_internal and not task.genus:
            genus_id = canonical_genus_id(event.genus_internal)
            task.genus = display_genus_name(genus_id, event.genus_internal)
        if event.species:
            task.species = event.species
        elif event.species_internal and not task.species:
            match = DEFAULT_CATALOG.resolve(event.species_internal)
            task.species = match.name if match else event.species_internal
        if event.variant:
            task.variant = event.variant
        elif event.variant_internal and not task.variant:
            task.variant = event.variant_internal
        match = DEFAULT_CATALOG.resolve(event.variant, event.variant_internal, event.species, event.species_internal, task.species, task.target)
        if match:
            task.species = match.name
            task.genus = display_genus_name(canonical_genus_id(match.genus), match.genus)
            task.base_value = task.base_value if task.base_value is not None else match.base_value
            task.colony_range_m = task.colony_range_m if task.colony_range_m is not None else match.colony_range_m
            task.metadata.setdefault("estimatedValue", match.base_value)
            task.metadata.setdefault("baseValue", match.base_value)
            if match.colony_range_m is not None:
                task.metadata.setdefault("colonyRangeMeters", match.colony_range_m)
            task.label = match.name
            task.target = task.variant or match.name
        else:
            task.label = task.variant or task.species or task.genus or task.label
            task.target = task.variant or task.species or task.genus or task.target
        resolution = task_taxonomy(task)
        task.genus_id = resolution.genus_id
        task.species_id = resolution.species_id
        task.variant_id = resolution.variant_id
        task.knowledge_level = resolution.knowledge_level
        task.organism_key = f"{stop.body_key}:{normalize_organic_name(task.variant or task.species or task.genus or task.target)}"

    @staticmethod
    def _unique_task_id(stop: RouteStop, base: str) -> str:
        existing = {task.id for task in stop.tasks}
        candidate = base
        suffix = 2
        while candidate in existing:
            candidate = f"{base}-{suffix}"
            suffix += 1
        return candidate

    def _handle_organic_sale(self, event: JournalEvent, actions: list[dict[str, Any]]) -> None:
        for record in event.bio_data:
            candidates = self._sale_candidates(record)
            if len(candidates) == 1:
                task = candidates[0]
                task.actual_value += record.value
                task.actual_bonus += record.bonus
                task.sale_status = "sold"
                actions.append(
                    {
                        "type": "organic_sold",
                        "task": task.id,
                        "label": task.display_organism,
                        "value": record.value,
                        "bonus": record.bonus,
                    }
                )
            else:
                entry = {
                    "genus": record.genus,
                    "species": record.species,
                    "variant": record.variant,
                    "value": record.value,
                    "bonus": record.bonus,
                    "allocated": False,
                    "reason": "ambiguous" if len(candidates) > 1 else "not-found",
                }
                self.sales_ledger.append(entry)
                actions.append(
                    {
                        "type": "organic_sale_unallocated",
                        "label": record.variant or record.species or record.genus,
                        "value": record.value,
                        "bonus": record.bonus,
                    }
                )
        self.route.metadata["salesLedger"] = list(self.sales_ledger)

    def _sale_candidates(self, record: OrganicSaleRecord) -> list[RouteTask]:
        variant = normalize_organic_name(record.variant)
        species = normalize_organic_name(record.species)
        completed = [
            task
            for stop in self.route.stops
            for task in stop.organic_tasks
            if task.complete and task.sale_status != "sold"
        ]
        if variant:
            matches = [task for task in completed if normalize_organic_name(task.variant or task.target) == variant]
            if matches:
                return matches
        if species:
            matches = [task for task in completed if normalize_organic_name(task.species or task.target) == species]
            if matches:
                return matches
        return []

    def _handle_material(self, stop: RouteStop, event: JournalEvent, actions: list[dict[str, Any]]) -> None:
        for task in stop.tasks:
            if task.complete or task.task_type.casefold() not in {"collectmaterial", "reachinventoryquantity", "material"}:
                continue
            if task.target and not _contains_either(event.material, task.target):
                continue
            count_mode = str(task.metadata.get("countMode", "session") or "session").casefold()
            if task.task_type.casefold() == "reachinventoryquantity" or count_mode == "inventory":
                if event.total is not None:
                    task.add_progress(event.total, absolute=True)
                else:
                    task.add_progress(event.quantity or 1)
            elif count_mode == "either" and event.total is not None:
                task.add_progress(max(task.quantity_completed + (event.quantity or 1), event.total), absolute=True)
            else:
                task.add_progress(event.quantity or 1)
            actions.append(_task_action(task))

    def _progress_tasks(self, stop: RouteStop, task_types: set[str], observed: str, increment: int, actions: list[dict[str, Any]]) -> None:
        for task in stop.tasks:
            if task.complete or task.task_type.casefold() not in task_types:
                continue
            target = task.target or self._implicit_target(stop, task.task_type)
            if target and not _contains_either(observed, target):
                continue
            task.add_progress(max(1, increment))
            actions.append(_task_action(task))

    @staticmethod
    def _implicit_target(stop: RouteStop, task_type: str) -> str:
        kind = task_type.casefold()
        if kind == "visitsystem":
            return stop.system
        if kind in {"visitbody", "landonbody", "scanbody", "mapbody"}:
            return stop.body
        if kind == "dockatstation":
            return stop.station or stop.settlement
        return ""

    def _evaluate_current_stop(self) -> list[dict[str, Any]]:
        stop = self.current_stop
        if not stop:
            return []
        body = self.projection.body_for(stop)
        work_complete = body.work_complete if body else stop.work_complete
        if not work_complete:
            return []
        return self._complete_or_ready()

    def _complete_or_ready(self) -> list[dict[str, Any]]:
        stop = self.current_stop
        if not stop:
            return []
        if self.guidance_mode == GuidanceMode.AUTO_ADVANCE and not self.paused:
            return self.complete_current(manual=False)
        if stop.status != ProgressStatus.READY:
            stop.status = ProgressStatus.READY
            if stop.stop_type == StopType.EXOBIOLOGY:
                stop.operation_phase = OperationPhase.READY
            return [{"type": "stop_ready", "system": stop.system, "body": stop.body}]
        return []

    def export_exobio_debug_bundle(self, destination_dir: str | None = None) -> str:
        from exobio_diagnostics import export_debug_bundle

        return str(export_debug_bundle(self, destination_dir))

    @staticmethod
    def _event_key(event: JournalEvent) -> str:
        if event.event_id:
            return f"id:{event.event_id}"
        if event.timestamp:
            return "|".join(
                [
                    event.timestamp,
                    event.event_type,
                    event.system,
                    str(event.system_address or ""),
                    event.body,
                    str(event.body_id or ""),
                    event.station,
                    event.commodity,
                    event.material,
                    event.variant or event.species,
                    str(event.quantity),
                ]
            ).casefold()
        return ""

    def to_state(self) -> dict[str, Any]:
        current_stop_id = self.current_stop.id if self.current_stop else ""
        selected_stop_id = self.selected_stop.id if self.selected_stop else ""
        self.route.metadata["salesLedger"] = list(self.sales_ledger)
        return {
            "stateVersion": 6,
            "routeId": self.route.id,
            "routeFile": self.route.source_path,
            "currentStopId": current_stop_id,
            "selectedStopId": selected_stop_id,
            "selectedTaskId": self.selected_task_id,
            "selectedSystemKey": self.selected_system_key,
            "navigationTarget": self.navigation_target.to_dict(),
            "guidanceMode": self.guidance_mode,
            "bodyOrderMode": self.body_order_mode,
            "pendingSkip": dict(self.pending_skip) if self.pending_skip else None,
            "skipDecisions": [item.to_dict() for item in self.skip_decisions],
            "paused": self.paused,
            "autoAdvance": self.auto_advance,
            "forceExobiologyMode": bool(self.route.metadata.get("forceExobiologyMode", False)),
            "excludedOrganismGenera": list(self.route.settings.excluded_organism_genera),
            "filterProfile": {
                "excludedGenusIds": [canonical_genus_id(item) or normalize_organic_name(item) for item in self.route.settings.excluded_organism_genera],
                "showExcludedOrganisms": self.route.settings.show_excluded_organisms,
                "hideEmptyBodies": self.route.settings.hide_empty_bodies,
                "hideEmptySystems": self.route.settings.hide_empty_systems,
                "routeViewMode": self.route.settings.route_view_mode,
                "guidanceMode": self.guidance_mode,
                "bodyOrderMode": self.body_order_mode,
                "defaultSkipReason": self.route.settings.default_skip_reason,
            },
            "currentLocation": dict(self.current_location),
            "salesLedger": list(self.sales_ledger),
            "stops": {
                stop.id: {
                    "status": stop.status,
                    "arrived": stop.arrived,
                    "operationPhase": stop.operation_phase,
                    "biologicalSignalCount": stop.biological_signal_count,
                    "knownGenusCount": stop.known_genus_count,
                    "distanceFromArrivalLs": stop.distance_from_arrival_ls,
                    "manifestSource": stop.manifest_source,
                    "manifestCompleteness": stop.manifest_completeness,
                    "manualOrder": stop.manual_order,
                    "priorityScore": stop.priority_score,
                    "system": stop.system,
                    "body": stop.body,
                    "stopType": stop.stop_type,
                    "completionPolicy": stop.completion_policy,
                    "systemAddress": stop.system_address,
                    "bodyId": stop.body_id,
                    "parentSystemKey": stop.parent_system_key,
                    "systemSequence": stop.system_sequence,
                    "bodySequence": stop.body_sequence,
                    "metadata": dict(stop.metadata),
                    "tasks": {task.id: task.to_state() for task in stop.tasks},
                }
                for stop in self.route.stops
            },
            "dynamicStops": [
                {
                    "id": stop.id,
                    "routeIndex": index,
                    "sequence": stop.sequence,
                    "system": stop.system,
                    "body": stop.body,
                    "stopType": stop.stop_type,
                    "systemAddress": stop.system_address,
                    "bodyId": stop.body_id,
                    "parentSystemKey": stop.parent_system_key,
                    "systemSequence": stop.system_sequence,
                    "bodySequence": stop.body_sequence,
                    "completionPolicy": stop.completion_policy,
                    "biologicalSignalCount": stop.biological_signal_count,
                    "knownGenusCount": stop.known_genus_count,
                    "distanceFromArrivalLs": stop.distance_from_arrival_ls,
                    "manifestSource": stop.manifest_source,
                    "manifestCompleteness": stop.manifest_completeness,
                    "manualOrder": stop.manual_order,
                    "priorityScore": stop.priority_score,
                    "metadata": dict(stop.metadata),
                }
                for index, stop in enumerate(self.route.stops)
                if bool(stop.metadata.get("discoveredDynamically", False))
            ],
            # 0.1.x compatibility keys.
            "route_id": self.route.id,
            "current_index": self.current_index,
            "auto_advance": self.auto_advance,
        }

    def apply_state(self, state: dict[str, Any]) -> None:
        state_route_id = state.get("routeId") or state.get("route_id")
        if state_route_id != self.route.id:
            return

        if bool(state.get("forceExobiologyMode", False)):
            self.enable_exobiology_mode()
        self._restore_dynamic_stops(state)
        filter_profile = state.get("filterProfile", {})
        if not isinstance(filter_profile, dict):
            filter_profile = {}
        excluded = filter_profile.get("excludedGenusIds", state.get("excludedOrganismGenera", self.route.settings.excluded_organism_genera))
        if isinstance(excluded, list):
            self.route.settings.excluded_organism_genera = [display_genus_name(canonical_genus_id(str(item)), str(item)) for item in excluded if str(item).strip()]
        self.route.settings.show_excluded_organisms = bool(filter_profile.get("showExcludedOrganisms", self.route.settings.show_excluded_organisms))
        self.route.settings.hide_empty_bodies = bool(filter_profile.get("hideEmptyBodies", self.route.settings.hide_empty_bodies))
        self.route.settings.hide_empty_systems = bool(filter_profile.get("hideEmptySystems", self.route.settings.hide_empty_systems))
        view_mode = str(filter_profile.get("routeViewMode", self.route.settings.route_view_mode) or "active").casefold()
        self.route.settings.route_view_mode = view_mode if view_mode in {"active", "all"} else "active"
        fallback_guidance = GuidanceMode.AUTO_ADVANCE if bool(state.get("autoAdvance", state.get("auto_advance", self.auto_advance))) else GuidanceMode.CONFIRM
        guidance = str(state.get("guidanceMode", filter_profile.get("guidanceMode", self.route.settings.guidance_mode)) or fallback_guidance).casefold()
        self.guidance_mode = guidance if guidance in GuidanceMode.ALL else fallback_guidance
        self.route.settings.guidance_mode = self.guidance_mode
        order_mode = str(state.get("bodyOrderMode", filter_profile.get("bodyOrderMode", self.route.settings.body_order_mode)) or "route").casefold()
        self.body_order_mode = order_mode if order_mode in BodyOrderMode.ALL else BodyOrderMode.ROUTE
        self.route.settings.body_order_mode = self.body_order_mode
        reason = str(filter_profile.get("defaultSkipReason", self.route.settings.default_skip_reason) or "too-difficult").casefold()
        self.route.settings.default_skip_reason = reason if reason in SKIP_REASONS else "too-difficult"
        self.selected_system_key = str(state.get("selectedSystemKey") or "")
        self.navigation_target = NavigationTarget.from_dict(state.get("navigationTarget"))
        pending = state.get("pendingSkip")
        self.pending_skip = dict(pending) if isinstance(pending, dict) else None
        raw_decisions = state.get("skipDecisions", [])
        if isinstance(raw_decisions, list):
            self.skip_decisions = [decision for decision in (SkipDecision.from_dict(item) for item in raw_decisions) if decision is not None]
            self.route.metadata["skipDecisions"] = [item.to_dict() for item in self.skip_decisions]

        current_id = str(state.get("currentStopId") or "")
        if current_id:
            self.current_index = next((index for index, stop in enumerate(self.route.stops) if stop.id == current_id), 0)
        else:
            self.current_index = max(0, min(int(state.get("current_index", 0)), len(self.route.stops)))

        selected_id = str(state.get("selectedStopId") or "")
        if selected_id:
            self.selected_index = next((index for index, stop in enumerate(self.route.stops) if stop.id == selected_id), self.current_index)
        else:
            self.selected_index = self.current_index if not self.complete else max(0, len(self.route.stops) - 1)

        self.selected_task_id = str(state.get("selectedTaskId") or "")
        self.paused = bool(state.get("paused", False))
        self.auto_advance = self.guidance_mode == GuidanceMode.AUTO_ADVANCE
        location = state.get("currentLocation", {})
        if isinstance(location, dict):
            for key in self.current_location:
                if key in location and location.get(key) not in (None, ""):
                    self.current_location[key] = location[key]
        ledger = state.get("salesLedger", [])
        if isinstance(ledger, list):
            self.sales_ledger = [dict(item) for item in ledger if isinstance(item, dict)]
            self.route.metadata["salesLedger"] = list(self.sales_ledger)

        stop_states = state.get("stops", {})
        if isinstance(stop_states, dict):
            for stop in self.route.stops:
                raw_stop = stop_states.get(stop.id, {})
                if not isinstance(raw_stop, dict):
                    continue
                stop.status = str(raw_stop.get("status", stop.status))
                stop.arrived = bool(raw_stop.get("arrived", stop.arrived))
                stop.operation_phase = str(raw_stop.get("operationPhase", stop.operation_phase))
                stop.system = str(raw_stop.get("system", stop.system) or stop.system)
                stop.body = str(raw_stop.get("body", stop.body) or "")
                stop.stop_type = str(raw_stop.get("stopType", stop.stop_type) or stop.stop_type)
                stop.completion_policy = str(raw_stop.get("completionPolicy", stop.completion_policy) or stop.completion_policy)
                stop.system_address = _safe_optional_int(raw_stop.get("systemAddress"), stop.system_address)
                stop.body_id = _safe_optional_int(raw_stop.get("bodyId"), stop.body_id)
                stop.parent_system_key = str(raw_stop.get("parentSystemKey", stop.parent_system_key) or stop.parent_system_key)
                stop.system_sequence = int(raw_stop.get("systemSequence", stop.system_sequence) or 0)
                stop.body_sequence = int(raw_stop.get("bodySequence", stop.body_sequence) or 0)
                raw_metadata = raw_stop.get("metadata", {})
                if isinstance(raw_metadata, dict):
                    stop.metadata.update(raw_metadata)
                stop.biological_signal_count = _safe_optional_int(raw_stop.get("biologicalSignalCount"), stop.biological_signal_count)
                stop.known_genus_count = _safe_optional_int(raw_stop.get("knownGenusCount"), stop.known_genus_count)
                stop.distance_from_arrival_ls = _safe_optional_float(raw_stop.get("distanceFromArrivalLs"), stop.distance_from_arrival_ls)
                stop.manifest_source = str(raw_stop.get("manifestSource", stop.manifest_source) or stop.manifest_source)
                stop.manifest_completeness = str(raw_stop.get("manifestCompleteness", stop.manifest_completeness) or stop.manifest_completeness)
                stop.manual_order = int(raw_stop.get("manualOrder", stop.manual_order) or 0)
                stop.priority_score = float(raw_stop.get("priorityScore", stop.priority_score) or 0)
                task_states = raw_stop.get("tasks", {})
                if not isinstance(task_states, dict):
                    continue
                # Restore dynamic organisms before applying task state.
                for task_id, raw_task in task_states.items():
                    if not isinstance(raw_task, dict) or any(task.id == task_id for task in stop.tasks):
                        continue
                    if not bool(raw_task.get("discoveredDynamically", False)):
                        continue
                    stop.tasks.append(self._task_from_state(task_id, raw_task, stop))
                for task in stop.tasks:
                    raw_task = task_states.get(task.id, {})
                    if not isinstance(raw_task, dict):
                        continue
                    quantity = raw_task.get("quantityCompleted", raw_task.get("current_quantity", 0))
                    task.quantity_completed = max(0, int(quantity or 0))
                    if raw_task.get("status"):
                        task.status = str(raw_task["status"])
                    elif bool(raw_task.get("complete", False)):
                        task.status = TaskStatus.COMPLETE
                    elif task.quantity_completed > 0:
                        task.status = TaskStatus.IN_PROGRESS
                    task.genus = str(raw_task.get("genus", task.genus) or "")
                    task.species = str(raw_task.get("species", task.species) or "")
                    task.variant = str(raw_task.get("variant", task.variant) or "")
                    task.organism_key = str(raw_task.get("organismKey", task.organism_key) or "")
                    task.base_value = _safe_optional_int(raw_task.get("baseValue"), task.base_value)
                    task.colony_range_m = _safe_optional_int(raw_task.get("colonyRangeMeters"), task.colony_range_m)
                    task.first_logged_status = str(raw_task.get("firstLoggedStatus", task.first_logged_status) or "unknown")
                    task.actual_value = max(0, int(raw_task.get("actualValue", task.actual_value) or 0))
                    task.actual_bonus = max(0, int(raw_task.get("actualBonus", task.actual_bonus) or 0))
                    task.sale_status = str(raw_task.get("saleStatus", task.sale_status) or "unsold")
                    task.discovered_dynamically = bool(raw_task.get("discoveredDynamically", task.discovered_dynamically))
                    task.genus_id = str(raw_task.get("genusId", task.genus_id) or "")
                    task.species_id = str(raw_task.get("speciesId", task.species_id) or "")
                    task.variant_id = str(raw_task.get("variantId", task.variant_id) or "")
                    task.knowledge_level = str(raw_task.get("knowledgeLevel", task.knowledge_level) or "unknown")
                    task.manual_inclusion = str(raw_task.get("manualInclusion", task.manual_inclusion) or "default")
                    task.sample_stage = str(raw_task.get("sampleStage", task.sample_stage) or "")
                    raw_event_ids = raw_task.get("sampleEventIds", task.sample_event_ids)
                    if isinstance(raw_event_ids, list):
                        task.sample_event_ids = [str(item) for item in raw_event_ids if str(item)]
                    task.search_difficulty = str(raw_task.get("searchDifficulty", task.search_difficulty) or "unknown")
                    task.search_started_at = str(raw_task.get("searchStartedAt", task.search_started_at) or "")
                    task.search_elapsed_seconds = max(0, int(raw_task.get("searchElapsedSeconds", task.search_elapsed_seconds) or 0))
                    raw_task_metadata = raw_task.get("metadata", {})
                    if isinstance(raw_task_metadata, dict):
                        task.metadata.update(raw_task_metadata)
        self._repair_legacy_filter_mutations()
        for stop in self.route.stops:
            if self._false_arrival_completion(stop):
                stop.status = ProgressStatus.PENDING
                stop.operation_phase = OperationPhase.IN_SYSTEM if stop.arrived else OperationPhase.EN_ROUTE
        self._rebuild_projection(repair_current=True)
        if self.navigation_target.stop_id and any(stop.id == self.navigation_target.stop_id for stop in self.route.stops):
            pass
        else:
            self._set_navigation_target_for_current(source="state-recovery")

    def _restore_dynamic_stops(self, state: dict[str, Any]) -> None:
        raw_stops = state.get("dynamicStops", [])
        if not isinstance(raw_stops, list):
            return
        existing = {stop.id for stop in self.route.stops}
        for raw in sorted(
            (item for item in raw_stops if isinstance(item, dict)),
            key=lambda item: int(item.get("routeIndex", len(self.route.stops)) or len(self.route.stops)),
        ):
            stop_id = str(raw.get("id") or "")
            if not stop_id or stop_id in existing:
                continue
            metadata = dict(raw.get("metadata", {})) if isinstance(raw.get("metadata"), dict) else {}
            metadata["discoveredDynamically"] = True
            stop = RouteStop(
                id=stop_id,
                sequence=max(1, int(raw.get("sequence", len(self.route.stops) + 1) or len(self.route.stops) + 1)),
                system=str(raw.get("system") or ""),
                stop_type=str(raw.get("stopType") or StopType.EXOBIOLOGY),
                body=str(raw.get("body") or ""),
                auto_complete_on_arrival=False,
                metadata=metadata,
                system_address=_safe_optional_int(raw.get("systemAddress")),
                body_id=_safe_optional_int(raw.get("bodyId")),
                parent_system_key=str(raw.get("parentSystemKey") or ""),
                system_sequence=int(raw.get("systemSequence", 0) or 0),
                body_sequence=int(raw.get("bodySequence", 0) or 0),
                completion_policy=str(raw.get("completionPolicy") or CompletionPolicy.LISTED_TARGETS),
                biological_signal_count=_safe_optional_int(raw.get("biologicalSignalCount")),
                known_genus_count=_safe_optional_int(raw.get("knownGenusCount")),
                distance_from_arrival_ls=_safe_optional_float(raw.get("distanceFromArrivalLs")),
                manifest_source=str(raw.get("manifestSource") or "live-journal"),
                manifest_completeness=str(raw.get("manifestCompleteness") or "live"),
                manual_order=int(raw.get("manualOrder", 0) or 0),
                priority_score=float(raw.get("priorityScore", 0) or 0),
            )
            insert_at = max(0, min(int(raw.get("routeIndex", len(self.route.stops)) or len(self.route.stops)), len(self.route.stops)))
            self.route.stops.insert(insert_at, stop)
            existing.add(stop_id)
        for sequence, stop in enumerate(self.route.stops, start=1):
            stop.sequence = sequence

    @staticmethod
    def _task_from_state(task_id: str, raw: dict[str, Any], stop: RouteStop) -> RouteTask:
        task = RouteTask(
            id=task_id,
            task_type=str(raw.get("taskType") or "scanOrganic"),
            label=str(raw.get("label") or raw.get("species") or raw.get("genus") or "Discovered organism"),
            required=bool(raw.get("required", stop.completion_policy == CompletionPolicy.ALL_SIGNALS)),
            target=str(raw.get("target") or raw.get("variant") or raw.get("species") or raw.get("genus") or ""),
            quantity_required=max(1, int(raw.get("quantityRequired", 3) or 3)),
            genus=str(raw.get("genus") or ""),
            species=str(raw.get("species") or ""),
            variant=str(raw.get("variant") or ""),
            organism_key=str(raw.get("organismKey") or ""),
            base_value=_safe_optional_int(raw.get("baseValue")),
            colony_range_m=_safe_optional_int(raw.get("colonyRangeMeters")),
            first_logged_status=str(raw.get("firstLoggedStatus") or "unknown"),
            actual_value=max(0, int(raw.get("actualValue", 0) or 0)),
            actual_bonus=max(0, int(raw.get("actualBonus", 0) or 0)),
            sale_status=str(raw.get("saleStatus") or "unsold"),
            discovered_dynamically=True,
            genus_id=str(raw.get("genusId") or ""),
            species_id=str(raw.get("speciesId") or ""),
            variant_id=str(raw.get("variantId") or ""),
            knowledge_level=str(raw.get("knowledgeLevel") or "unknown"),
            manual_inclusion=str(raw.get("manualInclusion") or "default"),
            sample_stage=str(raw.get("sampleStage") or ""),
            sample_event_ids=[str(item) for item in raw.get("sampleEventIds", []) if str(item)] if isinstance(raw.get("sampleEventIds", []), list) else [],
            search_difficulty=str(raw.get("searchDifficulty") or "unknown"),
            search_started_at=str(raw.get("searchStartedAt") or ""),
            search_elapsed_seconds=max(0, int(raw.get("searchElapsedSeconds", 0) or 0)),
            metadata=(
                dict(raw.get("metadata", {}))
                if isinstance(raw.get("metadata"), dict)
                else {"discoveredDynamically": True, "source": "state-v4"}
            ),
        )
        return task


def _safe_optional_int(value: Any, default: int | None = None) -> int | None:
    if value in (None, ""):
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _safe_optional_float(value: Any, default: float | None = None) -> float | None:
    if value in (None, ""):
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _normalise_name(value: str) -> str:
    text = str(value or "").strip().casefold().replace("$", "")
    text = re.sub(r"_name;?$", "", text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split())


def _same_name(left: str, right: str) -> bool:
    return _normalise_name(left) == _normalise_name(right) and bool(_normalise_name(right))


def _contains_either(left: str, right: str) -> bool:
    a = _normalise_name(left)
    b = _normalise_name(right)
    if not a or not b:
        return False
    return a == b or a in b or b in a


def _matches_optional(observed: str, target: str) -> bool:
    return True if not target else _contains_either(observed, target)


def _event_matches_system(event: JournalEvent, stop: RouteStop) -> bool:
    if event.system_address is not None and stop.system_address is not None:
        return int(event.system_address) == int(stop.system_address)
    return _same_name(event.system, stop.system)


def _same_stop_system(left: RouteStop, right: RouteStop) -> bool:
    if left.system_address is not None and right.system_address is not None:
        return int(left.system_address) == int(right.system_address)
    return _same_name(left.system, right.system)


def _slug(value: str) -> str:
    text = re.sub(r"[^a-z0-9]+", "-", _normalise_name(value)).strip("-")
    return text or "organism"


def _task_action(task: RouteTask) -> dict[str, Any]:
    return {
        "type": "task_progress",
        "task": task.id,
        "label": task.label,
        "current": task.quantity_completed,
        "target": task.quantity_required,
        "complete": task.complete,
        "baseValue": task.base_value,
    }
