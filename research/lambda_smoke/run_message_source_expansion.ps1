[CmdletBinding()]
param(
    [string]$Out = "output\message_channel_v3_sources",
    [ValidateSet("sources", "probe")][string]$Phase = "sources",
    [ValidateRange(0.01,24)][double]$Hours = 8,
    [ValidateRange(0,300)][int]$PauseSeconds = 30,
    [switch]$KeepAwake
)
$ErrorActionPreference = "Stop"
Set-Location (Resolve-Path (Join-Path $PSScriptRoot "..\.."))
$Python = (Resolve-Path ".\.venv\Scripts\python.exe").Path
$Module = "research.lambda_smoke.message_source_expansion"
if (-not (Test-Path -LiteralPath $Out)) {
    if ($Phase -ne "sources") { throw "Run source acquisition first." }
    & $Python -X utf8 -m $Module --stage plan --out $Out
    if ($LASTEXITCODE -ne 0) { throw "Cannot prepare the acquisition plan." }
}
$Out = (Resolve-Path -LiteralPath $Out).Path
$ControllerPath = Join-Path $Out "controller.json"
if (Test-Path -LiteralPath $ControllerPath) {
    $Controller = Get-Content -LiteralPath $ControllerPath -Raw | ConvertFrom-Json
    $Deadline = [DateTimeOffset]::Parse($Controller.deadline_utc)
} else {
    $Deadline = [DateTimeOffset]::UtcNow.AddHours($Hours)
    @{ deadline_utc = $Deadline.ToString("o") } | ConvertTo-Json |
        Set-Content -LiteralPath "$ControllerPath.tmp" -Encoding UTF8
    Move-Item -LiteralPath "$ControllerPath.tmp" -Destination $ControllerPath
}
if ($KeepAwake) {
    if (-not ("SourceExpansionPower" -as [type])) {
        Add-Type @'
using System;
using System.Runtime.InteropServices;
public static class SourceExpansionPower {
    [DllImport("kernel32.dll")]
    public static extern uint SetThreadExecutionState(uint flags);
}
'@
    }
    if ([SourceExpansionPower]::SetThreadExecutionState(2147483649) -eq 0) {
        throw "Windows refused temporary sleep prevention."
    }
}
try {
    while ($true) {
        $StatusText = & $Python -X utf8 -m $Module --stage status --phase $Phase --out $Out
        if ($LASTEXITCODE -ne 0) { throw "Cannot verify experiment status." }
        $Status = $StatusText | ConvertFrom-Json
        $Status | ConvertTo-Json -Depth 6
        if ($Status.complete) { break }
        if (-not $Status.ready) { throw "Phase is held. Inspect the actual state-selection audit before spending." }
        if ($Status.failed_or_active.Count -gt 0) { throw "Failed or interrupted session retained. No automatic restart." }
        if ($Status.sessions_remaining -le 0) { Write-Host "Frozen session limit reached."; break }
        if ($Status.budget_remaining_usd -lt $Status.next_session_reservation_usd) {
            Write-Host "Resource budget cannot reserve another full session."; break
        }
        if (($Deadline - [DateTimeOffset]::UtcNow).TotalSeconds -lt 4660) {
            Write-Host "Deadline cannot accommodate another bounded session."; break
        }
        & $Python -X utf8 -m $Module --stage batch --phase $Phase --out $Out
        if ($LASTEXITCODE -ne 0) { throw "Batch failed; evidence preserved and Modal host stopped." }
        Start-Sleep -Seconds $PauseSeconds
    }
    if ($Phase -eq "sources" -and $Status.complete) {
        & $Python -X utf8 -m $Module --stage audit --out $Out
        if ($LASTEXITCODE -ne 0) { throw "Source selection audit failed; no probe launched." }
        Write-Host "New source audit and immutable probe plan displayed. Review before running -Phase probe."
    }
    if ($Phase -eq "probe" -and $Status.complete) {
        Write-Host "Expanded v3 factorial completed."
    }
} finally {
    if ($KeepAwake) { [void][SourceExpansionPower]::SetThreadExecutionState(2147483648) }
}
