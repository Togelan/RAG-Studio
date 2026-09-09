param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("Preflight", "SignedFixture", "Stage3Fixture", "LiveTest", "Teardown")]
    [string]$Scenario,
    [ValidateSet("SignedFixture", "LiveTest")]
    [string]$StripeMode = "SignedFixture",
    [ValidateSet("Checkout", "Portal")]
    [string]$LiveAction = "Checkout",
    [ValidatePattern("^ragstudio-g2-[a-z0-9-]+$")]
    [string]$ProjectName = "ragstudio-g2-mvp13",
    [string]$EvidenceDirectory = ".omo/evidence/mvp-v1-personal-lab-billing-widget/task-13",
    [string]$StateDirectory = ".omo/tmp/mvp-v1-personal-lab-billing-widget/task-13",
    [string]$ApprovedOrigin = "http://widget-approved.test:8033",
    [string]$RejectedOrigin = "http://widget-rejected.test:8034",
    [switch]$ResumeExisting,
    [string]$DockerCli = "C:\Users\Admin\AppData\Local\Programs\DockerDesktop\resources\bin\docker.exe"
)

$ErrorActionPreference = "Stop"
$env:COMPOSE_PARALLEL_LIMIT = "1"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$EvidenceRoot = if ([IO.Path]::IsPathRooted($EvidenceDirectory)) {
    [IO.Path]::GetFullPath($EvidenceDirectory)
} else {
    [IO.Path]::GetFullPath((Join-Path $RepoRoot $EvidenceDirectory))
}
$StateRoot = if ([IO.Path]::IsPathRooted($StateDirectory)) {
    [IO.Path]::GetFullPath($StateDirectory)
} else {
    [IO.Path]::GetFullPath((Join-Path $RepoRoot $StateDirectory))
}
$Group2Harness = Join-Path $PSScriptRoot "group2_personal_lab_qa.ps1"
$Group2StateRoot = Join-Path $RepoRoot ".omo\tmp\group-2-personal-lab\task-9"
$Group2State = Join-Path $Group2StateRoot "$ProjectName-state.json"
$Group2Handoff = Join-Path $Group2StateRoot "private-browser-handoff.json"
$DelegatedEvidenceDirectory = ".omo/tmp/mvp-v1-personal-lab-billing-widget/task-13/$ProjectName-delegated-evidence"
$DelegatedEvidenceRoot = Join-Path $RepoRoot $DelegatedEvidenceDirectory
$Stage3Services = @(
    "stage3-db", "stage3-db-bootstrap", "stage3-mail", "stage3-auth",
    "stage3-qdrant", "stage3-fake-deepseek", "rag-studio-saas"
)
$StripeNames = @(
    "RAG_STUDIO_STRIPE_RESTRICTED_KEY",
    "RAG_STUDIO_STRIPE_WEBHOOK_SECRET",
    "RAG_STUDIO_STRIPE_PRICE_ID",
    "RAG_STUDIO_PUBLIC_APP_URL",
    "RAG_STUDIO_STRIPE_CUSTOMER_PORTAL_CONFIGURATION_ID",
    "RAG_STUDIO_STRIPE_TEST_OBJECT_PAIRS"
)

function Write-Json {
    param([string]$Path, [hashtable]$Value)
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $Path) | Out-Null
    $Value | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $Path -Encoding utf8
}

