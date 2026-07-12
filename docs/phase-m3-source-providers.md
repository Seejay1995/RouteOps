# M3 — Source Providers

## Purpose

M3 separates route source acquisition from route compilation. Providers resolve a source identifier into a local compile target and immutable source metadata. `RouteCompiler` remains responsible for normalization and diagnostics.

## Delivered scope

- Defined immutable provider-neutral `RouteSource` contracts.
- Added a file-backed source provider.
- Added ordered provider resolution through `RouteSourceRegistry`.
- Added provider-aware `RouteCompiler.compile_source()`.
- Preserved `compile_file()` as a compatibility entry point.
- Migrated application route loading to provider-aware compilation.
- Added provider, compiler, application, and package-contract coverage.
- Kept providers free of route-domain and gameplay logic.

## Non-goals

- No network provider implementation.
- No credentials, authentication, or background synchronization.
- No route-model, state, navigation, or UI redesign.
- No provider-specific logic in the kernel.

## Architecture

```text
source identifier
       |
RouteSourceRegistry
       |
RouteSourceProvider
       |
immutable RouteSource
       |
RouteCompiler
       |
normalized Route + diagnostics
       |
RouteKernel / RouteEngine
```

## Migration behavior

The EDDiscovery application adapter still delegates the surrounding load lifecycle to the legacy application. During that lifecycle, its importer binding is temporarily replaced by a compatibility function that calls `RouteCompiler.compile_source()`, converts the result to the existing `ImportResult`, and restores the original importer in a `finally` block.

This preserves existing UI refresh, persistence, diagnostics, and engine construction behavior while moving source acquisition behind the provider boundary.

## Rollback

Rollback is limited to the adapter and compiler entry point:

1. Change `KernelRouteOpsApplication._compile_import_result()` from `compile_source(source)` back to `compile_file(source)`.
2. The file provider and registry may remain packaged because `compile_file()` delegates through the same compiler contract.
3. For a full M3 rollback, revert the M3 merge commit; M2 remains a complete compiler-backed loading baseline.

No route data or persisted runtime state requires migration.

## Verification evidence

- Workflow run #51 validated the provider contracts, registry, compiler integration, EDDiscovery artifacts, and package layout.
- Workflow run #55 validated provider-aware application loading, importer restoration, diagnostics preservation, EDDiscovery artifacts, and clean package layout.
- The failed intermediate run #54 was caused by a truncated test-file write; no production provider, compiler, or application code change was required.

## Exit criteria

- [x] Source contracts and metadata are immutable.
- [x] File sources resolve through the registry.
- [x] Custom providers can feed the compiler without kernel changes.
- [x] `compile_file()` behavior remains compatible.
- [x] Application loading uses provider-aware compilation.
- [x] Provider and compiler modules are package-validated.
- [x] Existing regression, EDDiscovery, and package gates remain green.
- [x] Migration and rollback notes are complete.
