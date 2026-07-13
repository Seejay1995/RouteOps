from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PureWindowsPath
from typing import Any, Iterable


LIBRARY_CONFIG_KEY = "route_library"
DEFAULT_LIMIT = 12


@dataclass(frozen=True)
class RouteLibraryEntry:
    path: str
    name: str
    route_id: str
    route_type: str
    source_format: str
    system_count: