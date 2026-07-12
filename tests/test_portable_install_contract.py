from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class PortableInstallContractTests(unittest.TestCase):
    def test_installer_accepts_arbitrary_portable_install_root(self):
        installer = (ROOT / "install.ps1").read_text(encoding="utf-8")
        helper = (ROOT / "portable-root.ps1").read_text(encoding="utf-8")

        self.assertIn("[string]$EddInstallRoot", installer)
        self.assertIn("[string]$EddExecutable", installer)
        self.assertIn("Find-EddPortableDataRoot", installer)
        self.assertIn("EDDiscovery.exe was not found in the portable install", helper)
        self.assertIn("Get-EddAppFolderFromOptionsDirectory", helper)
        self.assertIn("portable data folder beside executable", helper)

    def test_portable_resolution_does_not_assume_c_drive_or_program_files(self):
        helper = (ROOT / "portable-root.ps1").read_text(encoding="utf-8")

        self.assertNotIn("C:\\", helper)
        self.assertNotIn("ProgramFiles", helper)
        self.assertIn("ConvertTo-EddNormalizedPath", helper)

    def test_installer_verifies_session_boundary_modules(self):
        installer = (ROOT / "install.ps1").read_text(encoding="utf-8")

        for module in (
            "session_storage.py",
            "route_session.py",
            "route_kernel.py",
            "route_compiler.py",
            "source_providers.py",
            "routeops_kernel_app.py",
        ):
            self.assertIn(module, installer)


if __name__ == "__main__":
    unittest.main()
