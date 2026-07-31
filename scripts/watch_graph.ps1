[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot ".."))

$graphify = Get-Command graphify -ErrorAction SilentlyContinue
if ($graphify) {
    & $graphify.Source watch $repoRoot.Path
    exit $LASTEXITCODE
}

$venvPython = Join-Path $repoRoot.Path ".venv\Scripts\python.exe"
if (Test-Path $venvPython) {
    try {
        & $venvPython -c "import graphify" 2>$null
        if ($LASTEXITCODE -eq 0) {
            & $venvPython -m graphify watch $repoRoot.Path
            exit $LASTEXITCODE
        }
    } catch {
        # Fall through to a PATH-provided Python with graphify installed.
    }
}

$python = Get-Command python -ErrorAction SilentlyContinue
if ($python) {
    & $python.Source -c "import graphify" 2>$null
    if ($LASTEXITCODE -eq 0) {
        & $python.Source -m graphify watch $repoRoot.Path
        exit $LASTEXITCODE
    }
}

throw "graphify is unavailable. Install project dependencies, then run .\scripts\watch_graph.ps1 again."
