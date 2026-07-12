from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tools.validate_release import (
    validate_action_files,
    validate_json_files,
    validate_no_nested_release_root,
)


class ReleaseValidationTests(unittest.TestCase):
    def test_actionfile_v4_is_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "UIInterface.act").write_text(
                "ACTIONFILE V4\n",
                encoding="utf-8",
            )

            self.assertEqual([], validate_action_files(root))

    def test_actionfile_v5_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "UIInterface.act").write_text(
                "ACTIONFILE V5\n",
                encoding="utf-8",
            )

            failures = validate_action_files(root)

            self.assertEqual(1, len(failures))
            self.assertIn("unsupported header", failures[0].message)

    def test_invalid_json_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "route.json").write_text("{", encoding="utf-8")

            failures = validate_json_files(root)

            self.assertEqual(1, len(failures))
            self.assertIn("invalid JSON", failures[0].message)

    def test_nested_release_root_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "RouteOps"
            root.mkdir()
            (root / "RouteOps").mkdir()

            failures = validate_no_nested_release_root(root)

            self.assertEqual(1, len(failures))
            self.assertIn("nested release root", failures[0].message)


if __name__ == "__main__":
    unittest.main()
