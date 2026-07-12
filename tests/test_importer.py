from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

PLUGIN = Path(__file__).resolve().parents[1] / "Plugin" / "RouteOps"
sys.path.insert(0, str(PLUGIN))

from route_importer import import_route, load_route  # noqa: E402
from route_models import RouteMode, StopType  # noqa: E402
from route_metrics import calculate_route_metrics  # noqa: E402


class ImporterTests(unittest.TestCase):
    def write_json(self, value) -> str:
        folder = Path(tempfile.mkdtemp())
        path = folder / "route.json"
        path.write_text(json.dumps(value), encoding="utf-8")
        return str(path)

    def test_native_edd_expedition_is_waypoint_route(self):
        route = load_route(self.write_json({"Name": "EDD Route", "Systems": ["Sol", "Colonia"]}))
        self.assertEqual("edd-expedition", route.source_format)
        self.assertEqual(RouteMode.WAYPOINT, route.route_type)
        self.assertTrue(all(stop.stop_type == StopType.WAYPOINT for stop in route.stops))
        self.assertTrue(all(stop.auto_complete_on_arrival for stop in route.stops))

    def test_native_edd_expedition_ignores_trailing_blank_stop(self):
        systems = [f"System {index}" for index in range(1, 12)] + ["   "]
        result = import_route(self.write_json({"Name": "Eleven Stops", "Systems": systems}))
        self.assertIsNotNone(result.route)
        self.assertEqual(11, len(result.route.stops))
        self.assertEqual("System 11", result.route.stops[-1].system)
        self.assertTrue(any("Ignored empty stop 12" in warning for warning in result.warnings))

    def test_blank_stop_preserves_later_source_sequence_for_legacy_state_ids(self):
        result = import_route(
            self.write_json({"Name": "Gap", "Systems": ["Sol", "", "Achenar"]})
        )
        self.assertIsNotNone(result.route)
        self.assertEqual(["stop-1", "stop-3"], [stop.id for stop in result.route.stops])
        self.assertEqual([1, 3], [stop.sequence for stop in result.route.stops])

    def test_edd_route_name_infers_trade_specialty_without_auto_advancing(self):
        route = load_route(
            self.write_json(
                {"Name": "Diaguandri to Ray Gateway (Trade)", "Systems": ["Diaguandri", "LHS 2936"]}
            )
        )
        self.assertEqual(RouteMode.TRADE, route.route_type)
        self.assertTrue(all(stop.stop_type == StopType.TRADE for stop in route.stops))
        self.assertTrue(all(not stop.auto_complete_on_arrival for stop in route.stops))

    def test_routeops_v2_infers_mixed_mode(self):
        route = load_route(
            self.write_json(
                {
                    "schemaVersion": 2,
                    "name": "Mixed",
                    "stops": [
                        {"system": "Sol", "stopType": "waypoint"},
                        {
                            "system": "HIP 36601",
                            "tasks": [{"type": "collectMaterial", "material": "Polonium", "quantity": 5}],
                        },
                    ],
                }
            )
        )
        self.assertEqual("routeops-v2", route.source_format)
        self.assertEqual(RouteMode.MIXED, route.route_type)
        self.assertEqual(StopType.MATERIALS, route.stops[1].stop_type)

    def test_exobiology_task_fields_are_normalized(self):
        route = load_route(
            self.write_json(
                {
                    "schemaVersion": 2,
                    "name": "Exo",
                    "routeMode": "exo",
                    "stops": [
                        {
                            "system": "Test",
                            "body": "Test 1 A",
                            "tasks": [
                                {
                                    "type": "scanSpecies",
                                    "species": "Stratum Tectonicas",
                                    "samplesRequired": 3,
                                    "optional": True,
                                }
                            ],
                        }
                    ],
                }
            )
        )
        task = route.stops[0].tasks[0]
        self.assertEqual("scanSpecies", task.task_type)
        self.assertEqual("Stratum Tectonicas", task.target)
        self.assertEqual(3, task.quantity_required)
        self.assertFalse(task.required)

    def test_duplicate_ids_are_renamed_with_warnings(self):
        result = import_route(
            self.write_json(
                {
                    "name": "Duplicates",
                    "stops": [
                        {"id": "same", "system": "Sol"},
                        {"id": "same", "system": "Achenar"},
                        {"id": "same", "system": "Colonia"},
                    ],
                }
            )
        )
        self.assertIsNotNone(result.route)
        self.assertEqual(3, len({stop.id for stop in result.route.stops}))
        self.assertTrue(any("Duplicate stop ID" in warning for warning in result.warnings))

    def test_missing_system_returns_clear_error(self):
        result = import_route(self.write_json({"name": "Bad", "stops": [{"label": "No system"}]}))
        self.assertIsNone(result.route)
        self.assertTrue(any("no system name" in error.casefold() for error in result.errors))

    def test_settings_are_loaded(self):
        route = load_route(
            self.write_json(
                {
                    "schemaVersion": 2,
                    "name": "Settings",
                    "settings": {
                        "autoCopyMode": "next-system",
                        "autoAdvance": False,
                        "clipboardRetryCount": 9,
                    },
                    "stops": ["Sol"],
                }
            )
        )
        self.assertEqual("next-system", route.settings.auto_copy_mode)
        self.assertFalse(route.settings.auto_advance)
        self.assertEqual(9, route.settings.clipboard_retry_count)


class TradeCsvImporterTests(unittest.TestCase):
    def write_csv(self, text: str, suffix: str = ".csv") -> str:
        folder = Path(tempfile.mkdtemp())
        path = folder / f"trade-route{suffix}"
        path.write_text(text, encoding="utf-8")
        return str(path)

    def test_edd_trade_router_csv_defines_buy_sell_and_dock_tasks(self):
        route = load_route(
            self.write_csv(
                'System,Note,Distance\n'
                'Diaguandri,"Station: Ray Gateway\nGold buy 4 profit 1200\nSilver buy 2 profit 500\nProfit so far: 1700",0\n'
                'LHS 2936,"Station: Fraser Orbital\nPalladium buy 3 profit 900\nProfit so far: 2600",20\n'
                'Arietes Sector UQ-O b6-1,"Fly to Smith Terminal and sell all",30\n'
            )
        )
        self.assertEqual("edd-trade-router-csv", route.source_format)
        self.assertEqual(RouteMode.TRADE, route.route_type)
        self.assertEqual(["Ray Gateway", "Fraser Orbital", "Smith Terminal"], [s.station for s in route.stops])
        self.assertEqual(
            ["dockAtStation", "buyCommodity", "buyCommodity"],
            [task.task_type for task in route.stops[0].tasks],
        )
        self.assertEqual(
            ["dockAtStation", "sellCommodity", "sellCommodity", "buyCommodity"],
            [task.task_type for task in route.stops[1].tasks],
        )
        self.assertEqual(
            ["dockAtStation", "sellCommodity"],
            [task.task_type for task in route.stops[2].tasks],
        )
        self.assertEqual([4, 2], [task.quantity_required for task in route.stops[0].tasks[1:]])
        self.assertEqual("Palladium", route.stops[2].tasks[1].target)
        self.assertEqual(3, route.stops[2].tasks[1].quantity_required)
        self.assertEqual(2600, calculate_route_metrics(route).estimated_value)

    def test_trade_csv_supports_semicolon_delimiter(self):
        route = load_route(
            self.write_csv(
                'System;Information;Distance\n'
                'Sol;"Station: Galileo\nGold buy 7 profit 100";0\n'
                'Achenar;"Fly to Dawes Hub and sell all";100\n'
            )
        )
        self.assertEqual(RouteMode.TRADE, route.route_type)
        self.assertEqual("Galileo", route.stops[0].station)
        self.assertEqual("Dawes Hub", route.stops[1].station)
        self.assertEqual("Gold", route.stops[1].tasks[1].target)

    def test_trade_named_expedition_warns_that_json_lost_trade_data(self):
        folder = Path(tempfile.mkdtemp())
        path = folder / "trade.json"
        path.write_text(
            json.dumps({"Name": "Diaguandri @ Ray Gateway (Trade)", "Systems": ["Diaguandri", "LHS 2936"]}),
            encoding="utf-8",
        )
        result = import_route(path)
        self.assertIsNotNone(result.route)
        self.assertTrue(result.route.metadata.get("tradeDataMissing"))
        self.assertTrue(all(stop.metadata.get("tradeDataMissing") for stop in result.route.stops))
        self.assertTrue(any("Excel/CSV" in warning for warning in result.warnings))


if __name__ == "__main__":
    unittest.main()
