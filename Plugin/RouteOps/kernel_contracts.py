from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Mapping


class KernelCommandType:
    SELECT_SYSTEM = "select-system"
    SELECT_BODY = "select-body"
    SELECT_TASK = "select-task"
    PREVIOUS_TARGET = "previous-target"
    NEXT_TARGET = "next-target"
    CYCLE_GUIDANCE = "cycle-guidance"
    CYCLE_BODY_ORDER = "cycle-body-order"
    CHOOSE_SELECTED_BODY = "choose-selected-body"
    COMPLETE_CURRENT = "complete-current"
    SKIP_CURRENT = "skip-current"
    REOPEN_STOP = "reopen-stop"
    COMPLETE_SELECTED_TASK = "complete-selected-task"
    PREVIEW_SELECTED_TASK_SKIP = "preview-selected-task-skip"
    CONFIRM_PENDING_SKIP = "confirm-pending-skip"
    CANCEL_PENDING_SKIP = "cancel-pending-skip"
    UNDO_LAST_SKIP = "undo-last-skip"
    CYCLE_SKIP_REASON = "cycle-skip-reason"
    CYCLE_SELECTED_DIFFICULTY = "cycle-selected-difficulty"
    REOPEN_SELECTED_TASK = "reopen-selected-task"
    RESET_STOP = "reset-stop"
    ENABLE_EXOBIOLOGY_MODE = "enable-exobiology-mode"
    TOGGLE_GENUS_FILTER = "toggle-genus-filter"
    TOGGLE_SHOW_EXCLUDED = "toggle-show-excluded"
    TOGGLE_ROUTE_VIEW = "toggle-route-view"
    SET_SELECTED_TASK_INCLUSION = "set-selected-task-inclusion"
    SET_SELECTED_BODY_INCLUSION = "set-selected-body-inclusion"

    ALL = frozenset(
        {
            SELECT_SYSTEM, SELECT_BODY, SELECT_TASK, PREVIOUS_TARGET, NEXT_TARGET,
            CYCLE_GUIDANCE, CYCLE_BODY_ORDER, CHOOSE_SELECTED_BODY,
            COMPLETE_CURRENT, SKIP_CURRENT, REOPEN_STOP, COMPLETE_SELECTED_TASK,
            PREVIEW_SELECTED_TASK_SKIP, CONFIRM_PENDING_SKIP, CANCEL_PENDING_SKIP,
            UNDO_LAST_SKIP, CYCLE_SKIP_REASON, CYCLE_SELECTED_DIFFICULTY,
            REOPEN_SELECTED_TASK, RESET_STOP, ENABLE_EXOBIOLOGY_MODE,
            TOGGLE_GENUS_FILTER, TOGGLE_SHOW_EXCLUDED, TOGGLE_ROUTE_VIEW,
            SET_SELECTED_TASK_INCLUSION, SET_SELECTED_BODY_INCLUSION,
        }
    )


@dataclass(frozen=True)
class KernelCommand:
    command_type: str
    payload: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "payload", MappingProxyType(dict(self.payload)))


@dataclass(frozen=True)
class KernelResult:
    actions: tuple[Mapping[str, Any], ...] = ()
    changed: bool = False
    error: str = ""

    def __post_init__(self) -> None:
        frozen = tuple(MappingProxyType(dict(action)) for action in self.actions)
        object.__setattr__(self, "actions", frozen)

    @property
    def success(self) -> bool:
        return not self.error

    @classmethod
    def from_actions(cls, actions: list[dict[str, Any]]) -> "KernelResult":
        return cls(actions=tuple(actions), changed=bool(actions))

    @classmethod
    def failure(cls, message: str) -> "KernelResult":
        return cls(error=message)
