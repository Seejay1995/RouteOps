from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import threading
import time
from copy import deepcopy
from pathlib import Path
from typing import Any

import RouteOps as legacy
import spansh_client
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


# Right-click context menus. Each entry is (tag, menu-text). Action tags reuse the
# _UI_COMMANDS keys; "DIFF:<value>" and "REASON:<value>" tags carry a selectable
# value routed to the SET_SELECTED_DIFFICULTY / SET_DEFAULT_SKIP_REASON commands.
_ORGANISMS_MENU: list[tuple[str, str]] = [
    ("TASKDONE", "Complete species"),
    ("SKIPPREVIEW", "Preview skip"),
    ("SKIPCONFIRM", "Confirm skip"),
    ("SKIPCANCEL", "Cancel skip"),
    ("SKIPUNDO", "Undo last skip"),
    ("TASKREOPEN", "Reopen species"),
    ("TASKINCLUDE", "Include species"),
    ("TASKEXCLUDE", "Exclude species"),
    ("TASKDEFAULT", "Reset species filter"),
    ("DIFF:easy", "Difficulty: Easy"),
    ("DIFF:normal", "Difficulty: Normal"),
    ("DIFF:hard", "Difficulty: Hard"),
    ("DIFF:very-hard", "Difficulty: Very hard"),
    ("DIFF:unknown", "Difficulty: Unknown"),
    ("REASON:too-difficult", "Skip reason: Too difficult"),
    ("REASON:low-value", "Skip reason: Low value"),
    ("REASON:terrain", "Skip reason: Terrain"),
    ("REASON:too-far", "Skip reason: Too far"),
    ("REASON:already-sampled", "Skip reason: Already sampled"),
    ("REASON:time-limit", "Skip reason: Time limit"),
    ("REASON:preference", "Skip reason: Preference"),
    ("REASON:other", "Skip reason: Other"),
]
_BODIES_MENU: list[tuple[str, str]] = [
    ("CHOOSETARGET", "Choose as target"),
    ("FINISHBODY", "Finish body"),
    ("SKIPBODY", "Skip body"),
    ("REOPENBODY", "Reopen body"),
    ("BODYINCLUDE", "Include body"),
    ("BODYEXCLUDE", "Exclude body"),
    ("BODYDEFAULT", "Reset body filter"),
    ("RESETSTOP", "Reset body"),
]
_CARGO_MENU: list[tuple[str, str]] = [
    ("CARGO_COPYDEST", "Copy destination system"),
    ("CARGO_COPYSRC", "Copy buy (source) system"),
    ("CARGO_SETCUR", "Set as current hop"),
    ("CARGO_SKIP", "Skip / un-skip this hop"),
]

