from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

PLUGIN = Path(__file__).resolve().parents[1] / "Plugin" / "RouteOps"
sys.path.insert(0, str(PLUGIN))

from route_engine import RouteEngine  # noqa: E402
from route_importer import import_route  # noqa: E402
from route_models import CompletionPolicy, ProgressStatus, StopType  # noqa: E402
from ui_renderer import render_rows, render_task_rows  # noqa: E402


class ExobiologyHotfixTests(unittest.TestCase):
    def write_route(self, payload: dict) -> Path:
        folder = Path(tempfile.mkdtemp())
        path = folder / "route.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def plain_engine(self) -> RouteEngine:
        route = import_route(self.write_route({"Name": "Generic Expedition", "Systems": ["Alpha", "Beta"]})).route
        self.assertIsNotNone(route)
        return RouteEngine(route)

    def enriched_engine(self) -> RouteEngine:
        route = import_route(
            self.write_route(
                {
                    "schemaVersion": 3,
                    "id": "filter-route",
                    "name": "Filter Route",
                    "routeMode": "exobiology",
                    "systems": [
                        {
                            "system": "Alpha",
                            "systemAddress": 100,
                            "bodies": [
                                {
                                    "body": "Alpha 1",
                                    "bodyId": 1,
                                    "organisms": [
                                        {"species": "Stratum Tectonicas"},
                                        {"species": "Bacterium Informem"},
                                    ],
                                }
                            ],
                        },
                        {
                            "system": "Beta",
                            "systemAddress": 200,
                            "bodies": [
                                {
                                    "body": "Beta 2",
                                    "bodyId": 2,
                                    "organisms": [{"species": "Frutexa Acus"}],
                                }
                            ],
                        },
                    ],
                }
            )
        ).route
        self.assertIsNotNone(route)
        return RouteEngine(route)

    def test_force_exobiology_mode_prevents_system_arrival_completion(self):
        engine = self.plain_engine()
        engine.enable_exobiology_mode()
        actions = engine.handle_journal(
            {"event": "FSDJump", "StarSystem": "Alpha", "SystemAddress": 100, "Id": 1}
        )
        self.assertEqual(0, engine.current_index)
        self.assertEqual(ProgressStatus.CURRENT, engine.current_stop.status)
        self.assertEqual(StopType.EXOBIOLOGY, engine.current_stop.stop_type)
        self.assertFalse(any(action.get("type") == "stop_completed" for action in actions))

    def test_legacy_arrival_only_completion_is_reopened(self):
        engine = self.enriched_engine()
        state = {
            "stateVersion": 3,
            "routeId": engine.route.id,
            "currentStopId": engine.route.stops[0].id,
            "stops": {
                engine.route.stops[0].id: {
                    "status": "complete",
                    "arrived": True,
                    "operationPhase": "complete",
                    "tasks": {},
                }
            },
        }
        engine.apply_state(state)
        self.assertEqual(ProgressStatus.CURRENT, engine.route.stops[0].status)
        self.assertNotEqual("complete", engine.route.stops[0].operation_phase)

    def test_dynamic_body_without_signal_count_never_completes_after_one_species(self):
        engine = self.plain_engine()
        engine.enable_exobiology_mode()
        engine.handle_journal({"event": "FSDJump", "StarSystem": "Alpha", "SystemAddress": 100, "Id": 1})
        engine.handle_journal(
            {
                "event": "ApproachBody",
                "StarSystem": "Alpha",
                "SystemAddress": 100,
                "BodyID": 1,
                "BodyName": "Alpha 1",
                "Id": 2,
            }
        )
        actions = engine.handle_journal(
            {
                "event": "ScanOrganic",
                "StarSystem": "Alpha",
                "SystemAddress": 100,
                "Body": 1,
                "BodyName": "Alpha 1",
                "Genus_Localised": "Stratum",
                "Species_Localised": "Stratum Tectonicas",
                "ScanType": "Analyse",
                "Id": 3,
            }
        )
        self.assertEqual(CompletionPolicy.MANUAL, engine.current_stop.completion_policy)
        self.assertEqual(ProgressStatus.CURRENT, engine.current_stop.status)
        self.assertFalse(any(action.get("type") == "advanced" for action in actions))

    def test_bacterium_filter_removes_targets_samples_and_value(self):
        engine = self.enriched_engine()
        engine.toggle_genus_filter("Bacterium")
        stop = engine.route.stops[0]
        bacterium = next(task for task in stop.tasks if task.species.startswith("Bacterium"))
        projected = engine.task_projection(bacterium, stop)
        self.assertIsNotNone(projected)
        self.assertTrue(projected.excluded)
        self.assertEqual("pending", bacterium.status)
        self.assertTrue(bacterium.required)
        metrics = engine.route_metrics()
        self.assertEqual(19010800 + 7774700, metrics.active_base_value)
        self.assertEqual(8418000, metrics.excluded_base_value)
        actions = engine.handle_journal(
            {
                "event": "ScanOrganic",
                "StarSystem": "Alpha",
                "SystemAddress": 100,
                "Body": 1,
                "BodyName": "Alpha 1",
                "Genus_Localised": "Bacterium",
                "Species_Localised": "Bacterium Informem",
                "ScanType": "Analyse",
                "Id": 4,
            }
        )
        self.assertEqual(3, bacterium.quantity_completed)
        self.assertEqual("complete", bacterium.status)
        self.assertTrue(any("remains excluded" in str(action.get("message", "")) for action in actions))

    def test_bacterium_filter_persists_and_can_be_reenabled(self):
        first = self.enriched_engine()
        first.toggle_genus_filter("Bacterium")
        state = first.to_state()
        second = self.enriched_engine()
        second.apply_state(state)
        self.assertTrue(second.is_genus_excluded("Bacterium"))
        bacterium = next(task for task in second.route.stops[0].tasks if task.species.startswith("Bacterium"))
        self.assertTrue(second.task_projection(bacterium, second.route.stops[0]).excluded)
        self.assertEqual("pending", bacterium.status)
        second.toggle_genus_filter("Bacterium")
        self.assertFalse(second.is_genus_excluded("Bacterium"))
        self.assertTrue(second.task_projection(bacterium, second.route.stops[0]).included)
        self.assertEqual("pending", bacterium.status)

    def test_bacterium_only_saa_body_is_skipped_when_filter_is_active(self):
        engine = self.plain_engine()
        engine.enable_exobiology_mode()
        engine.toggle_genus_filter("Bacterium")
        engine.handle_journal({"event": "FSDJump", "StarSystem": "Alpha", "SystemAddress": 100, "Id": 1})
        engine.handle_journal(
            {
                "event": "SAASignalsFound",
                "StarSystem": "Alpha",
                "SystemAddress": 100,
                "BodyName": "Alpha 1",
                "BodyID": 1,
                "Signals": [{"Type_Localised": "Biological", "Count": 1}],
                "Genuses": [{"Genus_Localised": "Bacterium"}],
                "Id": 2,
            }
        )
        alpha = next(stop for stop in engine.route.stops if stop.system == "Alpha")
        alpha_projection = engine.body_projection(alpha)
        self.assertFalse(alpha_projection.included_body)
        self.assertEqual("excluded", alpha_projection.inclusion_state)
        self.assertEqual(ProgressStatus.PENDING, alpha.status)
        self.assertEqual("Beta", engine.current_stop.system)
        self.assertNotIn(alpha, engine.visible_stops)

    def test_all_signals_adjusts_for_filtered_bacterium(self):
        engine = self.plain_engine()
        engine.enable_exobiology_mode()
        engine.toggle_genus_filter("Bacterium")
        engine.handle_journal({"event": "FSDJump", "StarSystem": "Alpha", "SystemAddress": 100, "Id": 1})
        engine.handle_journal(
            {
                "event": "SAASignalsFound",
                "StarSystem": "Alpha",
                "SystemAddress": 100,
                "BodyName": "Alpha 1",
                "BodyID": 1,
                "Signals": [{"Type_Localised": "Biological", "Count": 2}],
                "Genuses": [
                    {"Genus_Localised": "Bacterium"},
                    {"Genus_Localised": "Stratum"},
                ],
                "Id": 2,
            }
        )
        actions = engine.handle_journal(
            {
                "event": "ScanOrganic",
                "StarSystem": "Alpha",
                "SystemAddress": 100,
                "Body": 1,
                "BodyName": "Alpha 1",
                "Genus_Localised": "Stratum",
                "Species_Localised": "Stratum Tectonicas",
                "ScanType": "Analyse",
                "Id": 3,
            }
        )
        self.assertEqual(ProgressStatus.COMPLETE, engine.route.stops[0].status)
        self.assertEqual("Beta", engine.current_stop.system)
        self.assertTrue(any(action.get("type") == "advanced" for action in actions))

    def test_filter_hides_bacterium_task_and_bacterium_only_body_from_route_view(self):
        route = import_route(
            self.write_route(
                {
                    "schemaVersion": 3,
                    "name": "Filter View Route",
                    "routeMode": "exobiology",
                    "systems": [
                        {"system": "Alpha", "bodies": [{"body": "Alpha 1", "organisms": [
                            {"species": "Stratum Tectonicas"}, {"species": "Bacterium Informem"}
                        ]}]},
                        {"system": "Beta", "bodies": [{"body": "Beta 2", "organisms": [
                            {"species": "Bacterium Volu"}
                        ]}]},
                        {"system": "Gamma", "bodies": [{"body": "Gamma 3", "organisms": [
                            {"species": "Frutexa Acus"}
                        ]}]},
                    ],
                }
            )
        ).route
        self.assertIsNotNone(route)
        engine = RouteEngine(route)
        actions = engine.toggle_genus_filter("Bacterium")

        self.assertEqual(["Alpha 1", "Gamma 3"], [stop.body for stop in engine.visible_stops])
        beta = engine.route.stops[1]
        self.assertFalse(engine.body_projection(beta).included_body)
        self.assertEqual(ProgressStatus.PENDING, beta.status)
        route_targets = [row["cells"][2]["value"] for row in render_rows(engine)]
        self.assertEqual(["Alpha 1", "Gamma 3"], route_targets)
        organism_rows = render_task_rows(engine)
        self.assertEqual(["Stratum Tectonicas", "Bacterium Informem"], [row["cells"][2]["value"] for row in organism_rows])
        self.assertEqual(["YES", "NO"], [row["cells"][0]["value"].replace("▶ ", "") for row in organism_rows])
        self.assertTrue(any("excluded bodies: 1" in str(action.get("message", "")) for action in actions))

    def test_reenabling_bacterium_restores_hidden_body_and_task_rows(self):
        engine = self.enriched_engine()
        engine.toggle_genus_filter("Bacterium")
        filtered_rows = render_task_rows(engine)
        self.assertEqual(["Stratum Tectonicas", "Bacterium Informem"], [row["cells"][2]["value"] for row in filtered_rows])
        self.assertEqual("NO", filtered_rows[1]["cells"][0]["value"].replace("▶ ", ""))

        engine.toggle_genus_filter("Bacterium")

        self.assertEqual(["Alpha 1", "Beta 2"], [stop.body for stop in engine.visible_stops])
        restored_rows = render_task_rows(engine)
        self.assertEqual(["Stratum Tectonicas", "Bacterium Informem"], [row["cells"][2]["value"] for row in restored_rows])
        self.assertEqual(["YES", "YES"], [row["cells"][0]["value"].replace("▶ ", "") for row in restored_rows])

    def test_visible_route_row_selection_maps_around_hidden_body(self):
        route = import_route(
            self.write_route(
                {
                    "schemaVersion": 3,
                    "name": "Selection Route",
                    "routeMode": "exobiology",
                    "systems": [
                        {"system": "Alpha", "bodies": [{"body": "Alpha 1", "organisms": [{"species": "Stratum Tectonicas"}]}]},
                        {"system": "Beta", "bodies": [{"body": "Beta 2", "organisms": [{"species": "Bacterium Volu"}]}]},
                        {"system": "Gamma", "bodies": [{"body": "Gamma 3", "organisms": [{"species": "Frutexa Acus"}]}]},
                    ],
                }
            )
        ).route
        self.assertIsNotNone(route)
        engine = RouteEngine(route)
        engine.toggle_genus_filter("Bacterium")

        engine.select_visible_stop(1)
        self.assertEqual("Gamma 3", engine.selected_stop.body)
        self.assertEqual(2, engine.selected_index)

    def test_filter_recognizes_bacterium_from_organism_label(self):
        route = import_route(
            self.write_route(
                {
                    "schemaVersion": 2,
                    "name": "Label Filter Route",
                    "routeMode": "exobiology",
                    "stops": [
                        {
                            "system": "Alpha",
                            "body": "Alpha 1",
                            "type": "exobiology",
                            "tasks": [
                                {
                                    "type": "scanOrganic",
                                    "label": "Collect Bacterium Informem",
                                    "samplesRequired": 3,
                                }
                            ],
                        }
                    ],
                }
            )
        ).route
        self.assertIsNotNone(route)
        engine = RouteEngine(route)
        engine.toggle_genus_filter("Bacterium")

        self.assertEqual([], engine.visible_stops)
        task = engine.route.stops[0].tasks[0]
        self.assertEqual("bacterium", task.genus_id)
        self.assertTrue(engine.task_projection(task, engine.route.stops[0]).excluded)
        self.assertEqual("pending", task.status)
        self.assertFalse(engine.body_projection(engine.route.stops[0]).included_body)

    def test_dynamic_second_body_survives_state_round_trip(self):
        first = self.plain_engine()
        first.enable_exobiology_mode()
        first.handle_journal({"event": "FSDJump", "StarSystem": "Alpha", "SystemAddress": 100, "Id": 1})
        first.handle_journal(
            {"event": "ApproachBody", "StarSystem": "Alpha", "SystemAddress": 100, "BodyID": 1, "BodyName": "Alpha 1", "Id": 2}
        )
        first.handle_journal(
            {"event": "ApproachBody", "StarSystem": "Alpha", "SystemAddress": 100, "BodyID": 2, "BodyName": "Alpha 2", "Id": 3}
        )
        self.assertEqual(3, len(first.route.stops))
        state = first.to_state()
        second = self.plain_engine()
        second.apply_state(state)
        bodies = [stop.body for stop in second.route.stops if stop.system == "Alpha"]
        self.assertEqual(["Alpha 1", "Alpha 2"], bodies)
        self.assertTrue(second.route.metadata.get("forceExobiologyMode"))


if __name__ == "__main__":
    unittest.main()
