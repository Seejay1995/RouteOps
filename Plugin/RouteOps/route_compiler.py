from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

from route_importer import import_route
from route_models import Route


@dataclass(frozen=True)
class CompileResult:
    route: Route | None
    source_path: str
    source_format: str = ""
    warnings: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = MappingProxyType({})

    @property
    def success(self) -> bool:
        return self.route is not None and not self.errors


class RouteCompiler:
    """Stable source-to-route compilation boundary.

    M2 initially delegates to the proven importer. Later source providers can
    compile through this contract without changing the kernel or application.
    """

    def compile_file(self, path: str | Path) -> CompileResult:
        source_path = str(Path(path))
        result = import_route(source_path)
        route = result.route
        source_format = route.source_format if route is not None else ""
        metadata = MappingProxyType({
            "routeId": route.id if route is not None else "",
            "routeType": route.route_type if route is not None else "",
            "stopCount": len(route.stops) if route is not None else 0,
        })
        return CompileResult(
            route=route,
            source_path=source_path,
            source_format=source_format,
            warnings=tuple(result.warnings),
            errors=tuple(result.errors),
            metadata=metadata,
        )
