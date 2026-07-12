from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

SUPPORTED_ACTIONFILE_HEADERS = {"ACTIONFILE V4"}
IGNORED_DIRECTORY_NAMES = {".git", ".routeops-backups", "__pycache__"}


@dataclass(frozen=True)
class ValidationFailure:
    path: Path
    message: str

    def __str__(self) -> str:
        return f"{self.path}: {self.message}"


def iter_files(root: Path, suffix: str) -> Iterable[Path]:
    for path in root.rglob(f"*{suffix}"):
        if any(part in IGNORED_DIRECTORY_NAMES for part in path.parts):
            continue
        if path.is_file():
            yield path


def validate_action_files(root: Path) -> list[ValidationFailure]:
    failures: list[ValidationFailure] = []

    for path in iter_files(root, ".act"):
        try:
            first_line = path.read_text(encoding="utf-8-sig").splitlines()[0].strip()
        except (OSError, UnicodeError, IndexError) as exc:
            failures.append(ValidationFailure(path, f"cannot read header: {exc}"))
            continue

        if first_line not in SUPPORTED_ACTIONFILE_HEADERS:
            expected = ", ".join(sorted(SUPPORTED_ACTIONFILE_HEADERS))
            failures.append(
                ValidationFailure(
                    path,
                    f"unsupported header {first_line!r}; expected one of: {expected}",
                )
            )

    return failures


def validate_json_files(root: Path) -> list[ValidationFailure]:
    failures: list[ValidationFailure] = []

    for path in iter_files(root, ".json"):
        try:
            json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            failures.append(ValidationFailure(path, f"invalid JSON: {exc}"))

    return failures


def validate_no_nested_release_root(root: Path) -> list[ValidationFailure]:
    failures: list[ValidationFailure] = []
    root_name = root.resolve().name.casefold()

    for child in root.iterdir():
        if child.is_dir() and child.name.casefold() == root_name:
            failures.append(
                ValidationFailure(
                    child,
                    "nested release root duplicates the package directory name",
                )
            )

    return failures


def validate_manifest(root: Path) -> list[ValidationFailure]:
    manifest_path = root / "MANIFEST.sha256"
    if not manifest_path.exists():
        return []

    failures: list[ValidationFailure] = []
    for line_number, raw_line in enumerate(
        manifest_path.read_text(encoding="utf-8-sig").splitlines(), start=1
    ):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue

        try:
            expected_hash, relative_path = line.split(maxsplit=1)
        except ValueError:
            failures.append(
                ValidationFailure(
                    manifest_path,
                    f"line {line_number} is not '<sha256> <path>'",
                )
            )
            continue

        relative_path = relative_path.lstrip("*")
        target = root / Path(relative_path)
        if not target.is_file():
            failures.append(
                ValidationFailure(target, "manifest target does not exist")
            )
            continue

        actual_hash = hashlib.sha256(target.read_bytes()).hexdigest()
        if actual_hash.casefold() != expected_hash.casefold():
            failures.append(
                ValidationFailure(
                    target,
                    f"hash mismatch: expected {expected_hash}, got {actual_hash}",
                )
            )

    return failures


def validate(root: Path) -> list[ValidationFailure]:
    failures: list[ValidationFailure] = []
    failures.extend(validate_action_files(root))
    failures.extend(validate_json_files(root))
    failures.extend(validate_no_nested_release_root(root))
    failures.extend(validate_manifest(root))
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate RouteOps release artifacts.")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    args = parser.parse_args()

    root = args.root.resolve()
    if not root.is_dir():
        print(f"Validation root does not exist: {root}", file=sys.stderr)
        return 2

    failures = validate(root)
    if failures:
        print("RouteOps release validation failed:", file=sys.stderr)
        for failure in failures:
            print(f"- {failure}", file=sys.stderr)
        return 1

    print(f"RouteOps release validation passed: {root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
