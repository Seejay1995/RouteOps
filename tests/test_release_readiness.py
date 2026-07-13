from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ReleaseReadinessTests(unittest.TestCase):
    def _run_tool(self, relative_path: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-B", str(ROOT / relative_path), "--root", str(ROOT)]
            if relative_path.endswith("smoke_test.py")
            else [sys.executable, "-B", str(ROOT / relative_path)],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

    def test_version_metadata_is_consistent(self) -> None:
        result = self._run_tool("tools/validate_version.py")
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)

    def test_offline_install_smoke_test_passes(self) -> None:
        result = self._run_tool("tools/smoke_test.py")
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertIn("offline smoke test passed", result.stdout)

    def test_transactional_install_and_rollback_scripts_exist(self) -> None:
        install = (ROOT / "install.ps1").read_text(encoding="utf-8-sig")
        rollback = (ROOT / "rollback.ps1").read_text(encoding="utf-8-sig")
        self.assertIn(".routeops-install-staging-", install)
        self.assertIn(".routeops-backups", install)
        self.assertIn("Automatically restored backup", install)
        self.assertIn("RouteOps rollback restored", rollback)

    def test_release_candidate_version(self) -> None:
        self.assertEqual("0.6.0", (ROOT / "VERSION").read_text(encoding="utf-8-sig").strip())


if __name__ == "__main__":
    unittest.main()
