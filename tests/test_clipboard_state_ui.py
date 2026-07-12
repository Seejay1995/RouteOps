from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

PLUGIN = Path(__file__).resolve().parents[1] / "Plugin" / "RouteOps"
sys.path.insert(0, str(PLUGIN))

from clipboard_service import ClipboardBusyError, copy_text  # noqa: E402
from route_engine import RouteEngine  # noqa: E402
from route_importer import load_route  # noqa: E402
from state_store import fallback_state_path_for, load_state, save_state, state_path_for  # noqa: E402
from ui_renderer import render_detail, render_header, render_rows  # noqa: E402


class ClipboardTests(unittest.TestCase):
    def test_busy_clipboard_retries_then_succeeds(self):
        calls = {"count": 0}

        def backend(text):
            calls["count"] += 1
            if calls["count"] < 3:
                raise ClipboardBusyError("busy")

        result = copy_text("Sol", retries=5, windows_backend=backend, fallback=lambda text: None, sleeper=lambda _: None)
        self.assertTrue(result.success)
        self.assertEqual(3, result.attempts)

    def test_fallback_is_used_after_windows_failure(self):
        copied = []

        def backend(text):
            raise RuntimeError("broken")

        result = copy_text("Colonia", windows_backend=backend, fallback=copied.append, sleeper=lambda _: None)
        self.assertTrue(result.success)
        self.assertEqual(["Colonia"], copied)

    def test_total_failure_is_non_throwing_result(self):
        result = copy_text(
            "Sol",
            retries=2,
            windows_backend=lambda text: (_ for _ in ()).throw(ClipboardBusyError("busy")),
            fallback=lambda text: (_ for _ in ()).throw(RuntimeError("fallback failed")),
            sleeper=lambda _: None,
        )
        self.assertFalse(result.success)
        self.assertIn("busy", result.error)


class StateTests(unittest.TestCase):
    def test_save_and_load_sidecar(self):
        folder = Path(tempfile.mkdtemp())
        route = folder / "route.json"
        route.write_text("{}", encoding="utf-8")
        state = {"stateVersion": 2, "routeId": "abc"}
        destination = save_state(str(route), state, folder / "fallback")
        self.assertEqual(state_path_for(str(route)), destination)
        self.assertEqual("abc", load_state(str(route), folder / "fallback")["routeId"])

    def test_read_only_failure_uses_fallback(self):
        folder = Path(tempfile.mkdtemp())
        route = folder / "route.json"
        route.write_text("{}", encoding="utf-8")
        fallback = folder / "fallback"
        primary = state_path_for(str(route))
        original_write = Path.write_text

        def guarded_write(path, *args, **kwargs):
            if path.parent == primary.parent and path.name.startswith(primary.name):
                raise OSError("read only")
            return original_write(path, *args, **kwargs)

        with mock.patch.object(Path, "write_text", guarded_write):
            destination = save_state(str(route), {"stateVersion": 2, "routeId": "abc"}, fallback)
        self.assertEqual(fallback_state_path_for(str(route), fallback), destination)
        self.assertTrue(destination.exists())

    def test_corrupt_state_is_backed_up(self):
        folder = Path(tempfile.mkdtemp())
        route = folder / "route.json"
        route.write_text("{}", encoding="utf-8")
        state_path = state_path_for(str(route))
        state_path.write_text("not json", encoding="utf-8")
        self.assertEqual({}, load_state(str(route), folder / "fallback"))
        self.assertFalse(state_path.exists())
        self.assertTrue(list(folder.glob("*.corrupt-*")))


class RendererTests(unittest.TestCase):
    def engine(self) -> RouteEngine:
        folder = Path(tempfile.mkdtemp())
        path = folder / "route.json"
        path.write_text(
            json.dumps(
                {
                    "schemaVersion": 2,
                    "name": "Rendered",
                    "routeMode": "mixed",
                    "stops": [
                        {"system": "Sol", "stopType": "waypoint"},
                        {
                            "system": "HIP 36601",
                            "body": "HIP 36601 C 1 A",
                            "tasks": [{"type": "collectMaterial", "material": "Polonium", "quantity": 50}],
                        },
                    ],
                }
            ),
            encoding="utf-8",
        )
        return RouteEngine(load_route(path))

    def test_rows_have_eight_columns(self):
        rows = render_rows(self.engine())
        self.assertTrue(rows)
        self.assertTrue(all(len(row["cells"]) == 8 for row in rows))

    def test_header_is_compact_four_lines(self):
        header = render_header(self.engine(), "Ready")
        self.assertEqual(4, len(header.splitlines()))

    def test_detail_renders_specialty_and_tasks(self):
        engine = self.engine()
        engine.select_stop(1)
        detail = render_detail(engine)
        self.assertIn("Materials", detail)
        self.assertIn("Polonium", detail)


if __name__ == "__main__":
    unittest.main()
