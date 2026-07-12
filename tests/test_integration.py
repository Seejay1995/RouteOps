from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

import zmq

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "Plugin" / "RouteOps"


class IntegrationTests(unittest.TestCase):
    def test_fake_edd_startup_ui_selection_and_journal(self):
        folder = Path(tempfile.mkdtemp())
        route_path = folder / "route.json"
        route_path.write_text(
            json.dumps({"Name": "Integration", "Systems": ["Sol", "Colonia"]}),
            encoding="utf-8",
        )

        context = zmq.Context.instance()
        server = context.socket(zmq.DEALER)
        port = server.bind_to_random_port("tcp://127.0.0.1")
        process = subprocess.Popen(
            [sys.executable, str(PLUGIN / "RouteOps.py"), str(port), "1"],
            cwd=str(PLUGIN),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            self.assertTrue(server.poll(5000))
            start = json.loads(server.recv_string())
            self.assertEqual("start", start["requesttype"])
            self.assertEqual("0.5.0.0", start["version"])
            server.send_string(
                json.dumps(
                    {
                        "responsetype": "start",
                        "eddversion": "19.1.8.0",
                        "apiversion": 1,
                        "historylength": 0,
                        "commander": "TEST",
                        "config": json.dumps(
                            {
                                "route_path": str(route_path),
                                "auto_copy_mode": "off",
                            }
                        ),
                    }
                )
            )

            messages = self._collect(server, 2.0)
            controls = {message.get("control") for message in messages}
            request_types = {message.get("requesttype") for message in messages}
            self.assertIn("uisetdgvsetting", request_types)
            self.assertIn("HEADER", controls)
            self.assertIn("DETAIL", controls)
            self.assertIn("DGV", controls)

            server.send_string(json.dumps({"responsetype": "uievent", "control": "DGV", "value": 1}))
            selected_messages = self._collect(server, 0.8)
            detail_updates = [
                message for message in selected_messages
                if message.get("requesttype") == "uisetescape" and message.get("control") == "DETAIL"
            ]
            self.assertTrue(detail_updates)
            self.assertIn("Colonia", detail_updates[-1].get("value", ""))

            server.send_string(
                json.dumps(
                    {
                        "responsetype": "journalpush",
                        "journalEntry": {"EventTypeID": "FSDJump", "StarSystem": "Sol", "Id": 100},
                    }
                )
            )
            journal_messages = self._collect(server, 0.8)
            header_updates = [
                message for message in journal_messages
                if message.get("requesttype") == "uisetescape" and message.get("control") == "HEADER"
            ]
            self.assertTrue(header_updates)
            self.assertIn("NAVIGATION: SYSTEM - Colonia", header_updates[-1].get("value", ""))

            server.send_string(json.dumps({"responsetype": "terminate"}))
            exit_messages = self._collect(server, 1.0)
            self.assertTrue(any(message.get("requesttype") == "exit" for message in exit_messages))
            process.wait(timeout=5)
            self.assertEqual(0, process.returncode)
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=5)
            if process.stdout is not None:
                process.stdout.close()
            if process.stderr is not None:
                process.stderr.close()
            server.close(linger=0)

    def test_fake_edd_loads_trade_csv_with_generated_tasks(self):
        folder = Path(tempfile.mkdtemp())
        route_path = folder / "trade.csv"
        route_path.write_text(
            'System,Information\n'
            'Diaguandri,"Station: Ray Gateway\nGold buy 4 profit 1200"\n'
            'LHS 2936,"Fly to Fraser Orbital and sell all"\n',
            encoding="utf-8",
        )

        context = zmq.Context.instance()
        server = context.socket(zmq.DEALER)
        port = server.bind_to_random_port("tcp://127.0.0.1")
        process = subprocess.Popen(
            [sys.executable, str(PLUGIN / "RouteOps.py"), str(port), "1"],
            cwd=str(PLUGIN),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            self.assertTrue(server.poll(5000))
            start = json.loads(server.recv_string())
            self.assertEqual("start", start["requesttype"])
            server.send_string(
                json.dumps(
                    {
                        "responsetype": "start",
                        "eddversion": "19.1.8.0",
                        "apiversion": 1,
                        "historylength": 0,
                        "commander": "TEST",
                        "config": json.dumps({"route_path": str(route_path), "auto_copy_mode": "off"}),
                    }
                )
            )
            messages = self._collect(server, 2.0)
            detail_updates = [
                message for message in messages
                if message.get("requesttype") == "uisetescape" and message.get("control") == "DETAIL"
            ]
            self.assertTrue(detail_updates)
            detail = detail_updates[-1].get("value", "")
            self.assertIn("STATION: Ray Gateway", detail)
            self.assertIn("Buy 4 Gold", detail)
            server.send_string(json.dumps({"responsetype": "terminate"}))
            self._collect(server, 1.0)
            process.wait(timeout=5)
            self.assertEqual(0, process.returncode)
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=5)
            if process.stdout is not None:
                process.stdout.close()
            if process.stderr is not None:
                process.stderr.close()
            server.close(linger=0)

    @staticmethod
    def _collect(server, seconds: float):
        deadline = time.monotonic() + seconds
        messages = []
        while time.monotonic() < deadline:
            if server.poll(50):
                messages.append(json.loads(server.recv_string()))
        return messages


if __name__ == "__main__":
    unittest.main()
