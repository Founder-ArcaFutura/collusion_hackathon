# Four fresh seed blocks, same factorial, in two sequential bounded hosts.
$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $false
$previousEncoding = [Console]::OutputEncoding
$repoRoot = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
Push-Location $repoRoot
try {
    [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
    $python = Join-Path $repoRoot '.venv/Scripts/python.exe'
    if (-not (Test-Path -LiteralPath $python)) { throw 'Repository Python is missing.' }
    # Do not silently repeat a previously launched seed block.
    $requested = @(22, 23, 24, 25)
    $plans = Get-ChildItem -LiteralPath (Join-Path $repoRoot 'output') -Filter study_plan.json -Recurse -File
    foreach ($file in $plans) {
        $prior = Get-Content -LiteralPath $file.FullName -Raw | ConvertFrom-Json
        if ($prior.backend -eq 'live') {
            foreach ($seed in $requested) {
                if ($prior.seeds -contains $seed) { throw "Seed $seed already appears in $($file.FullName); refusing duplicate paid execution." }
            }
        }
    }
    # Both plans validate locally before the first host starts.
    & $python -X utf8 -m research.endogenous_defection.information_study --stage plan --seeds 22 23
    if ($LASTEXITCODE -ne 0) { throw 'First batch preflight failed.' }
    & $python -X utf8 -m research.endogenous_defection.information_study --stage plan --seeds 24 25
    if ($LASTEXITCODE -ne 0) { throw 'Second batch preflight failed.' }
    Write-Host 'Starting unchanged-design replication: 1,600 decisions, at most 3,200 requests total.'
    Write-Host 'Two sequential A10G batches. Approximately five hours at the observed pace; no completion guarantee.'
    Write-Host 'Each batch prints its output path and writes its own analysis automatically.'
    & $python -X utf8 -m research.endogenous_defection.information_study --stage run --seeds 22 23
    $firstExit = $LASTEXITCODE
    if ($firstExit -ne 0) {
        Write-Host "First batch exited $firstExit. Stopping; second batch will not start. Evidence is retained."
        exit $firstExit
    }
    & $python -X utf8 -m research.endogenous_defection.information_study --stage run --seeds 24 25
    $secondExit = $LASTEXITCODE
    Write-Host "Replication finished with exit code $secondExit. Preserve both printed output directories."
    exit $secondExit
} finally {
    [Console]::OutputEncoding = $previousEncoding
    Pop-Location
}
