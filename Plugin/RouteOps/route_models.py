from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


class RouteMode:
    WAYPOINT = "waypoint"
    EXPLORATION = "exploration"
    EXOBIOLOGY = "exobiology"
    MATERIALS = "materials"
    TRADE = "trade"
    CARGO = "cargo"
    CARRIER = "carrier"
    MIXED = "mixed"


class StopType:
    WAYPOINT = "waypoint"
    EXPLORATION = "exploration"
    EXOBIOLOGY = "exobiology"
    MATERIALS = "materials"
    TRADE = "trade"
    CARGO = "cargo"
    CARRIER = "carrier"
    DOCK = "dock"
    LAND = "land"
    CHECKLIST = "checklist"


class ProgressStatus:
    PENDING = "pending"
    CURRENT = "current"
    READY = "ready"
    COMPLETE = "complete"
    SKIPPED = "skipped"
    BLOCKED = "blocked"


class TaskStatus:
    PENDING = "pending"
    IN_PROGRESS = "in-progress"
    COMPLETE = "complete"
    SKIPPED = "skipped"


class OperationPhase:
    EN_ROUTE = "en-route"
    IN_SYSTEM = "in-system"
    APPROACHING = "approaching"
    NEAR_BODY = "near-body"
    LANDED = "landed"
    SAMPLING = "sampling"
    READY = "ready"
    COMPLETE = "complete"
    SKIPPED = "skipped"


class CompletionPolicy:
    LISTED_TARGETS = "listed-targets"
    ALL_SIGNALS = "all-signals"
    MANUAL = "manual"
    ANY_TARGET = "any-target"


@dataclass
class RouteSettings:
    auto_copy_mode: str = "smart-target"
    auto_advance: bool = True
    complete_waypoint_on_arrival: bool = True
    clipboard_retry_count: int = 6
    clipboard_retry_delay_ms: int = 75
    add_unplanned_organisms: bool = True
    default_completion_policy: str = CompletionPolicy.LISTED_TARGETS
    show_first_logged_potential: bool = True
    excluded_organism_genera: list[str] = field(default_factory=list)
    show_excluded_organisms: bool = True
    hide_empty_bodies: bool = True
    hide_empty_systems: bool = True
    route_view_mode: str = "active"
    guidance_mode: str = "auto-advance"
    body_order_mode: str = "route"
    default_skip_reason: str = "too-difficult"

    def to_dict(self) -> dict[str, Any]:
        return {
            "autoCopyMode": self.auto_copy_mode,
            "autoAdvance": self.auto_advance,
            "completeWaypointOnArrival": self.complete_waypoint_on_arrival,
            "clipboardRetryCount": self.clipboard_retry_count,
            "clipboardRetryDelayMs": self.clipboard_retry_delay_ms,
            "addUnplannedOrganisms": self.add_unplanned_organisms,
            "defaultCompletionPolicy": self.default_completion_policy,
            "showFirstLoggedPotential": self.show_first_logged_potential,
            "excludedOrganismGenera": list(self.excluded_organism_genera),
            "showExcludedOrganisms": self.show_excluded_organisms,
            "hideEmptyBodies": self.hide_empty_bodies,
            "hideEmptySystems": self.hide_empty_systems,
            "routeViewMode": self.route_view_mode,
            "guidanceMode": self.guidance_mode,
            "bodyOrderMode": self.body_order_mode,
            "defaultSkipReason": self.default_skip_reason,
        }