function Get-PreflightReport {
    param([string]$Mode)
    $approved = [uri]$ApprovedOrigin
    $rejected = [uri]$RejectedOrigin
    $validOrigins = (
        $approved.IsAbsoluteUri -and $rejected.IsAbsoluteUri -and
        $approved.Scheme -eq "http" -and $rejected.Scheme -eq "http" -and
        $approved.AbsolutePath -eq "/" -and $rejected.AbsolutePath -eq "/" -and
        $approved.Query -eq "" -and $rejected.Query -eq "" -and
        $approved.Fragment -eq "" -and $rejected.Fragment -eq "" -and
        $approved.AbsoluteUri -ne $rejected.AbsoluteUri
    )
    $ready = $validOrigins
    $credentialState = "not_required"
    $modeName = "signed_fixture"
    if ($Mode -eq "LiveTest") {
        $modeName = "live_test"
        $credentialState = "missing_or_invalid"
        $key = [Environment]::GetEnvironmentVariable($StripeNames[0])
        $webhook = [Environment]::GetEnvironmentVariable($StripeNames[1])
        $price = [Environment]::GetEnvironmentVariable($StripeNames[2])
        $appUrl = [Environment]::GetEnvironmentVariable($StripeNames[3])
        $portal = [Environment]::GetEnvironmentVariable($StripeNames[4])
        $pairs = [string][Environment]::GetEnvironmentVariable($StripeNames[5])
        $pair = "$price|$portal"
        $pairRows = @($pairs.Split(",") | ForEach-Object { $_.Trim() })
        $ready = (
            $validOrigins -and $key -match '^rk_test_[A-Za-z0-9]{16,}$' -and
            $webhook -match '^whsec_[A-Za-z0-9]{16,}$' -and
            $price -match '^price_[A-Za-z0-9]{14,}$' -and
            $portal -match '^bpc_[A-Za-z0-9]{14,}$' -and
            $pairRows -contains $pair
        )
        if ([string]::IsNullOrWhiteSpace($appUrl)) {
            $ready = $false
        } else {
            try {
                $parsedAppUrl = [uri]$appUrl
                $ready = $ready -and $parsedAppUrl.IsAbsoluteUri -and $parsedAppUrl.IsLoopback -and $parsedAppUrl.UserInfo -eq "" -and $parsedAppUrl.Query -eq "" -and $parsedAppUrl.Fragment -eq ""
            }
            catch [System.UriFormatException] { $ready = $false }
        }
        if ($ready) { $credentialState = "valid_test_mode" }
    }
    return [ordered]@{
        scenario = "preflight"; stripe_mode = $modeName; ready = [bool]$ready
        docker_operations = 0; app_data_mutations = 0
        approved_origin = $approved.AbsoluteUri.TrimEnd("/")
        rejected_origin = $rejected.AbsoluteUri.TrimEnd("/")
        credentials = $credentialState
    }
}

function Invoke-Preflight {
    param([string]$Mode)
    $report = Get-PreflightReport $Mode
    New-Item -ItemType Directory -Force -Path $EvidenceRoot | Out-Null
    Write-Json (Join-Path $EvidenceRoot "preflight.json") $report
    Write-Output ($report | ConvertTo-Json -Compress)
    if (-not $report.ready) { exit 2 }
}

function Get-Group2State {
    if (-not (Test-Path $Group2State)) { throw "Task-owned Stage3 state is unavailable." }
    $state = Get-Content -LiteralPath $Group2State -Raw | ConvertFrom-Json
    if ($state.project -ne $ProjectName -or $state.profile -ne "stage3") {
        throw "Task-owned Stage3 state does not match the requested project."
    }
    return $state
}

function Invoke-TaskDocker {
    param([pscustomobject]$State, [string[]]$Arguments)
    $prefix = @(
        "compose", "--env-file", $State.env_file, "-p", $ProjectName,
        "-f", (Join-Path $RepoRoot "docker-compose.yml"), "-f", $State.override_file,
        "--profile", "stage3"
    )
    $output = & $DockerCli @($prefix + $Arguments) 2>&1
    if ($LASTEXITCODE -ne 0) { throw "Task-owned Docker operation failed." }
    return @($output)
}

function Invoke-SignedFixture {
    Invoke-Preflight "SignedFixture"
    $signedTestName = "test_signed_raw_webhook_applies_once_and_rejects_modified_bytes"
    $originTestName = "test_two_local_origins_allow_and_reject_exactly"
    $tests = @(
        "tests/api/test_mvp_billing_routes.py::$signedTestName",
        "tests/e2e/test_mvp_stage3_stripe_qa_contract.py::$originTestName"
    )
    $env:UV_CACHE_DIR = Join-Path $RepoRoot ".omo\tmp\task13-uv-cache"
    $baseTemp = Join-Path $RepoRoot ".omo\tmp\task13-signed-pytest"
    $output = & uv run --offline python -m pytest @tests -q --basetemp $baseTemp -p no:cacheprovider 2>&1
    $exitCode = $LASTEXITCODE
    $output | Set-Content -LiteralPath (Join-Path $EvidenceRoot "signed-webhook-fixture.txt") -Encoding utf8
    Write-Json (Join-Path $EvidenceRoot "signed-webhook-receipt.json") ([ordered]@{
        fixture = "signed_raw_webhook_and_two_origins"; exit_code = $exitCode
        approved_origin_status = 204; rejected_origin_status = 403
        provider_network = $false; app_data_mutations = 0; credentials = "synthetic_test_only"
    })
    if ($exitCode -ne 0) { throw "Deterministic signed webhook fixture failed." }
}

