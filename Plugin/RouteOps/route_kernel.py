from __future__ import annotations

from typing import Any, Callable

from kernel_contracts import KernelCommand, KernelCommandType, KernelResult
from route_engine import RouteEngine
from route_session import RouteSession


class RouteKernel:
    """Stable command and journal boundary over a route session."""

    def __init__(self, runtime: RouteSession | RouteEngine) -> None:
        self._legacy_snapshot = isinstance(runtime, RouteEngine)
        self._session = RouteSession.attach(runtime) if self._legacy_snapshot else runtime
        self._engine = self._session.engine

    @property
    def session(self) -> RouteSession:
        return self._session

    @property
    def engine(self) -> RouteEngine:
        return self._engine

    def execute(self, command: KernelCommand) -> KernelResult:
        payload = dict(command.payload)
        handlers: dict[str, Callable[[], list[dict[str, Any]]]] = {
            KernelCommandType.SELECT_SYSTEM: lambda: self._engine.select_system(int(payload.get("index", 0))),
            KernelCommandType.SELECT_BODY: lambda: self._engine.select_system_body(int(payload.get("index", 0))),
            KernelCommandType.SELECT_TASK: lambda: self._engine.select_task(int(payload.get("index", 0))),
            KernelCommandType.PREVIOUS_TARGET: self._engine.previous_navigation_target,
            KernelCommandType.NEXT_TARGET: self._engine.next_navigation_target,
            KernelCommandType.CYCLE_GUIDANCE: self._engine.cycle_guidance_mode,
            KernelCommandType.CYCLE_BODY_ORDER: self._engine.cycle_body_order_mode,
            KernelCommandType.CHOOSE_SELECTED_BODY: self._engine.choose_selected_body,
            KernelCommandType.COMPLETE_CURRENT: self._engine.complete_current,
            KernelCommandType.SKIP_CURRENT: self._engine.skip_current,
            KernelCommandType.REOPEN_STOP: self._engine.reopen_stop,
            KernelCommandType.COMPLETE_SELECTED_TASK: self._engine.complete_selected_task,
            KernelCommandType.PREVIEW_SELECTED_TASK_SKIP: self._engine.preview_selected_task_skip,
            KernelCommandType.CONFIRM_PENDING_SKIP: self._engine.confirm_pending_skip,
            KernelCommandType.CANCEL_PENDING_SKIP: self._engine.cancel_pending_skip,
            KernelCommandType.UNDO_LAST_SKIP: self._engine.undo_last_skip,
            KernelCommandType.CYCLE_SKIP_REASON: self._engine.cycle_skip_reason,
            KernelCommandType.CYCLE_SELECTED_DIFFICULTY: self._engine.cycle_selected_difficulty,
            KernelCommandType.REOPEN_SELECTED_TASK: self._engine.reopen_selected_task,
            KernelCommandType.RESET_STOP: self._engine.reset_stop,
            KernelCommandType.ENABLE_EXOBIOLOGY_MODE: self._engine.enable_exobiology_mode,
            KernelCommandType.TOGGLE_GENUS_FILTER: lambda: self._engine.toggle_genus_filter(str(payload.get("genus", ""))),
            KernelCommandType.TOGGLE_SHOW_EXCLUDED: self._engine.toggle_show_excluded,
            KernelCommandType.TOGGLE_ROUTE_VIEW: self._engine.toggle_route_view,
            KernelCommandType.SET_SELECTED_TASK_INCLUSION: lambda: self._engine.set_selected_task_inclusion(str(payload.get("mode", "default"))),
            KernelCommandType.SET_SELECTED_BODY_INCLUSION: lambda: self._engine.set_selected_body_inclusion(str(payload.get("mode", "default"))),
            KernelCommandType.SET_SELECTED_DIFFICULTY: lambda: self._engine.set_selected_difficulty(str(payload.get("value", ""))),
            KernelCommandType.SET_DEFAULT_SKIP_REASON: lambda: self._engine.set_default_skip_reason(str(payload.get("value", ""))),
        }
        handler = handlers.get(command.command_type)
        if handler is None:
            return KernelResult.failure(f"Unsupported kernel command: {command.command_type}")
        try:
            return KernelResult.from_actions(handler())
        except (TypeError, ValueError) as exc:
            return KernelResult.failure(str(exc))

    def handle_journal(self, entry: dict[str, Any]) -> KernelResult:
        return KernelResult.from_actions(self._engine.handle_journal(entry))

    def hydrate_journal_knowledge(self, entry: dict[str, Any]) -> KernelResult:
        return KernelResult.from_actions(self._engine.hydrate_journal_knowledge(entry))

    def snapshot(self) -> dict[str, Any]:
        if self._legacy_snapshot:
            return self._engine.to_state()
        return self._session.snapshot()
