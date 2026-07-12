# M1 — Kernel Foundation

## Purpose

M1 introduces a stable application boundary between EDDiscovery/UI adapters and RouteOps domain execution while preserving the M0 behavioral baseline.

The first slice wraps the proven v0.5 `RouteEngine` rather than replacing it. This allows later phases to move journal ingestion, commands, persistence, and presentation behind explicit contracts without changing route behavior.

## Scope

- Add immutable kernel command and result contracts.
- Add a `RouteKernel` façade over the existing engine.
- Route journal events and user commands through one application boundary.
- Preserve existing action payloads, state serialization, navigation, values, and completion semantics.
- Add parity tests comparing façade execution with direct engine execution.
- Require kernel modules in the packaged plugin.

## Non-goals

- No route-model rewrite.
- No provider/plugin architecture yet.
- No UI redesign.
- No state-schema change.
- No removal of `RouteEngine` compatibility methods.
- No behavior changes to waypoint, exploration, exobiology, materials, trade, cargo, or carrier workflows.

## Initial architecture

```text
EDDiscovery / UI / persistence adapters
                 |
          KernelCommand
                 v
            RouteKernel
                 |
        proven RouteEngine
                 |
        domain actions + state
```

## Exit criteria

- [ ] Kernel command/result contracts are complete and immutable.
- [ ] `RouteKernel` dispatches supported commands and journal events.
- [ ] Application code uses the kernel boundary for journal and initial command paths.
- [ ] Direct-engine and kernel parity tests pass.
- [ ] Existing M0 regression suite remains green.
- [ ] Package and EDDiscovery validation remain green.
- [ ] Unsupported commands fail without mutating state.
- [ ] M1 architecture and migration notes are complete.

## Definition of done

M1 is complete when RouteOps has a tested, package-safe kernel boundary that can become the stable execution API for subsequent compiler, provider, state, navigation, and UI phases without changing current behavior.
