Set-StrictMode -Version 2.0

function ConvertTo-EddNormalizedPath {
    param(
        [string]$Path,
        [string]$BaseDirectory
    )

    if ([string]::IsNullOrWhiteSpace($Path)) { return $null }

    $expanded = [Environment]::ExpandEnvironmentVariables($Path.Trim().Trim('"'))
    try {
        if (-not [System.IO.Path]::IsPathRooted($expanded) -and -not [string]::IsNullOrWhiteSpace($BaseDirectory)) {
            $expanded = Join-Path $BaseDirectory $expanded
        }
        return [System.IO.Path]::GetFullPath($expanded)
    }
    catch {
        return $null
    }
}

function Get-EddAppFolderFromCommandLine {
    param(
        [string]$CommandLine,
        [string]$ExecutableDirectory
    )

    if ([string]::IsNullOrWhiteSpace($CommandLine)) { return $null }

    $match = [regex]::Match(
        $CommandLine,
        '(?i)(?:^|\s)-appfolder(?:\s+|=)(?:"([^"]+)"|([^\s]+))'
    )

    if (-not $match.Success) { return $null }

    $value = if ($match.Groups[1].Success) { $match.Groups[1].Value } else { $match.Groups[2].Value }
    return ConvertTo-EddNormalizedPath -Path $value -BaseDirectory $ExecutableDirectory
}

function Get-EddAppFolderFromOptionsDirectory {
    param([string]$ExecutableDirectory)

    if ([string]::IsNullOrWhiteSpace($ExecutableDirectory) -or -not (Test-Path $ExecutableDirectory)) {
        return $null
    }

    $resolved = $null
    $source = $null

    $optionFiles = Get-ChildItem -Path $ExecutableDirectory -Filter 'options*.txt' -File -ErrorAction SilentlyContinue |
        Sort-Object FullName

    foreach ($file in $optionFiles) {
        foreach ($line in (Get-Content -Path $file.FullName -ErrorAction SilentlyContinue)) {
            $clean = $line.Trim()
            if ($clean.Length -eq 0 -or $clean.StartsWith('#') -or $clean.StartsWith('//')) { continue }

            $match = [regex]::Match(
                $clean,
                '(?i)^-appfolder(?:\s+|=)(?:"([^"]+)"|(.+?))\s*$'
            )

            if ($match.Success) {
                $value = if ($match.Groups[1].Success) { $match.Groups[1].Value } else { $match.Groups[2].Value.Trim() }
                $candidate = ConvertTo-EddNormalizedPath -Path $value -BaseDirectory $ExecutableDirectory
                if ($candidate) {
                    $resolved = $candidate
                    $source = $file.FullName
                }
            }
        }
    }

    if (-not $resolved) { return $null }

    return [pscustomobject]@{
        Path = $resolved
        Source = $source
    }
}

function Get-EddRunningProcesses {
    $results = New-Object 'System.Collections.Generic.List[object]'

    try {
        Get-CimInstance Win32_Process -Filter "Name='EDDiscovery.exe'" -ErrorAction Stop | ForEach-Object {
            $results.Add([pscustomobject]@{
                ProcessId = $_.ProcessId
                ExecutablePath = $_.ExecutablePath
                CommandLine = $_.CommandLine
            })
        }
    }
    catch {
        Get-Process -Name 'EDDiscovery' -ErrorAction SilentlyContinue | ForEach-Object {
            try {
                $results.Add([pscustomobject]@{
                    ProcessId = $_.Id
                    ExecutablePath = $_.Path
                    CommandLine = $null
                })
            }
            catch { }
        }
    }

    return $results
}

function Get-EddExecutableCandidates {
    $paths = New-Object 'System.Collections.Generic.List[string]'

    function Add-ExecutablePath {
        param([string]$Candidate)
        if ([string]::IsNullOrWhiteSpace($Candidate)) { return }
        $normalized = ConvertTo-EddNormalizedPath -Path $Candidate -BaseDirectory $null
        if (-not $normalized -or -not (Test-Path $normalized -PathType Leaf)) { return }
        if (-not ($paths | Where-Object { $_ -ieq $normalized })) { $paths.Add($normalized) }
    }

    foreach ($proc in (Get-EddRunningProcesses)) {
        Add-ExecutablePath $proc.ExecutablePath
    }

    foreach ($candidate in @(
        (Join-Path $env:ProgramFiles 'EDDiscovery\EDDiscovery.exe'),
        $(if (${env:ProgramFiles(x86)}) { Join-Path ${env:ProgramFiles(x86)} 'EDDiscovery\EDDiscovery.exe' }),
        (Join-Path $env:LOCALAPPDATA 'Programs\EDDiscovery\EDDiscovery.exe')
    )) {
        Add-ExecutablePath $candidate
    }

    foreach ($drive in (Get-PSDrive -PSProvider FileSystem -ErrorAction SilentlyContinue)) {
        foreach ($relative in @(
            'EDDiscovery\EDDiscovery.exe',
            'Games\EDDiscovery\EDDiscovery.exe',
            'Gaming\EDDiscovery\EDDiscovery.exe'
        )) {
            Add-ExecutablePath (Join-Path $drive.Root $relative)
        }
    }

    foreach ($registryPath in @(
        'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*',
        'HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*',
        'HKLM:\Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*'
    )) {
        Get-ItemProperty $registryPath -ErrorAction SilentlyContinue |
            Where-Object {
                $displayNameProperty = $_.PSObject.Properties['DisplayName']
                $displayNameProperty -and $displayNameProperty.Value -like '*EDDiscovery*'
            } |
            ForEach-Object {
                $installLocationProperty = $_.PSObject.Properties['InstallLocation']
                if ($installLocationProperty -and -not [string]::IsNullOrWhiteSpace([string]$installLocationProperty.Value)) {
                    Add-ExecutablePath (Join-Path ([string]$installLocationProperty.Value) 'EDDiscovery.exe')
                }

                $displayIconProperty = $_.PSObject.Properties['DisplayIcon']
                if ($displayIconProperty -and -not [string]::IsNullOrWhiteSpace([string]$displayIconProperty.Value)) {
                    $iconPath = (([string]$displayIconProperty.Value) -split ',')[0].Trim('"')
                    Add-ExecutablePath $iconPath
                }
            }
    }

    return $paths
}

