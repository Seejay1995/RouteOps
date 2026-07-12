# EDD RouteOps v0.5.0

RouteOps is an EDDiscovery Python/ZMQ operations panel for navigation, exploration, exobiology, material farming, trade, cargo, and carrier routes.

## v0.5.0 Navigation and Target Triage

RouteOps now treats navigation as a first-class workflow instead of inferring it from a flat stop list.

- A system queue shows route order, body count, active body count, organism targets, active value, manifest completeness, and system state.
- A body queue shows every route-provided body before SAA scanning, including distance from arrival, biological signal count, included targets, sample totals, active value, and state.
- A species triage grid shows the exact body-qualified species or variant, scan progress, value, inclusion decision, search difficulty, and source.
- The navigation target is explicit and persistent. Inspecting a row does not silently change where RouteOps is guiding you.
- Entering a system changes guidance from the system to the first active body without completing exobiology work.
- Previous and Next Target move through active bodies in the current system before moving to another system.
- Guidance modes are explicit: **Confirm**, **Auto-copy**, and **Auto-advance**.
- Body order can use route order, nearest first, highest value first, or stored manual order.
- Species skips are previewed before confirmation with system, body, exact organism identity, certainty, progress, reason, value removed, remaining body value, and whether the body or system will leave active navigation.
- A skip applies to the selected organism on the selected body and can be reversed with **Undo Last Skip**.
- Search difficulty can be recorded per organism or variety.
- State schema v6 preserves navigation target, selected system/body, guidance, ordering, difficulty, pending skip, and skip decisions.
- Debug bundles now include the navigation plan and skip-decision ledger.

The v0.4 non-destructive Bacterium filtering and complete species workspace remain in place. Bacterium-only bodies leave active navigation while their raw progress and value remain inspectable in **View: All**.

## Requirements

- Windows
- EDDiscovery 19.0 or later
- Python 3 with `py.exe` or `python.exe`
- `pyzmq`; EDDiscovery installs it automatically when missing

## Install or upgrade

1. Fully close EDDiscovery and confirm `EDDiscovery.exe` is no longer running.
2. Run the supplied `INSTALL-EDD-RouteOps-v0.5.0.ps1` launcher from Downloads.
3. The launcher applies the upgrade to:

   ```text
   E:\Projects\EDD-RouteOps-v0.2.2 (1)\EDD-RouteOps-v0.2.2
   ```

4. It installs the verified plugin into:

   ```text
   E:\Gaming
   ```

5. Restart EDDiscovery and open RouteOps.

The installer validates package hashes, backs up the source, runs all 98 tests, restores the source automatically if tests fail, installs the plugin, and verifies the active EDDiscovery files.

For direct installation from an extracted source tree:

```powershell
powershell -ExecutionPolicy Bypass -File .\install.ps1 -EddDataRoot "E:\Gaming"
```

## Navigation workflow

### Before entering a system

The explicit target is the next system. Use **Copy System** through the main navigation button.

### In the target system

RouteOps selects the first active body from the imported manifest. The body queue is available before SAA whenever the source route includes body data.

### Inspecting versus navigating

- Selecting a system, body, or species changes the inspection workspace only.
- **Choose Body** makes the inspected body the explicit navigation target.
- **Previous Target** and **Next Target** change the explicit target without completing work.
- **Finish Body** completes the current body and selects the next active body only when the user intentionally invokes it.

### Guidance modes

- **Confirm** — location is detected automatically, but RouteOps never copies or advances without a command.
- **Auto-copy** — RouteOps selects and copies the next system or body but does not complete unfinished work.
- **Auto-advance** — journal-confirmed completion selects and copies the next active target. System entry never counts as completion.

### Body ordering

- **Route** — provider/import order.
- **Nearest** — distance from arrival, where supplied by the route source.
- **Value** — highest active body value first.
- **Manual** — stored body order from the route manifest.

## Target triage and skipping

Select a species on a body, then use **Preview Skip**. The detail pane displays:

- system and body;
- genus, species, and variant certainty;
- current scans;
- skip reason;
- value removed;
- body value before and after;
- whether the body or system leaves active navigation.

Use **Confirm Skip** only after reviewing the impact. **Cancel Skip** leaves the target unchanged, and **Undo Last Skip** restores the most recent body-specific skip and its value.

Skip reasons include difficult to locate, low value, unsuitable terrain, too far from arrival, already sampled, time limit, user preference, and other.

