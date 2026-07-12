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
from route_engine import RouteEngine  # noqa: E402
from route_models import Route, RouteStop  # noqa: E402
from routeops_kernel_app import KernelRouteOpsApplication  # noqa: E402


class CompilerApplicationTests(unittest.TestCase):
    def app(self) -> KernelRouteOpsApplication:
        return KernelRouteOpsApplication(SimpleNamespace(config={}))

    @staticmethod
    def route() -> Route:
        return Route(
            id="route-1",
            name="Route",
            route_type="expedition",
            source_format="routeops-v3",
            source_path="route.json",
            stops=[RouteStop(id="stop-1", sequence=1, system="Sol")],
        )

    def test_compile_result_preserves_template_and_returns_working_copy(self):
        app = self.app()
        route = self.route()
        compiled = CompileResult(
            route=route,
            source_path="route.json",
            source_format="routeops-v3",
            warnings=("warning",),
            errors=("error",),
        )
        compile_source = mock.Mock(return_value=compiled)
        app.compiler = SimpleNamespace(compile_source=compile_source)

        result = app._compile_import_result("route.json")

        compile_source.assert_called_once_with("route.json")
        self.assertIs(route, app.compiled_route)
        self.assertIsNot(route, result.route)
        self.assertEqual(route, result.route)
        self.assertEqual(["warning"], result.warnings)
        self.assertEqual(["error"], result.errors)

    def test_load_route_creates_session_and_kernel_for_working_route(self):
        app = self.app()
        route = self.route()
        app.compiler = SimpleNamespace(
            compile_source=mock.Mock(
                return_value=CompileResult(route=route, source_path="route.json")
            )
        )
        original_importer = adapter.legacy.import_route

        def fake_legacy_load(instance, path, quiet=False):
            imported = adapter.legacy.import_route(path)
            instance.engine = RouteEngine(imported.route)
            instance.route_path = path

        with mock.patch.object(adapter.legacy.RouteOpsApplication, "load_route", fake_legacy_load):
            with mock.patch.object(app, "persist") as persist:
                app.load_route("route.json", quiet=True)

        self.assertIs(original_importer, adapter.legacy.import_route)
        self.assertIsNotNone(app.session)
        self.assertIsNotNone(app.kernel)
        self.assertIs(app.engine, app.session.engine)
        self.assertIs(app.session, app.kernel.session)
        self.assertIs(route, app.compiled_route)
        self.assertIsNot(route, app.engine.route)
        persist.assert_called_once_with()

    def test_load_route_restores_importer_when_compilation_returns_no_route(self):
        app = self.app()
        compiled = CompileResult(
            route=None,
            source_path="route.json",
            warnings=("warning",),
            errors=("error",),
        )
        compile_source = mock.Mock(return_value=compiled)
        app.compiler = SimpleNamespace(compile_source=compile_source)
        original_importer = adapter.legacy.import_route
        captured = {}

        def fake_legacy_load(instance, path, quiet=False):
            captured["path"] = path
            captured["quiet"] = quiet
            captured["result"] = adapter.legacy.import_route(path)

        with mock.patch.object(adapter.legacy.RouteOpsApplication, "load_route", fake_legacy_load):
            app.load_route("route.json", quiet=True)

        compile_source.assert_called_once_with("route.json")
        self.assertEqual("route.json", captured["path"])
        self.assertTrue(captured["quiet"])
        self.assertEqual(["warning"], captured["result"].warnings)
        self.assertEqual(["error"], captured["result"].errors)
        self.assertIs(original_importer, adapter.legacy.import_route)
        self.assertIsNone(app.session)
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