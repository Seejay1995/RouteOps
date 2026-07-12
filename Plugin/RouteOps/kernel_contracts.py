from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


class KernelCommandType:
    SELECT_SYSTEM = "select-system"
    SELECT_BODY = "select-body"
    SELECT_TASK = "select-task"
    PREVIOUS_TARGET = "previous-target"
    NEXT_TARGET = "next-target"
    COMPLETE_CURRENT = "complete-current"
    SKIP_CURRENT = "skip-current"


@dataclass(frozen=True)
class KernelCommand:
    command_type: str
    payload: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class KernelResult:
    actions: tuple[dict[str, Any], ...] = ()
    changed: bool = False
    error: str = ""

    @property
    def success(self) -> bool:
        return not self.error

    @classmethod
    def from_actions(cls, actions: list[dict[str, Any]]) -> "KernelResult":
        copied = tuple(dict(action) for action in actions)
        return cls(actions=copied, changed=bool(copied))

    @classmethod
    def failure(cls, message: str) -> "KernelResult":
        return cls(error=message)
