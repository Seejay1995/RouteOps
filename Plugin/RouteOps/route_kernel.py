from __future__ import annotations

from typing import Any, Callable

from kernel_contracts import KernelCommand, KernelCommandType, KernelResult
from route_engine import RouteEngine
from route_session import RouteSession


class RouteKernel:
    """Stable command and journal boundary over a route session."""

    def __init__(self, runtime: RouteSession | RouteEngine) -> None:
        self._session