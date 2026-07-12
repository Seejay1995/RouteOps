from __future__ import annotations

import argparse
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class TestModuleResult:
    module: Path
    return_code: int
    output: str

    @property
    def passed(self) -> bool:
        return self.return_code == 0


def discover_test_modules(test_root: Path) -> list[Path]:
    return sorted(path for path in test_root.glob("test_*.py") if path.is_file())


def run_test_module(root: Path, module: Path) -> TestModuleResult:
    process = subprocess