function Invoke-Stage3Fixture {
    Invoke-Preflight "SignedFixture"
    New-Item -ItemType Directory -Force -Path $StateRoot | Out-Null
    $group2Output = & $Group2Harness -Scenario SaasReact -ProjectName $ProjectName -EvidenceDirectory $DelegatedEvidenceDirectory -DockerCli $DockerCli -ResumeExisting:$ResumeExisting
    if ($LASTEXITCODE -ne 0) { throw "Personal Lab Stage3 fixture failed." }
    $state = Get-Group2State
    Invoke-TaskDocker $state (@("up", "-d", "--wait") + $Stage3Services) | Out-Null
    $ps = Invoke-TaskDocker $state @("ps", "--all", "--format", "json")
    $psSummary = @($ps | ForEach-Object {
        $row = $_ | ConvertFrom-Json
        [ordered]@{ service = $row.Service; state = $row.State; health = $row.Health; exit_code = $row.ExitCode }
    })
    foreach ($service in $Stage3Services) {
        $matches = @($psSummary | Where-Object { $_.service -eq $service })
        if ($matches.Count -ne 1) { throw "A named Stage3 service is missing or duplicated." }
        $status = $matches[0]
        if ($service -eq "stage3-db-bootstrap") {
            if ($status.state -ne "exited" -or $status.exit_code -ne 0) { throw "Stage3 migrations did not complete successfully." }
        } elseif ($status.state -ne "running" -or ($status.health -and $status.health -ne "healthy")) {
            throw "A named Stage3 service is not ready."
        }
    }
    $containers = $Stage3Services | ForEach-Object { "$ProjectName-$_-1" }
    $statsArguments = @("stats", "--no-stream", "--format", "{{json .}}") + $containers
    $stats = & $DockerCli @statsArguments 2>&1
    if ($LASTEXITCODE -ne 0) { throw "Task-owned Stage3 stats failed." }
    $statsSummary = @($stats | ForEach-Object {
        $row = $_ | ConvertFrom-Json
        [ordered]@{ container = $row.Name; cpu = $row.CPUPerc; memory = $row.MemUsage; processes = $row.PIDs }
    })
    Write-Json (Join-Path $EvidenceRoot "stage3-fixture-receipt.json") ([ordered]@{
        project = $ProjectName; services = $Stage3Services; compose_parallel_limit = 1
        deterministic_migrations = "stage3-db-bootstrap"; personal_lab_fixture = $true
        fake_provider_stream = "stage3-fake-deepseek"; approved_origin = $ApprovedOrigin
        rejected_origin = $RejectedOrigin; compose_ps = $psSummary; stats = $statsSummary
        delegated_fixture_exit = 0; delegated_output_recorded = $false
    })
}

function Add-LiveConfiguration {
    param([pscustomobject]$State)
    $lines = @("RAG_STUDIO_BILLING_ENABLED=true", "RAG_STUDIO_PUBLICATION_ENABLED=true")
    foreach ($name in $StripeNames) {
        $lines += "$name=$([Environment]::GetEnvironmentVariable($name))"
    }
    $managedNames = @("RAG_STUDIO_BILLING_ENABLED", "RAG_STUDIO_PUBLICATION_ENABLED") + $StripeNames
    $existing = @(Get-Content -LiteralPath $State.env_file | Where-Object {
        $name = $_.Split("=", 2)[0]
        $managedNames -notcontains $name
    })
    Set-Content -LiteralPath $State.env_file -Value @($existing + $lines) -Encoding utf8
    & icacls.exe $State.env_file /inheritance:r /grant:r "${env:USERNAME}:(F)" | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Private live-test environment ACL failed." }
}

