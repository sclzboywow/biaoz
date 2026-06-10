function Write-LoopPidFile {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][int]$ProcessId
    )
    $dir = Split-Path -Parent $Path
    if ($dir -and -not (Test-Path $dir)) {
        New-Item -ItemType Directory -Force -Path $dir | Out-Null
    }
    [System.IO.File]::WriteAllText($Path, "$ProcessId")
}

function Read-LoopPidFile {
    param([Parameter(Mandatory = $true)][string]$Path)
    if (-not (Test-Path $Path)) { return $null }
    $raw = [System.IO.File]::ReadAllText($Path).Trim()
    if ($raw -match '^\d+$') { return [int]$raw }
    return $null
}

function Remove-LoopPidFileIfOwned {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][int]$ProcessId
    )
    if ((Read-LoopPidFile -Path $Path) -eq $ProcessId) {
        Remove-Item -Path $Path -Force -ErrorAction SilentlyContinue
    }
}

function Find-LoopProcess {
    param([Parameter(Mandatory = $true)][string]$ScriptPath)
    $needle = [regex]::Escape($ScriptPath)
    Get-CimInstance Win32_Process -Filter "Name='powershell.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -and ($_.CommandLine -match $needle) } |
        Select-Object -First 1
}

function Ensure-LoopPidFile {
    param(
        [Parameter(Mandatory = $true)][string]$PidPath,
        [Parameter(Mandatory = $true)][string]$ScriptPath
    )
    $existingPid = Read-LoopPidFile -Path $PidPath
    if ($null -ne $existingPid -and (Get-Process -Id $existingPid -ErrorAction SilentlyContinue)) {
        return $existingPid
    }

    $proc = Find-LoopProcess -ScriptPath $ScriptPath
    if ($proc) {
        Write-LoopPidFile -Path $PidPath -ProcessId $proc.ProcessId
        return $proc.ProcessId
    }
    return $null
}
