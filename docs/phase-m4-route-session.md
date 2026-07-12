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

## Exit criteria

- [ ] Runtime mutations do not alter the compiled route template.
- [ ] Session snapshots retain the existing engine state contract.
- [ ] State restoration rejects a mismatched route identifier.
- [ ] Kernel construction supports both sessions and legacy engines.
- [ ] Application loading creates a session and kernel over the working route.
- [ ] Session module is included in package validation.
- [ ] Existing regression, EDDiscovery, and package gates remain green.
- [ ] Migration and rollback evidence is complete.
