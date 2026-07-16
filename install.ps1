[CmdletBinding()]
param(
    [string]$EddDataRoot,
    [string]$EddInstallRoot,
    [string]$EddExecutable
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'edd-root.ps1')
. (Join-Path $PSScriptRoot 'portable-root.ps1')

$version = (Get-Content -LiteralPath (Join-Path $PSScriptRoot 'VERSION') -Raw).Trim()
$report = New-Object 'System.Collections.Generic.List[string]'
function Add-Report {
    param([string]$Text)
    $report.Add($Text)
    Write-Host $Text
}

Add-Report "EDD RouteOps v$version installer"
Add-Report ('Started: ' + (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'))
Add-Report ''

$selection = Find-EddPortableDataRoot -Requested $EddDataRoot -InstallRoot $EddInstallRoot -Executable $EddExecutable
$root = $selection.Path
$actions = Join-Path $root 'Actions'
$pluginsRoot = Join-Path $root 'Plugins'
$plugins = Join-Path $pluginsRoot 'RouteOps'
$registration = Join-Path $actions 'RouteOpsPanel.act'
$oldRegistration = Join-Path $actions 'V1\RouteOpsPanel.act'
$timestamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$backupRoot = Join-Path $root '.routeops-backups'
$backup = Join-Path $backupRoot "$timestamp-v$version"
$staging = Join-Path $root ('.routeops-install-staging-' + [guid]::NewGuid().ToString('N'))

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
}

$running = @(Get-EddRunningProcesses)
if ($running.Count -gt 0) {
    Add-Report ''
    Add-Report 'INSTALL BLOCKED: EDDiscovery is currently running.'
    foreach ($proc in $running) {
        Add-Report ("  PID {0}: {1}" -f $proc.ProcessId, $proc.ExecutablePath)
    }
    throw 'Fully close EDDiscovery before installing RouteOps.'
}

$sourcePlugin = Join-Path $PSScriptRoot 'Plugin\RouteOps'
$sourceRegistration = Join-Path $PSScriptRoot 'ActionFiles\V1\RouteOpsPanel.act'
$requiredRelative = @(
    'config.json', 'RouteOps.py', 'routeops_runtime.py', 'route_models.py', 'route_importer.py',
    'trade_csv_importer.py', 'spansh_exobiology_importer.py',
    'exobiology_catalog.py', 'exobio_taxonomy.py', 'exobio_projection.py',
    'exobio_diagnostics.py', 'navigation_model.py',
    'Data\exobiology_catalog.json', 'Data\exobiology_taxonomy.json',
    'route_engine.py', 'journal_normalizer.py', 'specializations.py',
    'route_metrics.py', 'clipboard_service.py', 'state_store.py',
    'session_storage.py', 'runtime_health.py', 'route_library.py',
    'route_session.py', 'kernel_contracts.py', 'route_kernel.py',
    'route_compiler.py', 'source_providers.py', 'routeops_kernel_app.py',
    'routeops_version.py', 'spansh_client.py', 'colonisation.py', 'cargo.py',
    'ui_renderer.py', 'checkmodules.py', 'UIInterface.act', 'routeops.png'
)

try {
    New-Item -ItemType Directory -Force -Path (Join-Path $staging 'Plugins') | Out-Null
    New-Item -ItemType Directory -Force -Path (Join-Path $staging 'Actions') | Out-Null
    Copy-Item -LiteralPath $sourcePlugin -Destination (Join-Path $staging 'Plugins\RouteOps') -Recurse -Force
    Copy-Item -LiteralPath $sourceRegistration -Destination (Join-Path $staging 'Actions\RouteOpsPanel.act') -Force

    $stagedPlugin = Join-Path $staging 'Plugins\RouteOps'
    $stagedRegistration = Join-Path $staging 'Actions\RouteOpsPanel.act'
    $missing = @($requiredRelative | ForEach-Object { Join-Path $stagedPlugin $_ } | Where-Object { -not (Test-Path -LiteralPath $_ -PathType Leaf) })
    if (-not (Test-Path -LiteralPath $stagedRegistration -PathType Leaf)) {
        $missing += $stagedRegistration
    }
    if ($missing.Count -gt 0) {
        Add-Report 'INSTALL FAILED. Staged package is missing required files:'
        foreach ($file in $missing) { Add-Report "  $file" }
        throw 'RouteOps staged-package verification failed.'
    }

    $hasExisting = (Test-Path -LiteralPath $plugins -PathType Container) -or (Test-Path -LiteralPath $registration -PathType Leaf)
    if ($hasExisting) {
        New-Item -ItemType Directory -Force -Path (Join-Path $backup 'Plugins') | Out-Null
        New-Item -ItemType Directory -Force -Path (Join-Path $backup 'Actions') | Out-Null
        if (Test-Path -LiteralPath $plugins) {
            Copy-Item -LiteralPath $plugins -Destination (Join-Path $backup 'Plugins\RouteOps') -Recurse -Force
        }
        if (Test-Path -LiteralPath $registration) {
            Copy-Item -LiteralPath $registration -Destination (Join-Path $backup 'Actions\RouteOpsPanel.act') -Force
        }
        Add-Report "Rollback backup: $backup"
    }

    New-Item -ItemType Directory -Force -Path $actions | Out-Null
    New-Item -ItemType Directory -Force -Path $pluginsRoot | Out-Null
    if (Test-Path -LiteralPath $plugins) {
        Remove-Item -LiteralPath $plugins -Recurse -Force
    }
    Move-Item -LiteralPath $stagedPlugin -Destination $plugins
    Copy-Item -LiteralPath $stagedRegistration -Destination $registration -Force

    if (Test-Path -LiteralPath $oldRegistration) {
        Remove-Item -LiteralPath $oldRegistration -Force
        Add-Report "Removed stale registration: $oldRegistration"
    }

    $installedMissing = @($requiredRelative | ForEach-Object { Join-Path $plugins $_ } | Where-Object { -not (Test-Path -LiteralPath $_ -PathType Leaf) })
    if ($installedMissing.Count -gt 0 -or -not (Test-Path -LiteralPath $registration -PathType Leaf)) {
        throw 'Installed-file verification failed.'
    }
}
catch {
    Add-Report "INSTALL FAILED: $($_.Exception.Message)"
    if (Test-Path -LiteralPath (Join-Path $backup 'Plugins\RouteOps')) {
        if (Test-Path -LiteralPath $plugins) { Remove-Item -LiteralPath $plugins -Recurse -Force }
        Copy-Item -LiteralPath (Join-Path $backup 'Plugins\RouteOps') -Destination $plugins -Recurse -Force
        Copy-Item -LiteralPath (Join-Path $backup 'Actions\RouteOpsPanel.act') -Destination $registration -Force
        Add-Report "Automatically restored backup: $backup"
    }
    throw
}
finally {
    if (Test-Path -LiteralPath $staging) {
        Remove-Item -LiteralPath $staging -Recurse -Force
    }
}

Add-Report ''
Add-Report "Installed RouteOps version: $version"
Add-Report "Plugin directory: $plugins"
Add-Report "Registration: $registration"
Add-Report 'First run: restart EDDiscovery, add RouteOps from the (+) panel selector, then press Health.'
if (Test-Path -LiteralPath $backup) {
    Add-Report "Rollback command: powershell -ExecutionPolicy Bypass -File `"$PSScriptRoot\rollback.ps1`" -EddDataRoot `"$root`" -BackupPath `"$backup`""
}

$rootReport = Join-Path $root 'RouteOps-install-report.txt'
$localReport = Join-Path $PSScriptRoot 'RouteOps-install-report.txt'
$report | Set-Content -Path $rootReport -Encoding UTF8
$report | Set-Content -Path $localReport -Encoding UTF8

Write-Host ''
Write-Host "RouteOps v$version installed and verified." -ForegroundColor Green
Write-Host "EDDiscovery data root: $root"
Write-Host 'Restart EDDiscovery, add RouteOps, then press Health.'
Write-Host "Install report: $localReport"
