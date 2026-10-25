[CmdletBinding()]
param(
    [string]$Out = "output\message_channel_modal_v2",
    [string]$Python = ".\.venv\Scripts\python.exe",
    [ValidateRange(0.01, 24)][double]$Hours = 8,
    [ValidateRange(1, 1000)][int]$MaxDecisions = 100,
    [ValidateRange(1200, 10800)][int]$MaxSessionSeconds = 5400,
    [ValidateRange(0, 300)][int]$PauseSeconds = 30,
    [switch]$KeepAwake
)
$ErrorActionPreference = "Stop"
Set-Location (Resolve-Path (Join-Path $PSScriptRoot "..\.."))
$Module = "research.lambda_smoke.message_channel_overnight"
$Out = (Resolve-Path -LiteralPath $Out).Path
$Python = (Resolve-Path -LiteralPath $Python).Path
$ControllerPath = Join-Path $Out "controller.json"

function Read-ProbeStatus {
    $statusText = & $Python -X utf8 -m $Module --stage status --out $Out
    if ($LASTEXITCODE -ne 0) { throw "Cannot verify experiment status; stopping." }
    return ($statusText | ConvertFrom-Json)
}

# The first deadline persists across PowerShell restarts. Hours does not extend it.
if (Test-Path -LiteralPath $ControllerPath) {
    $Controller = Get-Content -LiteralPath $ControllerPath -Raw | ConvertFrom-Json
    $Deadline = [DateTimeOffset]::Parse($Controller.deadline_utc)
} else {
    $Deadline = [DateTimeOffset]::UtcNow.AddHours($Hours)
    $Controller = @{ deadline_utc = $Deadline.ToString("o") }
    $Controller | ConvertTo-Json | Set-Content -LiteralPath "$ControllerPath.tmp" -Encoding UTF8
    Move-Item -LiteralPath "$ControllerPath.tmp" -Destination $ControllerPath
}

if ($KeepAwake) {
    if (-not ("ProbePower" -as [type])) {
        Add-Type @'
using System;
using System.Runtime.InteropServices;
public static class ProbePower {
    [DllImport("kernel32.dll")]
    public static extern uint SetThreadExecutionState(uint flags);
}
'@
    }
    if ([ProbePower]::SetThreadExecutionState(2147483649) -eq 0) {
        throw "Windows refused the temporary sleep-prevention request."
    }
}

try {
    while ($true) {
        $Status = Read-ProbeStatus
        if ($Status.complete) { Write-Host "All planned decisions completed."; break }
        if ($Status.blocked_decisions.Count -gt 0 -or $Status.failed_or_active_sessions.Count -gt 0) {
            throw "A failed or interrupted session needs evidence review. No automatic retries."
        }
        if ($Status.sessions_remaining -le 0) { Write-Host "Frozen session budget exhausted."; break }
        # Reserve cold start (600 seconds) and host cleanup (60 seconds).
        $Remaining = [int][Math]::Floor(($Deadline - [DateTimeOffset]::UtcNow).TotalSeconds) - 660
        $SessionSeconds = [int][Math]::Min($MaxSessionSeconds, $Remaining)
        if ($SessionSeconds -lt 1200) { Write-Host "Overnight deadline reached; no further session started."; break }
        Write-Host "Starting session $($Status.sessions_started + 1); $($Status.remaining_decisions) decisions remain."
        & $Python -X utf8 -m $Module --stage batch --out $Out `
            --max-decisions $MaxDecisions --max-session-seconds $SessionSeconds
        if ($LASTEXITCODE -ne 0) { throw "Modal batch failed. Evidence preserved; controller stopped." }
        $Status = Read-ProbeStatus
        if ($Status.complete) { Write-Host "All planned decisions completed."; break }
        # Batch returned after the attached Modal host exited; pause is local.
        Start-Sleep -Seconds $PauseSeconds
    }
    $Status | ConvertTo-Json -Depth 4
} finally {
    if ($KeepAwake) { [void][ProbePower]::SetThreadExecutionState(2147483648) }
}
