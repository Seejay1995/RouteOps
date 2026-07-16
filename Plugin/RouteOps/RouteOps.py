#!/usr/bin/env python3
from __future__ import annotations

import sys
import traceback
from pathlib import Path
from typing import Any

from clipboard_service import ClipboardResult, copy_text
from edd_client import EDDClient
from navigation_model import SKIP_REASON_LABELS
from route_engine import RouteEngine
from route_importer import RouteImportError, import_route
from state_store import load_state, save_state
from routeops_version import DISPLAY_VERSION, VERSION
from ui_renderer import (
    render_body_rows,
    render_detail,
    render_header,
    render_system_rows,
    render_species_rows,
)


class RouteOpsApplication:
    def __init__(self, client: EDDClient) -> None:
        self.client = client
        self.engine: RouteEngine | None = None
        self.route_path = str(client.config.get("route_path", "") or "")
        self.last_message = "Load an expedition, RouteOps manifest, Spansh export, or EDDiscovery Route CSV to begin."
        self.last_copied_target = ""
        self.state_folder = Path(__file__).resolve().parent / "State"

    def start(self) -> None:
        for grid in ("DGV", "BODIES", "ORGANISMS"):
            self.client.ui_set_dgv_setting(
                grid,
                column_reorder=True,
                per_column_word_wrap=False,
                allow_header_visibility=True,
                single_row_select=True,
            )
        self.client.ui_set_word_wrap("HEADER", True)
        self.client.ui_set_word_wrap("DETAIL", True)
        if self.route_path and Path(self.route_path).is_file():
            self.load_route(self.route_path, quiet=True)
        else:
            self.refresh_ui()

    def pump_background(self) -> None:
        """Hook called each main-loop iteration. No-op in the legacy base; the
        kernel app overrides it to drain the Spansh generation worker thread."""

    def load_route(self, path: str, quiet: bool = False) -> None:
        result = import_route(path)
        if result.route is None:
            message = "\n".join(result.errors or ["Route import failed."])
            self.last_message = f"Load failed: {message}"
            self.refresh_ui()
            if not quiet:
                self.client.message_box(message, "RouteOps - Route Load Error", "OK", "Error")
            return

        route = result.route
        engine = RouteEngine(route)
        engine.apply_state(load_state(route.source_path, self.state_folder))

        global_excluded = self.client.config.get("exobio_excluded_genera", None)
        if isinstance(global_excluded, list):
            engine.route.settings.excluded_organism_genera = [str(item) for item in global_excluded if str(item).strip()]
        if "exobio_show_excluded" in self.client.config:
            engine.route.settings.show_excluded_organisms = bool(self.client.config.get("exobio_show_excluded"))
        configured_view = str(self.client.config.get("exobio_route_view", "") or "")
        if configured_view in {"active", "all"}:
            engine.route.settings.route_view_mode = configured_view
        configured_guidance = str(self.client.config.get("navigation_guidance", "") or "")
        if configured_guidance in {"confirm", "auto-copy", "auto-advance"}:
            engine.guidance_mode = configured_guidance
            engine.route.settings.guidance_mode = configured_guidance
        configured_order = str(self.client.config.get("body_order_mode", "") or "")
        if configured_order in {"route", "nearest", "value", "manual"}:
            engine.body_order_mode = configured_order
            engine.route.settings.body_order_mode = configured_order
        configured_reason = str(self.client.config.get("default_skip_reason", "") or "")
        if configured_reason:
            engine.route.settings.default_skip_reason = configured_reason
        engine._rebuild_projection(repair_current=True)

        self.engine = engine
        self.route_path = route.source_path
        route.metadata["importWarnings"] = list(result.warnings)
        system_count = len(engine.system_plans)
        body_count = len(route.stops)
        if result.warnings:
            self.last_message = (
                f"Loaded {system_count} systems and {body_count} body operations as {route.route_type}. "
                f"Import warning: {result.warnings[0]}"
            )
        else:
            self.last_message = f"Loaded {system_count} systems and {body_count} body operations as {route.route_type}."
        self.persist()
        self.refresh_ui()

        if result.warnings and route.metadata.get("tradeDataMissing") and not quiet:
            self.client.message_box(result.warnings[0], "RouteOps - Trade Details Missing", "OK", "Warning")
        if engine.guidance_mode in {"auto-copy", "auto-advance"} and engine.navigation_text():
            self.copy_to_clipboard(engine.navigation_text(), engine.navigation_label())

    def persist(self) -> None:
        if self.engine and self.route_path:
            try:
                save_state(self.route_path, self.engine.to_state(), self.state_folder)
            except OSError as exc:
                self.last_message = f"State save failed: {exc}"
        self.client.config["route_path"] = self.route_path
        if self.engine:
            self.client.config["exobio_excluded_genera"] = list(self.engine.route.settings.excluded_organism_genera)
            self.client.config["exobio_show_excluded"] = self.engine.route.settings.show_excluded_organisms
            self.client.config["exobio_route_view"] = self.engine.route.settings.route_view_mode
            self.client.config["navigation_guidance"] = self.engine.guidance_mode
            self.client.config["body_order_mode"] = self.engine.body_order_mode
            self.client.config["default_skip_reason"] = self.engine.route.settings.default_skip_reason

    def refresh_ui(self) -> None:
        if not self.engine:
            self.client.ui_set_escape(
                "HEADER",
                f"ROUTEOPS {DISPLAY_VERSION}\r\n"
                "No route loaded.\r\n"
                "Load an enriched exobiology manifest to see systems, bodies, species, distances, and values before SAA.\r\n"
                f"STATUS: {self.last_message}",
            )
            self.client.ui_set_escape(
                "DETAIL",
                "NAVIGATION-FIRST WORKFLOW\r\n"
                "1. Select a system. 2. Inspect its body manifest. 3. Choose the next body. "
                "4. Triage exact species on that body. 5. Copy the explicit navigation target.",
            )
            for grid in ("DGV", "BODIES", "ORGANISMS"):
                self.client.ui_clear(grid)
            self._update_buttons()
            return

        self.client.ui_set_escape(
            "HEADER", render_header(self.engine, self.last_message, getattr(self, "telemetry_line", ""))
        )
        self.client.ui_set_escape("DETAIL", render_detail(self.engine))
        for grid, rows in (
            ("DGV", render_system_rows(self.engine)),
            ("BODIES", render_body_rows(self.engine)),
            ("ORGANISMS", render_species_rows(self.engine)),
        ):
            self.client.ui_suspend(grid)
            self.client.ui_clear(grid)
            self.client.ui_add_set_rows(grid, rows)
            self.client.ui_resume(grid)
        self._update_buttons()

    def _update_buttons(self) -> None:
        engine = self.engine
        has_route = engine is not None
        has_current = bool(engine and engine.current_stop)
        has_selected_body = bool(engine and engine.selected_stop)
        has_selected_task = bool(engine and engine.selected_task)
        has_pending_skip = bool(engine and engine.pending_skip)

        target_label = "Copy Target"
        if engine:
            target_label = {
                "system": "Copy System",
                "body": "Copy Body",
                "surface-search": "Copy Search Body",
            }.get(engine.navigation_target.target_type, "Copy Target")
        self.client.ui_set("NAVCOPY", target_label)
        self.client.ui_set("GUIDANCE", f"Guidance: {engine.guidance_mode if engine else 'confirm'}")
        self.client.ui_set("ORDER", f"Order: {engine.body_order_mode if engine else 'route'}")
        self.client.ui_set("SKIPREASON", f"Skip: {SKIP_REASON_LABELS.get(engine.route.settings.default_skip_reason, engine.route.settings.default_skip_reason) if engine else 'Too difficult'}")
        self.client.ui_set("DIFFICULTY", f"Difficulty: {engine.selected_task.search_difficulty if has_selected_task else 'unknown'}")
        exobio_active = bool(engine and engine.exobiology_mode_active)
        self.client.ui_set("EXOMODE", "Exobio: Active" if exobio_active else "Use Exobio")
        bacterium_filtered = bool(engine and engine.is_genus_excluded("Bacterium"))
        self.client.ui_set("BACTERIUM", "Bacterium: Excluded" if bacterium_filtered else "Bacterium: Included")
        self.client.ui_set("SHOWEXCLUDED", "Show Excluded: Yes" if engine and engine.route.settings.show_excluded_organisms else "Show Excluded: No")
        self.client.ui_set("ROUTEVIEW", "View: All" if engine and engine.route.settings.route_view_mode == "all" else "View: Active")

        enabled = {
            "RELOAD": bool(self.route_path),
            "NAVCOPY": has_current,
            "PREVTARGET": has_current,
            "NEXTTARGET": has_current,
            "GUIDANCE": has_route,
            "ORDER": has_route,
            "CHOOSETARGET": has_selected_body,
            "FINISHBODY": has_current,
            "SKIPBODY": has_current,
            "REOPENBODY": has_selected_body,
            "EXOMODE": bool(engine and not engine.exobiology_mode_active),
            "BACTERIUM": exobio_active,
            "SHOWEXCLUDED": exobio_active,
            "ROUTEVIEW": exobio_active,
            "BODYINCLUDE": bool(exobio_active and has_selected_body),
            "BODYEXCLUDE": bool(exobio_active and has_selected_body),
            "BODYDEFAULT": bool(exobio_active and has_selected_body),
            "TASKDONE": has_selected_task,
            "SKIPPREVIEW": has_selected_task and not has_pending_skip,
            "SKIPCONFIRM": has_pending_skip,
            "SKIPCANCEL": has_pending_skip,
            "SKIPUNDO": bool(engine and any(not decision.reversed_at for decision in engine.skip_decisions)),
            "TASKREOPEN": has_selected_task,
            "TASKINCLUDE": has_selected_task,
            "TASKEXCLUDE": has_selected_task,
            "TASKDEFAULT": has_selected_task,
            "DIFFICULTY": has_selected_task,
            "SKIPREASON": has_route,
            "RESETSTOP": has_selected_body,
            "DEBUGBUNDLE": exobio_active,
        }
        for control, value in enabled.items():
            self.client.ui_enable(control, value)

    def copy_to_clipboard(self, text: str, label: str = "Target") -> ClipboardResult:
        if not text:
            self.last_message = f"No {label.casefold()} is available to copy."
            self.refresh_ui()
            return ClipboardResult(False, error=self.last_message)
        settings = self.engine.route.settings if self.engine else None
        result = copy_text(
            text,
            retries=settings.clipboard_retry_count if settings else 6,
            delay_ms=settings.clipboard_retry_delay_ms if settings else 75,
        )
        if result.success:
            self.last_copied_target = text
            if self.engine and text == self.engine.navigation_target.text:
                self.engine.mark_navigation_copied()
            self.last_message = f"{label} copied: {text}"
            self.persist()
        else:
            self.last_message = (
                f"Clipboard failed after {result.attempts} attempt(s); manual copy remains available. "
                f"{result.error or ''}"
            ).strip()
        self.refresh_ui()
        return result

    def process_actions(self, actions: list[dict[str, Any]]) -> None:
        copy_request = ""
        navigation_changed = False
        for action in actions:
            action_type = str(action.get("type", ""))
            if action_type == "arrived":
                self.last_message = f"Entered {action.get('system', '')}; body work remains open."
                navigation_changed = True
            elif action_type == "task_progress":
                self.last_message = f"{action.get('label') or action.get('task')}: {action.get('current')}/{action.get('target')}"
            elif action_type == "advanced":
                target = action.get("body") or action.get("system", "")
                self.last_message = f"Next navigation target: {target}."
                navigation_changed = True
            elif action_type in {"navigation_target", "jumped"}:
                target = action.get("body") or action.get("system", "")
                self.last_message = f"Navigation target selected: {target}."
                copy_request = str(action.get("text") or "")
                navigation_changed = True
            elif action_type == "system_selected":
                self.last_message = f"Inspecting system {action.get('system', '')}."
            elif action_type in {"body_inspected", "row_selected", "body_selected"}:
                self.last_message = f"Inspecting {action.get('body') or action.get('system', '')}."
            elif action_type == "task_selected":
                self.last_message = f"Selected {action.get('label') or action.get('task', '')} on the inspected body."
            elif action_type == "skip_preview":
                suffix = " The body will leave active navigation." if action.get("bodyRemoved") else ""
                self.last_message = f"Skip preview: {action.get('organism')} on {action.get('body')}.{suffix}"
            elif action_type == "task_skipped":
                self.last_message = (
                    f"Skipped {action.get('label') or action.get('task')} on {action.get('body', '')}: "
                    f"{action.get('reason', '')}."
                )
                navigation_changed = bool(action.get("bodyRemoved"))
            elif action_type == "task_reopened":
                self.last_message = f"Restored {action.get('label') or action.get('task', '')} on {action.get('body', '')}."
            elif action_type == "stop_ready":
                self.last_message = "Included work is complete. Use Finish Body to select the next target."
            elif action_type == "stop_completed":
                self.last_message = f"Completed {action.get('body') or action.get('system', '')}."
                navigation_changed = True
            elif action_type == "stop_skipped":
                self.last_message = f"Skipped body {action.get('body') or action.get('system', '')}."
                navigation_changed = True
            elif action_type == "reopened":
                self.last_message = f"Reopened {action.get('body') or action.get('system', '')}."
            elif action_type == "reset":
                self.last_message = f"Reset {action.get('body') or action.get('system', '')}."
            elif action_type == "organism_added":
                self.last_message = f"Added {action.get('label') or action.get('task', 'organism')} to the body manifest."
            elif action_type == "body_added":
                self.last_message = f"Added live body manifest: {action.get('body') or action.get('system', '')}."
            elif action_type == "organic_sold":
                self.last_message = f"Sold {action.get('label', 'organic data')} for {int(action.get('value', 0)):,} CR + {int(action.get('bonus', 0)):,} bonus."
            elif action_type == "organic_sale_unallocated":
                self.last_message = f"Recorded unallocated sale for {action.get('label', 'organic data')}."
            elif action_type == "route_complete":
                self.last_message = "Route complete."
            elif action_type == "message":
                self.last_message = str(action.get("message", ""))
            elif action_type == "copy" and action.get("text"):
                copy_request = str(action["text"])
                navigation_changed = True

        self.persist()
        self.refresh_ui()
        if self.engine and self.engine.guidance_mode in {"auto-copy", "auto-advance"} and navigation_changed:
            copy_request = self.engine.navigation_text() or copy_request
        if copy_request and self.engine and self.engine.guidance_mode in {"auto-copy", "auto-advance"}:
            self.copy_to_clipboard(copy_request, self.engine.navigation_label())

    @staticmethod
    def _extract_row_index(message: dict[str, Any]) -> int | None:
        candidates = [message.get("value"), message.get("value2"), message.get("data")]
        for candidate in candidates:
            if isinstance(candidate, bool) or candidate is None:
                continue
            if isinstance(candidate, int):
                return candidate
            if isinstance(candidate, float):
                return int(candidate)
            if isinstance(candidate, str) and candidate.strip().lstrip("-").isdigit():
                return int(candidate.strip())
            if isinstance(candidate, dict):
                for key in ("row", "Row", "rowindex", "RowIndex", "index", "Index"):
                    if key in candidate:
                        try:
                            return int(candidate[key])
                        except (TypeError, ValueError):
                            pass
            if isinstance(candidate, list) and candidate:
                try:
                    return int(candidate[0])
                except (TypeError, ValueError):
                    pass
        return None

    def handle_ui_event(self, message: dict[str, Any]) -> None:
        control = str(message.get("control", ""))
        if control == "DGV" and self.engine:
            row = self._extract_row_index(message)
            if row is not None and row >= 0:
                self.process_actions(self.engine.select_system(row))
            return
        if control == "BODIES" and self.engine:
            row = self._extract_row_index(message)
            if row is not None and row >= 0:
                self.process_actions(self.engine.select_system_body(row))
            return
        if control == "ORGANISMS" and self.engine:
            row = self._extract_row_index(message)
            if row is not None and row >= 0:
                self.process_actions(self.engine.select_task(row))
            return

        if control == "LOAD":
            folder = str(Path(self.route_path).parent) if self.route_path else str(Path.home())
            response = self.client.open_file_dialog(
                folder,
                "Route files|*.json;*.csv;*.tsv|JSON route files|*.json|EDDiscovery Route CSV|*.csv;*.tsv|All files|*.*",
                "*.*",
            )
            if response and response.get("DialogResult") == "OK" and response.get("FileName"):
                self.load_route(str(response["FileName"]))
        elif control == "RELOAD" and self.route_path:
            self.load_route(self.route_path)
        elif control == "NAVCOPY" and self.engine:
            self.copy_to_clipboard(self.engine.navigation_text(), self.engine.navigation_label())
        elif control == "PREVTARGET" and self.engine:
            self.process_actions(self.engine.previous_navigation_target())
        elif control == "NEXTTARGET" and self.engine:
            self.process_actions(self.engine.next_navigation_target())
        elif control == "GUIDANCE" and self.engine:
            self.process_actions(self.engine.cycle_guidance_mode())
        elif control == "ORDER" and self.engine:
            self.process_actions(self.engine.cycle_body_order_mode())
        elif control == "CHOOSETARGET" and self.engine:
            self.process_actions(self.engine.choose_selected_body())
        elif control == "FINISHBODY" and self.engine:
            self.process_actions(self.engine.complete_current())
        elif control == "SKIPBODY" and self.engine:
            self.process_actions(self.engine.skip_current())
        elif control == "REOPENBODY" and self.engine:
            self.process_actions(self.engine.reopen_stop())
        elif control == "TASKDONE" and self.engine:
            self.process_actions(self.engine.complete_selected_task())
        elif control == "SKIPPREVIEW" and self.engine:
            self.process_actions(self.engine.preview_selected_task_skip())
        elif control == "SKIPCONFIRM" and self.engine:
            self.process_actions(self.engine.confirm_pending_skip())
        elif control == "SKIPCANCEL" and self.engine:
            self.process_actions(self.engine.cancel_pending_skip())
        elif control == "SKIPUNDO" and self.engine:
            self.process_actions(self.engine.undo_last_skip())
        elif control == "SKIPREASON" and self.engine:
            self.process_actions(self.engine.cycle_skip_reason())
        elif control == "DIFFICULTY" and self.engine:
            self.process_actions(self.engine.cycle_selected_difficulty())
        elif control == "TASKREOPEN" and self.engine:
            self.process_actions(self.engine.reopen_selected_task())
        elif control == "RESETSTOP" and self.engine:
            self.process_actions(self.engine.reset_stop())
        elif control == "EXOMODE" and self.engine:
            self.process_actions(self.engine.enable_exobiology_mode())
        elif control == "BACTERIUM" and self.engine:
            self.process_actions(self.engine.toggle_genus_filter("Bacterium"))
        elif control == "SHOWEXCLUDED" and self.engine:
            self.process_actions(self.engine.toggle_show_excluded())
        elif control == "ROUTEVIEW" and self.engine:
            self.process_actions(self.engine.toggle_route_view())
        elif control == "TASKINCLUDE" and self.engine:
            self.process_actions(self.engine.set_selected_task_inclusion("include"))
        elif control == "TASKEXCLUDE" and self.engine:
            self.process_actions(self.engine.set_selected_task_inclusion("exclude"))
        elif control == "TASKDEFAULT" and self.engine:
            self.process_actions(self.engine.set_selected_task_inclusion("default"))
        elif control == "BODYINCLUDE" and self.engine:
            self.process_actions(self.engine.set_selected_body_inclusion("include"))
        elif control == "BODYEXCLUDE" and self.engine:
            self.process_actions(self.engine.set_selected_body_inclusion("exclude"))
        elif control == "BODYDEFAULT" and self.engine:
            self.process_actions(self.engine.set_selected_body_inclusion("default"))
        elif control == "DEBUGBUNDLE" and self.engine:
            try:
                destination = self.engine.export_exobio_debug_bundle()
                self.last_message = f"Exobiology debug bundle exported: {destination}"
            except OSError as exc:
                self.last_message = f"Debug export failed: {exc}"
            self.refresh_ui()

    def handle_message(self, message: dict[str, Any]) -> bool:
        response_type = message.get("responsetype")
        if response_type == "terminate":
            self.persist()
            self.client.send_exit("Server requested")
            return False
        if response_type == "uievent":
            self.handle_ui_event(message)
        elif response_type == "journalpush" and self.engine:
            entry = message.get("journalEntry")
            if isinstance(entry, dict):
                actions = self.engine.handle_journal(entry)
                if actions:
                    self.process_actions(actions)
        elif response_type in {"historypush", "historyload"} and self.engine:
            raw_entries = message.get("journalEntries", message.get("entries", message.get("history", [])))
            if isinstance(message.get("journalEntry"), dict):
                raw_entries = [message["journalEntry"]]
            if isinstance(raw_entries, list):
                actions: list[dict[str, Any]] = []
                for entry in raw_entries:
                    if isinstance(entry, dict):
                        actions.extend(self.engine.hydrate_journal_knowledge(entry))
                if actions:
                    self.last_message = f"Hydrated body and species manifests from {len(raw_entries)} historical journal event(s)."
                    self.persist()
                    self.refresh_ui()
        return True


def main() -> int:
    if len(sys.argv) < 2:
        print("RouteOps must be launched by EDDiscovery with a ZMQ port argument.")
        return 2
    client = EDDClient(sys.argv[1])
    try:
        if not client.send_start(VERSION, timeout_ms=30_000):
            print("RouteOps could not establish an EDDiscovery API v1 connection.")
            return 3
        app = RouteOpsApplication(client)
        app.start()
        running = True
        while running:
            client.fill_queue(100)
            message = client.get_next()
            if message:
                running = app.handle_message(message)
            app.pump_background()
        return 0
    except (RouteImportError, OSError, ValueError) as exc:
        traceback.print_exc()
        try:
            client.send_exit(f"RouteOps error: {exc}")
        except Exception:
            pass
        return 1
    except Exception as exc:
        traceback.print_exc()
        try:
            client.send_exit(f"RouteOps unexpected error: {exc}")
        except Exception:
            pass
        return 1
    finally:
        client.close()


if __name__ == "__main__":
    raise SystemExit(main())
