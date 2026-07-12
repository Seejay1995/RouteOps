from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

PLUGIN = Path(__file__).resolve().parents[1] / "Plugin" / "RouteOps"
sys.path.insert(0, str(PLUGIN))

from kernel_contracts import KernelCommand, KernelCommandType  # noqa: E402
from route_engine import RouteEngine  # noqa: E402
from route_importer import load_route  # noqa: E402
from route_kernel import RouteKernel  # noqa: E402


class RouteKernelTests(unittest.TestCase):
    def make_route_path(self, value: dict) -> Path:
        folder = Path(tempfile.mkdtemp())
        path = folder / "route.json"
        path.write_text(json.dumps(value), encoding="utf-8")
        return path

    def make_engine(self, value: dict) -> RouteEngine:
        return RouteEngine(load_route(self.make_route_path(value)))

    def test_journal_dispatch_matches_direct_engine_behavior(self):
        route = {"Name": "EDD", "Systems": ["Sol", "Colonia"]}
        path = self.make_route_path(route)
        direct = RouteEngine(load_route(path))
        wrapped = RouteEngine(load_route(path))

        entry = {"EventTypeID": "FSDJump", "StarSystem": "Sol", "Id": 1}
        expected = direct.handle_journal(entry)
        actual = RouteKernel(wrapped).handle_journal(entry)

        self.assertTrue(actual.success)
        self.assertEqual(tuple(expected), actual.actions)
        self.assertEqual(direct.to_state(), wrapped.to_state())

    def test_select_system_command_matches_engine(self):
        route = {"Name": "EDD", "Systems": ["Sol", "Colonia"]}
        direct = self.make_engine(route)
        wrapped = self.make_engine(route)

        expected = direct.select_system(1)
        actual = RouteKernel(wrapped).execute(
            KernelCommand(KernelCommandType.SELECT_SYSTEM, {"index": 1})
        )

        self.assertTrue(actual.success)
        self.assertEqual(tuple(expected), actual.actions)
        self.assertEqual(direct.selected_system_key, wrapped.selected_system_key)

    def test_snapshot_is_engine_state(self):
        engine = self.make_engine({"Name": "EDD", "Systems": ["Sol"]})
        kernel = RouteKernel(engine)
        self.assertEqual(engine.to_state(), kernel.snapshot())

    def test_unsupported_command_is_rejected_without_mutation(self):
        engine = self.make_engine({"Name": "EDD", "Systems": ["Sol"]})
        kernel = RouteKernel(engine)
        before = engine.to_state()

        result = kernel.execute(KernelCommand("not-a-command"))

        self.assertFalse(result.success)
        self.assertIn("Unsupported kernel command", result.error)
        self.assertEqual(before, engine.to_state())


if __name__ == "__main__":
    unittest.main()
