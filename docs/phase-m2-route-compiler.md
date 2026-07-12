# M2 — Route Compiler

## Purpose

M2 separates source ingestion from runtime execution. Route files are compiled into the existing normalized `Route` model before the kernel creates or operates a `RouteEngine`.

## Scope

- Add a stable source-to-route compiler contract.
- Preserve all existing importer behavior and diagnostics.
- Record source format and compile metadata explicitly.
- Move application route loading behind the compiler boundary.
- Add provider-neutral source contracts after compiler parity is established.
- Keep the M0 and M1 regression suites green.

## Non-goals

- No route-model rewrite.
- No gameplay or completion changes.
- No provider-specific business logic in the kernel.
- No state, navigation, or UI redesign.

## Initial architecture

```text
route file / future provider
          |
     RouteCompiler
          |
  normalized Route + diagnostics
          |
      RouteKernel
          |
     RouteEngine
```

## Exit criteria

- [ ] Compiler result contract is stable and read-only.
- [ ] Existing file formats compile with importer parity.
- [ ] Compile errors are returned as diagnostics without partial runtime state.
- [ ] Application route loading uses `RouteCompiler`.
- [ ] Compiler modules are included in package validation.
- [ ] Existing regression, EDDiscovery, and package gates remain green.
- [ ] Compiler migration and rollback notes are complete.
