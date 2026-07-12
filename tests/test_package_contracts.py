from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "Plugin" / "RouteOps"


class PackageContractTests(unittest.TestCase):
    def test_module_checker_exact_contract(self):
        result = subprocess.run(
            [sys.executable, str(PLUGIN / "checkmodules.py")],
            cwd=str(PLUGIN),
            capture_output=True,
            text=True,
            check=True,
        )
        self.assertEqual("Module Check OK", result.stdout.strip())
        self.assertEqual("", result.stderr.strip())

    def test_ui_dock_order_prevents_fill_overlap(self):
        text = (PLUGIN / "UIInterface.act").read_text(encoding="utf-8")
        dgv = text.index("DialogEntry controls,DGV")
        detail = text.index("DialogEntry controls,DETAIL,richtextbox")
        toolbar = text.index("DialogEntry controls,TOOLBAR")
        header = text.index("DialogEntry controls,HEADER")
        self.assertLess(dgv, detail)
        self.assertLess(detail, toolbar)
        self.assertLess(toolbar, header)
        self.assertNotIn("controls,RTB,richtextbox", text)

    def test_registration_and_ui_versions_match(self):
        registration = (ROOT / "ActionFiles" / "V1" / "RouteOpsPanel.act").read_text(encoding="utf-8")
        ui = (PLUGIN / "UIInterface.act").read_text(encoding="utf-8")
        self.assertIn("Version=0.5.0.0", registration)
        self.assertIn("Version=0.5.0.0", ui)

    def test_trade_csv_importer_and_load_filter_are_packaged(self):
        self.assertTrue((PLUGIN / "trade_csv_importer.py").is_file())
        self.assertTrue((PLUGIN / "spansh_exobiology_importer.py").is_file())
        self.assertTrue((PLUGIN / "exobiology_catalog.py").is_file())
        self.assertTrue((PLUGIN / "exobio_taxonomy.py").is_file())
        self.assertTrue((PLUGIN / "exobio_projection.py").is_file())
        self.assertTrue((PLUGIN / "exobio_diagnostics.py").is_file())
        self.assertTrue((PLUGIN / "navigation_model.py").is_file())
        self.assertTrue((ROOT / "samples" / "sample_routeops_exobiology_v5.json").is_file())
        self.assertTrue((PLUGIN / "Data" / "exobiology_catalog.json").is_file())
        self.assertTrue((PLUGIN / "Data" / "exobiology_taxonomy.json").is_file())
        ui = (PLUGIN / "UIInterface.act").read_text(encoding="utf-8")
        app = (PLUGIN / "RouteOps.py").read_text(encoding="utf-8")
        self.assertIn('Button,"Load Route"', ui)
        self.assertIn("*.csv;*.tsv", app)
        self.assertIn("DialogEntry controls,ORGANISMS", ui)
        self.assertIn("DialogEntry controls,BODYEXCLUDE", ui)
        self.assertIn("DialogEntry controls,BODIES", ui)
        self.assertIn("DialogEntry controls,NAVCOPY", ui)
        self.assertIn("DialogEntry controls,SKIPPREVIEW", ui)
        self.assertIn("DialogEntry controls,SKIPCONFIRM", ui)


if __name__ == "__main__":
    unittest.main()