Filtering and skipping remain separate:

- **Filter** applies a reusable preference such as excluding Bacterium.
- **Skip** records a deliberate decision for a particular target on a particular body.
- **Complete** records finished work.
- **Unresolved** means RouteOps does not yet know the exact organism.

## Manifest completeness

RouteOps labels the quality of navigation data:

- **Exact** — bodies and organism targets were supplied by the route source.
- **Bodies known** — bodies are known, but exact organisms may still be unresolved.
- **System only** — the route contains no body manifest. Use **Use Exobio** and allow live journal events to create body operations.
- **Live** — the body or organism was discovered from journal events.

A plain EDDiscovery expedition cannot provide body or species details that were never included in the exported file. For pre-SAA body manifests, load a RouteOps v5 or compatible Spansh-style exobiology export.

## Main controls

- **Load Route / Reload** — load or refresh an expedition, RouteOps manifest, Spansh export, or EDDiscovery Route CSV.
- **Copy Target** — copy the explicit system or body target.
- **Previous Target / Next Target** — navigate active targets without changing completion.
- **Guidance** — cycle Confirm, Auto-copy, and Auto-advance.
- **Order** — cycle Route, Nearest, Value, and Manual body order.
- **Choose Body** — make the inspected body the navigation target.
- **Finish Body / Skip Body / Reopen Body** — explicit body work controls.
- **Preview Skip / Confirm Skip / Cancel Skip / Undo Last Skip** — value-aware organism triage.
- **Skip Reason** — cycle the reason stored with the next skip.
- **Difficulty** — rate the selected organism or variety.
- **Bacterium: Included / Excluded** — recalculate active targets and value using canonical taxonomy.
- **Show Excluded** — show filtered species while keeping them excluded from route calculations.
- **View: Active / All** — operational route versus complete raw inventory.
- **Export Debug** — export route, navigation, species, filters, values, skip decisions, state, and recent journal observations.


## Supported input formats

### EDDiscovery Trade Router CSV

EDDiscovery expedition JSON cannot preserve Spansh Trade Router instructions. It contains only the route name and system-name list. To create real trade tasks:

1. Build the route in **Route → Trade Router**.
2. Do **not** use the expedition JSON as the task source.
3. In the Route panel, click the **Excel/CSV export** button above the route grid.
4. Export all route rows as CSV. Keep the **System** and **Information/Notes** columns included.
5. In RouteOps, click **Load Route** and select the CSV.

RouteOps parses rows produced by EDDiscovery in this form:

```text
Station: Ray Gateway
Gold buy 64 profit 121600
Silver buy 32 profit 44800
Profit so far: 166400
```

The final row is normally:

```text
Fly to Smith Terminal and sell all
```

RouteOps converts the chain into:

- dock at the source station;
- buy each listed commodity and quantity;
- dock at the next station;
- sell the incoming commodities;
- buy the next leg's commodities;
- sell all incoming cargo at the final station.

Market transactions may occur in multiple partial purchases or sales; RouteOps aggregates them until the required quantity is reached.

### Native EDDiscovery expedition JSON

```json
{
  "Name": "My Expedition",
  "Systems": ["Sol", "Colonia", "Sagittarius A*"]
}
```

By default, each entry is imported as a waypoint. For exobiology, press **Use Exobio** after loading the route; this creates non-completing system placeholders until live body data is available. The conversion is persistent for that route and prevents system arrival from completing the stop. RouteOps then creates body operations from live journal events.

When the SAA reports biological signals, RouteOps can automatically finish a body after every non-filtered signal has been analysed. When the route has no body list and no SAA signal count is available, the body remains manual and must be closed with **Finish Body** after all desired organisms are sampled.

A route name containing `(Trade)` is classified as Trade, but the exported expedition JSON does not contain stations, commodities, quantities, prices, or buy/sell instructions. RouteOps warns about this and directs you to load the Route panel CSV instead.

### Minimal system list

```json
["Sol", "Colonia", "Sagittarius A*"]
```

### RouteOps schema v2

