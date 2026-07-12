from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping, Protocol


@dataclass(frozen=True)
class RouteSource:
    provider_id: str
    source_id: str
    compile_path: str
    display_name: str = ""
    metadata: Mapping[str, Any] = MappingProxyType({})

    def __post_init__(self) -> None:
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))


class RouteSourceProvider(Protocol):
    provider_id: str

    def supports(self, source: str) -> bool:
        ...

    def resolve(self, source: str) -> RouteSource:
        ...


class FileRouteSourceProvider:
    provider_id = "file"

    def supports(self, source: str) -> bool:
        return bool(str(source).strip())

    def resolve(self, source: str) -> RouteSource:
        path = Path(source).expanduser()
        return RouteSource(
            provider_id=self.provider_id,
            source_id=str(path),
            compile_path=str(path),
            display_name=path.name,
            metadata={"suffix": path.suffix.casefold(), "exists": path.exists()},
        )


class RouteSourceRegistry:
    def __init__(self, providers: list[RouteSourceProvider] | None = None) -> None:
        self._providers = tuple(providers or [FileRouteSourceProvider()])

    @property
    def providers(self) -> tuple[RouteSourceProvider, ...]:
        return self._providers

    def resolve(self, source: str) -> RouteSource:
        for provider in self._providers:
            if provider.supports(source):
                return provider.resolve(source)
        raise ValueError(f"No route source provider supports: {source}")