@dataclass
class RouteTask:
    id: str
    task_type: str
    label: str = ""
    required: bool = True
    target: str = ""
    quantity_required: int = 1
    quantity_completed: int = 0
    status: str = TaskStatus.PENDING
    metadata: dict[str, Any] = field(default_factory=dict)
    genus: str = ""
    species: str = ""
    variant: str = ""
    organism_key: str = ""
    base_value: int | None = None
    colony_range_m: int | None = None
    first_logged_status: str = "unknown"
    actual_value: int = 0
    actual_bonus: int = 0
    sale_status: str = "unsold"
    discovered_dynamically: bool = False
    genus_id: str = ""
    species_id: str = ""
    variant_id: str = ""
    knowledge_level: str = "unknown"
    manual_inclusion: str = "default"
    sample_stage: str = ""
    sample_event_ids: list[str] = field(default_factory=list)
    search_difficulty: str = "unknown"
    search_started_at: str = ""
    search_elapsed_seconds: int = 0

    @property
    def complete(self) -> bool:
        return self.status == TaskStatus.COMPLETE or self.quantity_completed >= self.quantity_required

    @complete.setter
    def complete(self, value: bool) -> None:
        self.status = TaskStatus.COMPLETE if value else TaskStatus.PENDING
        if value:
            self.quantity_completed = max(self.quantity_completed, self.quantity_required)

    @property
    def optional(self) -> bool:
        return not self.required

    @optional.setter
    def optional(self, value: bool) -> None:
        self.required = not value

    @property
    def is_organic(self) -> bool:
        return self.task_type.casefold() in {"scanorganic", "scanspecies", "samplespecies"}

    @property
    def display_organism(self) -> str:
        return self.variant or self.species or self.genus or self.target or self.label

    @property
    def potential_first_logged_value(self) -> int:
        return int(self.base_value or 0) * 5

    # Compatibility aliases for the 0.1.x engine/tests and saved state.
    @property
    def type(self) -> str:
        return self.task_type

    @type.setter
    def type(self, value: str) -> None:
        self.task_type = value

    @property
    def target_quantity(self) -> int:
        return self.quantity_required

    @target_quantity.setter
    def target_quantity(self, value: int) -> None:
        self.quantity_required = max(1, int(value))

    @property
    def current_quantity(self) -> int:
        return self.quantity_completed

    @current_quantity.setter
    def current_quantity(self, value: int) -> None:
        self.quantity_completed = max(0, int(value))
        if self.quantity_completed >= self.quantity_required:
            self.status = TaskStatus.COMPLETE
        elif self.quantity_completed > 0:
            self.status = TaskStatus.IN_PROGRESS

    def reset(self) -> None:
        self.quantity_completed = 0
        self.status = TaskStatus.PENDING
        self.actual_value = 0
        self.actual_bonus = 0
        self.sale_status = "unsold"

    def add_progress(self, amount: int = 1, absolute: bool = False) -> None:
        amount = max(0, int(amount))
        if absolute:
            # Organic journal stages can be delivered out of order. Never let a
            # late Log/Sample event reduce progress already recorded by Analyse.
            self.quantity_completed = max(
                self.quantity_completed,
                min(self.quantity_required, amount),
            )
        else:
            self.quantity_completed = min(
                self.quantity_required,
                self.quantity_completed + amount,
            )
        if self.quantity_completed >= self.quantity_required:
            self.status = TaskStatus.COMPLETE
        elif self.quantity_completed > 0:
            self.status = TaskStatus.IN_PROGRESS

    def to_state(self) -> dict[str, Any]:
        return {
            "taskType": self.task_type,
            "label": self.label,
            "required": self.required,
            "target": self.target,
            "quantityRequired": self.quantity_required,
            "quantityCompleted": self.quantity_completed,
            "status": self.status,
            "genus": self.genus,
            "species": self.species,
            "variant": self.variant,
            "organismKey": self.organism_key,
            "baseValue": self.base_value,
            "colonyRangeMeters": self.colony_range_m,
            "firstLoggedStatus": self.first_logged_status,
            "actualValue": self.actual_value,
            "actualBonus": self.actual_bonus,
            "saleStatus": self.sale_status,
            "discoveredDynamically": self.discovered_dynamically,
            "genusId": self.genus_id,
            "speciesId": self.species_id,
            "variantId": self.variant_id,
            "knowledgeLevel": self.knowledge_level,
            "manualInclusion": self.manual_inclusion,
            "sampleStage": self.sample_stage,
            "sampleEventIds": list(self.sample_event_ids),
            "searchDifficulty": self.search_difficulty,
            "searchStartedAt": self.search_started_at,
            "searchElapsedSeconds": self.search_elapsed_seconds,
            "metadata": dict(self.metadata),
            # v1 compatibility keys make rollback safer.
            "current_quantity": self.quantity_completed,
            "complete": self.complete,
        }


