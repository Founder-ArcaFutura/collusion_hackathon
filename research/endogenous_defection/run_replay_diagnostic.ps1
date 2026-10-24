param(
    [string]$Source = 'research/endogenous_defection/results/factorial_3x5_comms_off_v4_guided_2048'
)

$ErrorActionPreference = 'Stop'
$previousConsoleOutputEncoding = [Console]::OutputEncoding
$repoRoot = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
Push-Location $repoRoot
try {
    # Windows PowerShell 5 also uses this to decode native piped stdout.
    [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
    $python = Join-Path $repoRoot '.venv/Scripts/python.exe'
    if (-not (Test-Path -LiteralPath $python)) { throw 'Repository .venv Python is missing.' }
    $runId = (Get-Date -Format 'yyyyMMdd_HHmmss') + '_' + [guid]::NewGuid().ToString('N').Substring(0, 8)
    $runRoot = Join-Path $repoRoot ('output/replay_diagnostic_' + $runId)
    $probeOut = Join-Path $runRoot 'probe'
    # Validate sealed evidence and all bounds before any Modal startup.
    $planLines = & $python -X utf8 -m research.endogenous_defection.replay_diagnostic --stage plan --source $Source --out $probeOut
    if ($LASTEXITCODE -ne 0) { throw 'Local diagnostic preflight failed; Modal was not started.' }
    $plan = ($planLines -join "`n") | ConvertFrom-Json
    New-Item -ItemType Directory -Path $runRoot -ErrorAction Stop | Out-Null
    $planLines | Set-Content -LiteralPath (Join-Path $runRoot 'preflight.json') -Encoding utf8
    Write-Host 'Preflight passed. Four requests, maximum 2,048 completion tokens each, no retries, no market rounds.'
    Write-Host ('Output: ' + $runRoot)
    Write-Host 'Starting one ephemeral A10G host. Server/startup logs will be saved to host.log.'
    $hostLog = Join-Path $runRoot 'host.log'
    # Native stderr is included in the transcript. Keep the native exit code,
    # including expected diagnostic exit 2, rather than terminating on log lines.
    $ErrorActionPreference = 'Continue'
    $PSNativeCommandUseErrorActionPreference = $false
    # Redirected Python on Windows otherwise defaults to cp1252. Modal/Rich
    # prints Unicode status symbols; both parent and replay must use UTF-8.
    # Import the CLI entry point directly: package __init__ already imports
    # hosted_model, so running that same module via -m produces a runpy warning.
    & $python -X utf8 -c 'from poseidon_compute.hosted_model import main; main()' --model $plan.model --gpu A10G --ready-timeout 600 --run-timeout 480 -- $python -X utf8 -m research.endogenous_defection.replay_diagnostic --stage live --source $Source --out $probeOut 2>&1 | Tee-Object -FilePath $hostLog
    $hostExitCode = $LASTEXITCODE
    $ErrorActionPreference = 'Stop'
    Write-Host ('Host exit code: ' + $hostExitCode)
    Write-Host ('Full server/client log: ' + $hostLog)
    $summaryPath = Join-Path $probeOut 'diagnostic_summary.json'
    if (Test-Path -LiteralPath $summaryPath) {
        $summary = Get-Content -LiteralPath $summaryPath -Raw | ConvertFrom-Json
        $summary.cases | Select-Object case, accepted, response_received, elapsed_seconds, finish_reason, error_type | Format-Table -AutoSize
        Write-Host ('Diagnostic status: ' + $summary.status)
        Write-Host ('Summary: ' + $summaryPath)
        Write-Host 'Exit 2 means at least one fixed diagnostic case was rejected or timed out; the evidence is retained.'
    } else {
        Write-Host 'No diagnostic summary: the host or preflight failed before replay. Inspect host.log.'
    }
    exit $hostExitCode
} finally {
    [Console]::OutputEncoding = $previousConsoleOutputEncoding
    Pop-Location
}
