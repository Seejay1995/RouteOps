from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run RouteOps test modules independently.")
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Optional UTF-8 file that receives the complete test report.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = Path(__file__).resolve().parents[1]
    tests = root / "tests"
    modules = sorted(tests.glob("test_*.py"))
    report: list[str] = []

    def emit(text: str = "") -> None:
        print(text)
        report.append(text)

    if not modules:
        emit("No test modules found.")
        return 1

    failed: list[str] = []
    for module in modules:
        emit()
        emit(f"=== {module.name} ===")
        result = subprocess.run(
            [sys.executable, "-B", "-m", "unittest", module.stem, "-v"],
            cwd=tests,
            text=True,
            capture_output=True,
        )
        output = ((result.stdout or "") + (result.stderr or "")).rstrip()
        emit(output)
        if result.returncode != 0:
            failed.append(module.name)

    emit()
    emit("=== Summary ===")
    emit(f"Modules: {len(modules)}")
    emit(f"Passed: {len(modules) - len(failed)}")
    emit(f"Failed: {len(failed)}")
    if failed:
        emit("Failing modules:")
        for name in failed:
            emit(f"- {name}")

    if args.output is not None:
        output_path = args.output
        if not output_path.is_absolute():
            output_path = root / output_path
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text("\n".join(report) + "\n", encoding="utf-8")

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
