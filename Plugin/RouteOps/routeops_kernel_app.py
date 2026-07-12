from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import RouteOps as legacy
from kernel_contracts import KernelCommand, KernelCommandType, KernelResult
from route_compiler import RouteCompiler
from route_importer import ImportResult
from route_kernel import RouteKernel
from route_models import Route
from route_session import RouteSession, RouteSession