from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

PLUGIN = Path(__file__).resolve().parents[1] / "Plugin" / "RouteOps"
sys.path.insert(0, str(PLUGIN))

from session_storage import FileSessionStorage  # noqa: E402


class SessionStorageTests(unittest.TestCase):
    def test_default_fallback_is_plugin_local(self):
        root = Path(tempfile.mkdtemp()) / "Plugins" / "RouteOps"
        storage = FileSessionStorage.for_plugin(root)

        self.assertEqual((root / "State").resolve(), storage.fallback_dir)

    def test_relative_override_is_resolved_from_plugin_directory(self):
        root = Path(tempfile.mkdtemp()) / "Plugins" / "RouteOps"
        storage = FileSessionStorage.for_plugin(root, "PortableState")

        self.assertEqual((root / "PortableState").resolve(), storage.fallback_dir)

    def test_absolute_override_is_preserved(self):
        root = Path(tempfile.mkdtemp()) / "Plugins" / "RouteOps"
        destination = Path(tempfile.mkdtemp()) / "RouteOpsState"
        storage = FileSessionStorage.for_plugin(root, destination)

        self.assertEqual(destination.resolve(), storage.fallback_dir)

    def test_paths_are_deterministic_for_portable_drive_routes(self):
        root = Path(tempfile.mkdtemp()) / "Plugins" / "RouteOps"
        storage = FileSessionStorage.for_plugin(root)
        route_path = r"E:\Expeditions\Distant Worlds.json"

        first = storage.paths_for(route_path)
        second = storage.paths_for(route_path)

        self.assertEqual(first, second)
        self.assertEqual(storage.fallback_dir, first.fallback.parent)
        self.assertTrue(first.fallback.name.endswith(".routeops.state.json"))

    def test_round_trip_preserves_state_contract(self):
        folder = Path(tempfile.mkdtemp())
        route_path = folder / "route.json"
        route_path.write_text("{}", encoding="utf-8")
        storage = FileSessionStorage.for_plugin(folder / "Plugins" / "RouteOps")
        state = {"routeId": "route-1", "currentStopId": "stop-1"}

        saved = storage.save(str(route_path), state)
        loaded = storage.load(str(route_path))

        self.assertEqual(storage.paths_for(str(route_path)).primary, saved)
        self.assertEqual(state["routeId"], loaded["routeId"])
        self.assertEqual(state["currentStopId"], loaded["currentStopId"])


if __name__ == "__main__":
    unittest.main()
