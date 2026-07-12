from __future__ import annotations

import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

PLUGIN = Path(__file__).resolve().parents[1] / "Plugin" / "RouteOps"
sys.path.insert(0, str(PLUGIN))

from exobio_taxonomy import InclusionState, canonical_genus_id, resolve_taxonomy  # noqa: E402
from route_engine import RouteEngine  # noqa: E402
from route_importer import import_route  # noqa: E402
from route_models import ProgressStatus, TaskStatus  # noqa: E402
from ui_renderer import render_task_rows  # noqa: E402


class ExobiologyV4Tests(unittest.TestCase):
    def write_route(self, payload: dict) -> Path:
        folder = Path(tempfile.mkdtemp())
        path = folder / "route.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def engine(self, organisms: list[dict], *, signals: int | None = None) -> RouteEngine:
        body: dict = {"body": "Alpha 1", "bodyId": 1, "organisms": organisms}
        if signals is not None:
            body["biologicalSignals"] = signals
        route = import_route(
            self.write_route(
                {
                    "schemaVersion": 3,
                    "id": "v4-route",
                    "name": "V4 Route",
                    "routeMode": "exobiology",
                    "systems": [
                        {"system": "Alpha", "systemAddress": 100, "bodies": [body]},
                        {
                            "system": "Beta",
                            "systemAddress": 200,
                            "bodies": [{"body": "Beta 2", "bodyId": 2, "organisms": [{"species": "Frutexa Acus"}]}],
                        },
                    ],
                }
            )
        ).route
        self.assertIsNotNone(route)
        return RouteEngine(route)

    def test_frontier_bacterial_internal_symbol_canonicalizes_to_bacterium(self):
        self.assertEqual("bacterium", canonical_genus_id("$Codex_Ent_Bacterial_Genus_Name;"))
        resolution = resolve_taxonomy(genus_internal="$Codex_Ent_Bacterial_Genus_Name;")
        self.assertEqual("bacterium", resolution.genus_id)
        self.assertEqual("exact-alias", resolution.confidence)

    def test_filter_does_not_mutate_raw_progress_or_required_state(self):
        engine = self.engine([{"species": "Bacterium Informem"}, {"species": "Stratum Tectonicas"}])
        bacterium = engine.route.stops[0].tasks[0]
        original = (bacterium.status, bacterium.required, bacterium.quantity_completed)
        engine.set_genus_excluded("Bacterium", True)
        self.assertEqual(original, (bacterium.status, bacterium.required, bacterium.quantity_completed))
        self.assertTrue(engine.task_projection(bacterium, engine.route.stops[0]).excluded)
        self.assertNotIn("filteredOut", bacterium.metadata)

    def test_excluded_scan_is_recorded_and_shown_with_sample_count(self):
        engine = self.engine([{"species": "Bacterium Informem"}, {"species": "Stratum Tectonicas"}])
        engine.set_genus_excluded("Bacterium", True)
        engine.handle_journal(
            {
                "event": "ScanOrganic",
                "StarSystem": "Alpha",
                "SystemAddress": 100,
                "Body": 1,
                "BodyName": "Alpha 1",
                "Genus": "$Codex_Ent_Bacterial_Genus_Name;",
                "Genus_Localised": "Bacterium",
                "Species_Localised": "Bacterium Informem",
                "ScanType": "Sample",
                "Id": 10,
            }
        )
        bacterium = engine.route.stops[0].tasks[0]
        self.assertEqual(2, bacterium.quantity_completed)
        self.assertEqual(TaskStatus.IN_PROGRESS, bacterium.status)
        row = next(row for row in render_task_rows(engine) if "Bacterium Informem" in row["cells"][2]["value"])
        self.assertEqual("2/3", row["cells"][3]["value"])
        self.assertEqual("Excluded", row["cells"][5]["value"])

    def test_bacterium_only_body_is_removed_without_becoming_skipped_or_complete(self):
        engine = self.engine([{"species": "Bacterium Informem"}])
        body = engine.route.stops[0]
        engine.set_genus_excluded("Bacterium", True)
        projection = engine.body_projection(body)
        self.assertFalse(projection.included_body)
        self.assertEqual(InclusionState.EXCLUDED, projection.inclusion_state)
        self.assertEqual(ProgressStatus.PENDING, body.status)
        self.assertEqual(["Beta 2"], [stop.body for stop in engine.visible_stops])
        self.assertEqual("Beta 2", engine.current_stop.body)

    def test_mixed_body_recalculates_raw_excluded_and_active_values(self):
        engine = self.engine([{"species": "Bacterium Informem"}, {"species": "Stratum Tectonicas"}])
        engine.set_genus_excluded("Bacterium", True)
        body = engine.body_projection(engine.route.stops[0])
        self.assertTrue(body.included_body)
        self.assertEqual(27428800, body.values.raw_exact)
        self.assertEqual(8418000, body.values.excluded_exact)
        self.assertEqual(19010800, body.values.active_exact)
        metrics = engine.route_metrics()
        self.assertEqual(35203500, metrics.raw_base_value)
        self.assertEqual(8418000, metrics.excluded_base_value)
        self.assertEqual(26785500, metrics.active_base_value)

    def test_bacterium_plus_unresolved_signal_remains_active(self):
        route = import_route(self.write_route({"Name": "Generic Expedition", "Systems": ["Alpha", "Beta"]})).route
        engine = RouteEngine(route)
        engine.enable_exobiology_mode()
        engine.set_genus_excluded("Bacterium", True)
        engine.handle_journal({"event": "FSDJump", "StarSystem": "Alpha", "SystemAddress": 100, "Id": 1})
        engine.handle_journal(
            {
                "event": "SAASignalsFound",
                "StarSystem": "Alpha",
                "SystemAddress": 100,
                "BodyName": "Alpha 1",
                "BodyID": 1,
                "Signals": [{"Type_Localised": "Biological", "Count": 2}],
                "Genuses": [{"Genus": "$Codex_Ent_Bacterial_Genus_Name;"}],
                "Id": 2,
            }
        )
        alpha = next(stop for stop in engine.route.stops if stop.system == "Alpha" and stop.body == "Alpha 1")
        projection = engine.body_projection(alpha)
        self.assertTrue(projection.included_body)
        self.assertEqual(InclusionState.UNRESOLVED, projection.inclusion_state)
        self.assertEqual(1, projection.excluded_count)
        self.assertGreaterEqual(projection.unresolved_count, 1)

    def test_disabling_filter_restores_body_progress_and_value(self):
        engine = self.engine([{"species": "Bacterium Informem"}])
        body = engine.route.stops[0]
        bacterium = body.tasks[0]
        engine.set_genus_excluded("Bacterium", True)
        engine.handle_journal(
            {
                "event": "ScanOrganic",
                "StarSystem": "Alpha",
                "SystemAddress": 100,
                "Body": 1,
                "BodyName": "Alpha 1",
                "Genus_Localised": "Bacterium",
                "Species_Localised": "Bacterium Informem",
                "ScanType": "Log",
                "Id": 3,
            }
        )
        self.assertFalse(engine.body_projection(body).included_body)
        engine.set_genus_excluded("Bacterium", False)
        self.assertTrue(engine.body_projection(body).included_body)
        self.assertEqual(1, bacterium.quantity_completed)
        self.assertEqual(8418000, engine.body_projection(body).values.active_exact)

    def test_show_excluded_changes_workspace_visibility_only(self):
        engine = self.engine([{"species": "Bacterium Informem"}, {"species": "Stratum Tectonicas"}])
        engine.set_genus_excluded("Bacterium", True)
        self.assertEqual(2, len(render_task_rows(engine)))
        engine.toggle_show_excluded()
        rows = render_task_rows(engine)
        self.assertEqual(1, len(rows))
        self.assertIn("Stratum Tectonicas", rows[0]["cells"][2]["value"])
        self.assertEqual(8418000, engine.body_projection(engine.route.stops[0]).values.excluded_exact)

    def test_all_bodies_view_shows_filtered_body_but_navigation_rejects_it(self):
        engine = self.engine([{"species": "Bacterium Informem"}])
        engine.set_genus_excluded("Bacterium", True)
        self.assertEqual(["Beta 2"], [stop.body for stop in engine.visible_stops])
        engine.toggle_route_view()
        self.assertEqual(["Alpha 1", "Beta 2"], [stop.body for stop in engine.visible_stops])
        engine.select_stop(0)
        actions = engine.jump_to()
        self.assertEqual("Beta 2", engine.current_stop.body)
        self.assertTrue(any("excluded from active navigation" in action.get("message", "") for action in actions))

    def test_manual_species_include_overrides_global_bacterium_filter(self):
        engine = self.engine([{"species": "Bacterium Informem"}])
        engine.set_genus_excluded("Bacterium", True)
        engine.toggle_route_view()
        engine.select_stop(0)
        engine.select_task(0)
        engine.set_selected_task_inclusion("include")
        task = engine.route.stops[0].tasks[0]
        projected = engine.task_projection(task, engine.route.stops[0])
        self.assertEqual(InclusionState.MANUAL_INCLUDED, projected.decision.state)
        self.assertTrue(engine.body_projection(engine.route.stops[0]).included_body)
        self.assertEqual(8418000, engine.body_projection(engine.route.stops[0]).values.active_exact)

    def test_manual_body_exclude_is_separate_from_work_status(self):
        engine = self.engine([{"species": "Stratum Tectonicas"}])
        body = engine.route.stops[0]
        engine.set_selected_body_inclusion("exclude")
        projected = engine.body_projection(body)
        self.assertEqual(InclusionState.MANUAL_EXCLUDED, projected.inclusion_state)
        self.assertFalse(projected.included_body)
        self.assertEqual(ProgressStatus.PENDING, body.status)
        engine.toggle_route_view()
        engine.select_stop(0)
        engine.set_selected_body_inclusion("default")
        self.assertTrue(engine.body_projection(body).included_body)

    def test_legacy_mutating_filter_state_is_repaired(self):
        engine = self.engine([{"species": "Bacterium Informem"}])
        stop = engine.route.stops[0]
        task = stop.tasks[0]
        state = engine.to_state()
        state["filterProfile"]["excludedGenusIds"] = ["bacterium"]
        raw_stop = state["stops"][stop.id]
        raw_stop["status"] = "skipped"
        raw_stop["operationPhase"] = "skipped"
        raw_stop["metadata"].update({
            "filteredOutByGenus": True,
            "filterPreviousStatus": "pending",
            "filterPreviousPhase": "en-route",
        })
        raw_task = raw_stop["tasks"][task.id]
        raw_task["status"] = "skipped"
        raw_task["metadata"].update({
            "filteredOut": True,
            "filterPreviousStatus": "pending",
            "filterPreviousRequired": True,
        })
        restored = self.engine([{"species": "Bacterium Informem"}])
        restored.apply_state(state)
        restored_stop = restored.route.stops[0]
        restored_task = restored_stop.tasks[0]
        self.assertEqual(ProgressStatus.PENDING, restored_stop.status)
        self.assertEqual(TaskStatus.PENDING, restored_task.status)
        self.assertTrue(restored_task.required)
        self.assertFalse(restored.body_projection(restored_stop).included_body)

    def test_history_hydration_enriches_species_without_current_progress(self):
        route = import_route(self.write_route({"Name": "Generic Expedition", "Systems": ["Alpha"]})).route
        engine = RouteEngine(route)
        engine.enable_exobiology_mode()
        engine.hydrate_journal_knowledge(
            {
                "event": "ScanOrganic",
                "StarSystem": "Alpha",
                "SystemAddress": 100,
                "Body": 1,
                "BodyName": "Alpha 1",
                "Genus_Localised": "Stratum",
                "Species_Localised": "Stratum Tectonicas",
                "ScanType": "Analyse",
                "Id": 42,
            }
        )
        body = next(stop for stop in engine.route.stops if stop.body == "Alpha 1")
        task = next(task for task in body.tasks if task.species == "Stratum Tectonicas")
        self.assertEqual(0, task.quantity_completed)
        self.assertEqual(TaskStatus.PENDING, task.status)
        self.assertEqual("journal-history", task.metadata.get("knowledgeSource"))

    def test_state_round_trip_preserves_filter_profile_samples_and_view(self):
        first = self.engine([{"species": "Bacterium Informem"}, {"species": "Stratum Tectonicas"}])
        first.set_genus_excluded("Bacterium", True)
        first.toggle_route_view()
        first.handle_journal(
            {
                "event": "ScanOrganic",
                "StarSystem": "Alpha",
                "SystemAddress": 100,
                "Body": 1,
                "BodyName": "Alpha 1",
                "Genus_Localised": "Bacterium",
                "Species_Localised": "Bacterium Informem",
                "ScanType": "Log",
                "Id": 50,
            }
        )
        state = first.to_state()
        second = self.engine([{"species": "Bacterium Informem"}, {"species": "Stratum Tectonicas"}])
        second.apply_state(state)
        bacterium = second.route.stops[0].tasks[0]
        self.assertTrue(second.is_genus_excluded("Bacterium"))
        self.assertEqual("all", second.route.settings.route_view_mode)
        self.assertEqual(1, bacterium.quantity_completed)
        self.assertTrue(second.task_projection(bacterium, second.route.stops[0]).excluded)

    def test_debug_bundle_contains_projection_filter_state_and_events(self):
        engine = self.engine([{"species": "Bacterium Informem"}, {"species": "Stratum Tectonicas"}])
        engine.set_genus_excluded("Bacterium", True)
        folder = Path(tempfile.mkdtemp())
        bundle = Path(engine.export_exobio_debug_bundle(str(folder)))
        self.assertTrue(bundle.is_file())
        with zipfile.ZipFile(bundle) as archive:
            names = set(archive.namelist())
            self.assertTrue({
                "normalized-route.json",
                "active-projection.json",
                "navigation-plan.json",
                "skip-decisions.json",
                "state.json",
                "recent-exobio-events.json",
                "filter-profile.json",
                "diagnostic-summary.txt",
            }.issubset(names))
            projection = json.loads(archive.read("active-projection.json"))
            self.assertEqual(8418000, projection["routeValues"]["excludedExact"])


if __name__ == "__main__":
    unittest.main()
