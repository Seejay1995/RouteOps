from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

PLUGIN = Path(__file__).resolve().parents[1] / "Plugin" / "RouteOps"
sys.path.insert(0, str(PLUGIN))

import routeops_kernel_app as adapter  # noqa: E402
from route_compiler import CompileResult  # noqa: E402
from routeops_kernel_app import KernelRouteOpsApplication  # noqa: E402


class CompilerApplicationTests(unittest.TestCase):
    def app(self) -> KernelRouteOpsApplication:
        return KernelRouteOpsApplication(SimpleNamespace(config={}))

    def test_compile_result_preserves_route_and_diagnostics(self):
        app = self.app()
        route = object()
        compiled = CompileResult(
            route=route,
            source_path="route.json",
            source_format="routeops-v3",
            warnings=("warning",),
            errors=("error",),
        )
        app.compiler = SimpleNamespace(compile_file=mock.Mock(return_value=compiled))

        result = app._compile_import_result("route.json")

        self.assertIs(route, result.route)
        self.assertEqual(["warning"], result.warnings)
        self.assertEqual(["error"], result.errors)

    def test_load_route_uses_compiler_and_restores_legacy_importer(self):
        app = self.app()
        compiled = CompileResult(
            route=None,
            source_path="route.json",
            warnings=("warning",),
            errors=("error",),
        )
        compile_file = mock.Mock(return_value=compiled)
        app.compiler = SimpleNamespace(compile_file=compile_file)
        original_importer = adapter.legacy.import_route
        captured = {}

        def fake_legacy_load(instance, path, quiet=False):
            captured["path"] = path
            captured["quiet"] = quiet
            captured["result"] = adapter.legacy.import_route(path)

        with mock.patch.object(adapter.legacy.RouteOpsApplication, "load_route", fake_legacy_load):
            app.load_route("route.json", quiet=True)

        compile_file.assert_called_once_with("route.json")
        self.assertEqual("route.json", captured["path"])
        self.assertTrue(captured["quiet"])
        self.assertEqual(["warning"], captured["result"].warnings)
        self.assertEqual(["error"], captured["result"].errors)
        self.assertIs(original_importer, adapter.legacy.import_route)
        self.assertIsNone(app.kernel)

    def test_legacy_importer_is_restored_when_load_raises(self):
        app = self.app()
        original_importer = adapter.legacy.import_route

        def failing_legacy_load(instance, path, quiet=False):
            raise RuntimeError("load failed")

        with mock.patch.object(adapter.legacy.RouteOpsApplication, "load_route", failing_legacy_load):
            with self.assertRaisesRegex(RuntimeError, "load failed"):
                app.load_route("route.json")

        self.assertIs(original_importer, adapter.legacy.import_route)


if __name__ == "__main__":
    unittest.main()
