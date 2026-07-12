from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    tests = root / "tests"
    modules = sorted(tests.glob("test_*.py"))

    if not modules:
        print("No test modules found.")
        return 1

    failed: list[str] = []
    for module in modules:
        print(f"\n=== {module.name} ===")
        result = subprocess.run(
            [sys.executable, "-m", "unittest", module.stem, "-v"],
            cwd=tests,
            text=True,
            capture_output=True,
        )
        output = (result.stdout or "") + (result.stderr or "")
        print(output.rstrip())
        if result.returncode != 0:
            failed.append(module.name)

    print("\n=== Summary ===")
    print(f"Modules: {len(modules)}")
    print(f"Passed: {len(modules) - len(failed)}")
    print(f"Failed: {len(failed)}")
    if failed:
        print("Failing modules:")
        for name in failed:
            print(f"- {name}")
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