# Controls shown only in Exobiology mode vs only in Colonisation mode. The mode
# switcher (MODEBAR) toggles these via ui_visible so each modality gets the whole
# panel (EDDiscovery ZMQ panels have no native tabs). MODEBAR itself is always shown.
_EXO_VIEW = ("DGV", "BODIES", "ORGANISMS", "HEADER", "DETAIL", "GENBAR", "TOOLBAR")
_COLONY_VIEW = ("COLBAR", "COLGRID")
_CARGO_VIEW = ("CARGOBAR", "CARGOGRID")
# The triage/body button bars are retired in favour of the grid right-click menus,
# and the individual route/nav/diagnostics buttons are folded into the toolbar
# dropdowns (ROUTEMENU/NAVMENU/DIAGMENU). Keep the controls defined (so button-state
# code keeps working) but never show them.
_ALWAYS_HIDDEN = (
    "TRIAGEBAR", "BODYBAR",
    "LOAD", "RECENTROUTE", "ROUTELIBRARY", "RELOAD",
    "NAVCOPY", "PREVTARGET", "NEXTTARGET",
    "HEALTH", "HEALTHEXPORT", "DEBUGBUNDLE",
)


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
        # Spansh generation (worker thread -> main-loop pump).
        self._spansh_thread: threading.Thread | None = None
        self._spansh_result: str | None = None
        self._spansh_error: str | None = None
        self._spansh_status: str = ""
        self._spansh_status_shown: str = ""
        # Colonisation supply sourcing (worker thread -> main-loop pump).
        self._colony_thread: threading.Thread | None = None
        self._colony_result: tuple[dict[str, Any], list[dict[str, Any]]] | None = None
        self._colony_error: str | None = None
        self._colony_status: str = ""
        self._colony_status_shown: str = ""
        self._colony_prefilled = False
        # Cargo (trade) routing (worker thread -> main-loop pump).
        self._cargo_thread: threading.Thread | None = None
        self._cargo_result: dict[str, Any] | None = None
        self._cargo_error: str | None = None
        self._cargo_status: str = ""
        self._cargo_status_shown: str = ""
        self._cargo_prefilled = False
        self._cargo_pad_large = True
        self._cargo_planetary = True
        self._cargo_sys_prefill = ""
        # Live trade-run tracking: the generated route + which hop is in progress.
        self._cargo_route: dict[str, Any] | None = None
        self._cargo_hop = 0
        self._cargo_row_hops: list[int | None] = []
        self._cargo_skipped: set[int] = set()
        self._context_menus_registered = False
        self.mode = "exo"
        # Live telemetry state (populated from EDDiscovery edduievent/newtarget pushes).
        self.telemetry_line = ""
        self._telemetry_displayed = ""
        self._telemetry_last_refresh = 0.0
        self._tele_body: str | None = None
        self._tele_dest: str | None = None
        self._tele_edd_target: str | None = None
        self._tele_fuel: float | None = None
        self._tele_cargo: int | None = None

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

    @staticmethod
    def _is_menu_tag(tag: Any) -> bool:
        return isinstance(tag, str) and (
            tag in _UI_COMMANDS or tag.startswith("DIFF:") or tag.startswith("REASON:")
        )

    def _handle_context_menu(self, control: str, tag: str, row: int | None) -> None:
        # Select the right-clicked row first so the command acts on it.
        if row is not None and row >= 0:
            select = KernelCommandType.SELECT_BODY if control == "BODIES" else KernelCommandType.SELECT_TASK
            self._execute(select, {"index": row})
        if tag.startswith("DIFF:"):
            self._execute(KernelCommandType.SET_SELECTED_DIFFICULTY, {"value": tag[len("DIFF:"):]})
            return
        if tag.startswith("REASON:"):
            self._execute(KernelCommandType.SET_DEFAULT_SKIP_REASON, {"value": tag[len("REASON:"):]})
            return
        # Finish/Skip act on the *current* body, so make the selected row current first.
        if control == "BODIES" and tag in ("FINISHBODY", "SKIPBODY"):
            self._execute(KernelCommandType.CHOOSE_SELECTED_BODY, {})
        command = _UI_COMMANDS.get(tag)
        if command:
            self._execute(command[0], command[1])

    def handle_ui_event(self, message: dict[str, Any]) -> None:
        control = str(message.get("control", ""))
        # Toolbar dropdown menus: a Button-type item fires DropDownButtonPressed with
        # data=<tag>. Re-dispatch the tag as if that toolbar button was clicked.
        event = str(message.get("event", ""))
        if event == "DropDownButtonPressed":
            tag = str(message.get("data") or "")
            try:
                self.client.ui_close_drop_down_button()
            except Exception:  # noqa: BLE001
                pass
            if tag:
                self.handle_ui_event({"control": tag})
            return
        if event == "DropDownButtonClosed":
            return
        if control == "GENERATE":
            self._start_spansh_generation()
            return
        if control == "COLONISE":
            self._start_colonisation()
            return
        if control == "CARGO_GO":
            self._start_cargo()
            return
        if control == "CARGOPAD":
            self._cargo_pad_large = not self._cargo_pad_large
            self.client.ui_set(
                "CARGOPAD", "Pad: Large only" if self._cargo_pad_large else "Pad: Any pad"
            )
            return
        if control == "CARGOPLANET":
            self._cargo_planetary = not self._cargo_planetary
            self.client.ui_set(
                "CARGOPLANET", "Stations: Any" if self._cargo_planetary else "Stations: Space only"
            )
            return
        if control == "CARGO_SAVE":
            self._cargo_save()
            return
        if control == "CARGO_LOAD":
            self._cargo_load()
            return
        if control == "MODE_EXO":
            self.set_mode("exo")
            return
        if control == "MODE_COLONY":
            self.set_mode("colony")
            return
        if control == "MODE_CARGO":
            self.set_mode("cargo")
            return
        if control == "FIRSTS_RADAR":
            self._launch_firsts_radar()
            return
        tag = message.get("value")
        if control in ("BODIES", "ORGANISMS") and self._is_menu_tag(tag):
            self._handle_context_menu(control, tag, self._extract_row_index(message))
            return
        if control == "CARGOGRID" and isinstance(tag, str) and tag.startswith("CARGO_"):
            self._handle_cargo_menu(tag, self._extract_row_index(message))
            return
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

    def _handle_telemetry(self, message: dict[str, Any]) -> None:
        """Consume an EDDiscovery UIOverallStatus push and update the live status line."""
        if message.get("type") != "UIOverallStatus":
            return
        event = message.get("event")
        if not isinstance(event, dict):
            return
        prev_body, prev_dest = self._tele_body, self._tele_dest
        body = event.get("BodyName")
        self._tele_body = body.strip() if isinstance(body, str) and body.strip() else None
        dest = event.get("DestinationName")
        self._tele_dest = dest.strip() if isinstance(dest, str) and dest.strip() else None
        fuel = event.get("Fuel")
        self._tele_fuel = float(fuel) if isinstance(fuel, (int, float)) and fuel > 0 else None
        cargo = event.get("Cargo")
        self._tele_cargo = int(cargo) if isinstance(cargo, bool) is False and isinstance(cargo, int) and cargo >= 0 else None
        important = (self._tele_body != prev_body) or (self._tele_dest != prev_dest)
        self._refresh_telemetry(important=important)

    def _handle_new_target(self, message: dict[str, Any]) -> None:
        """Consume an EDDiscovery newtarget push (user changed the EDD target system)."""
        system = message.get("system")
        self._tele_edd_target = system.strip() if isinstance(system, str) and system.strip() else None
        self._refresh_telemetry(important=True)

    def _compose_telemetry(self) -> str:
        parts: list[str] = []
        if self._tele_body:
            parts.append(f"AT {self._tele_body}")
        if self._tele_dest:
            parts.append(f"NAV {self._tele_dest}")
        if self._tele_edd_target:
            parts.append(f"EDD-TGT {self._tele_edd_target}")
        if self._tele_fuel is not None:
            parts.append(f"FUEL {self._tele_fuel:.1f}t")
        if self._tele_cargo is not None:
            parts.append(f"CARGO {self._tele_cargo}t")
        return ("LIVE: " + "  |  ".join(parts)) if parts else ""

    def _refresh_telemetry(self, important: bool) -> None:
        line = self._compose_telemetry()
        self.telemetry_line = line
        if not self.engine:
            return
        if line == self._telemetry_displayed:
            return
        now = time.perf_counter()
        if important or (now - self._telemetry_last_refresh) >= 1.5:
            self._telemetry_last_refresh = now
            self._telemetry_displayed = line
            self.refresh_ui()

    def _capture_column_layouts(self) -> None:
        """Persist each grid's user column layout into config so it survives restarts."""
        layouts: dict[str, Any] = {}
        for grid in ("DGV", "BODIES", "ORGANISMS"):
            try:
                settings = self.client.ui_get_columns_setting(grid, timeout_ms=2000)
            except Exception:
                settings = None
            if settings:
                layouts[grid] = settings
        if layouts:
            self.client.config["column_layouts"] = layouts

    # --- Mode switching (in-panel "tabs") -----------------------------------
    def set_mode(self, mode: str) -> None:
        """Swap the whole panel between the Exobiology, Colonisation and Cargo views."""
        if mode not in ("exo", "colony", "cargo"):
            mode = "exo"
        self.mode = mode
        for name in _EXO_VIEW:
            self.client.ui_visible(name, mode == "exo")
        for name in _COLONY_VIEW:
            self.client.ui_visible(name, mode == "colony")
        for name in _CARGO_VIEW:
            self.client.ui_visible(name, mode == "cargo")
        for name in _ALWAYS_HIDDEN:
            self.client.ui_visible(name, False)
        self.client.ui_set("MODE_EXO", "[ Exobiology ]" if mode == "exo" else "Exobiology")
        self.client.ui_set("MODE_COLONY", "[ Colonisation ]" if mode == "colony" else "Colonisation")
        self.client.ui_set("MODE_CARGO", "[ Cargo ]" if mode == "cargo" else "Cargo")
        if mode == "cargo":
            self._prefill_cargo()
        elif mode == "colony":
            self._prefill_colony()

    def _launch_firsts_radar(self) -> None:
        """Open the bundled standalone Firsts Radar window as a detached process."""
        radar = Path(__file__).resolve().parent / "FirstsRadar" / "firsts_radar.py"
        if not radar.is_file():
            self.client.message_box(
                "Firsts Radar files were not found in the plugin folder.", "RouteOps", "OK", "Warning"
            )
            return
        # Prefer a system pythonw/python (has tkinter); fall back to the running interpreter.
        executable = shutil.which("pythonw") or shutil.which("python") or sys.executable
        flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        try:
            subprocess.Popen([executable, str(radar)], cwd=str(radar.parent), creationflags=flags, close_fds=True)
        except Exception as exc:  # noqa: BLE001 - surface to the panel, never crash it
            self.client.message_box(f"Could not open Firsts Radar: {exc}", "RouteOps", "OK", "Error")

    def _prefill_cargo(self) -> None:
        """Fill the cargo start SYSTEM and cargo capacity from the journal (once).

        The station is left blank on purpose: cargo generation finds the nearest
        real market itself (routing there for the first buy if needed).
        """
        try:
            import colonisation as col

            # Cargo capacity: fill once from the latest Loadout.
            if not self._cargo_prefilled:
                capacity = col.read_cargo_capacity()
                if capacity:
                    self.client.ui_set("CARGOCARGO", str(capacity))
                self._cargo_prefilled = True
            # Start system: keep it on your CURRENT location each time you enter cargo
            # mode, unless you've typed your own (so it never goes stale in deep space).
            current = col.read_current_system()
            field = str(self.client.ui_get("CARGOSYS") or "").strip()
            if current and (not field or field == self._cargo_sys_prefill):
                self.client.ui_set("CARGOSYS", current)
                self._cargo_sys_prefill = current
        except Exception:  # noqa: BLE001 - prefill is best-effort
            pass

    # --- Right-click context menus ------------------------------------------
    def register_context_menus(self) -> None:
        """Attach the per-row right-click menus to the BODIES/ORGANISMS grids."""
        if self._context_menus_registered:
            return
        self.client.ui_right_click_menu(
            "ORGANISMS", [tag for tag, _ in _ORGANISMS_MENU], [text for _, text in _ORGANISMS_MENU]
        )
        self.client.ui_right_click_menu(
            "BODIES", [tag for tag, _ in _BODIES_MENU], [text for _, text in _BODIES_MENU]
        )
        self.client.ui_right_click_menu(
            "CARGOGRID", [tag for tag, _ in _CARGO_MENU], [text for _, text in _CARGO_MENU]
        )
        self._context_menus_registered = True

    def _handle_cargo_menu(self, tag: str, row: int | None) -> None:
        route = self._cargo_route
        hops = (route or {}).get("hops") or []
        if row is None or row < 0 or row >= len(self._cargo_row_hops):
            return
        hop_idx = self._cargo_row_hops[row]
        if hop_idx is None or hop_idx >= len(hops):
            return
        hop = hops[hop_idx]
        destination = hop.get("destination") or {}
        source = hop.get("source") or {}
        if tag == "CARGO_COPYDEST":
            ok = self._copy_system(destination.get("system"))
            self.client.ui_set("CARGOSTATUS", f"Copied destination: {destination.get('system')}" + ("" if ok else " (copy failed)"))
        elif tag == "CARGO_COPYSRC":
            ok = self._copy_system(source.get("system"))
            self.client.ui_set("CARGOSTATUS", f"Copied buy system: {source.get('system')}" + ("" if ok else " (copy failed)"))
        elif tag == "CARGO_SETCUR":
            self._cargo_hop = hop_idx
            ok = self._copy_system(destination.get("system"))
            self.client.ui_set("CARGOSTATUS", f"Current hop {hop_idx + 1}: sell at {destination.get('system')}" + ("  (copied)" if ok else ""))
            self._render_cargo()
        elif tag == "CARGO_SKIP":
            if hop_idx in self._cargo_skipped:
                self._cargo_skipped.discard(hop_idx)
            else:
                self._cargo_skipped.add(hop_idx)
            self._render_cargo()

    def _cargo_routes_dir(self) -> Path:
        folder = Path(__file__).resolve().parent / "CargoRoutes"
        folder.mkdir(parents=True, exist_ok=True)
        return folder

    def _cargo_save(self) -> None:
        if not self._cargo_route:
            self.client.ui_set("CARGOSTATUS", "Generate a cargo route first, then Save.")
            return
        import cargo as cargo_mod

        folder = self._cargo_routes_dir()
        hops = self._cargo_route.get("hops") or []
        start = self._cargo_route.get("start_system") or "route"
        profit = cargo_mod.total_profit(self._cargo_route)
        stem = re.sub(r"[^A-Za-z0-9._-]+", "_", f"{start}_{len(hops)}hops_{profit // 1_000_000}M").strip("_")
        path = folder / f"{(stem or 'cargo_route')[:80]}.json"
        try:
            path.write_text(json.dumps({"kind": "routeops-cargo", "route": self._cargo_route}, indent=2), encoding="utf-8")
            self.client.ui_set("CARGOSTATUS", f"Saved: {path.name}  (in {folder})")
        except OSError as exc:
            self.client.ui_set("CARGOSTATUS", f"Save failed: {exc}")

    def _cargo_load(self) -> None:
        folder = self._cargo_routes_dir()
        response = self.client.open_file_dialog(
            str(folder), "Cargo routes|*.json|All files|*.*", "*.json"
        )
        if not (response and response.get("DialogResult") == "OK" and response.get("FileName")):
            return
        try:
            data = json.loads(Path(str(response["FileName"])).read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            self.client.ui_set("CARGOSTATUS", f"Load failed: {exc}")
            return
        route = data.get("route") if isinstance(data, dict) and data.get("kind") == "routeops-cargo" else data
        hops = (route or {}).get("hops") if isinstance(route, dict) else None
        if not hops:
            self.client.ui_set("CARGOSTATUS", "That file is not a saved cargo route.")
            return
        import cargo as cargo_mod

        self._cargo_route = route
        self._cargo_hop = 0
        self._cargo_skipped = set()
        self.set_mode("cargo")
        self._render_cargo()
        first_source = (hops[0].get("source") or {}).get("system") or route.get("start_system")
        copied = self._copy_system(first_source)
        self.client.ui_set(
            "CARGOSTATUS",
            f"Loaded {len(hops)} hops, {cargo_mod.total_profit(route):,} CR - go to {first_source}"
            + ("  (copied)" if copied else ""),
        )

    # --- Spansh route generation (threaded) ---------------------------------
    def _start_spansh_generation(self) -> None:
        thread = self._spansh_thread
        if thread is not None and thread.is_alive():
            self.client.ui_set("GENSTATUS", "Spansh generation already running...")
            return
        from_system = str(self.client.ui_get("GENFROM") or "").strip()
        if not from_system:
            self.client.ui_set("GENSTATUS", "Enter a start system to generate.")
            return
        params = self._read_spansh_params(from_system)
        self._spansh_result = None
        self._spansh_error = None
        self._spansh_status = "Contacting Spansh..."
        self._spansh_status_shown = ""
        self.client.ui_set("GENSTATUS", self._spansh_status)
        self.client.ui_enable("GENERATE", False)

        def worker() -> None:
            try:
                route = spansh_client.generate_exobiology(on_progress=self._set_spansh_status, **params)
                self._spansh_result = self._save_generated_route(route)
            except Exception as exc:  # noqa: BLE001 - surfaced to the panel via pump
                self._spansh_error = str(exc)

        self._spansh_thread = threading.Thread(target=worker, name="routeops-spansh", daemon=True)
        self._spansh_thread.start()

    def _read_spansh_params(self, from_system: str) -> dict[str, Any]:
        def number(control: str, default: Any) -> Any:
            raw = str(self.client.ui_get(control) or "").strip().replace(",", "")
            if not raw:
                return default
            try:
                return type(default)(float(raw))
            except (TypeError, ValueError):
                return default

        return {
            "from_system": from_system,
            "jump_range": number("GENRANGE", 50.0),
            "radius": number("GENRADIUS", 100.0),
            "min_value": number("GENMINVAL", 1_000_000),
            "max_results": number("GENMAX", 50),
            "loop": False,
            "use_mapping_value": True,
            "name": f"Spansh Exobiology from {from_system}",
        }

    def _set_spansh_status(self, message: str) -> None:
        # Runs on the worker thread: only store the string (the ZMQ socket is
        # single-threaded). The main-loop pump pushes it to the control.
        self._spansh_status = message

    def _save_generated_route(self, route: dict[str, Any]) -> str:
        folder = Path(__file__).resolve().parent / "GeneratedRoutes"
        folder.mkdir(parents=True, exist_ok=True)
        stem = re.sub(r"[^A-Za-z0-9._-]+", "_", str(route.get("name") or "spansh_route")).strip("_")
        path = folder / f"{(stem or 'spansh_route')[:80]}.json"
        path.write_text(json.dumps(route, indent=2), encoding="utf-8")
        return str(path)

    # --- Colonisation supply sourcing (threaded) ----------------------------
    def _start_colonisation(self) -> None:
        thread = self._colony_thread
        if thread is not None and thread.is_alive():
            self.client.ui_set("COLSTATUS", "Colony sourcing already running...")
            return
        cargo = self._read_colony_cargo()
        large_pad_only = str(self.client.ui_get("COLPAD") or "large").strip().lower() != "any"
        laden_range = self._read_float("COLLADEN")
        unladen_range = self._read_float("COLUNLADEN")
        self._colony_result = None
        self._colony_error = None
        self._colony_status = "Reading colony needs from journal..."
        self._colony_status_shown = ""
        self.client.ui_set("COLSTATUS", self._colony_status)
        self.client.ui_enable("COLONISE", False)

        def worker() -> None:
            try:
                import colonisation as col

                construction = col.read_latest_construction()
                if not construction or not construction.get("needs"):
                    self._colony_error = "No outstanding colony construction found in your journal."
                    return
                board = col.build_sourcing_board(
                    construction,
                    cargo_capacity=cargo,
                    large_pad_only=large_pad_only,
                    laden_range=laden_range,
                    unladen_range=unladen_range,
                    on_progress=self._set_colony_status,
                )
                self._colony_result = (construction, board)
            except Exception as exc:  # noqa: BLE001 - surfaced to the panel via pump
                self._colony_error = str(exc)

        self._colony_thread = threading.Thread(target=worker, name="routeops-colony", daemon=True)
        self._colony_thread.start()

    def _prefill_colony(self) -> None:
        """Fill colony cargo capacity and jump ranges from the journal (once)."""
        if self._colony_prefilled:
            return
        try:
            import colonisation as col

            capacity = col.read_cargo_capacity()
            if capacity:
                self.client.ui_set("COLCARGO", str(capacity))
            unladen = col.read_jump_range()
            if unladen:
                self.client.ui_set("COLUNLADEN", str(round(unladen, 1)))
                # Laden range isn't in the journal; seed a conservative estimate the
                # player can correct from the in-game FSD panel.
                self.client.ui_set("COLLADEN", str(round(unladen * 0.6, 1)))
            self._colony_prefilled = True
        except Exception:  # noqa: BLE001 - prefill is best-effort
            pass

    def _read_colony_cargo(self) -> int:
        return self._read_int("COLCARGO", 720)

    def _read_int(self, control: str, default: int) -> int:
        raw = str(self.client.ui_get(control) or "").strip().replace(",", "")
        if not raw:
            return default
        try:
            return max(1, int(float(raw)))
        except (TypeError, ValueError):
            return default

    def _read_float(self, control: str) -> float | None:
        raw = str(self.client.ui_get(control) or "").strip().replace(",", "")
        if not raw:
            return None
        try:
            value = float(raw)
        except (TypeError, ValueError):
            return None
        return value if value > 0 else None

    def _set_colony_status(self, message: str) -> None:
        # Worker thread: store only; the main-loop pump pushes it to the control.
        self._colony_status = message

    # --- Cargo (trade) routing (threaded) -----------------------------------
    def _start_cargo(self) -> None:
        thread = self._cargo_thread
        if thread is not None and thread.is_alive():
            self.client.ui_set("CARGOSTATUS", "Cargo routing already running...")
            return
        system = str(self.client.ui_get("CARGOSYS") or "").strip()
        station = str(self.client.ui_get("CARGOSTN") or "").strip()
        if not system:
            self.client.ui_set("CARGOSTATUS", "Enter a start system (station optional).")
            return
        cargo = self._read_int("CARGOCARGO", 720)
        max_hops = self._read_int("CARGOHOPS", 5)
        large_pad_only = self._cargo_pad_large
        planetary = self._cargo_planetary
        self._cargo_result = None
        self._cargo_error = None
        self._cargo_status = "Contacting Spansh..."
        self._cargo_status_shown = ""
        self.client.ui_set("CARGOSTATUS", self._cargo_status)
        self.client.ui_enable("CARGO_GO", False)

        def worker() -> None:
            try:
                route = spansh_client.generate_trade(
                    system=system,
                    station=station,
                    cargo=cargo,
                    max_hops=max_hops,
                    large_pad_only=large_pad_only,
                    allow_planetary=planetary,
                    on_progress=self._set_cargo_status,
                )
                self._cargo_result = route
            except Exception as exc:  # noqa: BLE001 - surfaced to the panel via pump
                self._cargo_error = str(exc)

        self._cargo_thread = threading.Thread(target=worker, name="routeops-cargo", daemon=True)
        self._cargo_thread.start()

    def _set_cargo_status(self, message: str) -> None:
        self._cargo_status = message

    def pump_background(self) -> None:
        """Called every main-loop iteration; drains worker-thread results safely."""
        self._pump_spansh()
        self._pump_colony()
        self._pump_cargo()

    def _pump_spansh(self) -> None:
        status = self._spansh_status
        if status and status != self._spansh_status_shown:
            self._spansh_status_shown = status
            self.client.ui_set("GENSTATUS", status)
        if self._spansh_error:
            error = self._spansh_error
            self._spansh_error = None
            self.client.ui_enable("GENERATE", True)
            self.client.ui_set("GENSTATUS", f"Failed: {error}")
            self.last_message = f"Spansh generation failed: {error}"
            self.refresh_ui()
            return
        if self._spansh_result:
            path = self._spansh_result
            self._spansh_result = None
            self.client.ui_enable("GENERATE", True)
            self.client.ui_set("GENSTATUS", "Route generated. Loading...")
            self.load_route(path)

    def _pump_colony(self) -> None:
        status = self._colony_status
        if status and status != self._colony_status_shown:
            self._colony_status_shown = status
            self.client.ui_set("COLSTATUS", status)
        if self._colony_error:
            error = self._colony_error
            self._colony_error = None
            self.client.ui_enable("COLONISE", True)
            self.client.ui_set("COLSTATUS", f"Failed: {error}")
            return
        if self._colony_result:
            construction, board = self._colony_result
            self._colony_result = None
            self.client.ui_enable("COLONISE", True)
            sourced = sum(1 for row in board if row.get("sources"))
            system = construction.get("system") or "colony"
            self.client.ui_set("COLSTATUS", f"{system}: {sourced}/{len(board)} sourced.")
            import colonisation as col

            self.set_mode("colony")
            self.client.ui_suspend("COLGRID")
            self.client.ui_clear("COLGRID")
            self.client.ui_add_set_rows("COLGRID", col.board_to_rows(board))
            self.client.ui_resume("COLGRID")

    def _pump_cargo(self) -> None:
        status = self._cargo_status
        if status and status != self._cargo_status_shown:
            self._cargo_status_shown = status
            self.client.ui_set("CARGOSTATUS", status)
        if self._cargo_error:
            error = self._cargo_error
            self._cargo_error = None
            self.client.ui_enable("CARGO_GO", True)
            self.client.ui_set("CARGOSTATUS", f"Failed: {error}")
            return
        if self._cargo_result:
            result = self._cargo_result
            self._cargo_result = None
            self.client.ui_enable("CARGO_GO", True)
            import cargo as cargo_mod

            hops = result.get("hops", [])
            profit = cargo_mod.total_profit(result)
            distance = cargo_mod.total_distance(result)
            start = result.get("start_station") or result.get("start_system") or ""
            per_hop = profit // len(hops) if hops else 0
            self.client.ui_set(
                "CARGOSTATUS",
                f"From {start}:  {len(hops)} hops  |  {profit:,} CR  |  {distance} ly loop  |  {per_hop:,} CR/hop",
            )
            # Arm live trade-run tracking and copy the first buy system to the clipboard.
            self._cargo_route = result
            self._cargo_hop = 0
            self._cargo_skipped = set()
            first_source = (hops[0].get("source") or {}) if hops else {}
            start_system = first_source.get("system") or result.get("start_system")
            copied = self._copy_system(start_system)
            if start_system:
                self.client.ui_set(
                    "CARGOSTATUS",
                    f"Go to {start_system} and buy  -  {len(hops)} hops, {profit:,} CR"
                    + ("  (copied)" if copied else ""),
                )
            self.set_mode("cargo")
            self._render_cargo()

    # --- live trade-run tracking --------------------------------------------
    def _copy_system(self, system: Any) -> bool:
        if not system:
            return False
        try:
            from clipboard_service import copy_text

            return bool(copy_text(str(system)).success)
        except Exception:  # noqa: BLE001 - clipboard is best-effort
            return False

    def _render_cargo(self) -> None:
        if not self._cargo_route:
            return
        import cargo as cargo_mod

        rows, self._cargo_row_hops = cargo_mod.build_cargo_grid(
            self._cargo_route, self._cargo_hop, self._cargo_skipped
        )
        self.client.ui_suspend("CARGOGRID")
        self.client.ui_clear("CARGOGRID")
        self.client.ui_add_set_rows("CARGOGRID", rows)
        self.client.ui_resume("CARGOGRID")

    @staticmethod
    def _norm(value: Any) -> str:
        return str(value or "").strip().casefold()

    def _cargo_track(self, entry: dict[str, Any]) -> None:
        """Drive the trade run from live journal events: buy -> copy next system."""
        route = self._cargo_route
        hops = (route or {}).get("hops") or []
        if not hops:
            return
        event = entry.get("event")
        if event == "MarketBuy":
            bought = self._norm(entry.get("Type_Localised") or entry.get("Type"))
            if not bought:
                return
            # Find the hop that buys this commodity (search from the current hop, wrapping),
            # so buying the right good anywhere in the loop advances the run.
            count = len(hops)
            match = None
            for step in range(count):
                idx = (self._cargo_hop + step) % count
                if idx in self._cargo_skipped:
                    continue
                if any(self._norm(c.get("name")) == bought for c in (hops[idx].get("commodities") or [])):
                    match = idx
                    break
            if match is None:
                return
            self._cargo_hop = match
            destination = hops[match].get("destination") or {}
            dest_system = destination.get("system")
            dest_station = destination.get("station")
            copied = self._copy_system(dest_system)
            commodity = entry.get("Type_Localised") or entry.get("Type")
            self.client.ui_set(
                "CARGOSTATUS",
                f"Hop {match + 1}/{count}: bought {commodity}  ->  sell at "
                f"{dest_system} / {dest_station}" + ("  (copied)" if copied else ""),
            )
            self._render_cargo()
        elif event == "Docked":
            system = entry.get("StarSystem")
            hop = hops[self._cargo_hop] if self._cargo_hop < len(hops) else None
            destination = (hop or {}).get("destination") or {}
            if system and self._norm(system) == self._norm(destination.get("system")):
                commodity = (hops[self._cargo_hop].get("commodities") or [{}])[0].get("name", "cargo")
                self.client.ui_set(
                    "CARGOSTATUS",
                    f"Arrived {entry.get('StationName')}: sell {commodity}, then buy the next hop",
                )

    def handle_message(self, message: dict[str, Any]) -> bool:
        response_type = message.get("responsetype")
        if response_type == "terminate":
            self._capture_column_layouts()
            return super().handle_message(message)
        if response_type == "uievent":
            return super().handle_message(message)
        if response_type == "edduievent":
            self._handle_telemetry(message)
            return True
        if response_type == "newtarget":
            self._handle_new_target(message)
            return True
        if response_type == "journalpush":
            entry = message.get("journalEntry")
            if isinstance(entry, dict):
                if self._cargo_route:  # live trade-run tracking (independent of any exo route)
                    try:
                        self._cargo_track(entry)
                    except Exception as exc:  # noqa: BLE001
                        print(f"RouteOps: cargo tracking skipped {entry.get('event')!r}: {exc}")
                if self.kernel:
                    try:
                        result = self.kernel.handle_journal(entry)
                        if result.actions:
                            self._accept_kernel_result(result)
                    except Exception as exc:  # noqa: BLE001 - one bad event must not kill the panel
                        print(f"RouteOps: skipped journal event {entry.get('event')!r}: {exc}")
            return True
        if response_type in {"historypush", "historyload"} and self.kernel:
            entries = message.get("journalEntries", message.get("entries", message.get("history", [])))
            if isinstance(message.get("journalEntry"), dict):
                entries = [message["journalEntry"]]
            actions: list[dict[str, Any]] = []
            if isinstance(entries, list):
                for entry in entries:
                    if isinstance(entry, dict):
                        try:
                            actions.extend(self.kernel.hydrate_journal_knowledge(entry).actions)
                        except Exception as exc:  # noqa: BLE001 - skip bad entries, keep loading
                            print(f"RouteOps: skipped history event {entry.get('event')!r}: {exc}")
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
