from __future__ import annotations

import sys
import unittest
from pathlib import Path

PLUGIN = Path(__file__).resolve().parents[1] / "Plugin" / "RouteOps"
sys.path.insert(0, str(PLUGIN))

from route_models import ProgressStatus, Route, RouteStop, RouteTask  # noqa: E402
from route_session import RouteSession  # noqa: E402


class RouteSessionTests(unittest.TestCase):
    def route(self) -> Route:
        return Route(
            id="route-1",
            name="Test Route",
            route_type="expedition",
            source_format="routeops-v3",
            source_path="route.json",
            stops=[
                RouteStop(
                    id="stop-1",
                    sequence=1,
                    system="Sol",
                    tasks=[RouteTask(id="task-1", task_type="visitSystem", target="Sol")],
                )
            ],
        )

    def test_session_uses_working_copy_and_preserves_compiled_template(self):
        compiled = self.route()
        session = RouteSession.start(compiled)

        self.assertIsNot(compiled, session.route)
        self.assertIsNot(compiled.stops[0], session.route.stops[0])

        session.route.stops[0].status = ProgressStatus.COMPLETE
        session.route.stops[0].tasks[0].complete = True

        self.assertEqual(ProgressStatus.PENDING, compiled.stops[0].status)
        self.assertFalse(compiled.stops[0].tasks[0].complete)

    def test_snapshot_adds_session_identity_without_removing_engine_state(self):
        session = RouteSession.start(self.route())
        snapshot = session.snapshot()

        self.assertEqual(1, snapshot["sessionVersion"])
        self.assertEqual("route-1", snapshot["routeId"])
        self.assertEqual("route-1", snapshot["routeDefinition"]["routeId"])
        self.assertEqual(64, len(snapshot["routeFingerprint"]))
        self.assertIn("stops", snapshot)

    def test_state_for_another_route_is_rejected(self):
        session = RouteSession.start(self.route())

        accepted = session.apply_state({"routeId": "another-route", "current_index": 0})

        self.assertFalse(accepted)
        self.assertEqual("route-1", session.route.id)

    def test_matching_state_is_applied(self):
        session = RouteSession.start(
            self.route(),
            {
                "routeId": "route-1",
                "currentStopId": "stop-1",
                "selectedStopId": "stop-1",
                "stops": {
                    "stop-1": {
                        "status": ProgressStatus.COMPLETE,
                        "tasks": {
                            "task-1": {
                                "quantityCompleted": 1,
                                "status": "complete",
                            }
                        },
                    }
                },
            },
        )

        self.assertEqual(ProgressStatus.COMPLETE, session.route.stops[0].status)
        self.assertTrue(session.route.stops[0].tasks[0].complete)


if __name__ == "__main__":
    unittest.main()