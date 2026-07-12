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

    function Add-PortableCandidate {
        param(
            [string]$Path,
            [string]$Reason,
            [int]$Priority
        )

        $normalized = ConvertTo-EddNormalizedPath -Path $Path -BaseDirectory $null
        if (-not $normalized) { return }

        $key = $normalized.ToLowerInvariant()
        $score = Get-EddFolderScore $normalized
        if ($candidateMap.ContainsKey($key)) {
            $existing = $candidateMap[$key]
            if ($Priority -gt $existing.Priority) { $existing.Priority = $Priority }
            if ($score -gt $existing.Score) { $existing.Score = $score }
            if ($existing.Reason -notlike "*$Reason*") { $existing.Reason += "; $Reason" }
            return
        }

        $candidateMap[$key] = [pscustomobject]@{
            Path = $normalized
            Reason = $Reason
            Priority = $Priority
            Score = $score
        }
    }

    $resolvedInstall = $null
    if (-not [string]::IsNullOrWhiteSpace($InstallRoot)) {
        $resolvedInstall = ConvertTo-EddNormalizedPath -Path $InstallRoot -BaseDirectory $null
        if (-not $resolvedInstall) { throw "Invalid EDDiscovery install root: $InstallRoot" }
    }

    $resolvedExecutable = $null
    if (-not [string]::IsNullOrWhiteSpace($Executable)) {
        $resolvedExecutable = ConvertTo-EddNormalizedPath -Path $Executable -BaseDirectory $resolvedInstall
        if (-not $resolvedExecutable) { throw "Invalid EDDiscovery executable path: $Executable" }
        if ((Split-Path -Leaf $resolvedExecutable) -ine 'EDDiscovery.exe') {
            throw "EDDiscovery executable must be named EDDiscovery.exe: $resolvedExecutable"
        }
        if (-not $resolvedInstall) { $resolvedInstall = Split-Path -Parent $resolvedExecutable }
    }

    if ($resolvedInstall) {
        $expectedExecutable = Join-Path $resolvedInstall 'EDDiscovery.exe'
        if (-not $resolvedExecutable) { $resolvedExecutable = $expectedExecutable }
        if (-not (Test-Path -LiteralPath $resolvedExecutable -PathType Leaf)) {
            throw "EDDiscovery.exe was not found in the portable install: $resolvedExecutable"
        }

        $optionsRoot = Get-EddAppFolderFromOptionsDirectory -ExecutableDirectory $resolvedInstall
        if ($optionsRoot) {
            Add-PortableCandidate $optionsRoot.Path "portable options file $($optionsRoot.Source)" 10000
        }

        # Without an explicit -appfolder, all conventional portable locations
        # share a priority. Database and folder evidence decide the active root.
        Add-PortableCandidate $resolvedInstall 'portable executable directory' 9000
        Add-PortableCandidate (Join-Path $resolvedInstall 'EDDiscovery') 'portable data folder beside executable' 9000
        Add-PortableCandidate (Join-Path $resolvedInstall 'Data') 'portable Data folder beside executable' 9000
    }

    $candidates = @($candidateMap.Values)
    $best = $candidates |
        Sort-Object -Property @{ Expression = 'Priority'; Descending = $true }, @{ Expression = 'Score'; Descending = $true }, @{ Expression = 'Path'; Descending = $false } |
        Select-Object -First 1

    if (-not $best) { return Find-EddDataRoot }

    return [pscustomobject]@{
        Path = $best.Path
        Reason = $best.Reason
        Priority = $best.Priority
        Score = $best.Score
        Candidates = $candidates
        InstallRoot = $resolvedInstall
        ExecutablePath = $resolvedExecutable
        Portable = $true
    }
}