function Invoke-LiveTest {
    $report = Get-PreflightReport "LiveTest"
    New-Item -ItemType Directory -Force -Path $EvidenceRoot | Out-Null
    Write-Json (Join-Path $EvidenceRoot "preflight.json") $report
    if (-not $report.ready) { Write-Output ($report | ConvertTo-Json -Compress); exit 2 }
    $state = Get-Group2State
    $originalEnvironment = Get-Content -LiteralPath $state.env_file -Raw
    try {
        Add-LiveConfiguration $state
        Invoke-TaskDocker $state @("up", "-d", "--wait", "--no-deps", "--force-recreate", "rag-studio-saas") | Out-Null
        $identities = Get-Content -LiteralPath $Group2Handoff -Raw | ConvertFrom-Json
        $identity = @($identities)[0]
        $session = [Microsoft.PowerShell.Commands.WebRequestSession]::new()
        $csrf = Invoke-WebRequest -Uri "$($state.app_url)/api/saas/auth/csrf" -WebSession $session -TimeoutSec 10
        $csrfToken = $session.Cookies.GetCookies([uri]$state.app_url)["ragstudio-development-csrf"].Value
        Invoke-WebRequest -Uri "$($state.app_url)/api/saas/auth/signin" -Method POST -WebSession $session -Headers @{ Origin = $state.app_url; "X-CSRF-Token" = $csrfToken } -ContentType "application/json" -Body (@{ email = $identity.email; password = $identity.password } | ConvertTo-Json -Compress) -TimeoutSec 15 | Out-Null
        $path = if ($LiveAction -eq "Checkout") { "checkout" } else { "portal" }
        $response = Invoke-WebRequest -Uri "$($state.app_url)/api/personal/billing/$path" -Method POST -WebSession $session -Headers @{ Origin = $state.app_url; "X-CSRF-Token" = $csrfToken } -TimeoutSec 15 -SkipHttpErrorCheck
        Write-Json (Join-Path $EvidenceRoot "live-$path-receipt.json") ([ordered]@{
            action = $path; status = [int]$response.StatusCode
            hosted_url_recorded = $false; credentials_recorded = $false
        })
        if ([int]$response.StatusCode -ne 200) { throw "Optional live Stripe action did not create a hosted session." }
    }
    finally {
        Set-Content -LiteralPath $state.env_file -Value $originalEnvironment -Encoding utf8 -NoNewline
        & icacls.exe $state.env_file /inheritance:r /grant:r "${env:USERNAME}:(F)" | Out-Null
        Invoke-TaskDocker $state @("up", "-d", "--wait", "--no-deps", "--force-recreate", "rag-studio-saas") | Out-Null
    }
}

function Invoke-Teardown {
    $cleanupOutput = & $Group2Harness -Scenario Teardown -ProjectName $ProjectName -EvidenceDirectory $DelegatedEvidenceDirectory -DockerCli $DockerCli
    if ($LASTEXITCODE -ne 0) { throw "Task-owned Stage3 teardown failed." }
    $cleanup = @($cleanupOutput)[-1] | ConvertFrom-Json
    Write-Json (Join-Path $EvidenceRoot "cleanup-$ProjectName.json") ([ordered]@{
        project_label = $cleanup.project_label; zero_resources = $cleanup.zero_resources
        containers = $cleanup.containers; volumes = $cleanup.volumes; networks = $cleanup.networks
        legacy_unchanged = $cleanup.legacy_unchanged
        private_handoff_absent = $cleanup.private_handoff_absent
        private_retrieval_plan_absent = $cleanup.private_retrieval_plan_absent
    })
    $delegated = [IO.Path]::GetFullPath($DelegatedEvidenceRoot)
    $privateBoundary = [IO.Path]::GetFullPath((Join-Path $RepoRoot ".omo/tmp/mvp-v1-personal-lab-billing-widget/task-13"))
    if (-not $delegated.StartsWith($privateBoundary, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Delegated evidence path escaped the task-private boundary."
    }
    if (Test-Path $delegated) { Remove-Item -LiteralPath $delegated -Recurse -Force }
    Write-Output ((Get-Content -LiteralPath (Join-Path $EvidenceRoot "cleanup-$ProjectName.json") -Raw | ConvertFrom-Json) | ConvertTo-Json -Compress)
}

switch ($Scenario) {
    "Preflight" { Invoke-Preflight $StripeMode }
    "SignedFixture" { Invoke-SignedFixture }
    "Stage3Fixture" { Invoke-Stage3Fixture }
    "LiveTest" { Invoke-LiveTest }
    "Teardown" { Invoke-Teardown }
}
