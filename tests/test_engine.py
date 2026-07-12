from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

PLUGIN = Path(__file__).resolve().parents[1] / "Plugin" / "RouteOps"
sys.path.insert(0, str(PLUGIN))

from route_engine import RouteEngine  # noqa: E402
from route_importer import load_route  # noqa: E402
from route_models import ProgressStatus  # noqa: E402


class EngineTests(unittest.TestCase):
    def engine(self, value) -> RouteEngine:
        folder = Path(tempfile.mkdtemp())
        path = folder / "route.json"
        path.write_text(json.dumps(value), encoding="utf-8")
        return RouteEngine(load_route(path))

    def test_waypoint_arrival_advances_and_copies_next(self):
        engine = self.engine({"Name": "EDD", "Systems": ["Sol", "Colonia"]})
        actions = engine.handle_journal({"EventTypeID": "FSDJump", "StarSystem": "Sol", "Id": 1})
        self.assertEqual(1, engine.current_index)
        self.assertTrue(any(action.get("type") == "copy" and action.get("text") == "Colonia" for action in actions))

    def test_pause_tracks_arrival_but_does_not_advance(self):
        engine = self.engine({"Name": "EDD", "Systems": ["Sol", "Colonia"]})
        engine.paused = True
        engine.handle_journal({"EventTypeID": "FSDJump", "StarSystem": "Sol", "Id": 1})
        self.assertEqual(0, engine.current_index)
        self.assertEqual(ProgressStatus.READY, engine.current_stop.status)

    def test_exobiology_analyse_completes_required_species(self):
        engine = self.engine(
            {
                "schemaVersion": 2,
                "name": "Exo",
                "stops": [
                    {
                        "system": "Test",
                        "stopType": "exobiology",
                        "tasks": [{"type": "scanOrganic", "species": "Stratum Tectonicas", "samplesRequired": 3}],
                    },
                    {"system": "Next"},
                ],
            }
        )
        engine.handle_journal({"EventTypeID": "FSDJump", "StarSystem": "Test", "Id": 1})
        engine.handle_journal(
            {
                "EventTypeID": "ScanOrganic",
                "Species_Localised": "Stratum Tectonicas",
                "ScanType": "Analyse",
                "Id": 2,
            }
        )
        self.assertEqual(1, engine.current_index)

    def test_optional_exobiology_target_does_not_block(self):
        engine = self.engine(
            {
                "name": "Exo",
                "stops": [
                    {
                        "system": "Test",
                        "tasks": [
                            {"type": "scanOrganic", "species": "Stratum", "samplesRequired": 3},
                            {"type": "scanOrganic", "species": "Bacterium", "samplesRequired": 3, "optional": True},
                        ],
                    },
                    {"system": "Next"},
                ],
            }
        )
        engine.handle_journal(
            {"EventTypeID": "ScanOrganic", "Species_Localised": "Stratum", "ScanType": "Analyse", "Id": 1}
        )
        self.assertEqual(1, engine.current_index)

    def test_material_collection_aggregates(self):
        engine = self.engine(
            {
                "name": "Mats",
                "stops": [
                    {
                        "system": "HIP 36601",
                        "tasks": [{"type": "collectMaterial", "material": "Polonium", "quantity": 5}],
                    },
                    {"system": "Next"},
                ],
            }
        )
        engine.handle_journal({"EventTypeID": "MaterialCollected", "Name_Localised": "Polonium", "Count": 3, "Id": 1})
        self.assertEqual(3, engine.current_stop.tasks[0].quantity_completed)
        engine.handle_journal({"EventTypeID": "MaterialCollected", "Name_Localised": "Polonium", "Count": 2, "Id": 2})
        self.assertEqual(1, engine.current_index)

    def test_wrong_material_is_ignored(self):
        engine = self.engine(
            {
                "name": "Mats",
                "stops": [{"system": "HIP", "tasks": [{"type": "collectMaterial", "material": "Polonium", "quantity": 5}]}],
            }
        )
        engine.handle_journal({"EventTypeID": "MaterialCollected", "Name_Localised": "Iron", "Count": 5, "Id": 1})
        self.assertEqual(0, engine.current_stop.tasks[0].quantity_completed)

    def test_market_buy_and_dock_both_required(self):
        engine = self.engine(
            {
                "name": "Trade",
                "stops": [
                    {
                        "system": "Diaguandri",
                        "station": "Ray Gateway",
                        "tasks": [
                            {"type": "dockAtStation", "station": "Ray Gateway"},
                            {"type": "buyCommodity", "commodity": "Gold", "quantity": 10},
                        ],
                    },
                    {"system": "Next"},
                ],
            }
        )
        engine.handle_journal({"EventTypeID": "MarketBuy", "Type_Localised": "Gold", "Count": 10, "Id": 1})
        self.assertEqual(0, engine.current_index)
        engine.handle_journal({"EventTypeID": "Docked", "StationName": "Ray Gateway", "Id": 2})
        self.assertEqual(1, engine.current_index)

    def test_market_buys_aggregate(self):
        engine = self.engine(
            {
                "name": "Trade",
                "stops": [
                    {"system": "D", "tasks": [{"type": "buyCommodity", "commodity": "Gold", "quantity": 10}]},
                    {"system": "Next"},
                ],
            }
        )
        engine.handle_journal({"EventTypeID": "MarketBuy", "Type_Localised": "Gold", "Count": 4, "Id": 1})
        self.assertEqual(4, engine.current_stop.tasks[0].quantity_completed)
        engine.handle_journal({"EventTypeID": "MarketBuy", "Type_Localised": "Gold", "Count": 6, "Id": 2})
        self.assertEqual(1, engine.current_index)

    def test_selecting_row_does_not_change_current(self):
        engine = self.engine({"Name": "EDD", "Systems": ["Sol", "Achenar", "Colonia"]})
        engine.select_stop(2)
        self.assertEqual(0, engine.current_index)
        self.assertEqual(2, engine.selected_index)

    def test_jump_to_selected_changes_current(self):
        engine = self.engine({"Name": "EDD", "Systems": ["Sol", "Achenar", "Colonia"]})
        engine.select_stop(2)
        engine.jump_to()
        self.assertEqual(2, engine.current_index)
        self.assertEqual("Colonia", engine.current_stop.system)

    def test_complete_selected_task_manual(self):
        engine = self.engine(
            {
                "name": "Checklist",
                "settings": {"autoAdvance": False},
                "stops": [{"system": "Sol", "tasks": [{"type": "manualChecklist", "label": "Take screenshot"}]}],
            }
        )
        engine.complete_selected_task()
        self.assertTrue(engine.current_stop.tasks[0].complete)
        self.assertEqual(ProgressStatus.READY, engine.current_stop.status)

    def test_v1_state_current_index_migrates(self):
        engine = self.engine({"Name": "EDD", "Systems": ["Sol", "Achenar", "Colonia"]})
        engine.apply_state(
            {
                "route_id": engine.route.id,
                "current_index": 1,
                "paused": True,
                "auto_advance": True,
                "stops": {},
            }
        )
        self.assertEqual(1, engine.current_index)
        self.assertEqual("Achenar", engine.current_stop.system)
        self.assertTrue(engine.paused)

    def test_state_round_trip_keeps_selection_and_tasks(self):
        first = self.engine(
            {
                "name": "State",
                "stops": [
                    {"system": "Sol", "tasks": [{"type": "collectMaterial", "material": "Iron", "quantity": 3}]},
                    {"system": "Next"},
                ],
            }
        )
        first.select_stop(1)
        first.handle_journal({"EventTypeID": "MaterialCollected", "Name_Localised": "Iron", "Count": 2, "Id": 1})
        state = first.to_state()
        second = self.engine(
            {
                "name": "State",
                "stops": [
                    {"system": "Sol", "tasks": [{"type": "collectMaterial", "material": "Iron", "quantity": 3}]},
                    {"system": "Next"},
                ],
            }
        )
        second.apply_state(state)
        self.assertEqual(1, second.selected_index)
        self.assertEqual(2, second.route.stops[0].tasks[0].quantity_completed)

    def test_trade_csv_tasks_advance_after_dock_buy_sell_sequence(self):
        folder = Path(tempfile.mkdtemp())
        path = folder / "trade.csv"
        path.write_text(
            'System,Note\n'
            'Diaguandri,"Station: Ray Gateway\nGold buy 4 profit 100"\n'
            'LHS 2936,"Fly to Fraser Orbital and sell all"\n',
            encoding="utf-8",
        )
        engine = RouteEngine(load_route(path))
        # Trade CSV routes infer docking from a matching market transaction so
        # loading RouteOps while already docked does not leave the dock task stuck.
        engine.handle_journal({"EventTypeID": "MarketBuy", "Type_Localised": "Gold", "Count": 4, "Id": 1})
        self.assertEqual(1, engine.current_index)
        engine.handle_journal({"EventTypeID": "MarketSell", "Type_Localised": "Gold", "Count": 4, "Id": 2})
        self.assertTrue(engine.complete)


if __name__ == "__main__":
    unittest.main()