@dataclass
class RouteStop:
    id: str
    sequence: int
    system: str
    label: str = ""
    stop_type: str = StopType.WAYPOINT
    body: str = ""
    station: str = ""
    settlement: str = ""
    notes: str = ""
    instructions: str = ""
    tasks: list[RouteTask] = field(default_factory=list)
    status: str = ProgressStatus.PENDING
    arrived: bool = False
    auto_complete_on_arrival: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)
    system_address: int | None = None
    body_id: int | None = None
    parent_system_key: str = ""
    system_sequence: int = 0
    body_sequence: int = 0
    operation_phase: str = OperationPhase.EN_ROUTE
    completion_policy: str = CompletionPolicy.LISTED_TARGETS
    biological_signal_count: int | None = None
    known_genus_count: int | None = None
    distance_from_arrival_ls: float | None = None
    manifest_source: str = ""
    manifest_completeness: str = ""
    manual_order: int = 0
    priority_score: float = 0.0

    @property
    def title(self) -> str:
        return self.label

    @title.setter
    def title(self, value: str) -> None:
        self.label = value

    @property
    def activity(self) -> str:
        return self.stop_type

    @activity.setter
    def activity(self, value: str) -> None:
        self.stop_type = value

    @property
    def required_tasks(self) -> list[RouteTask]:
        return [task for task in self.tasks if task.required and task.status != TaskStatus.SKIPPED]

    @property
    def optional_tasks(self) -> list[RouteTask]:
        return [task for task in self.tasks if not task.required]

    @property
    def organic_tasks(self) -> list[RouteTask]:
        return [task for task in self.tasks if task.is_organic]

    @property
    def active_organic_tasks(self) -> list[RouteTask]:
        return [
            task
            for task in self.organic_tasks
            if not bool(task.metadata.get("filteredOut", False))
        ]

    @property
    def work_complete(self) -> bool:
        required = self.required_tasks
        if self.stop_type != StopType.EXOBIOLOGY:
            return bool(required) and all(task.complete for task in required)

        policy = self.completion_policy or CompletionPolicy.LISTED_TARGETS
        if policy == CompletionPolicy.MANUAL:
            return False
        if policy == CompletionPolicy.ANY_TARGET:
            return any(task.complete for task in required)
        if not required or not all(task.complete for task in required):
            return False
        if policy == CompletionPolicy.ALL_SIGNALS:
            expected = int(self.biological_signal_count or 0)
            filtered = sum(
                1 for task in self.organic_tasks
                if bool(task.metadata.get("filteredOut", False))
            )
            effective_expected = max(0, expected - filtered)
            completed_organic = sum(1 for task in self.active_organic_tasks if task.complete)
            return effective_expected > 0 and completed_organic >= effective_expected
        return True

    @property
    def display_name(self) -> str:
        return self.label or self.body or self.system

    @property
    def secondary_target(self) -> str:
        return self.station or self.settlement or self.body

    @property
    def body_key(self) -> str:
        if self.system_address is not None and self.body_id is not None:
            return f"{self.system_address}:{self.body_id}"
        return f"{self.system.casefold()}:{self.body.casefold()}"

    def reset(self) -> None:
        self.status = ProgressStatus.PENDING
        self.arrived = False
        self.operation_phase = OperationPhase.EN_ROUTE
        for task in self.tasks:
            task.reset()


@dataclass
class Route:
    id: str
    name: str
    route_type: str
    source_format: str
    stops: list[RouteStop]
    source_path: str = ""
    schema_version: int = 3
    settings: RouteSettings = field(default_factory=RouteSettings)
    metadata: dict[str, Any] = field(default_factory=dict)


# Compatibility names used by the original 0.1.x code.
Task = RouteTask
Stop = RouteStop
RouteDocument = Route
