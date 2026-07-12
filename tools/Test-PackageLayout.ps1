[CmdletBinding()]
param(
    [Parameter()]
    [string] $Root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$resolvedRoot = (Resolve-Path -LiteralPath $Root).Path
$rootName = Split-Path -Leaf $resolvedRoot
$nestedDuplicate = Join-Path $resolvedRoot $rootName

if (Test-Path -LiteralPath $nestedDuplicate -PathType Container) {
    throw "Nested package root detected: $nestedDuplicate"
}

$backupFiles = Get-ChildItem -LiteralPath $resolvedRoot -Recurse -File -ErrorAction Stop |
    Where-Object { $_.FullName -match '[\\/]\.routeops-backups[\\/]' }

if ($backupFiles) {
    $paths = $backupFiles.FullName -join "`n"
    throw "Release tree contains backup payload files:`n$paths"
}

$forbiddenExtensions = @('.pyc', '.pyo', '.tmp')
$forbiddenFiles = Get-ChildItem -LiteralPath $resolvedRoot -Recurse -File -ErrorAction Stop |
    Where-Object { $forbiddenExtensions -contains $_.Extension.ToLowerInvariant() }

if ($forbiddenFiles) {
    $paths = $forbiddenFiles.FullName -join "`n"
    throw "Release tree contains generated or temporary files:`n$paths"
}

Write-Host "Package layout validation passed: $resolvedRoot"
