Set-StrictMode -Version 2.0

function Find-EddPortableDataRoot {
    param(
        [string]$Requested,
        [string]$InstallRoot,
        [string]$Executable
    )

    if (-not [string]::IsNullOrWhiteSpace($Requested)) {
        return Find-EddDataRoot -Requested $Requested
    }

    if ([string]::IsNullOrWhiteSpace($InstallRoot) -and
        [string]::IsNullOrWhiteSpace($Executable)) {
        return Find-EddDataRoot
    }

    $candidateMap = @{}

    function Add-Portable