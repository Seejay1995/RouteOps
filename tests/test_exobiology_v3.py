from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

PLUGIN = Path(__file__).resolve().parents[1] / "Plugin" / "RouteOps"
sys.path.insert(0, str(PLUGIN))

from journal_normalizer import normalize_journal_event  # noqa: E402
from route_engine import RouteEngine  # noqa: E402
from route_importer import import_route, load_route  # noqa: E402
from route_models import CompletionPolicy, OperationPhase, ProgressStatus, TaskStatus  # noqa: E402


class ExobiologyV3Tests(unittest.TestCase):
    def engine(self, value) -> RouteEngine:
        folder = Path(tempfile.mkdtemp())
        path = folder / "route.json"
        path.write_text(json.dumps(value), encoding="utf-8")
        return RouteEngine(load_route(path))

    @staticmethod
    def route_value(two_same_species: bool = True):
        return {
            "schemaVersion": 3,
            "id": "exo-v3-test",
            "name": "Exobiology V3",
            "routeMode": "exobiology",
            "settings": {"autoCopyMode": "smart-target", "autoAdvance": True},
            "systems": [
                {
                    "system": "Alpha",
                    "systemAddress": 100,
                    "bodies": [
                        {
                            "body": "Alpha 1 A",
                            "bodyId": 1,
                            "biologicalSignals": 1,
                            "organisms": [{"id": "alpha-one", "species": "Stratum Tectonicas"}],
                        },
                        {
                            "body": "Alpha 2 B",
                            "bodyId": 2,
                            "biologicalSignals": 1,
                            "organisms": [
                                {
                                    "id": "alpha-two",
                                    "species": "Stratum Tectonicas" if two_same_species else "Bacterium Informem",
                                }
                            ],
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
                            "organisms": [{"id": "beta-three", "species": "Bacterium Informem"}],
                        }
                    ],
                },
            ],
        }

    def test_v3_hierarchy_flattens_to_body_operations_and_resolves_values(self):
        engine = self.engine(self.route_value())
        self.assertEqual("routeops-v3", engine.route.source_format)
        self.assertEqual(3, engine.route.schema_version)
        self.assertEqual(["Alpha 1 A", "Alpha 2 B", "Beta 3"], [stop.body for stop in engine.route.stops])
        self.assertEqual([1, 2, 3], [stop.body_id for stop in engine.route.stops])
        self.assertEqual(19010800, engine.route.stops[0].tasks[0].base_value)
        self.assertEqual(500, engine.route.stops[0].tasks[0].colony_range_m)

    def test_numeric_body_is_body_id_not_body_name(self):
        event = normalize_journal_event(
            {
                "event": "ScanOrganic",
                "SystemAddress": 100,
                "Body": 2,
                "BodyName": "Alpha 2 B",
                "Species_Localised": "Stratum Tectonicas",
            }
        )
        self.assertEqual(2, event.body_id)
        self.assertEqual("Alpha 2 B", event.body)
        self.assertEqual(100, event.system_address)

    def test_system_arrival_does_not_complete_exobiology_body(self):
        engine = self.engine(self.route_value())
        engine.handle_journal({"event": "FSDJump", "StarSystem": "Alpha", "SystemAddress": 100, "Id": 1})
        self.assertEqual(0, engine.current_index)
        self.assertEqual(ProgressStatus.CURRENT, engine.current_stop.status)
        self.assertEqual(OperationPhase.IN_SYSTEM, engine.current_stop.operation_phase)
        self.assertFalse(engine.current_stop.tasks[0].complete)

    def test_same_species_is_scoped_to_exact_body_and_out_of_order_body_is_selected(self):
        engine = self.engine(self.route_value())
        engine.handle_journal({"event": "FSDJump", "StarSystem": "Alpha", "SystemAddress": 100, "Id": 1})
        engine.handle_journal(
            {
                "event": "ScanOrganic",
                "StarSystem": "Alpha",
                "SystemAddress": 100,
                "Body": 2,
                "BodyName": "Alpha 2 B",
                "Genus_Localised": "Stratum",
                "Species_Localised": "Stratum Tectonicas",
                "ScanType": "Log",
                "Id": 2,
            }
        )
        self.assertEqual(1, engine.current_index)
        self.assertEqual(0, engine.route.stops[0].tasks[0].quantity_completed)
        self.assertEqual(1, engine.route.stops[1].tasks[0].quantity_completed)

    def test_scan_progress_is_monotonic(self):
        engine = self.engine(self.route_value())
        base = {
            "event": "ScanOrganic",
            "StarSystem": "Alpha",
            "SystemAddress": 100,
            "Body": 1,
            "BodyName": "Alpha 1 A",
            "Genus_Localised": "Stratum",
            "Species_Localised": "Stratum Tectonicas",
        }
        engine.handle_journal({**base, "ScanType": "Sample", "Id": 1})
        engine.handle_journal({**base, "ScanType": "Log", "Id": 2})
        self.assertEqual(2, engine.route.stops[0].tasks[0].quantity_completed)

    def test_completing_out_of_order_body_returns_to_unfinished_body_and_copies_body(self):
        engine = self.engine(self.route_value())
        copied = ""
        for number, stage in enumerate(("Log", "Sample", "Analyse"), 1):
            actions = engine.handle_journal(
                {
                    "event": "ScanOrganic",
                    "StarSystem": "Alpha",
                    "SystemAddress": 100,
                    "Body": 2,
                    "BodyName": "Alpha 2 B",
                    "Genus_Localised": "Stratum",
                    "Species_Localised": "Stratum Tectonicas",
                    "ScanType": stage,
                    "Id": number,
                }
            )
            copied = next((action["text"] for action in actions if action.get("type") == "copy"), copied)
        self.assertEqual("Alpha 1 A", engine.current_stop.body)
        self.assertEqual("Alpha 1 A", copied)
        self.assertEqual(ProgressStatus.COMPLETE, engine.route.stops[1].status)

    def test_finishing_last_body_in_system_copies_next_system(self):
        engine = self.engine(self.route_value(two_same_species=False))
        for body_id, body_name, species, start_id in (
            (1, "Alpha 1 A", "Stratum Tectonicas", 10),
            (2, "Alpha 2 B", "Bacterium Informem", 20),
        ):
            for offset, stage in enumerate(("Log", "Sample", "Analyse")):
                actions = engine.handle_journal(
                    {
                        "event": "ScanOrganic",
                        "StarSystem": "Alpha",
                        "SystemAddress": 100,
                        "Body": body_id,
                        "BodyName": body_name,
                        "Genus_Localised": species.split()[0],
                        "Species_Localised": species,
                        "ScanType": stage,
                        "Id": start_id + offset,
                    }
                )
        copy = [action for action in actions if action.get("type") == "copy"][-1]
        self.assertEqual("Beta", copy["text"])
        self.assertEqual("Beta 3", engine.current_stop.body)

    def test_saa_signals_add_genus_placeholder_and_scan_enriches_it(self):
        engine = self.engine(
            {
                "schemaVersion": 3,
                "id": "signals",
                "name": "Signals",
                "routeMode": "exobiology",
                "systems": [
                    {
                        "system": "Alpha",
                        "systemAddress": 100,
                        "bodies": [
                            {
                                "body": "Alpha 1 A",
                                "bodyId": 1,
                                "completionPolicy": "all-signals",
                                "organisms": [],
                            }
                        ],
                    }
                ],
            }
        )
        engine.handle_journal(
            {
                "event": "SAASignalsFound",
                "StarSystem": "Alpha",
                "SystemAddress": 100,
                "BodyName": "Alpha 1 A",
                "BodyID": 1,
                "Signals": [{"Type_Localised": "Biological", "Count": 1}],
                "Genuses": [{"Genus_Localised": "Bacterium"}],
                "Id": 1,
            }
        )
        stop = engine.current_stop
        self.assertEqual(1, stop.biological_signal_count)
        self.assertEqual(1, len(stop.tasks))
        self.assertEqual("Bacterium", stop.tasks[0].genus)
        self.assertTrue(stop.tasks[0].required)
        engine.handle_journal(
            {
                "event": "ScanOrganic",
                "StarSystem": "Alpha",
                "SystemAddress": 100,
                "Body": 1,
                "BodyName": "Alpha 1 A",
                "Genus_Localised": "Bacterium",
                "Species_Localised": "Bacterium Informem",
                "ScanType": "Log",
                "Id": 2,
            }
        )
        self.assertEqual("Bacterium Informem", stop.tasks[0].species)
        self.assertEqual(8418000, stop.tasks[0].base_value)

    def test_unplanned_organism_is_optional_under_listed_targets(self):
        engine = self.engine(self.route_value(two_same_species=False))
        engine.handle_journal(
            {
                "event": "ScanOrganic",
                "StarSystem": "Alpha",
                "SystemAddress": 100,
                "Body": 1,
                "BodyName": "Alpha 1 A",
                "Genus_Localised": "Frutexa",
                "Species_Localised": "Frutexa Acus",
                "ScanType": "Log",
                "Id": 1,
            }
        )
        dynamic = [task for task in engine.route.stops[0].tasks if task.discovered_dynamically]
        self.assertEqual(1, len(dynamic))
        self.assertFalse(dynamic[0].required)
        self.assertEqual(7774700, dynamic[0].base_value)

    def test_value_metrics_separate_secured_remaining_potential_and_actual(self):
        engine = self.engine(self.route_value(two_same_species=False))
        task = engine.route.stops[0].tasks[0]
        task.complete = True
        metrics = engine.route_metrics()
        self.assertEqual(35846800, metrics.planned_base_value)
        self.assertEqual(19010800, metrics.secured_base_value)
        self.assertEqual(16836000, metrics.remaining_base_value)
        self.assertEqual(metrics.planned_base_value * 5, metrics.potential_first_logged_value)

    def test_sell_organic_data_allocates_unique_species(self):
        engine = self.engine(self.route_value(two_same_species=False))
        task = engine.route.stops[0].tasks[0]
        task.complete = True
        engine.handle_journal(
            {
                "event": "SellOrganicData",
                "BioData": [
                    {
                        "Species_Localised": "Stratum Tectonicas",
                        "Value": 19010800,
                        "Bonus": 76043200,
                    }
                ],
                "Id": 90,
            }
        )
        self.assertEqual("sold", task.sale_status)
        self.assertEqual(19010800, task.actual_value)
        self.assertEqual(76043200, task.actual_bonus)
        self.assertEqual(0, len(engine.sales_ledger))

    def test_sell_organic_data_ambiguous_species_stays_unallocated(self):
        engine = self.engine(self.route_value(two_same_species=True))
        engine.route.stops[0].tasks[0].complete = True
        engine.route.stops[1].tasks[0].complete = True
        engine.handle_journal(
            {
                "event": "SellOrganicData",
                "BioData": [{"Species_Localised": "Stratum Tectonicas", "Value": 19010800, "Bonus": 0}],
                "Id": 91,
            }
        )
        self.assertEqual(1, len(engine.sales_ledger))
        self.assertEqual("ambiguous", engine.sales_ledger[0]["reason"])
        self.assertEqual(1, engine.route_metrics().unallocated_sale_entries)

    def test_dynamic_organism_and_selected_task_survive_state_round_trip(self):
        first = self.engine(self.route_value(two_same_species=False))
        first.handle_journal(
            {
                "event": "ScanOrganic",
                "StarSystem": "Alpha",
                "SystemAddress": 100,
                "Body": 1,
                "BodyName": "Alpha 1 A",
                "Genus_Localised": "Frutexa",
                "Species_Localised": "Frutexa Acus",
                "ScanType": "Sample",
                "Id": 1,
            }
        )
        dynamic = [task for task in first.current_stop.tasks if task.discovered_dynamically][0]
        first.selected_task_id = dynamic.id
        state = first.to_state()
        second = self.engine(self.route_value(two_same_species=False))
        second.apply_state(state)
        restored = next(task for task in second.current_stop.tasks if task.id == dynamic.id)
        self.assertEqual(2, restored.quantity_completed)
        self.assertEqual(dynamic.id, second.selected_task_id)

    def test_manual_completion_policy_does_not_auto_complete(self):
        value = self.route_value(two_same_species=False)
        value["systems"][0]["bodies"][0]["completionPolicy"] = CompletionPolicy.MANUAL
        engine = self.engine(value)
        task = engine.current_stop.tasks[0]
        task.complete = True
        self.assertFalse(engine.current_stop.work_complete)

    def test_task_skip_and_reopen_are_individual(self):
        engine = self.engine(self.route_value(two_same_species=False))
        task = engine.selected_task
        engine.skip_selected_task()
        self.assertEqual(TaskStatus.SKIPPED, task.status)
        engine.toggle_route_view()
        engine.select_stop(0)
        engine.select_task(0)
        engine.reopen_selected_task()
        self.assertEqual(TaskStatus.PENDING, task.status)


class SpanshImportTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.temp_dir.cleanup()

    def write_json(self, payload):
        path = Path(self.temp_dir.name) / "spansh.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def test_spansh_style_json_rows_group_by_body(self):
        payload = {
            "results": [
                {"system_name": "Alpha", "system_address": 100, "body_name": "Alpha 1", "body_id": 1, "species": "Stratum Tectonicas", "value": 19010800},
                {"system_name": "Alpha", "system_address": 100, "body_name": "Alpha 1", "body_id": 1, "species": "Bacterium Informem", "value": 8418000},
                {"system_name": "Alpha", "system_address": 100, "body_name": "Alpha 2", "body_id": 2, "species": "Frutexa Acus", "value": 7774700},
            ]
        }
        path = self.write_json(payload)
        result = import_route(path)
        self.assertEqual([], result.errors)
        self.assertEqual("spansh-exobiology-json", result.route.source_format)
        self.assertEqual(2, len(result.route.stops))
        self.assertEqual(2, len(result.route.stops[0].tasks))

    def test_spansh_style_csv_is_not_treated_as_trade(self):
        path = Path(self.temp_dir.name) / "spansh.csv"
        path.write_text(
            "System Name,System Address,Body Name,Body ID,Species,Value\n"
            "Alpha,100,Alpha 1,1,Stratum Tectonicas,19010800\n",
            encoding="utf-8",
        )
        result = import_route(path)
        self.assertEqual([], result.errors)
        self.assertEqual("spansh-exobiology-csv", result.route.source_format)
        self.assertEqual("exobiology", result.route.route_type)
        self.assertEqual(19010800, result.route.stops[0].tasks[0].base_value)


if __name__ == "__main__":
    unittest.main()
