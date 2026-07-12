from __future__ import annotations

from typing import Any

import RouteOps as legacy
from kernel_contracts import KernelCommand, KernelCommandType, KernelResult
from route_kernel import RouteKernel


_UI_COMMANDS: dict[str, tuple[str, dict[str, Any]]] = {
    "PREVTARGET": (KernelCommandType.PREVIOUS_TARGET, {}),
    "NEXTTARGET": (KernelCommandType.NEXT_TARGET, {}),
    "GUIDANCE": (KernelCommandType.CYCLE_GUIDANCE, {}),
    "ORDER": (KernelCommandType.CYCLE_BODY_ORDER, {}),
    "CHOOSETARGET": (KernelCommandType.CHOOSE_SELECTED_BODY, {}),
    "FINISHBODY": (KernelCommandType.COMPLETE_CURRENT, {}),
    "SKIPBODY": (KernelCommandType.SKIP_CURRENT, {}),
    "REOPENBODY": (KernelCommandType.REOPEN_STOP, {}),
    "TASKDONE": (KernelCommandType.COMPLETE_SELECTED_TASK, {}),
    "SKIPPREVIEW": (KernelCommandType.PREVIEW_SELECTED_TASK_SKIP, {}),
    "SKIPCONFIRM": (KernelCommandType.CONFIRM_PENDING_SKIP, {}),
    "SKIPCANCEL": (KernelCommandType.CANCEL_PENDING_SKIP, {}),
    "SKIPUNDO": (KernelCommandType.UNDO_LAST_SKIP, {}),
    "SKIPREASON": (KernelCommandType.CYCLE_SKIP_REASON, {}),
    "DIFFICULTY": (KernelCommandType.CYCLE_SELECTED_DIFFICULTY, {}),
    "TASKREOPEN": (KernelCommandType.REOPEN_SELECTED_TASK, {}),
    "RESETSTOP": (KernelCommandType.RESET_STOP, {}),
    "EXOMODE": (KernelCommandType.ENABLE_EXOBIOLOGY_MODE, {}),
    "BACTERIUM": (KernelCommandType.TOGGLE_GENUS_FILTER, {"genus": "Bacterium"}),
    "SHOWEXCLUDED": (KernelCommandType.TOGGLE_SHOW_EXCLUDED, {}),
    "ROUTEVIEW": (KernelCommandType.TOGGLE_ROUTE_VIEW, {}),
    "TASKINCLUDE": (KernelCommandType.SET_SELECTED_TASK_INCLUSION, {"mode": "include"}),
    "TASKEXCLUDE": (KernelCommandType.SET_SELECTED_TASK_INCLUSION, {"mode": "exclude"}),
    "TASKDEFAULT": (KernelCommandType.SET_SELECTED_TASK_INCLUSION, {"mode": "default"}),
    "BODYINCLUDE": (KernelCommandType.SET_SELECTED_BODY_INCLUSION, {"mode": "include"}),
    "BODYEXCLUDE": (KernelCommandType.SET_SELECTED_BODY_INCLUSION, {"mode": "exclude"}),
    "BODYDEFAULT": (KernelCommandType.SET_SELECTED_BODY_INCLUSION, {"mode": "default"}),
}


class KernelRouteOpsApplication(legacy.RouteOpsApplication):
    """EDDiscovery adapter that routes mutations through RouteKernel."""

    def __init__(self, client: Any) -> None:
        super().__init__(client)
        self.kernel: RouteKernel | None = None

    def load_route(self, path: str, quiet: bool = False) -> None:
        super().load_route(path, quiet=quiet)
        self.kernel = RouteKernel(self.engine) if self.engine else None

    def _accept_kernel_result(self, result: KernelResult) -> None:
        if not result.success:
            self.last_message = f"Kernel command failed: {result.error}"
            self.refresh_ui()
            return
        self.process_actions(list(result.actions))

    def _execute(self, command_type: str, payload: dict[str, Any] | None = None) -> bool:
        if not self.kernel:
            return False
        self._accept_kernel_result(self.kernel.execute(KernelCommand(command_type, payload or {})))
        return True

    def handle_ui_event(self, message: dict[str, Any]) -> None:
        control = str(message.get("control", ""))
        row_commands = {
            "DGV": KernelCommandType.SELECT_SYSTEM,
            "BODIES": KernelCommandType.SELECT_BODY,
            "ORGANISMS": KernelCommandType.SELECT_TASK,
        }
        if control in row_commands:
            row = self._extract_row_index(message)
            if row is not None and row >= 0:
                self._execute(row_commands[control], {"index": row})
            return
        command = _UI_COMMANDS.get(control)
        if command:
            self._execute(command[0], command[1])
            return
        super().handle_ui_event(message)

    def handle_message(self, message: dict[str, Any]) -> bool:
        response_type = message.get("responsetype")
        if response_type in {"terminate", "uievent"}:
            return super().handle_message(message)
        if response_type == "journalpush" and self.kernel:
            entry = message.get("journalEntry")
            if isinstance(entry, dict):
                result = self.kernel.handle_journal(entry)
                if result.actions:
                    self._accept_kernel_result(result)
            return True
        if response_type in {"historypush", "historyload"} and self.kernel:
            entries = message.get("journalEntries", message.get("entries", message.get("history", [])))
            if isinstance(message.get("journalEntry"), dict):
                entries = [message["journalEntry"]]
            actions: list[dict[str, Any]] = []
            if isinstance(entries, list):
                for entry in entries:
                    if isinstance(entry, dict):
                        actions.extend(self.kernel.hydrate_journal_knowledge(entry).actions)
            if actions:
                self.last_message = f"Hydrated body and species manifests from {len(entries)} historical journal event(s)."
                self.persist()
                self.refresh_ui()
            return True
        return True


def main() -> int:
    legacy.RouteOpsApplication = KernelRouteOpsApplication
    return legacy.main()


if __name__ == "__main__":
    raise SystemExit(main())
