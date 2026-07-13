from __future__ import annotations

import re
import sys
from pathlib import Path


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    version = (root / "VERSION").read_text(encoding="utf-8-sig").strip()
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        print(f"Invalid VERSION value: {version!r}", file=sys.stderr)
        return 1

    action_version = f"{version}.0"
    checks = {
        root / "ActionFiles" / "V1" / "RouteOpsPanel.act": [
            f"INSTALL Version={action_version}",
            f"RouteOps {version} installed",
        ],
        root / "Plugin" / "RouteOps" / "UIInterface.act": [
            f"INSTALL Version={action_version}",
            f"RouteOps v{version} starting",
        ],
        root / "install.ps1": [
            "Get-Content -LiteralPath (Join-Path $PSScriptRoot 'VERSION')",
        ],
    }

    failures: list[str] = []
    for path, expected_values in checks.items():
        text = path.read_text(encoding="utf-8-sig")
        for expected in expected_values:
            if expected not in text:
                failures.append(f"{path.relative_to(root)}: missing {expected!r}")

    if failures:
        print("RouteOps version validation failed:", file=sys.stderr)
        for failure in failures:
            print(f"- {failure}", file=sys.stderr)
        return 1

    print(f"RouteOps version validation passed: {version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
