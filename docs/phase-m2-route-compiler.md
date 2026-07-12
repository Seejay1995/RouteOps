# M2 — Route Compiler

## Purpose

M2 separates source ingestion from runtime execution. Route files are compiled into the existing normalized `Route` model before the kernel creates or operates a `RouteEngine`.

## Scope

- Add a stable source-to-route compiler contract.
- Preserve all existing importer behavior and diagnostics.
- Record source format and compile metadata explicitly.
- Move application route loading behind the compiler boundary.
- Keep the M0 and M1 regression suites green.

## Non-goals

- No route-model rewrite.
- No gameplay or completion changes.
- No provider-specific business logic in the kernel.
- No state, navigation, or UI redesign.

## Final architecture

```text
route file / future provider
          |
     RouteCompiler
          |
  normalized Route + diagnostics
          |
 KernelRouteOpsApplication
          |
      RouteKernel
          |
     RouteEngine
```

The application preserves the proven v0.5 load lifecycle by temporarily adapting the legacy importer call to `RouteCompiler.compile_file()`. The original importer binding is restored in a `finally` block after every load, providing a contained rollback path while avoiding duplicated configuration, state restoration, persistence, and UI logic.

## Validation evidence

- Importer/compiler parity covers the normalized `Route`, warnings, errors, and source format.
- Invalid sources return diagnostics without creating a route.
- Compile metadata is read-only.
- Application-level tests confirm route loading invokes the compiler, preserves diagnostics, creates the kernel after successful compilation, and restores the legacy importer binding.
- GitHub Actions run #48 passed Python compilation and tests, PowerShell parsing, repository and EDDiscovery artifact validation, and clean package-layout validation.

## Exit criteria

- [x] Compiler result contract is stable and read-only.
- [x] Existing file formats compile with importer parity.
- [x] Compile errors are returned as diagnostics without partial runtime state.
- [x] Application route loading uses `RouteCompiler`.
- [x] Compiler modules are included in package validation.
- [x] Existing regression, EDDiscovery, and package gates remain green.
- [x] Compiler migration and rollback notes are complete.

## Definition of done

M2 is complete: source ingestion is isolated behind a tested compiler boundary, the EDDiscovery application loads through that boundary, and current RouteOps behavior remains unchanged.
