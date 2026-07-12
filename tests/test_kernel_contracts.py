from __future__ import annotations

import sys
import unittest
from dataclasses import FrozenInstanceError
from pathlib import Path

PLUGIN = Path(__file__).resolve().parents[1] / "Plugin" / "RouteOps"
sys.path.insert(0, str(PLUGIN))

from kernel_contracts import KernelCommand, KernelResult  # noqa: E402


class KernelContractTests(unittest.TestCase):
    def test_command_fields_and_payload_are_immutable(self):
        command = KernelCommand("select-system", {"index": 1})

        with self.assertRaises(FrozenInstanceError):
            command.command_type = "select-body"
        with self.assertRaises(TypeError):
            command.payload["index"] = 2

    def test_command_copies_input_payload(self):
        payload