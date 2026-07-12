from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

PLUGIN = Path(__file__).resolve().parents[1] / "Plugin" / "RouteOps"
sys.path.insert(0, str(PLUGIN))

from kernel_contracts import KernelCommandType, KernelResult  # noqa: E402
from routeops_kernel_app import KernelRouteOpsApplication  # noqa: E402


class KernelApplicationTests(unittest.TestCase):
    def app(self) -> KernelRouteOpsApplication:
        return KernelRouteOpsApplication(SimpleNamespace(config={}))

    def test_system_row_is_dispatched_through_kernel(self):
        app = self.app()
        with mock.patch.object(app, "_execute", return_value=True) as execute:
            app.handle_ui_event({"control": "DGV", "value": 2})
        execute.assert_called_once_with(KernelCommandType.SELECT_SYSTEM, {"index": 2})

    def test_mutating_button_is_dispatched_through_kernel(self):
        app = self.app()
        with mock.patch.object(app, "_execute", return_value=True) as execute:
            app.handle_ui_event({"control": "FINISHBODY"})
        execute.assert_called_once_with(KernelCommandType.COMPLETE_CURRENT, {})

    def test_journal_actions_are_accepted_from_kernel(self):
        app = self.app()
        result = KernelResult.from_actions([{"type": "message", "message": "ok"}])
        app.kernel = SimpleNamespace(handle_journal=mock.Mock(return_value=result))
        with mock.patch.object(app, "_accept_kernel_result") as accept:
            self.assertTrue(app.handle_message({"responsetype": "journalpush", "journalEntry": {"EventTypeID": "FSDJump"}}))
        accept.assert_called_once_with(result)

    def test_package_starts_kernel_adapter(self):
        config = json.loads((PLUGIN / "config.json").read_text(encoding="utf-8"))
        self.assertEqual("routeops_kernel_app.py", config["Python"]["Start"])
        self.assertTrue((PLUGIN / "RouteOps.py").is_file())


if __name__ == "__main__":
    unittest.main()
