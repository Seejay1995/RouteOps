[CmdletBinding()]
param(
    [string]$EddDataRoot,
    [string]$BackupPath
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'edd-root.ps1')
. (Join-Path $PSScriptRoot 'portable-root.ps1')

$selection = Find-EddPortableDataRoot -Requested $EddDataRoot
$root = $selection.Path
$plugin = Join-Path $root 'Plugins\RouteOps'
$registration = Join-Path $root 'Actions\RouteOpsPanel.act'
$backupRoot = Join-Path $root '.routeops-backups'

if (-not $BackupPath) {
    $candidate = Get-ChildItem -LiteralPath $backupRoot -Directory -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTimeUtc -Descending |
        Select-Object -First 1
    if (-not $candidate) {
        throw "No RouteOps backup was found under $backupRoot"
    }
    $BackupPath = $candidate.FullName
}

$resolvedBackup = (Resolve-Path -LiteralPath $BackupPath).Path
$backupPlugin = Join-Path $resolvedBackup 'Plugins\RouteOps'
$backupRegistration = Join-Path $resolvedBackup 'Actions\RouteOpsPanel.act'

if (-not (Test-Path -LiteralPath $backupPlugin -PathType Container)) {
    throw "Backup does not contain Plugins\RouteOps: $resolvedBackup"
}
if (-not (Test-Path -LiteralPath $backupRegistration -PathType Leaf)) {
    throw "Backup does not contain Actions\RouteOpsPanel.act: $resolvedBackup"
}

$staging = Join-Path $root ('.routeops-rollback-staging-' + [guid]::NewGuid().ToString('N'))
try {
    New-Item -ItemType Directory -Force -Path (Join-Path $staging 'Plugins') | Out-Null
    New-Item -ItemType Directory -Force -Path (Join-Path $staging 'Actions') | Out-Null
    Copy-Item -LiteralPath $backupPlugin -Destination (Join-Path $staging 'Plugins\RouteOps') -Recurse -Force
    Copy-Item -LiteralPath $backupRegistration -Destination (Join-Path $staging 'Actions\RouteOpsPanel.act') -Force

    if (Test-Path -LiteralPath $plugin) {
        Remove-Item -LiteralPath $plugin -Recurse -Force
    }
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $plugin) | Out-Null
    Move-Item -LiteralPath (Join-Path $staging 'Plugins\RouteOps') -Destination $plugin

    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $registration) | Out-Null
    Copy-Item -LiteralPath (Join-Path $staging 'Actions\RouteOpsPanel.act') -Destination $registration -Force
}
finally {
    if (Test-Path -LiteralPath $staging) {
        Remove-Item -LiteralPath $staging -Recurse -Force
    }
}

Write-Host "RouteOps rollback restored: $resolvedBackup" -ForegroundColor Green
Write-Host "EDDiscovery data root: $root"
Write-Host 'Fully restart EDDiscovery before opening RouteOps.'
