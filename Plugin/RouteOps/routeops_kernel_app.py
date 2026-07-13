from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import RouteOps as legacy
from kernel_contracts import KernelCommand, KernelCommandType, KernelResult
from route_compiler import RouteCompiler
from route_importer import ImportResult
from route_kernel import RouteKernel
from route_library import RouteLibrary
from route_models import Route
from route_session import RouteSession, RouteSessionDefinition
from runtime_health import RuntimeHealthReport, RuntimeHealthService
from session_storage import FileSessionStorage, SessionStorage


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
    """EDDiscovery adapter using compiler, session, storage, health, library, and kernel boundaries."""

    def __init__(self, client: Any) -> None:
        super().__init__(client)
        self.compiler = RouteCompiler()
        self.compiled_route: Route | None = None
        self.session: RouteSession | None = None
        self.kernel: RouteKernel | None = None
        configured_root = client.config.get("session_state_root", "")
        plugin_directory = Path(__file__).resolve().parent
        self.session_storage: SessionStorage = FileSessionStorage.for_plugin(
            plugin_directory,
            configured_root,
        )
        self.health_service = RuntimeHealthService(plugin_directory, self.session_storage)
        self.health_report: RuntimeHealthReport | None = None
        self.route_library = RouteLibrary.from_config(client.config)
        configured_search_roots = client.config.get("route_library_roots", [])
        self.route_library_roots = [
            Path(str(item)).expanduser()
            for item in configured_search_roots
            if str(item).strip()
        ] if isinstance(configured_search_roots, list) else []
        self.route_library_roots.extend([plugin_directory.parent.parent, plugin_directory])

    def start(self) -> None:
        self.route_library.refresh_availability(self.route_library_roots)
        self.route_library.save_to_config(self.client.config)
        if self.route_path and not Path(self.route_path).is_file():
            recovered = self._library_entry_for_path(self.route_path)
            if recovered and recovered.available:
                self.route_path = recovered.path
                self.client.config["route_path"] = recovered.path
                self.last_message = f"Recovered moved route: {recovered.name}."
        self.health_report = self.health_service.run(self.route_path)
        if self.health_report.overall_status != "healthy" and not self.last_message.startswith("Recovered moved route"):
            self.last_message = self.health_report.summary
        super().start()

    def _compile_import_result(self, source: str) -> ImportResult:
        compiled = self.compiler.compile_source(source)
        self.compiled_route = compiled.route
        return ImportResult(
            route=deepcopy(compiled.route) if compiled.route is not None else None,
            warnings=list(compiled.warnings),
            errors=list(compiled.errors),
        )

    def load_route(self, path: str, quiet: bool = False) -> None:
        self.compiled_route = None
        self.session = None
        self.kernel = None
        original_import_route = legacy.import_route
        original_load_state = legacy.load_state
        legacy.import_route = self._compile_import_result
        legacy.load_state = lambda route_path, fallback_dir=None: self.session_storage.load(route_path)
        try:
            super().load_route(path, quiet=quiet)
        finally:
            legacy.import_route = original_import_route
            legacy.load_state = original_load_state
        if self.engine and self.compiled_route:
            definition = RouteSessionDefinition.from_route(self.compiled_route)
            self.session = RouteSession(definition, self.engine)
            self.kernel = RouteKernel(self.session)
            self.route_library.record(self.engine.route, self.route_path)
            self.health_report = self.health_service.run(self.route_path)
            self.persist()

    def persist(self) -> None:
        self.route_library.save_to_config(self.client.config)
        if self.session and self.route_path:
            try:
                self.session_storage.save(self.route_path, self.session.snapshot())
            except OSError as exc:
                self.last_message = f"State save failed: {exc}"
            self.client.config["route_path"] = self.route_path
            engine = self.session.engine
            self.client.config["exobio_excluded_genera"] = list(engine.route.settings.excluded_organism_genera)
            self.client.config["exobio_show_excluded"] = engine.route.settings.show_excluded_organisms
            self.client.config["exobio_route_view"] = engine.route.settings.route_view_mode
            self.client.config["navigation_guidance"] = engine.guidance_mode
            self.client.config["body_order_mode"] = engine.body_order_mode
            self.client.config["default_skip_reason"] = engine.route.settings.default_skip_reason
            return
        super().persist()
        self.route_library.save_to_config(self.client.config)

    def _update_buttons(self) -> None:
        super()._update_buttons()
        self.client.ui_enable("HEALTH", True)
        self.client.ui_enable("HEALTHEXPORT", True)
        self.client.ui_enable("ROUTELIBRARY", True)
        recent = self.route_library.most_recent(available_only=True)
        self.client.ui_enable("RECENTROUTE", recent is not None)
        self.client.ui_set("RECENTROUTE", f"Recent: {recent.name}" if recent else "Recent Route")

    def run_health_check(self, export: bool = False) -> RuntimeHealthReport:
        self.health_report = self.health_service.run(self.route_path)
        self.last_message = self.health_report.summary
        if export:
            try:
                destination = self.health_service.export(self.health_report)
                self.last_message = f"Runtime health exported: {destination}"
            except OSError as exc:
                self.last_message = f"Runtime health export failed: {exc}"
        self.refresh_ui()
        self.client.ui_set_escape("DETAIL", self.health_report.render_text())
        return self.health_report

    def show_route_library(self) -> None:
        self.route_library.refresh_availability(self.route_library_roots)
        self.route_library.save_to_config(self.client.config)
        available = sum(entry.available for entry in self.route_library.entries)
        self.last_message = f"Route library: {available}/{len(self.route_library.entries)} route(s) available."
        self.refresh_ui()
        self.client.ui_set_escape("DETAIL", self.route_library.render_text())

    def open_recent_route(self) -> bool:
        self.route_library.refresh_availability(self.route_library_roots)
        entry = self.route_library.most_recent(available_only=True)
        if entry is None:
            self.last_message = "No available recent route was found. Use Load Route to add one."
            self.refresh_ui()
            return False
        self.load_route(entry.path)
        return self.engine is not None

    def _library_entry_for_path(self, path: str):
        normalized = str(Path(path).expanduser())
        for entry in self.route_library.entries:
            if entry.path == path or str(Path(entry.path).expanduser()) == normalized or entry.recovered_from == path:
                return entry
        return None

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
        if control == "HEALTH":
            self.run_health_check(export=False)
            return
        if control == "HEALTHEXPORT":
            self.run_health_check(export=True)
            return
        if control == "ROUTELIBRARY":
            self.show_route_library()
            return
        if control == "RECENTROUTE":
            self.open_recent_route()
            return
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
