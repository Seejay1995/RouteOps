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
        route