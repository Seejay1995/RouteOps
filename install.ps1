[CmdletBinding()]
param(
    [string]$EddDataRoot,
    [string]$EddInstallRoot,
    [string]$EddExecutable
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'edd-root.ps1')
. (Join-Path $PSScriptRoot 'portable-root.ps1')

$report = New-Object 'System.Collections.Generic.List[string]'
function Add-Report {
    param([string]$Text)
    $report.Add($Text)
    Write-Host $Text
}

Add-Report 'EDD RouteOps v0.5.0 installer'
Add-Report ('Started: ' + (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'))
Add-Report ''

$selection = Find-EddPortableDataRoot -Requested $EddDataRoot -InstallRoot $EddInstallRoot -Executable $EddExecutable
$root = $selection.Path
$actions = Join-Path $root 'Actions'
$plugins = Join-Path $root 'Plugins\RouteOps'
$registration = Join-Path $actions 'RouteOpsPanel.act'
$oldRegistration = Join-Path $actions 'V1\RouteOpsPanel.act'
$timestamp = Get-Date -Format 'yyyyMMdd-HHmmss'

if ($selection.Candidates.Count -gt 0) {
    Add-Report 'Detected EDDiscovery data-folder candidates:'
    foreach ($candidate in ($selection.Candidates |
        Sort-Object -Property @{ Expression = 'Priority'; Descending = $true }, @{ Expression = 'Score'; Descending = $true }, @{ Expression = 'Path'; Descending = $false })) {
        Add-Report ("  Priority {0,5} / Score {1,3}: {2} [{3}]" -f $candidate.Priority, $candidate.Score, $candidate.Path, $candidate.Reason)
    }
    Add-Report ''
}

if ($selection.PSObject.Properties['Portable'] -and $selection.Portable) {
    Add-Report ("Portable install root: {0}" -f $selection.InstallRoot)
    Add-Report ("Portable executable: {0}" -f $selection.ExecutablePath)
}
Add-Report ("Selected ACTIVE data root: {0}" -f $root)
Add-Report ("Selection reason: {0}; priority {1}; score {2}" -f $selection.Reason, $selection.Priority, $selection.Score)

if (-not (Test-Path (Join-Path $root 'EDDUser.sqlite')) -and
    -not (Test-Path (Join-Path $root 'EDDSystem.sqlite'))) {
    Add-Report 'WARNING: No EDDUser.sqlite or EDDSystem.sqlite was found in the selected folder.'
    Add-Report 'Rerun with an explicit portable install or data root if this is incorrect:'
    Add-Report '  powershell -ExecutionPolicy Bypass -File .\install.ps1 -EddInstallRoot "E:\Your\EDDiscovery"'
    Add-Report '  powershell -ExecutionPolicy Bypass -File .\install.ps1 -EddDataRoot "E:\Your\EDDiscoveryData"'
}

$running = @(Get-EddRunningProcesses)
if ($running.Count -gt 0) {
    Add-Report ''
    Add-Report 'NOTICE: EDDiscovery is currently running.'
    foreach ($proc in $running) {
        Add-Report ("  PID {0}: {1}" -f $proc.ProcessId, $proc.ExecutablePath)
    }
    Add-Report 'Installation can continue, but EDDiscovery must be fully restarted before RouteOps appears.'
}

New-Item -ItemType Directory -Force -Path $actions | Out-Null
New-Item -ItemType Directory -Force -Path $plugins | Out-Null

$existingPluginFiles = Get-ChildItem -Path $plugins -Force -ErrorAction SilentlyContinue
if ($existingPluginFiles) {
    $backup = "$plugins.backup-$timestamp"
    Copy-Item -Path $plugins -Destination $backup -Recurse -Force
    Add-Report "Backed up existing active-root plugin to: $backup"
}

Copy-Item -Path (Join-Path $PSScriptRoot 'Plugin\RouteOps\*') -Destination $plugins -Recurse -Force
Copy-Item -Path (Join-Path $PSScriptRoot 'ActionFiles\V1\RouteOpsPanel.act') -Destination $registration -Force

if (Test-Path $oldRegistration) {
    Remove-Item $oldRegistration -Force
    Add-Report "Removed stale registration: $oldRegistration"
}

$required = @(
    $registration,
    (Join-Path $plugins 'config.json'),
    (Join-Path $plugins 'RouteOps.py'),
    (Join-Path $plugins 'route_models.py'),
    (Join-Path $plugins 'route_importer.py'),
    (Join-Path $plugins 'trade_csv_importer.py'),
    (Join-Path $plugins 'spansh_exobiology_importer.py'),
    (Join-Path $plugins 'exobiology_catalog.py'),
    (Join-Path $plugins 'exobio_taxonomy.py'),
    (Join-Path $plugins 'exobio_projection.py'),
    (Join-Path $plugins 'exobio_diagnostics.py'),
    (Join-Path $plugins 'navigation_model.py'),
    (Join-Path $plugins 'Data\exobiology_catalog.json'),
    (Join-Path $plugins 'Data\exobiology_taxonomy.json'),
    (Join-Path $plugins 'route_engine.py'),
    (Join-Path $plugins 'journal_normalizer.py'),
    (Join-Path $plugins 'specializations.py'),
    (Join-Path $plugins 'route_metrics.py'),
    (Join-Path $plugins 'clipboard_service.py'),
    (Join-Path $plugins 'state_store.py'),
    (Join-Path $plugins 'session_storage.py'),
    (Join-Path $plugins 'runtime_health.py'),
    (Join-Path $plugins 'route_library.py'),
    (Join-Path $plugins 'route_session.py'),
    (Join-Path $plugins 'kernel_contracts.py'),
    (Join-Path $plugins 'route_kernel.py'),
    (Join-Path $plugins 'route_compiler.py'),
    (Join-Path $plugins 'source_providers.py'),
    (Join-Path $plugins 'routeops_kernel_app.py'),
    (Join-Path $plugins 'ui_renderer.py'),
    (Join-Path $plugins 'checkmodules.py'),
    (Join-Path $plugins 'UIInterface.act'),
    (Join-Path $plugins 'routeops.png')
)

$missing = @($required | Where-Object { -not (Test-Path $_) })
if ($missing.Count -gt 0) {
    Add-Report 'INSTALL FAILED. Missing required files:'
    foreach ($file in $missing) { Add-Report "  $file" }
    throw 'RouteOps verification failed.'
}

Add-Report ''
Add-Report 'Verified active-root files:'
foreach ($file in $required) { Add-Report "  $file" }

$inactiveCopies = @()
if ($selection.Candidates.Count -gt 0) {
    foreach ($candidate in $selection.Candidates) {
        if ($candidate.Path -ieq $root) { continue }
        $otherRegistration = Join-Path $candidate.Path 'Actions\RouteOpsPanel.act'
        $otherPlugin = Join-Path $candidate.Path 'Plugins\RouteOps'
        if ((Test-Path $otherRegistration) -or (Test-Path $otherPlugin)) {
            $inactiveCopies += $candidate.Path
        }
    }
}

if ($inactiveCopies.Count -gt 0) {
    Add-Report ''
    Add-Report 'Inactive RouteOps copies were found. They do not affect the active EDD installation:'
    foreach ($copy in ($inactiveCopies | Sort-Object -Unique)) { Add-Report "  $copy" }
}

$rootReport = Join-Path $root 'RouteOps-install-report.txt'
$localReport = Join-Path $PSScriptRoot 'RouteOps-install-report.txt'
$report | Set-Content -Path $rootReport -Encoding UTF8
$report | Set-Content -Path $localReport -Encoding UTF8

Write-Host ''
Write-Host 'RouteOps installed and verified in the ACTIVE EDDiscovery data root.' -ForegroundColor Green
Write-Host "EDDiscovery data root: $root"
Write-Host 'Fully close EDDiscovery, make sure EDDiscovery.exe is gone, then restart it.'
Write-Host 'After startup, open the (+) panel selector and add RouteOps.'
Write-Host "Install report: $localReport"
