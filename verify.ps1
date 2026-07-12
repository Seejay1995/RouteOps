[CmdletBinding()]
param(
    [string]$EddDataRoot
)

$ErrorActionPreference = 'Continue'
. (Join-Path $PSScriptRoot 'edd-root.ps1')

$selection = Find-EddDataRoot -Requested $EddDataRoot
$root = $selection.Path

Write-Host 'EDD RouteOps v0.5.0 verification' -ForegroundColor Cyan
Write-Host "Active data root: $root"
Write-Host "Reason: $($selection.Reason)"
Write-Host ''

$checks = @(
    (Join-Path $root 'EDDUser.sqlite'),
    (Join-Path $root 'EDDSystem.sqlite'),
    (Join-Path $root 'Actions\RouteOpsPanel.act'),
    (Join-Path $root 'Plugins\RouteOps\config.json'),
    (Join-Path $root 'Plugins\RouteOps\RouteOps.py'),
    (Join-Path $root 'Plugins\RouteOps\route_models.py'),
    (Join-Path $root 'Plugins\RouteOps\route_importer.py'),
    (Join-Path $root 'Plugins\RouteOps\trade_csv_importer.py'),
    (Join-Path $root 'Plugins\RouteOps\spansh_exobiology_importer.py'),
    (Join-Path $root 'Plugins\RouteOps\exobiology_catalog.py'),
    (Join-Path $root 'Plugins\RouteOps\exobio_taxonomy.py'),
    (Join-Path $root 'Plugins\RouteOps\exobio_projection.py'),
    (Join-Path $root 'Plugins\RouteOps\exobio_diagnostics.py'),
    (Join-Path $root 'Plugins\RouteOps\navigation_model.py'),
    (Join-Path $root 'Plugins\RouteOps\Data\exobiology_catalog.json'),
    (Join-Path $root 'Plugins\RouteOps\Data\exobiology_taxonomy.json'),
    (Join-Path $root 'Plugins\RouteOps\route_engine.py'),
    (Join-Path $root 'Plugins\RouteOps\journal_normalizer.py'),
    (Join-Path $root 'Plugins\RouteOps\specializations.py'),
    (Join-Path $root 'Plugins\RouteOps\route_metrics.py'),
    (Join-Path $root 'Plugins\RouteOps\clipboard_service.py'),
    (Join-Path $root 'Plugins\RouteOps\state_store.py'),
    (Join-Path $root 'Plugins\RouteOps\ui_renderer.py'),
    (Join-Path $root 'Plugins\RouteOps\checkmodules.py'),
    (Join-Path $root 'Plugins\RouteOps\UIInterface.act'),
    (Join-Path $root 'Plugins\RouteOps\routeops.png')
)

$missing = 0
foreach ($path in $checks) {
    $exists = Test-Path $path
    if (-not $exists) { $missing++ }
    $state = if ($exists) { 'FOUND  ' } else { 'MISSING' }
    Write-Host "$state  $path"
}

Write-Host ''
Write-Host 'Recent startup-log references:' -ForegroundColor Cyan
$logRoot = Join-Path $root 'Log'
$logs = Get-ChildItem -Path $logRoot -Filter 'Trace_*.log' -File -ErrorAction SilentlyContinue |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 5

if (-not $logs) {
    Write-Host 'No trace logs found.'
}
else {
    $matches = $logs | Select-String -Pattern 'RouteOps|did not install|Failed to load files|UserControlZMQPanel|Added panel|ActionFileList Loaded pack' -SimpleMatch:$false
    if ($matches) {
        $matches | ForEach-Object { Write-Host ("{0}:{1}: {2}" -f $_.Path, $_.LineNumber, $_.Line.Trim()) }
    }
    else {
        Write-Host 'No RouteOps loading entry was found yet. Restart EDDiscovery after installation.'
    }
}

Write-Host ''
if ($missing -eq 0) {
    Write-Host 'File verification passed.' -ForegroundColor Green
}
else {
    Write-Host "$missing required item(s) are missing from the active data root." -ForegroundColor Red
    exit 1
}
