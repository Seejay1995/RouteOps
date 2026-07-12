from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

PLUGIN = Path(__file__).resolve().parents[1] / "Plugin" / "RouteOps"
sys.path.insert(0, str(PLUGIN))

from navigation_model import GuidanceMode, NavigationTargetType  # noqa: E402
from route_engine import RouteEngine  # noqa: E402
from route_importer import import_route  # noqa: E402
from route_models import ProgressStatus, TaskStatus  # noqa: E402
from ui_renderer import render_body_rows, render_species_rows, render_system_rows  # noqa: E402


class NavigationV5Tests(unittest.TestCase):
    def setUp(self):
        self.folder = Path(tempfile.mkdtemp())

    def write_route(self, payload: dict, name: str = "route.json") -> Path:
        path = self.folder / name
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def engine(self, *, guidance: str = "confirm") -> RouteEngine:
        payload = {
            "schemaVersion": 5,
            "id": "nav-v5",
            "name": "Navigation V5",
            "routeMode": "exobiology",
            "settings": {
                "guidanceMode": guidance,
                "bodyOrderMode": "route",
                "autoAdvance": True,
            },
            "systems": [
                {
                    "system": "Alpha",
                    "systemAddress": 100,
                    "bodies": [
                        {
                            "body": "Alpha 1",
                            "bodyId": 1,
                            "distanceFromArrivalLs": 1200,
                            "manifestCompleteness": "exact",
                            "organisms": [
                                {"species": "Stratum Tectonicas", "variant": "Stratum Tectonicas - Green"},
                                {"species": "Bacterium Informem"},
                            ],
                        },
                        {
                            "body": "Alpha 2",
                            "bodyId": 2,
                            "distanceFromArrivalLs": 400,
                            "manifestCompleteness": "exact",
                            "organisms": [{"species": "Stratum Tectonicas"}],
                        },
                    ],
                },
                {
                    "system": "Beta",
                    "systemAddress": 200,
                    "bodies": [
                        {
                            "body": "Beta 3",
                            "bodyId": 3,
                            "distanceFromArrivalLs": 25,
                            "organisms": [{"species": "Frutexa Acus"}],
                        }
                    ],
                },
            ],
        }
        result = import_route(self.write_route(payload))
        self.assertIsNotNone(result.route, result.errors)
        return RouteEngine(result.route)

    def test_system_and_body_manifests_exist_before_saa(self):
        engine = self.engine()
        self.assertEqual(["Alpha", "Beta"], [system.name for system in engine.system_plans])
        alpha = engine.system_plans[0]
        self.assertEqual(["Alpha 1", "Alpha 2"], [body.body_name for body in alpha.bodies])
        self.assertEqual(2, alpha.active_body_count)
        self.assertEqual(3, alpha.target_count)
        self.assertEqual("exact", alpha.manifest_completeness)
        self.assertEqual(2, len(render_system_rows(engine)))
        self.assertEqual(2, len(render_body_rows(engine)))

    def test_selection_is_separate_from_navigation_target(self):
        engine = self.engine()
        self.assertEqual("Alpha 1", engine.current_stop.body)
        engine.select_system_body(1)
        self.assertEqual("Alpha 2", engine.selected_stop.body)
        self.assertEqual("Alpha 1", engine.current_stop.body)
        engine.choose_selected_body()
        self.assertEqual("Alpha 2", engine.current_stop.body)

    def test_navigation_target_changes_from_system_to_body_on_entry(self):
        engine = self.engine()
        self.assertEqual(NavigationTargetType.SYSTEM, engine.navigation_target.target_type)
        self.assertEqual("Alpha", engine.navigation_text())
        engine.handle_journal({"event": "FSDJump", "StarSystem": "Alpha", "SystemAddress": 100, "Id": 1})
        self.assertEqual(NavigationTargetType.BODY, engine.navigation_target.target_type)
        self.assertEqual("Alpha 1", engine.navigation_text())
        self.assertNotEqual(ProgressStatus.COMPLETE, engine.current_stop.status)

    def test_nearest_order_uses_distance_from_arrival(self):
        engine = self.engine()
        engine.cycle_body_order_mode()  # route -> nearest
        self.assertEqual("nearest", engine.body_order_mode)
        self.assertEqual(["Alpha 2", "Alpha 1"], [body.body_name for body in engine.selected_system_body_plans])

    def test_next_target_stays_in_system_before_next_system(self):
        engine = self.engine()
        engine.handle_journal({"event": "FSDJump", "StarSystem": "Alpha", "SystemAddress": 100, "Id": 1})
        engine.next_navigation_target()
        self.assertEqual("Alpha 2", engine.current_stop.body)
        engine.next_navigation_target()
        self.assertEqual("Beta 3", engine.current_stop.body)
        self.assertEqual(NavigationTargetType.SYSTEM, engine.navigation_target.target_type)

    def test_confirm_guidance_marks_ready_but_does_not_advance(self):
        engine = self.engine(guidance="confirm")
        task = engine.current_stop.tasks[0]
        engine.current_stop.tasks[1].status = TaskStatus.SKIPPED
        engine.complete_selected_task()
        self.assertTrue(task.complete)
        self.assertEqual("Alpha 1", engine.current_stop.body)
        self.assertEqual(ProgressStatus.READY, engine.current_stop.status)

    def test_skip_preview_is_body_qualified_and_value_aware(self):
        engine = self.engine()
        actions = engine.preview_selected_task_skip(reason="too-difficult")
        self.assertEqual("skip_preview", actions[0]["type"])
        pending = engine.pending_skip
        self.assertEqual("Alpha", pending["systemName"])
        self.assertEqual("Alpha 1", pending["bodyName"])
        self.assertIn("Stratum", pending["organismName"])
        self.assertGreater(pending["valueRemoved"], 0)
        self.assertLess(pending["bodyValueAfter"], pending["bodyValueBefore"])

    def test_confirm_skip_only_affects_exact_target_on_exact_body(self):
        engine = self.engine()
        engine.preview_selected_task_skip()
        engine.confirm_pending_skip()
        alpha1 = engine.route.stops[0]
        alpha2 = engine.route.stops[1]
        self.assertEqual(TaskStatus.SKIPPED, alpha1.tasks[0].status)
        self.assertEqual(TaskStatus.PENDING, alpha2.tasks[0].status)
        self.assertEqual("Alpha 1", engine.skip_decisions[-1].body_name)
        self.assertEqual(alpha1.tasks[0].id, engine.skip_decisions[-1].task_id)

    def test_undo_skip_restores_progress_and_value(self):
        engine = self.engine()
        before = engine.body_projection(engine.route.stops[0]).values.active_exact
        engine.preview_selected_task_skip()
        engine.confirm_pending_skip()
        after = engine.body_projection(engine.route.stops[0]).values.active_exact
        self.assertLess(after, before)
        engine.undo_last_skip()
        self.assertEqual(TaskStatus.PENDING, engine.route.stops[0].tasks[0].status)
        self.assertEqual(before, engine.body_projection(engine.route.stops[0]).values.active_exact)
        self.assertTrue(engine.skip_decisions[-1].reversed_at)

    def test_skipping_last_target_removes_body_from_active_navigation(self):
        engine = self.engine()
        engine.select_system_body(1)
        engine.choose_selected_body()
        engine.preview_selected_task_skip()
        self.assertTrue(engine.pending_skip["bodyRemovedFromRoute"])
        engine.confirm_pending_skip()
        self.assertFalse(engine.body_projection(engine.route.stops[1]).included_body)
        self.assertNotEqual("Alpha 2", engine.current_stop.body)

    def test_species_workspace_shows_exact_variant_scans_and_difficulty(self):
        engine = self.engine()
        engine.cycle_selected_difficulty()  # unknown -> easy
        rows = render_species_rows(engine)
        self.assertEqual(2, len(rows))
        self.assertIn("Stratum Tectonicas", rows[0]["cells"][2]["value"])
        self.assertIn("Green", rows[0]["cells"][3]["value"])
        self.assertEqual("0/3", rows[0]["cells"][4]["value"])
        self.assertEqual("Easy", rows[0]["cells"][6]["value"])

    def test_state_v6_preserves_navigation_skip_and_difficulty(self):
        engine = self.engine()
        engine.cycle_body_order_mode()
        engine.cycle_selected_difficulty()
        engine.preview_selected_task_skip(reason="low-value")
        engine.confirm_pending_skip()
        state = engine.to_state()
        self.assertEqual(6, state["stateVersion"])

        restored = self.engine()
        restored.apply_state(state)
        self.assertEqual("nearest", restored.body_order_mode)
        self.assertEqual("easy", restored.route.stops[0].tasks[0].search_difficulty)
        self.assertEqual(1, len(restored.skip_decisions))
        self.assertEqual(TaskStatus.SKIPPED, restored.route.stops[0].tasks[0].status)

    def test_bacterium_filter_recalculates_system_manifest(self):
        engine = self.engine()
        raw_alpha = engine.system_plans[0].active_value
        engine.set_genus_excluded("Bacterium", True)
        alpha = engine.system_plans[0]
        self.assertLess(alpha.active_value, raw_alpha)
        self.assertEqual(1, engine.body_projection(engine.route.stops[0]).excluded_count)
        self.assertIn("Alpha 1", [body.body_name for body in alpha.bodies])


if __name__ == "__main__":
    unittest.main()