function Get-EddFolderScore {
    param([string]$Path)

    $score = 0
    if (Test-Path (Join-Path $Path 'EDDUser.sqlite')) { $score += 100 }
    if (Test-Path (Join-Path $Path 'EDDSystem.sqlite')) { $score += 80 }
    if (Test-Path (Join-Path $Path 'Actions')) { $score += 30 }
    if (Test-Path (Join-Path $Path 'Expeditions')) { $score += 15 }
    if (Test-Path (Join-Path $Path 'Log')) { $score += 10 }
    if (Test-Path (Join-Path $Path 'Plugins')) { $score += 5 }
    return $score
}

function Find-EddDataRoot {
    param([string]$Requested)

    if (-not [string]::IsNullOrWhiteSpace($Requested)) {
        $explicit = ConvertTo-EddNormalizedPath -Path $Requested -BaseDirectory $null
        if (-not $explicit) { throw "Invalid EDDiscovery data root: $Requested" }
        return [pscustomobject]@{
            Path = $explicit
            Reason = 'explicit -EddDataRoot parameter'
            Priority = 10000
            Score = (Get-EddFolderScore $explicit)
            Candidates = @()
        }
    }

    $candidateMap = @{}

    function Add-DataCandidate {
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
        }
        else {
            $candidateMap[$key] = [pscustomobject]@{
                Path = $normalized
                Reason = $Reason
                Priority = $Priority
                Score = $score
            }
        }
    }

    if ($env:EDD_APPDATA) {
        Add-DataCandidate $env:EDD_APPDATA 'EDD_APPDATA environment variable' 6000
    }

    $running = Get-EddRunningProcesses
    foreach ($proc in $running) {
        if (-not $proc.ExecutablePath) { continue }
        $exeDir = Split-Path -Parent $proc.ExecutablePath

        $commandRoot = Get-EddAppFolderFromCommandLine -CommandLine $proc.CommandLine -ExecutableDirectory $exeDir
        if ($commandRoot) {
            Add-DataCandidate $commandRoot "running EDDiscovery PID $($proc.ProcessId) command line -appfolder" 9000
        }

        $optionsRoot = Get-EddAppFolderFromOptionsDirectory -ExecutableDirectory $exeDir
        if ($optionsRoot) {
            Add-DataCandidate $optionsRoot.Path "running EDDiscovery options file $($optionsRoot.Source)" 8500
        }

        Add-DataCandidate $exeDir "running EDDiscovery executable folder $exeDir" 500
        Add-DataCandidate (Join-Path $exeDir 'EDDiscovery') "portable data folder beside running EDDiscovery" 500
    }

    foreach ($exe in (Get-EddExecutableCandidates)) {
        $exeDir = Split-Path -Parent $exe
        $optionsRoot = Get-EddAppFolderFromOptionsDirectory -ExecutableDirectory $exeDir
        if ($optionsRoot) {
            Add-DataCandidate $optionsRoot.Path "options file $($optionsRoot.Source)" 7500
        }
        Add-DataCandidate $exeDir "EDDiscovery executable folder $exeDir" 300
        Add-DataCandidate (Join-Path $exeDir 'EDDiscovery') "portable data folder beside $exeDir" 300
    }

    Add-DataCandidate (Join-Path $env:LOCALAPPDATA 'EDDiscovery') 'default LocalAppData location' 100
    Add-DataCandidate (Join-Path $env:APPDATA 'EDDiscovery') 'legacy Roaming AppData location' 50

    foreach ($base in @($env:LOCALAPPDATA, $env:APPDATA)) {
        if (-not $base -or -not (Test-Path $base)) { continue }
        Get-ChildItem -Path $base -Directory -ErrorAction SilentlyContinue | ForEach-Object {
            if ((Test-Path (Join-Path $_.FullName 'EDDUser.sqlite')) -or
                (Test-Path (Join-Path $_.FullName 'EDDSystem.sqlite'))) {
                Add-DataCandidate $_.FullName 'database discovered under AppData' 200
            }
        }
    }

    $candidates = @($candidateMap.Values)
    $best = $candidates |
        Sort-Object -Property @{ Expression = 'Priority'; Descending = $true }, @{ Expression = 'Score'; Descending = $true }, @{ Expression = 'Path'; Descending = $false } |
        Select-Object -First 1

    if (-not $best) {
        $fallback = Join-Path $env:LOCALAPPDATA 'EDDiscovery'
        return [pscustomobject]@{
            Path = $fallback
            Reason = 'fallback default LocalAppData location'
            Priority = 0
            Score = 0
            Candidates = @()
        }
    }

    return [pscustomobject]@{
        Path = $best.Path
        Reason = $best.Reason
        Priority = $best.Priority
        Score = $best.Score
        Candidates = $candidates
    }
}
