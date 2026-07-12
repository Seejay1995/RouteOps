# M1 — Kernel Foundation

## Purpose

M1 introduces a stable application boundary between EDDiscovery/UI adapters and RouteOps domain execution while preserving the M0 behavioral baseline.

The implementation wraps the proven v0.5 `RouteEngine` rather than replacing it. This allows later phases to move compilation, providers, persistence, navigation, and presentation behind explicit contracts without changing route behavior.

## Delivered architecture

```text
EDDiscovery ZMQ + action-file UI
              |
     KernelRouteOpsApplication
              |
         KernelCommand
              v
          RouteKernel
              |
       proven RouteEngine
              |
   domain actions + state snapshot
```

The packaged `config.json` starts `routeops_kernel_app.py`. The legacy `RouteOps.py` application remains packaged and unchanged as the rollback entry point.

## Delivered contracts

- Frozen `KernelCommand` values with copied, read-only payload mappings.
- Frozen `KernelResult` values with copied, read-only action mappings.
- A complete command vocabulary for every existing mutating UI operation.
- Explicit journal-event and history-hydration entry points.
- A state-snapshot entry point preserving the v0.5 serialization contract.
- Rejection of unsupported commands without state mutation.

## Behavioral preservation

M1 does not redesign route behavior. `RouteKernel` delegates to the M0-proven engine while parity tests compare direct-engine and kernel execution. Existing waypoint, exploration, exobiology, materials, trade, cargo, and carrier behavior remains governed by the legacy engine and regression suite.

## Migration notes

- UI row selections and mutating buttons now enter through `KernelCommand`.
- Journal pushes enter through `RouteKernel.handle_journal()`.
- Historical journal hydration enters through `RouteKernel.hydrate_journal_knowledge()`.
- Rendering and persistence continue to read the same engine-backed models during M1.
- Rollback requires changing `Python.Start` in `config.json` from `routeops_kernel_app.py` to `RouteOps.py`.

## Non-goals

- No route-model rewrite.
- No provider/plugin architecture yet.
- No UI redesign.
- No state-schema change.
- No removal of `RouteEngine` compatibility methods.
- No behavior changes to current activity workflows.

## Exit criteria

- [x] Kernel command/result contracts are complete and immutable.
- [x] `RouteKernel` dispatches supported commands and journal events.
- [x] Application code uses the kernel boundary for journal and UI command paths.
- [x] Direct-engine and kernel parity tests pass.
- [x] Existing M0 regression suite remains green.
- [x] Package and EDDiscovery validation remain green.
- [x] Unsupported commands fail without mutating state.
- [x] M1 architecture and migration notes are complete.

## Validation evidence

- Workflow run #33 validated the initial kernel boundary.
- Workflow run #36 validated the complete command dispatcher.
- Workflow run #39 validated the packaged kernel application adapter and rollback contract.
- The final closure run validates contract immutability tests and this completion record.

## Definition of done

M1 is complete when the final closure workflow is green. RouteOps then has a tested, package-safe kernel boundary that can serve as the stable execution API for subsequent compiler, provider, state, navigation, and UI phases without changing current behavior.
