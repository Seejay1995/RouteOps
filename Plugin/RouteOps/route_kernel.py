from __future__ import annotations

from typing import Any, Callable

from kernel_contracts import KernelCommand, KernelCommandType, KernelResult
from route_engine import RouteEngine


class RouteKernel:
    """Stable application boundary over the legacy RouteEngine.

    M1 introduces this facade without changing route behavior. EDDiscovery,
    persistence, and UI adapters should depend on this boundary rather than
    calling RouteEngine mutation methods directly.
    """

    def __init__(self, engine: RouteEngine) -> None:
        self._engine = engine

    @property
    def