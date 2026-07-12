from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

PLUGIN = Path(__file__).resolve().parents[1] / "Plugin" / "RouteOps"
sys.path.insert(0, str(PLUGIN))

from route_compiler import RouteCompiler  # noqa: E402
from route_importer import import_route  # noqa: E402


class RouteCompilerTests(unittest.TestCase):
    def write_route(self, value: dict) -> Path:
        path = Path(tempfile.mkdtemp()) / "route.json"
        path.write_text(json.dumps(value), encoding="utf-8")
        return path

    def test_compiler_matches_importer_route_and_diagnostics(self):
        path = self.write_route({"Name": "EDD", "Systems": ["Sol", "Colonia"]})
        imported = import_route(path)
        compiled = RouteCompiler().compile_file(path)

        self.assertTrue(compiled.success)
        self.assertEqual(imported.route.to_state(), compiled.route.to_state())
        self.assertEqual(tuple(imported.warnings), compiled.warnings)
        self.assertEqual(tuple(imported.errors), compiled.errors)
        self.assertEqual(imported.route.source_format, compiled.source_format)

    def test_compile_failure_is_returned_without_exception(self):
        path = self.write_route({"name": "Broken", "stops": [{}]})
        compiled = RouteCompiler().compile_file(path)

        self.assertFalse(compiled.success)
        self.assertIsNone(compiled.route)
        self.assertTrue(compiled.errors)

    def test_metadata_is_read_only(self):
        path = self.write_route({"Name": "EDD", "Systems": ["Sol"]})
        compiled = RouteCompiler().compile_file(path)

        with self.assertRaises(TypeError):
            compiled.metadata["stopCount"] = 99


if __name__ == "__main__":
    unittest.main()
