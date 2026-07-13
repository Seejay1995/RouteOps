from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path


def _configure_import_path(root: Path) -> None:
    plugin = root / "Plugin" / "RouteOps"
    sys.path.insert(0, str(plugin))


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the RouteOps offline install smoke test.")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()

    root = args.root.resolve()
    fixture = root / "samples" / "smoke-expedition.json"
    if not fixture.is_file():
        print(f"Smoke route missing: {fixture}", file=sys.stderr)
        return 2

    _configure_import_path(root)
    from route_compiler import RouteCompiler
    from route_library import RouteLibrary
    from route_session import RouteSession, RouteSessionDefinition
    from route_engine import RouteEngine

    compiler = RouteCompiler()
    result = compiler.compile_file(fixture)
    if not result.success or result.route is None:
        print(f"Compilation failed: {result.errors}", file=sys.stderr)
        return 1

    route = result.route
    if route.name != "RouteOps Install Smoke Test" or len(route.stops) != 3:
        print("Unexpected smoke route normalization result.", file=sys.stderr)
        return 1

    engine = RouteEngine(route)
    session = RouteSession(RouteSessionDefinition.from_route(route), engine)
    snapshot = session.snapshot()
    definition = snapshot.get("routeDefinition") if isinstance(snapshot, dict) else None
    if not isinstance(definition, dict) or definition.get("routeId") != route.id:
        print("Session snapshot was not produced with the route definition.", file=sys.stderr)
        return 1

    library = RouteLibrary()
    library.record(route, fixture)
    config: dict[str, object] = {}
    library.save_to_config(config)
    if not config.get("route_library"):
        print("Route library did not persist the smoke route.", file=sys.stderr)
        return 1

    with tempfile.TemporaryDirectory(prefix="routeops-smoke-") as temp_dir:
        output = Path(temp_dir) / "snapshot.json"
        output.write_text(json.dumps(snapshot, indent=2), encoding="utf-8")
        if output.stat().st_size == 0:
            print("Snapshot output was empty.", file=sys.stderr)
            return 1

    print(
        "RouteOps offline smoke test passed: "
        f"{route.name}; {len(route.stops)} stops; library and session verified."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
