from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

from route_importer import import_route
from route_models import Route
from source_providers import RouteSource, RouteSourceRegistry


@dataclass(frozen=True)
class CompileResult:
    route: Route | None
    source_path: str
    source_format: str = ""
    warnings: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = MappingProxyType({})

    def __post_init__(self) -> None:
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))

    @property
    def success(self) -> bool:
        return self.route is not None and not self.errors


class RouteCompiler:
    """Stable provider-to-route compilation boundary."""

    def __init__(self, sources: RouteSourceRegistry | None = None) -> None:
        self.sources = sources or RouteSourceRegistry()

    def compile_source(self, source: str) -> CompileResult:
        resolved = self.sources.resolve(source)
        return self._compile_resolved(resolved)

    def compile_file(self, path: str | Path) -> CompileResult:
        return self.compile_source(str(path))

    def _compile_resolved(self, source: RouteSource) -> CompileResult:
        result = import_route(source.compile_path)
        route = result.route
        source_format = route.source_format if route is not None else ""
        metadata = {
            "providerId": source.provider_id,
            "sourceId": source.source_id,
            "displayName": source.display_name,
            "routeId": route.id if route is not None else "",
            "routeType": route.route_type if route is not None else "",
            "stopCount": len(route.stops) if route is not None else 0,
            "sourceMetadata": dict(source.metadata),
        }
        return CompileResult(
            route=route,
            source_path=source.compile_path,
            source_format=source_format,
            warnings=tuple(result.warnings),
            errors=tuple(result.errors),
            metadata=metadata,
        )
