from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


class KernelCommandType:
    SELECT_SYSTEM = "select-system"
    SELECT_BODY = "select-body"
    SELECT_TASK = "select-task"
    PREVIOUS_TARGET = "previous-target"
    NEXT_TARGET = "next-target"
    CYCLE_GUIDANCE = "cycle-guidance"
    CYCLE_BODY_ORDER = "cycle-body-order"
    CH