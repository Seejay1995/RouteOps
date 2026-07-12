from __future__ import annotations

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class TestModuleResult:
    module: Path
    return_code: int
    output: str
    test_count: int

    @property
    def passed(self) -> bool:
        return self.return_code == 0


def discover_test_modules(test_root: Path) -> list[Path]:
    return sorted(path for path in test_root.glob