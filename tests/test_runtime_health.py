from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

PLUGIN = Path(__file__).resolve().parents[1] / "Plugin" / "RouteOps"
sys.path.insert(0, str(PLUGIN))

from runtime_health import (  # noqa: E402
    DEFAULT_REQUIRED_FILES,
    STATUS_ERROR,
    STATUS_WARNING,
    RuntimeHealthReport,
    RuntimeHealthService,
)
from session_storage import FileSessionStorage  # noqa: E402


class RuntimeHealthServiceTests(unittest.TestCase):
    def create_layout(self, root: Path) -> tuple[Path, FileSessionStorage]:
        plugin = root / "Plugins" / "RouteOps"
        actions = root / "Actions"
        plugin.mkdir(parents=True)
        actions.mkdir(parents=True)
        for name in DEFAULT_REQUIRED_FILES:
            target = plugin / name
            target.parent.mkdir(parents=True, exist_ok=True)
            if name == "config.json":
                target.write_text(
                    json.dumps({"Python": {"Start": "routeops_kernel_app.py"}}),
                    encoding="utf-8",
                )
            else:
                target.write_text("test", encoding="utf-8")
        (actions / "RouteOpsPanel.act").write_text("ACTIONFILE V4", encoding="utf-8")
        return plugin, FileSessionStorage.for_plugin(plugin)

    def test_complete_portable_layout_is_healthy_without_a_route(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            plugin, storage = self.create_layout(root)
            service = RuntimeHealthService(plugin, storage, required_modules=())

            report = service.run()

            self.assertEqual("healthy", report.overall_status)
            self.assertEqual(str(root.resolve()), report.eddiscovery_data_root)
            self.assertTrue((plugin / "State").is_dir())
            self.assertEqual([], list((plugin / "State").glob(".routeops-health-*.tmp")))

    def test_missing_runtime_file_is_an_error(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            plugin, storage = self.create_layout(root)
            (plugin / "route_kernel.py").unlink()
            service = RuntimeHealthService(plugin, storage, required_modules=())

            report = service.run()

            self.assertEqual("error", report.overall_status)
            runtime_files = next(check for check in report.checks if check.name == "Runtime files")
            self.assertEqual(STATUS_ERROR, runtime_files.status)
            self.assertIn("route_kernel.py", runtime_files.detail)

    def test_missing_configured_route_is_a_warning_with_storage_paths(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            plugin, storage = self.create_layout(root)
            route = root / "Routes" / "missing.json"
            service = RuntimeHealthService(plugin, storage, required_modules=())

            report = service.run(str(route))

            self.assertEqual("warning", report.overall_status)
            route_check = next(check for check in report.checks if check.name == "Route file")
            self.assertEqual(STATUS_WARNING, route_check.status)
            self.assertIn("drive letters may have changed", route_check.action)
            self.assertTrue(report.storage_primary.endswith("missing.json.routeops.state.json"))
            self.assertIn(str(plugin / "State"), report.storage_fallback)

    def test_export_writes_json_and_text_reports(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            plugin, storage = self.create_layout(root)
            service = RuntimeHealthService(plugin, storage, required_modules=())
            report = service.run()
            destination = root / "Exports"

            json_path = service.export(report, destination)

            self.assertTrue(json_path.is_file())
            text_path = json_path.with_suffix(".txt")
            self.assertTrue(text_path.is_file())
            payload = json.loads(json_path.read_text(encoding="utf-8"))
            self.assertEqual("healthy", payload["overallStatus"])
            self.assertIn("ROUTEOPS RUNTIME HEALTH: HEALTHY", text_path.read_text(encoding="utf-8"))


class RuntimeHealthApplicationTests(unittest.TestCase):
    def test_health_action_works_without_loaded_route(self):
        from routeops_kernel_app import KernelRouteOpsApplication

        client = SimpleNamespace(config={})
        app = KernelRouteOpsApplication(client)
        report = RuntimeHealthReport(
            generated_at="2026-07-12T00:00:00+00:00",
            plugin_directory="E:/EDD/Plugins/RouteOps",
            eddiscovery_data_root="E:/EDD",
            route_path="",
            storage_primary="",
            storage_fallback="E:/EDD/Plugins/RouteOps/State",
            checks=(),
        )
        app.health_service = SimpleNamespace(run=mock.Mock(return_value=report))
        app.refresh_ui = mock.Mock()
        client.ui_set_escape = mock.Mock()

        result = app.run_health_check()

        self.assertIs(report, result)
        app.health_service.run.assert_called_once_with("")
        app.refresh_ui.assert_called_once_with()
        client.ui_set_escape.assert_called_once_with("DETAIL", report.render_text())


if __name__ == "__main__":
    unittest.main()
