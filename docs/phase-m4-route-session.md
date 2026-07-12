# M4 — Route Session Boundary

## Purpose

M4 separates a compiled route definition from the mutable runtime progress created while flying it. The compiler output is retained as a template, while `RouteSession` owns the working route, state restoration, snapshots, and the engine used by the kernel.

## Scope

- Introduce an immutable route-session definition.
- Fingerprint the structural route definition.
- Deep-copy compiler output before runtime mutation.
- Make the kernel session-aware without breaking direct `RouteEngine` construction.
- Route persistence snapshots through the session.
- Preserve the existing state-store file format and migration path.
- Package and test the new boundary.

## Non-goals

- No state schema rewrite.
- No multi-session UI.
- No cloud synchronization.
- No route editing workflow.
- No engine behavior or journal-processing redesign.

## Architecture

```text
RouteSourceProvider
        |
 RouteCompiler
        |
compiled Route template
        |
  RouteSession
   |        |
working Route  snapshot/restore
        |
   RouteEngine
        |
   RouteKernel
        |
EDDiscovery adapter
```

## Compatibility

`RouteKernel(RouteEngine(...))` remains supported through `RouteSession.attach()` so M1–M3 callers and tests can roll back independently. Session snapshots extend the existing engine state with `sessionVersion`, `routeFingerprint`, and `routeDefinition`; legacy keys remain present.

## Validation evidence

- Workflow run #61 completed successfully on Windows.
- Python source compilation passed.
- Python regression tests passed.
- PowerShell parsing passed.
- Repository and EDDiscovery artifact validation passed.
- Clean package layout validation passed.
- The full `route_kernel.py` source was committed atomically through Git blob/tree operations after the contents API repeatedly truncated the file.

## Migration and rollback

Migration requires no state-file rewrite. Existing saved state continues to load through the current state-store migration path and is applied to the session working copy. The compiled route template remains unchanged.

Rollback can construct `RouteKernel` directly from `RouteEngine`; this uses the compatibility bridge and returns the legacy engine snapshot contract. Removing the adapter session wiring restores the M3 runtime path without changing saved-state files.

## Exit criteria

- [x] Runtime mutations do not alter the compiled route template.
- [x] Session snapshots retain the existing engine state contract.
- [x] State restoration rejects a mismatched route identifier.
- [x] Kernel construction supports both sessions and legacy engines.
- [x] Application loading creates a session and kernel over the working route.
- [x] Session module is included in package validation.
- [x] Existing regression, EDDiscovery, and package gates remain green.
- [x] Migration and rollback evidence is complete.
