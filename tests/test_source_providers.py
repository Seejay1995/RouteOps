from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import MappingProxyType

PLUGIN = Path(__file__).resolve().parents[1] / "Plugin" / "RouteOps"
sys.path.insert(0, str(PLUGIN))

from route_compiler import RouteCompiler  # noqa: E402
from source_providers import (  # noqa: E402
    FileRouteSourceProvider,
    RouteSource,
    RouteSourceRegistry,
)


class StubProvider:
    provider_id = "stub"

    def __init__(self, compile_path: str) -> None:
        self.compile_path = compile_path

    def supports(self, source: str) -> bool:
        return source.startswith("stub:")

    def resolve(self, source: str) -> RouteSource:
        return RouteSource(
            provider_id=self.provider_id,
            source_id=source,
            compile_path=self.compile_path,
            display_name="Generated route",
            metadata={"kind": "generated"},
        )


class RouteSourceProviderTests(unittest.TestCase):
    def write_route(self) -> Path:
        path = Path(tempfile.mkdtemp()) / "route.json"
        path.write_text(json.dumps({"Name": "Provider", "Systems": ["Sol"]}), encoding="utf-8")
        return path

    def test_file_provider_resolves_path_metadata(self):
        path = self.write_route()
        source = FileRouteSourceProvider().resolve(str(path))

        self.assertEqual("file", source.provider_id)
        self.assertEqual(str(path), source.compile_path)
        self.assertEqual(".json", source.metadata["suffix"])
        self.assertTrue(source.metadata["exists"])
        with self.assertRaises(TypeError):
            source.metadata["exists"] = False

    def test_registry_uses_first_supporting_provider(self):
        path = self.write_route()
        registry = RouteSourceRegistry([StubProvider(str(path)), FileRouteSourceProvider()])

        source = registry.resolve("stub:route")

        self.assertEqual("stub", source.provider_id)
        self.assertEqual("stub:route", source.source_id)

    def test_compiler_accepts_provider_source_and_preserves_metadata(self):
        path = self.write_route()
        compiler = RouteCompiler(RouteSourceRegistry([StubProvider(str(path))]))

        compiled = compiler.compile_source("stub:route")

        self.assertTrue(compiled.success)
        self.assertEqual("stub", compiled.metadata["providerId"])
        self.assertEqual("stub:route", compiled.metadata["sourceId"])
        self.assertEqual("generated", compiled.metadata["sourceMetadata"]["kind"])

    def test_compile_file_remains_compatible(self):
        path = self.write_route()
        compiled = RouteCompiler().compile_file(path)

        self.assertTrue(compiled.success)
        self.assertEqual("file", compiled.metadata["providerId"])
        self.assertEqual(str(path), compiled.source_path)


if __name__ == "__main__":
    unittest.main()
