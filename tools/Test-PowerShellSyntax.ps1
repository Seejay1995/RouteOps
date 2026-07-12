[CmdletBinding()]
param(
    [Parameter()]
    [string] $Root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$files = Get-ChildItem -LiteralPath $Root -Recurse -File -Filter '*.ps1' |
    Where-Object { $_.FullName -notmatch '[\\/]\.git[\\/]' }

$failures = [System.Collections.Generic.List[string]]::new()

foreach ($file in $files) {
    $tokens = $null
    $errors = $null

    [void][System.Management.Automation.Language.Parser]::ParseFile(
        $file.FullName,
        [ref] $tokens,
        [ref] $errors
    )

    foreach ($parseError in $errors) {
        $failures.Add(
            ('{0}:{1}:{2}: {3}' -f `
                $file.FullName,
                $parseError.Extent.StartLineNumber,
                $parseError.Extent.StartColumnNumber,
                $parseError.Message)
        )
    }
}

if ($failures.Count -gt 0) {
    Write-Error ("PowerShell parsing failed:`n" + ($failures -join "`n"))
    exit 1
}

Write-Host ("PowerShell syntax passed for {0} file(s)." -f $files.Count)