```json
{
  "schemaVersion": 2,
  "name": "Mixed Operations Route",
  "routeMode": "mixed",
  "settings": {
    "autoCopyMode": "current-target",
    "autoAdvance": true,
    "clipboardRetryCount": 6,
    "clipboardRetryDelayMs": 75,
    "excludedOrganismGenera": ["Bacterium"]
  },
  "stops": [
    {
      "id": "buy-gold",
      "stopType": "trade",
      "system": "Diaguandri",
      "station": "Ray Gateway",
      "label": "Buy Gold",
      "tasks": [
        {
          "type": "dockAtStation",
          "station": "Ray Gateway"
        },
        {
          "type": "buyCommodity",
          "commodity": "Gold",
          "quantity": 192
        }
      ]
    }
  ]
}
```

## Stop specialties

### Waypoint

Completes on `FSDJump`, `CarrierJump`, or `Location` when the target system matches.

### Exploration

Supports:

- `visitSystem`
- `scanStar`
- `scanBody`
- `mapBody`
- `visitBody`
- `landOnBody`
- `dockAtStation`
- `manualChecklist`

Observed events include `Scan`, `SAAScanComplete`, `ApproachBody`, `Touchdown`, and `Docked`.

### Exobiology

Supports `scanOrganic`, `scanSpecies`, and `sampleSpecies`. `ScanOrganic` stages update progress as:

- `Log` → first sample stage
- `Sample` → second sample stage
- `Analyse` → task complete

Optional species do not block advancement.

### Materials

Supports:

- `collectMaterial`
- `reachInventoryQuantity`
- `countMode`: `session`, `inventory`, or `either`

`MaterialCollected` and compatible `MaterialTrade` fields update progress. Inventory mode uses a total field when one is present and otherwise records observed gains.

### Trade

Supports:

- `dockAtStation`
- `buyCommodity`
- `sellCommodity`

Multiple market transactions aggregate until the required quantity is reached.

### Cargo and carrier operations

Supports:

- `loadCommodity`
- `collectCargo`
- `deliverCommodity`
- `unloadCommodity`
- `dockAtStation`

Handled journal events include `MarketBuy`, `MarketSell`, `CollectCargo`, `EjectCargo`, and `CargoDepot` where usable.

## Task fields

Common task fields:

```json
{
  "id": "task-id",
  "type": "collectMaterial",
  "label": "Collect Polonium",
  "target": "Polonium",
  "quantity": 50,
  "required": true,
  "optional": false
}
```

Specialized target keys are also accepted:

- `material`
- `commodity`
- `species`
- `genus`
- `body`
- `station`

Quantity aliases include `quantity`, `targetQuantity`, `quantityRequired`, `desiredGain`, and `samplesRequired`.

## State files

The preferred state location is beside the route:

```text
<route-file>.routeops.state.json
```

If that folder is read-only, RouteOps stores state under:

```text
E:\Gaming\Plugins\RouteOps\State\
```

State schema v2 stores:

- current stop;
- selected stop;
- pause and auto-advance state;
- current known location;
- stop status and arrival state;
- individual task quantities and completion status.

Existing v0.1.x state is migrated when compatible with the same route ID.

## Included samples

- `samples/sample_edd_expedition.json`
- `samples/sample_edd_trade_router.csv`
- `samples/sample_routeops_exobiology_v2.json`
- `samples/sample_routeops_materials_v2.json`
- `samples/sample_routeops_trade_v2.json`
- `samples/sample_routeops_mixed_v2.json`

## Tests

Run from the extracted package:

```powershell
py -m unittest discover -s tests -v
```

The v0.2.2 package includes 41 tests covering:

- EDDiscovery expedition JSON, EDDiscovery Route CSV, v1, and v2 imports;
- mode and specialty inference;
- waypoint advancement;
- exobiology stages and optional targets;
- material and trade aggregation;
- selection, jump, reopen, reset, and state restoration;
- clipboard retries and fallback behavior;
- state corruption and read-only fallback;
- compact header and six-column rendering;
- exact EDDiscovery module-check output;
- dock-order regression protection;
- a live fake-EDD ZMQ startup, UI-event, journal-event, and termination integration test.

## Current limits

- Route authoring remains JSON-based; an in-panel editor is planned for a later release.
- Native EDDiscovery expedition exports contain only route name and systems. Trade tasks require the Route panel CSV export or RouteOps JSON.
- Fleet-carrier multi-run loop generation and route branching are not yet authored automatically.
- Some journal entries expose only transaction deltas rather than a complete inventory snapshot.
- The package is tested against a fake EDDiscovery ZMQ server and unit tests. Final sizing and event-field adjustments may still be required after live use in EDDiscovery 19.1.8.
