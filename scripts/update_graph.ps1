[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot ".."))

$graphify = Get-Command graphify -ErrorAction SilentlyContinue
if ($graphify) {
    & $graphify.Source $repoRoot.Path --update
    exit $LASTEXITCODE
}

$venvPython = Join-Path $repoRoot.Path ".venv\Scripts\python.exe"
if (Test-Path $venvPython) {
    try {
        & $venvPython -c "import graphify" 2>$null
        if ($LASTEXITCODE -eq 0) {
            & $venvPython -m graphify $repoRoot.Path --update
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
        & $python.Source -m graphify $repoRoot.Path --update
        exit $LASTEXITCODE
    }
}

throw "graphify is unavailable. Install project dependencies, then run .\scripts\update_graph.ps1 again."
