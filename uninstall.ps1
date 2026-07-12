[CmdletBinding()]
param(
    [string]$EddDataRoot
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'edd-root.ps1')

$selection = Find-EddDataRoot -Requested $EddDataRoot
$root = $selection.Path
$registration = Join-Path $root 'Actions\RouteOpsPanel.act'
$oldRegistration = Join-Path $root 'Actions\V1\RouteOpsPanel.act'
$plugin = Join-Path $root 'Plugins\RouteOps'

Write-Host "Removing RouteOps from active data root: $root"
foreach ($path in @($registration, $oldRegistration)) {
    if (Test-Path $path) { Remove-Item $path -Force }
}
if (Test-Path $plugin) { Remove-Item $plugin -Recurse -Force }
Write-Host 'RouteOps removed. Restart EDDiscovery.' -ForegroundColor Green
