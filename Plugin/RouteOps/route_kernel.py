from __future__ import annotations

from typing import Any, Callable

from kernel_contracts import KernelCommand, KernelCommandType, KernelResult
from route_engine import RouteEngine


class RouteKernel:
    """Stable application boundary over the legacy RouteEngine.

    M1 introduces this facade without changing route behavior. EDDiscovery,
    persistence, and UI adapters should depend on this boundary rather than
    calling RouteEngine methods directly.
    """

    def __init__(self, engine: RouteEngine) -> None:
        self._engine = engine

    @property
    def engine(self) -> RouteEngine:
        return self._engine

    def execute(self, command: KernelCommand) -> KernelResult:
        handlers: dict[str, Callable[[dict[str, Any]], list[dict[str, Any]]]] = {
            KernelCommandType.SELECT_SYSTEM: lambda payload: self._engine.select_system(int(payload.get("index", 0))),
            KernelCommandType.SELECT_BODY: lambda payload: self._engine.select_system_body(int(payload.get("index", 0))),
            KernelCommandType.SELECT_TASK: lambda payload: self._engine.select_task(int(payload.get("index", 0))),
            KernelCommandType.PREVIOUS_TARGET: lambda payload: self._engine.previous_navigation_target(),
            KernelCommandType.NEXT_TARGET: lambda payload: self._engine.next_navigation_target(),
            KernelCommandType.COMPLETE_CURRENT: lambda payload: self._engine.complete_current(),
            KernelCommandType.SKIP_CURRENT: lambda payload: self._engine.skip_current(),
        }
        handler = handlers.get(command.command_type)
        if handler is None:
            return KernelResult.failure(f"Unsupported kernel command: {command.command_type}")
        try:
            return KernelResult.from_actions(handler(dict(command.payload)))
        except (TypeError, ValueError) as exc:
            return KernelResult.failure(str(exc))

    def handle_journal(self, entry: dict[str, Any]) -> KernelResult:
        return KernelResult.from_actions(self._engine.handle_journal(entry))

    def hydrate_journal_knowledge(self, entry: dict[str, Any]) -> KernelResult:
        return KernelResult.from_actions(self._engine.hydrate_journal_knowledge(entry))

    def snapshot(self) -> dict[str, Any]:
        return self._engine.to_state()
