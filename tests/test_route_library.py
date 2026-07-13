from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

PLUGIN = Path(__file__).resolve().parents[1] / "Plugin" / "RouteOps"
sys.path.insert(0, str(PLUGIN))

from route_library import RouteLibrary, RouteLibraryEntry, file_fingerprint  # noqa: E402
from route_models import ProgressStatus, Route, RouteStop  # noqa: E402


class RouteLibraryTests(unittest.TestCase):
    def create_route_file(self, folder: Path, name: str = "route.json") -> Path:
        path = folder / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"route": ["Sol", "Achenar"]}), encoding="utf-8")
        return path

    def route(self, path: Path, route_id: str = "route-1") -> Route:
        return Route(
            id=route_id,
            name="Portable Expedition",
            route_type="exobiology",
            source_format="routeops-v3",
            source_path=str(path),
            stops=[
                RouteStop(id="one", sequence=1, system="Sol", status=ProgressStatus.COMPLETE),
                RouteStop(id="two", sequence=2, system="Achenar", status=ProgressStatus.CURRENT),
            ],
        )

    def test_record_deduplicates_by_fingerprint_and_keeps_latest_path(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            first = self.create_route_file(root / "old")
            second = self.create_route_file(root / "new")
            library = RouteLibrary(limit=5)

            library.record(self.route(first), first)
            library.record(self.route(second), second)

            self.assertEqual(1, len(library.entries))
            self.assertEqual(str(second.resolve()), library.entries[0].path)
            self.assertEqual(50.0, library.entries[0].completion_percent)
            self.assertEqual(2, library.entries[0].system_count)

    def test_config_round_trip_preserves_recent_order(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            first = self.create_route_file(root, "first.json")
            second = self.create_route_file(root, "second.json")
            library = RouteLibrary(limit=5)
            library.record(self.route(first, "one"), first)
            second.write_text(json.dumps({"route": ["Colonia"]}), encoding="utf-8")
            library.record(self.route(second, "two"), second)
            config: dict[str, object] = {}

            library.save_to_config(config)
            restored = RouteLibrary.from_config(config, limit=5)

            self.assertEqual(2, len(restored.entries))
            self.assertEqual("two", restored.entries[0].route_id)
            self.assertEqual("one", restored.entries[1].route_id)

    def test_missing_route_recovers_from_bounded_search_root_by_fingerprint(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            original = self.create_route_file(root / "old")
            fingerprint = file_fingerprint(original)
            moved = root / "portable" / "Routes" / original.name
            moved.parent.mkdir(parents=True)
            moved.write_bytes(original.read_bytes())
            original.unlink()
            entry = RouteLibraryEntry(
                path=str(original),
                name="Moved Route",
                route_id="moved",
                route_type="expedition",
                source_format="routeops-v3",
                system_count=2,
                stop_count=2,
                completion_percent=0.0,
                last_system="",
                fingerprint=fingerprint,
                last_opened_at="2026-07-13T00:00:00+00:00",
            )
            library = RouteLibrary([entry])

            refreshed = library.refresh_availability([root / "portable"], drive_roots=())

            self.assertTrue(refreshed[0].available)
            self.assertEqual(str(moved.resolve()), refreshed[0].path)
            self.assertEqual(str(original), refreshed[0].recovered_from)

    def test_wrong_content_is_not_accepted_as_recovery(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            original = self.create_route_file(root / "old")
            fingerprint = file_fingerprint(original)
            candidate = root / "portable" / "Routes" / original.name
            candidate.parent.mkdir(parents=True)
            candidate.write_text("different route", encoding="utf-8")
            original.unlink()
            entry = RouteLibraryEntry(
                path=str(original), name="Route", route_id="id", route_type="expedition",
                source_format="json", system_count=0, stop_count=0,
                completion_percent=0.0, last_system="", fingerprint=fingerprint,
                last_opened_at="2026-07-13T00:00:00+00:00",
            )
            library = RouteLibrary([entry])

            refreshed = library.refresh_availability([root / "portable"], drive_roots=())

            self.assertFalse(refreshed[0].available)
            self.assertEqual(str(original), refreshed[0].path)

    def test_library_is_bounded(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            library = RouteLibrary(limit=2)
            for index in range(3):
                path = self.create_route_file(root, f"route-{index}.json")
                path.write_text(str(index), encoding="utf-8")
                library.record(self.route(path, f"route-{index}"), path)

            self.assertEqual(2, len(library.entries))
            self.assertEqual("route-2", library.entries[0].route_id)
            self.assertEqual("route-1", library.entries[1].route_id)


if __name__ == "__main__":
    unittest.main()
