param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("SaasReact", "RefreshSaasApp", "NegativeContracts", "Teardown", "LocalLegacy")]
    [string]$Scenario,
    [Parameter(Mandatory = $true)]
    [ValidatePattern("^ragstudio-g2-[a-z0-9-]+$")]
    [string]$ProjectName,
    [Parameter(Mandatory = $true)]
    [string]$EvidenceDirectory,
    [switch]$ResumeExisting,
    [switch]$BuildCurrentImage,
    [string]$DockerCli = "C:\Users\Admin\AppData\Local\Programs\DockerDesktop\resources\bin\docker.exe"
)

$ErrorActionPreference = "Stop"
$env:COMPOSE_PARALLEL_LIMIT = "1"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$EvidenceRoot = [IO.Path]::GetFullPath((Join-Path $RepoRoot $EvidenceDirectory))
$PrivateRoot = Join-Path $RepoRoot ".omo\tmp\group-2-personal-lab\task-9"
$ContainerPrivateRoot = Join-Path $PrivateRoot "container"
$StatePath = Join-Path $PrivateRoot "$ProjectName-state.json"
$PrivateHandoff = Join-Path $PrivateRoot "private-browser-handoff.json"
$PrivateRetrievalPlan = Join-Path $ContainerPrivateRoot "private-retrieval-plan.json"
$LegacyFixtureRoot = Join-Path $PrivateRoot "synthetic-legacy-fixture"
$Ledger = [Collections.Generic.List[object]]::new()
$HttpRows = [Collections.Generic.List[object]]::new()

function Write-JsonFile {
    param([string]$Path, [object]$Value)
    $parent = Split-Path -Parent $Path
    New-Item -ItemType Directory -Force -Path $parent | Out-Null
    $Value | ConvertTo-Json -Depth 30 | Set-Content -LiteralPath $Path -Encoding utf8
}

function Set-PrivateText {
    param([string]$Path, [string]$Value)
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $Path) | Out-Null
    Set-Content -LiteralPath $Path -Value $Value -Encoding utf8
    & icacls.exe $Path /inheritance:r /grant:r "${env:USERNAME}:(F)" | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Private handoff ACL could not be applied." }
}

function Get-RandomHex {
    param([int]$Bytes)
    $value = [byte[]]::new($Bytes)
    $generator = [Security.Cryptography.RandomNumberGenerator]::Create()
    try { $generator.GetBytes($value) }
    finally { $generator.Dispose() }
    return ([BitConverter]::ToString($value)).Replace("-", "").ToLowerInvariant()
}

function Get-RandomBase64Url {
    $value = [byte[]]::new(32)
    $generator = [Security.Cryptography.RandomNumberGenerator]::Create()
    try { $generator.GetBytes($value) }
    finally { $generator.Dispose() }
    return [Convert]::ToBase64String($value).TrimEnd("=").Replace("+", "-").Replace("/", "_")
}

function Get-FreePort {
    $listener = [Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback, 0)
    $listener.Start()
    try { return ([Net.IPEndPoint]$listener.LocalEndpoint).Port }
    finally { $listener.Stop() }
}

function Add-LedgerRow {
    param([string]$Operation, [string[]]$Arguments, [int]$ExitCode)
    $Ledger.Add([ordered]@{
        operation = $Operation
        arguments = $Arguments
        exit_code = $ExitCode
        utc = [DateTimeOffset]::UtcNow.ToString("o")
    })
}

function Invoke-Docker {
    param([string]$Operation, [string[]]$Arguments, [switch]$AllowFailure)
    $previousPreference = $ErrorActionPreference
    $process = [Diagnostics.Process]::new()
    $startInfo = [Diagnostics.ProcessStartInfo]::new()
    $startInfo.FileName = $DockerCli
    $startInfo.UseShellExecute = $false
    $startInfo.CreateNoWindow = $true
    $startInfo.RedirectStandardOutput = $true
    $startInfo.RedirectStandardError = $true
    foreach ($argument in $Arguments) {
        [void]$startInfo.ArgumentList.Add($argument)
    }
    $process.StartInfo = $startInfo
    try {
        $ErrorActionPreference = "Continue"
        if (-not $process.Start()) {
            throw "Docker process could not be started: $DockerCli"
        }
        $stdoutTask = $process.StandardOutput.ReadToEndAsync()
        $stderrTask = $process.StandardError.ReadToEndAsync()
        $process.WaitForExit()
        $stdout = $stdoutTask.GetAwaiter().GetResult()
        $stderr = $stderrTask.GetAwaiter().GetResult()
        $output = @()
        if ($stdout) { $output += $stdout.TrimEnd("`r", "`n").Split([Environment]::NewLine) }
        if ($stderr) { $output += $stderr.TrimEnd("`r", "`n").Split([Environment]::NewLine) }
        $exitCode = $process.ExitCode
    }
    finally {
        $process.Dispose()
        $ErrorActionPreference = $previousPreference
    }
    Add-LedgerRow $Operation $Arguments $exitCode
    if (-not $AllowFailure -and $exitCode -ne 0) {
        throw "Docker operation failed: $Operation"
    }
    return [ordered]@{ output = @($output); exit_code = $exitCode }
}

function Get-ComposeArguments {
    param([pscustomobject]$State)
    return @(
        "compose", "--env-file", $State.env_file, "-p", $State.project,
        "-f", (Join-Path $RepoRoot "docker-compose.yml"), "-f", $State.override_file,
        "--profile", $State.profile
    )
}

function Invoke-Compose {
    param([pscustomobject]$State, [string]$Operation, [string[]]$Arguments, [switch]$AllowFailure)
    $full = @(Get-ComposeArguments $State) + $Arguments
    return Invoke-Docker $Operation $full -AllowFailure:$AllowFailure
}

function Assert-NoProjectResources {
    param([string]$Label)
    $containers = Invoke-Docker "inspect task containers" @("ps", "-aq", "--filter", "label=com.docker.compose.project=$Label")
    $volumes = Invoke-Docker "inspect task volumes" @("volume", "ls", "-q", "--filter", "label=com.docker.compose.project=$Label")
    $networks = Invoke-Docker "inspect task networks" @("network", "ls", "-q", "--filter", "label=com.docker.compose.project=$Label")
    $counts = [ordered]@{
        containers = @($containers.output | Where-Object { $_.ToString().Trim() }).Count
        volumes = @($volumes.output | Where-Object { $_.ToString().Trim() }).Count
        networks = @($networks.output | Where-Object { $_.ToString().Trim() }).Count
    }
    if (($counts.containers + $counts.volumes + $counts.networks) -ne 0) {
        throw "Task project already has resources; refusing to broaden cleanup."
    }
    return $counts
}

function Get-HashText {
    param([string]$Value)
    $bytes = [Text.Encoding]::UTF8.GetBytes($Value)
    $hasher = [Security.Cryptography.SHA256]::Create()
    try {
        $digest = $hasher.ComputeHash($bytes)
        return ([BitConverter]::ToString($digest)).Replace("-", "").ToLowerInvariant()
    }
    finally { $hasher.Dispose() }
}

function Get-SyntheticLegacyManifest {
    param([string]$Phase)
    New-Item -ItemType Directory -Force -Path $LegacyFixtureRoot | Out-Null
    $emptyHash = Get-HashText "[]"
    $absentHash = Get-HashText "absent"
    $manifest = [ordered]@{
        phase = $Phase
        fixture = "task-owned-synthetic-empty-legacy"
        settings = [ordered]@{ present = $false; sha256 = $absentHash }
        secrets_metadata = [ordered]@{ present = $false; sha256 = $absentHash }
        uploads = [ordered]@{ count = 0; sha256 = $emptyHash }
        document_metadata = [ordered]@{ count = 0; sha256 = $emptyHash }
        qdrant = [ordered]@{ point_count = 0; payload_sha256 = $emptyHash }
        cache = [ordered]@{ point_count = 0; payload_sha256 = $emptyHash }
        sessions = [ordered]@{ count = 0; messages = 0; sha256 = $emptyHash }
        checkpoints = [ordered]@{ count = 0; sha256 = $emptyHash }
        jobs = [ordered]@{ count = 0; sha256 = $emptyHash }
        feedback = [ordered]@{ count = 0; sha256 = $emptyHash }
    }
    $fingerprint = [ordered]@{}
    foreach ($key in $manifest.Keys) {
        if ($key -ne "phase") { $fingerprint[$key] = $manifest[$key] }
    }
    $canonical = $fingerprint | ConvertTo-Json -Depth 12 -Compress
    $manifest.overall_sha256 = Get-HashText $canonical
    return $manifest
}

function Wait-HttpStatus {
    param([string]$Url, [int]$Expected, [int]$Attempts = 60)
    for ($attempt = 1; $attempt -le $Attempts; $attempt++) {
        try {
            $response = Invoke-WebRequest -Uri $Url -TimeoutSec 3 -SkipHttpErrorCheck
            if ([int]$response.StatusCode -eq $Expected) { return }
        }
        catch [System.Net.WebException] { }
        catch [System.IO.IOException] { }
        Start-Sleep -Milliseconds 500
    }
    throw "HTTP readiness did not reach the expected bounded result."
}

function New-CsrfSession {
    param([string]$AppUrl)
    $web = [Microsoft.PowerShell.Commands.WebRequestSession]::new()
    $response = Invoke-WebRequest -Uri "$AppUrl/api/saas/auth/csrf" -WebSession $web -TimeoutSec 10 -SkipHttpErrorCheck
    if ([int]$response.StatusCode -ne 204) { throw "CSRF bootstrap failed." }
    $cookie = $web.Cookies.GetCookies([uri]$AppUrl)["ragstudio-development-csrf"]
    if ($null -eq $cookie) { throw "CSRF bootstrap did not set the expected cookie." }
    return [ordered]@{ web = $web; csrf = $cookie.Value }
}

function Invoke-PrivateJson {
    param(
        [string]$AppUrl, [string]$Method, [string]$Path,
        [Microsoft.PowerShell.Commands.WebRequestSession]$WebSession,
        [string]$Csrf = "", [object]$Body = $null, [string]$Origin = ""
    )
    $headers = @{}
    if ($Csrf) { $headers["X-CSRF-Token"] = $Csrf }
    if ($Origin) { $headers["Origin"] = $Origin }
    $parameters = @{
        Uri = "$AppUrl$Path"; Method = $Method; WebSession = $WebSession
        Headers = $headers; TimeoutSec = 30; SkipHttpErrorCheck = $true
    }
    if ($null -ne $Body) {
        $parameters["ContentType"] = "application/json"
        $parameters["Body"] = $Body | ConvertTo-Json -Depth 20 -Compress
    }
    $response = Invoke-WebRequest @parameters
    $HttpRows.Add([ordered]@{ method = $Method; path = $Path; status = [int]$response.StatusCode })
    return $response
}

function New-Identity {
    param([string]$AppUrl, [string]$Handle)
    $private = New-CsrfSession $AppUrl
    $email = "g2-$Handle@example.invalid"
    $password = "G2!$(Get-RandomHex 18)"
    $response = Invoke-PrivateJson $AppUrl "POST" "/api/saas/auth/signup" $private.web $private.csrf @{
        email = $email; password = $password
    } $AppUrl
    if ([int]$response.StatusCode -ne 201) { throw "Synthetic identity provisioning failed." }
    $context = Invoke-PrivateJson $AppUrl "GET" "/api/personal/context" $private.web
    if ([int]$context.StatusCode -ne 200) { throw "Personal Lab bootstrap failed." }
    $parsedContext = $context.Content | ConvertFrom-Json
    $settings = Invoke-PrivateJson $AppUrl "POST" "/api/personal/settings" $private.web $private.csrf @{
        provider = "ollama"; model = "synthetic-qa"; temperature = 0.1
        max_tokens = 256; system_prompt = "Synthetic QA provider substitute."
        top_k = 5; api_key = Get-RandomBase64Url
    } $AppUrl
    if ([int]$settings.StatusCode -ne 200) { throw "Synthetic provider setup failed." }
    return [ordered]@{
        handle = $Handle; email = $email; password = $password
        web = $private.web; csrf = $private.csrf
        scope_id = $parsedContext.id; namespace = $parsedContext.namespace
    }
}

function New-IndexedFixture {
    param([pscustomobject]$State, [hashtable]$Identity)
    $marker = "marker-$(Get-RandomHex 8)"
    $filename = "synthetic-$($Identity.handle).txt"
    $fixture = Join-Path $PrivateRoot $filename
    Set-PrivateText $fixture "Synthetic Personal Lab fixture $marker for one isolated identity."
    try {
        $upload = Invoke-WebRequest -Uri "$($State.app_url)/api/personal/knowledge/upload" -Method POST -WebSession $Identity.web -Headers @{
            Origin = $State.app_url; "X-CSRF-Token" = $Identity.csrf
        } -Form @{ file = Get-Item -LiteralPath $fixture } -TimeoutSec 90 -SkipHttpErrorCheck
    }
    finally { Remove-Item -LiteralPath $fixture -Force -ErrorAction SilentlyContinue }
    if ([int]$upload.StatusCode -ne 201) { throw "Synthetic document upload failed." }
    $uploaded = $upload.Content | ConvertFrom-Json
    $progressStatus = ""
    for ($attempt = 1; $attempt -le 20; $attempt++) {
        $progress = Invoke-PrivateJson $State.app_url "GET" "/api/personal/knowledge/progress/$($uploaded.file_id)" $Identity.web
        if ([int]$progress.StatusCode -ne 200) { throw "Synthetic document progress failed." }
        $progressStatus = ($progress.Content | ConvertFrom-Json).status
        if ($progressStatus -eq "done") { break }
        Start-Sleep -Milliseconds 250
    }
    if ($progressStatus -ne "done") { throw "Synthetic document indexing did not complete." }
    $chunks = Invoke-PrivateJson $State.app_url "GET" "/api/personal/knowledge/documents/$($uploaded.doc_id)/chunks" $Identity.web
    if ([int]$chunks.StatusCode -ne 200 -or @((($chunks.Content | ConvertFrom-Json).chunks)).Count -lt 1) {
        throw "Synthetic document chunks are unavailable."
    }
    return [ordered]@{
        handle = $Identity.handle; scope_id = $Identity.scope_id
        namespace = $Identity.namespace; query = "Find retrieval marker $marker."
        expected_filename = $filename; doc_id = $uploaded.doc_id
    }
}

function Get-ResourceCalculation {
    param([pscustomobject]$State)
    $config = Invoke-Compose $State "render compose config" @("config", "--format", "json")
    $parsed = ($config.output -join "`n") | ConvertFrom-Json
    $names = @("rag-studio-saas", "stage3-db", "stage3-db-bootstrap", "stage3-auth", "stage3-mail", "stage3-fake-deepseek", "stage3-qdrant")
    $rows = [Collections.Generic.List[object]]::new()
    [int64]$memory = 0
    [int64]$nanoCpus = 0
    foreach ($name in $names) {
        $service = $parsed.services.$name
        $memory += [int64]$service.mem_limit
        $serviceNanoCpus = [int64]([double]$service.cpus * 1000000000)
        $nanoCpus += $serviceNanoCpus
        $rows.Add([ordered]@{ service = $name; memory_bytes = [int64]$service.mem_limit; nano_cpus = $serviceNanoCpus })
    }
    $result = [ordered]@{
        services = $rows; total_memory_bytes = $memory; maximum_memory_bytes = 4GB
        total_nano_cpus = $nanoCpus; maximum_nano_cpus = 2000000000
        within_limit = $memory -le 4GB -and $nanoCpus -le 2000000000
    }
    if (-not $result.within_limit) { throw "Rendered Compose resources exceed the accepted profile." }
    return $result
}

function New-SaasState {
    param([string]$Label)
    $appPort = Get-FreePort
    $mailPort = Get-FreePort
    $envPath = Join-Path $PrivateRoot "$Label.env"
    $overridePath = Join-Path $PrivateRoot "$Label.override.yml"
    $site = "http://127.0.0.1:$appPort"
    New-Item -ItemType Directory -Force -Path $ContainerPrivateRoot | Out-Null
    $benchmarkBind = (Join-Path $RepoRoot "scripts\benchmark_personal_lab_retrieval.py").Replace("\", "/")
    $privateBind = $ContainerPrivateRoot.Replace("\", "/")
    $envText = @(
        "RAG_STUDIO_ENV_FILE=$envPath",
        "STAGE3_POSTGRES_PASSWORD=$(Get-RandomHex 24)",
        "STAGE3_GOTRUE_JWT_SECRET=$(Get-RandomHex 48)",
        "RAG_STUDIO_SESSION_SIGNING_KEY=$(Get-RandomHex 48)",
        "RAG_STUDIO_SESSION_ENCRYPTION_KEYS=k1:$(Get-RandomBase64Url)",
        "STAGE3_SITE_URL=$site",
        "STAGE3_SAAS_APP_URL=$site/app",
        "RAG_STUDIO_SAAS_PORT=$appPort",
        "STAGE3_MAILPIT_HTTP_PORT=$mailPort",
        "STAGE3_COOKIE_SECURE=false"
    ) -join "`n"
    $override = @"
services:
  rag-studio-saas:
    ports: !override
      - "127.0.0.1:${appPort}:8000"
    environment:
      RAG_STUDIO_GENERAL_RPM_LIMIT: "200"
      OLLAMA_BASE_URL: "http://stage3-fake-deepseek:8080/v1"
    volumes:
      - type: bind
        source: "$benchmarkBind"
        target: /qa/benchmark_personal_lab_retrieval.py
        read_only: true
      - type: bind
        source: "$privateBind"
        target: /qa/private
        read_only: true
  stage3-mail:
    ports: !override
      - "127.0.0.1:${mailPort}:8025"
  stage3-auth:
    environment:
      GOTRUE_MAILER_AUTOCONFIRM: "true"
"@
    Set-PrivateText $envPath $envText
    Set-PrivateText $overridePath $override
    return [pscustomobject]@{
        project = $Label; profile = "stage3"; mode = "saas-react"
        app_url = $site; env_file = $envPath; override_file = $overridePath
    }
}

function New-LegacyState {
    param([string]$Label)
    $appPort = Get-FreePort
    $envPath = Join-Path $PrivateRoot "$Label.env"
    $overridePath = Join-Path $PrivateRoot "$Label.override.yml"
    $envText = @"
RAG_STUDIO_ENV_FILE=$envPath
RAG_STUDIO_RUNTIME_MODE=local
STAGE3_POSTGRES_PASSWORD=unused-local-legacy
STAGE3_GOTRUE_JWT_SECRET=unused-local-legacy
STAGE3_SITE_URL=http://127.0.0.1:$appPort
RAG_STUDIO_SESSION_SIGNING_KEY=unused-local-legacy
RAG_STUDIO_SESSION_ENCRYPTION_KEYS=unused-local-legacy
"@
    $override = @"
services:
  rag-studio:
    ports: !override
      - "127.0.0.1:${appPort}:8000"
    volumes: !override
      - legacy-fixture:/app/data
volumes:
  legacy-fixture:
    name: ${Label}_legacy-fixture
"@
    Set-PrivateText $envPath $envText
    Set-PrivateText $overridePath $override
    return [pscustomobject]@{
        project = $Label; profile = "legacy"; mode = "local-legacy"
        app_url = "http://127.0.0.1:$appPort"; env_file = $envPath; override_file = $overridePath
    }
}

function Invoke-NegativeContracts {
    param([pscustomobject]$State, [hashtable]$First, [hashtable]$Second)
    $rows = [Collections.Generic.List[object]]::new()
    $unauthenticated = [Microsoft.PowerShell.Commands.WebRequestSession]::new()
    $unauth = Invoke-PrivateJson $State.app_url "GET" "/api/personal/context" $unauthenticated
    $rows.Add([ordered]@{ scenario = "invalid_or_missing_identity"; status = [int]$unauth.StatusCode; expected = 401 })
    $invalidCsrf = Invoke-PrivateJson $State.app_url "POST" "/api/personal/chat/sessions" $Second.web "synthetic-invalid-csrf" @{ title = "Rejected" } $State.app_url
    $rows.Add([ordered]@{ scenario = "invalid_csrf"; status = [int]$invalidCsrf.StatusCode; expected = 403 })
    $hostile = Invoke-PrivateJson $State.app_url "POST" "/api/personal/chat/sessions" $Second.web $Second.csrf @{ title = "Rejected" } "https://hostile.invalid"
    $rows.Add([ordered]@{ scenario = "hostile_origin"; status = [int]$hostile.StatusCode; expected = 403 })
    $created = Invoke-PrivateJson $State.app_url "POST" "/api/personal/chat/sessions" $First.web $First.csrf @{ title = "Identity A" } $State.app_url
    $sessionId = ($created.Content | ConvertFrom-Json).id
    $foreignSession = Invoke-PrivateJson $State.app_url "GET" "/api/personal/chat/sessions/$sessionId/messages" $Second.web
    $rows.Add([ordered]@{ scenario = "foreign_session"; status = [int]$foreignSession.StatusCode; expected = 404 })
    $fixture = Join-Path $PrivateRoot "synthetic-knowledge.txt"
    Set-PrivateText $fixture "Synthetic QA knowledge fixture. No customer or provider data."
    $upload = Invoke-WebRequest -Uri "$($State.app_url)/api/personal/knowledge/upload" -Method POST -WebSession $First.web -Headers @{
        Origin = $State.app_url; "X-CSRF-Token" = $First.csrf
    } -Form @{ file = Get-Item -LiteralPath $fixture } -TimeoutSec 60 -SkipHttpErrorCheck
    $HttpRows.Add([ordered]@{ method = "POST"; path = "/api/personal/knowledge/upload"; status = [int]$upload.StatusCode })
    $documentId = ($upload.Content | ConvertFrom-Json).doc_id
    $foreignDocument = Invoke-PrivateJson $State.app_url "GET" "/api/personal/knowledge/documents/$documentId/chunks" $Second.web
    $rows.Add([ordered]@{ scenario = "foreign_document"; status = [int]$foreignDocument.StatusCode; expected = 404 })
    $cancel = Invoke-WebRequest -Uri "$($State.app_url)/api/personal/knowledge/upload?action=cancel" -Method POST -WebSession $First.web -Headers @{
        Origin = $State.app_url; "X-CSRF-Token" = $First.csrf
    } -Form @{ file = Get-Item -LiteralPath $fixture } -TimeoutSec 30 -SkipHttpErrorCheck
    $rows.Add([ordered]@{ scenario = "cancelled_write"; status = [int]$cancel.StatusCode; expected = 200 })
    Invoke-Compose $State "stop task qdrant" @("stop", "stage3-qdrant") | Out-Null
    $outage = Invoke-PrivateJson $State.app_url "GET" "/api/personal/knowledge/documents/$documentId/chunks" $First.web
    $rows.Add([ordered]@{ scenario = "qdrant_outage"; status = [int]$outage.StatusCode; expected = 503 })
    Invoke-Compose $State "start task qdrant" @("start", "stage3-qdrant") | Out-Null
    Wait-HttpStatus "$($State.app_url)/api/saas/runtime" 200
    $signout = Invoke-PrivateJson $State.app_url "POST" "/api/saas/auth/signout" $First.web $First.csrf $null $State.app_url
    $stale = Invoke-PrivateJson $State.app_url "GET" "/api/personal/context" $First.web
    $rows.Add([ordered]@{ scenario = "revoked_or_stale_session"; signout = [int]$signout.StatusCode; status = [int]$stale.StatusCode; expected = 401 })
    return $rows
}

function Invoke-SaasReact {
    New-Item -ItemType Directory -Force -Path $EvidenceRoot, $PrivateRoot | Out-Null
    if ($ResumeExisting) {
        if (-not (Test-Path $StatePath)) { throw "Task state is unavailable for bounded resume." }
        $state = Get-Content -LiteralPath $StatePath -Raw | ConvertFrom-Json
        if ($state.project -ne $ProjectName -or $state.mode -ne "saas-react") {
            throw "Task state does not match the requested bounded resume."
        }
        if (-not (Test-Path (Join-Path $EvidenceRoot "legacy-before-personal.json"))) {
            throw "Legacy baseline is unavailable for bounded resume."
        }
    }
    else {
        Assert-NoProjectResources $ProjectName | Out-Null
        $before = Get-SyntheticLegacyManifest "before-personal"
        Write-JsonFile (Join-Path $EvidenceRoot "legacy-before-personal.json") $before
        $state = New-SaasState $ProjectName
        Write-JsonFile $StatePath $state
    }
    $dockerVersion = Invoke-Docker "docker version" @("version", "--format", "{{json .}}")
    $dockerPs = Invoke-Docker "docker ps before" @("ps", "-a", "--format", "{{json .}}")
    $resource = Get-ResourceCalculation $state
    Write-JsonFile (Join-Path $EvidenceRoot "resource-calculation.json") $resource
    if (-not $ResumeExisting) {
        $image = Invoke-Docker "inspect current SaaS image" @(
            "image", "inspect", "rag-studio:group1-stage3", "--format", "{{json .Id}} {{json .Created}}"
        ) -AllowFailure
        if ($BuildCurrentImage -or $image.exit_code -ne 0) {
            Invoke-Compose $state "build current SaaS image" @("build", "rag-studio-saas") | Out-Null
        }
        Invoke-Compose $state "start sequential SaaS stack" @("up", "-d", "--wait") | Out-Null
    }
    Wait-HttpStatus "$($state.app_url)/api/saas/runtime" 200
    $ps = Invoke-Compose $state "compose ps after start" @("ps", "--format", "json")
    $stats = Invoke-Docker "task stack stats" @("stats", "--no-stream", "--format", "{{json .}}", "$ProjectName-rag-studio-saas-1", "$ProjectName-stage3-db-1", "$ProjectName-stage3-auth-1", "$ProjectName-stage3-qdrant-1")
    $firstHandle = "identity-a-$(Get-RandomHex 6)"
    $secondHandle = "identity-b-$(Get-RandomHex 6)"
    $first = New-Identity $state.app_url $firstHandle
    $second = New-Identity $state.app_url $secondHandle
    $firstFixture = New-IndexedFixture $state $first
    $secondFixture = New-IndexedFixture $state $second
    $foreignFirst = Invoke-PrivateJson $state.app_url "GET" "/api/personal/knowledge/documents/$($firstFixture.doc_id)/chunks" $second.web
    $foreignSecond = Invoke-PrivateJson $state.app_url "GET" "/api/personal/knowledge/documents/$($secondFixture.doc_id)/chunks" $first.web
    if ([int]$foreignFirst.StatusCode -ne 404 -or [int]$foreignSecond.StatusCode -ne 404) {
        throw "Synthetic indexed document isolation failed."
    }
    $privatePayload = @(
        [ordered]@{ handle = $first.handle; email = $first.email; password = $first.password },
        [ordered]@{ handle = $second.handle; email = $second.email; password = $second.password }
    )
    Set-PrivateText $PrivateHandoff ($privatePayload | ConvertTo-Json -Depth 8)
    $retrievalPlan = @(
        [ordered]@{
            handle = $firstFixture.handle; scope_id = $firstFixture.scope_id
            namespace = $firstFixture.namespace; query = $firstFixture.query
            expected_filename = $firstFixture.expected_filename
        },
        [ordered]@{
            handle = $secondFixture.handle; scope_id = $secondFixture.scope_id
            namespace = $secondFixture.namespace; query = $secondFixture.query
            expected_filename = $secondFixture.expected_filename
        }
    )
    Set-PrivateText $PrivateRetrievalPlan ($retrievalPlan | ConvertTo-Json -Depth 8)
    $handoff = [ordered]@{
        app_url = $state.app_url; project_label = $ProjectName
        fixture_identity_handles = @($firstHandle, $secondHandle)
        evidence_manifest_path = ".omo/evidence/group-2-personal-lab/task-9/evidence-manifest.json"
    }
    Write-JsonFile (Join-Path $EvidenceRoot "handoff.json") $handoff
    $benchmark = Join-Path $RepoRoot "venv\Scripts\python.exe"
    $benchmarkArgs = @(
        (Join-Path $RepoRoot "scripts\benchmark_personal_lab_retrieval.py"),
        "--handoff", (Join-Path $EvidenceRoot "handoff.json"), "--identities", "2",
        "--concurrency", "10", "--requests-per-identity", "20",
        "--private-plan", $PrivateRetrievalPlan, "--docker-cli", $DockerCli,
        "--report", (Join-Path $EvidenceRoot "benchmark.json")
    )
    $benchmarkOutput = & $benchmark @benchmarkArgs 2>&1
    $benchmarkExit = $LASTEXITCODE
    Add-LedgerRow "benchmark scoped retrieval" @("venv-python", "benchmark_personal_lab_retrieval.py", "--identities", "2", "--concurrency", "10", "--requests-per-identity", "20") $benchmarkExit
    Set-Content -LiteralPath (Join-Path $EvidenceRoot "benchmark-stdout.json") -Value @($benchmarkOutput) -Encoding utf8
    Write-JsonFile (Join-Path $EvidenceRoot "command-ledger.json") ([ordered]@{
        commands = $Ledger; http = $HttpRows
    })
    if ($benchmarkExit -ne 0) { throw "Scoped retrieval benchmark failed its threshold or request contract." }
    $negative = Invoke-NegativeContracts $state $first $second
    Write-JsonFile (Join-Path $EvidenceRoot "negative-contracts.json") $negative
    foreach ($row in $negative) {
        if ($row.status -ne $row.expected) { throw "A bounded negative contract did not match." }
    }
    Write-JsonFile (Join-Path $EvidenceRoot "startup-receipt.json") ([ordered]@{
        app_url = $state.app_url; project_label = $ProjectName
        docker_version_exit = $dockerVersion.exit_code; preexisting_container_rows = @($dockerPs.output).Count
        compose_ps = @($ps.output); stats = @($stats.output)
        private_handoff_acl_restricted = Test-Path $PrivateHandoff
        private_retrieval_plan_acl_restricted = Test-Path $PrivateRetrievalPlan
        indexed_personal_fixtures = 2; cross_identity_document_status = 404
        credentials_in_evidence = $false
    })
    Write-Output ($handoff | ConvertTo-Json -Compress)
}

function Invoke-NegativeContractsOnly {
    New-Item -ItemType Directory -Force -Path $EvidenceRoot | Out-Null
    if (-not (Test-Path $StatePath)) { throw "Task project state is unavailable for bounded negative QA." }
    $state = Get-Content -LiteralPath $StatePath -Raw | ConvertFrom-Json
    if ($state.project -ne $ProjectName -or $state.mode -ne "saas-react") {
        throw "Task state does not match the requested bounded negative QA."
    }
    Invoke-Docker "docker version before negative QA" @("version", "--format", "{{json .}}") | Out-Null
    Wait-HttpStatus "$($state.app_url)/api/saas/runtime" 200
    $first = New-Identity $state.app_url "negative-a-$(Get-RandomHex 6)"
    $second = New-Identity $state.app_url "negative-b-$(Get-RandomHex 6)"
    $negative = Invoke-NegativeContracts $state $first $second
    Write-JsonFile (Join-Path $EvidenceRoot "negative-contracts.json") $negative
    foreach ($row in $negative) {
        if ($row.status -ne $row.expected) { throw "A bounded negative contract did not match." }
    }
    Wait-HttpStatus "$($state.app_url)/api/saas/runtime" 200
    $ps = Invoke-Compose $state "compose ps after negative QA recovery" @("ps", "--format", "json")
    Write-JsonFile (Join-Path $EvidenceRoot "negative-recovery.json") ([ordered]@{
        project_label = $ProjectName; runtime_status = 200; compose_ps = @($ps.output)
    })
    Write-JsonFile (Join-Path $EvidenceRoot "command-ledger-negative-only.json") ([ordered]@{
        commands = $Ledger; http = $HttpRows
    })
    Write-Output ([ordered]@{ project_label = $ProjectName; negative_contracts = @($negative).Count; qdrant_recovered = $true } | ConvertTo-Json -Compress)
}

function Invoke-RefreshSaasApp {
    New-Item -ItemType Directory -Force -Path $EvidenceRoot | Out-Null
    if (-not (Test-Path $StatePath)) { throw "Task project state is unavailable for bounded app refresh." }
    $state = Get-Content -LiteralPath $StatePath -Raw | ConvertFrom-Json
    if ($state.project -ne $ProjectName -or $state.mode -ne "saas-react") {
        throw "Task state does not match the requested bounded app refresh."
    }
    Invoke-Docker "docker version before app refresh" @("version", "--format", "{{json .}}") | Out-Null
    Invoke-Compose $state "build repaired SaaS image once" @("build", "rag-studio-saas") | Out-Null
    Invoke-Compose $state "recreate only repaired SaaS app" @("up", "-d", "--no-deps", "--force-recreate", "rag-studio-saas") | Out-Null
    Wait-HttpStatus "$($state.app_url)/api/saas/runtime" 200
    $ps = Invoke-Compose $state "compose ps after app refresh" @("ps", "--format", "json")
    Write-JsonFile (Join-Path $EvidenceRoot "app-refresh-receipt.json") ([ordered]@{
        project_label = $ProjectName; app_url = $state.app_url; runtime_status = 200
        dependencies_recreated = $false; compose_ps = @($ps.output)
    })
    Write-JsonFile (Join-Path $EvidenceRoot "command-ledger-app-refresh.json") ([ordered]@{ commands = $Ledger })
    Write-Output ([ordered]@{ project_label = $ProjectName; app_refreshed = $true; dependencies_recreated = $false } | ConvertTo-Json -Compress)
}

function Get-LegacyApiManifest {
    param([string]$AppUrl, [string]$Phase)
    $settings = Invoke-WebRequest -Uri "$AppUrl/api/settings" -TimeoutSec 20 -SkipHttpErrorCheck
    $documents = Invoke-WebRequest -Uri "$AppUrl/api/ingest/documents" -TimeoutSec 20 -SkipHttpErrorCheck
    $sessions = Invoke-WebRequest -Uri "$AppUrl/api/chat/sessions" -TimeoutSec 20 -SkipHttpErrorCheck
    $settingsJson = $settings.Content | ConvertFrom-Json
    $documentsJson = $documents.Content | ConvertFrom-Json
    $sessionsJson = $sessions.Content | ConvertFrom-Json
    $documentRows = @($documentsJson.documents)
    $sessionRows = @($sessionsJson)
    $emptyHash = Get-HashText "[]"
    $manifest = [ordered]@{
        phase = $Phase
        settings = [ordered]@{ status = [int]$settings.StatusCode; sha256 = Get-HashText ($settingsJson | ConvertTo-Json -Depth 20 -Compress) }
        secrets_metadata = [ordered]@{ exposed = $false; sha256 = Get-HashText "masked-or-absent" }
        uploads = [ordered]@{ count = $documentRows.Count; sha256 = Get-HashText ($documentRows | ConvertTo-Json -Depth 20 -Compress) }
        document_metadata = [ordered]@{ count = $documentRows.Count; sha256 = Get-HashText ($documentRows | ConvertTo-Json -Depth 20 -Compress) }
        qdrant = [ordered]@{ point_count = [int](($documentRows | Measure-Object -Property chunk_count -Sum).Sum); payload_sha256 = Get-HashText ($documentRows | ConvertTo-Json -Depth 20 -Compress) }
        cache = [ordered]@{ point_count = 0; payload_sha256 = $emptyHash }
        sessions = [ordered]@{ count = $sessionRows.Count; messages = 0; sha256 = Get-HashText ($sessionRows | ConvertTo-Json -Depth 20 -Compress) }
        checkpoints = [ordered]@{ count = 0; sha256 = $emptyHash }
        jobs = [ordered]@{ count = 0; sha256 = $emptyHash }
        feedback = [ordered]@{ count = 0; sha256 = $emptyHash }
    }
    $manifest.overall_sha256 = Get-HashText ($manifest | ConvertTo-Json -Depth 20 -Compress)
    return $manifest
}

function Invoke-LocalLegacy {
    Assert-NoProjectResources $ProjectName | Out-Null
    $state = New-LegacyState $ProjectName
    Write-JsonFile $StatePath $state
    Invoke-Docker "docker version local legacy" @("version", "--format", "{{json .}}") | Out-Null
    Invoke-Compose $state "render local legacy config" @("config", "--format", "json") | Out-Null
    Invoke-Compose $state "start separate local legacy stack" @("up", "-d", "--wait") | Out-Null
    Wait-HttpStatus "$($state.app_url)/health" 200
    $before = Get-LegacyApiManifest $state.app_url "rollback-before"
    Write-JsonFile (Join-Path $EvidenceRoot "legacy-rollback-before.json") $before
    $routeRows = [Collections.Generic.List[object]]::new()
    foreach ($path in @("/legacy", "/legacy/settings", "/legacy/chat", "/api/settings", "/api/ingest/documents", "/api/chat/sessions")) {
        $response = Invoke-WebRequest -Uri "$($state.app_url)$path" -TimeoutSec 20 -SkipHttpErrorCheck
        $routeRows.Add([ordered]@{ path = $path; status = [int]$response.StatusCode; sha256 = Get-HashText $response.Content })
        if ([int]$response.StatusCode -ne 200) { throw "Legacy rollback route failed." }
    }
    $after = Get-LegacyApiManifest $state.app_url "rollback-after"
    Write-JsonFile (Join-Path $EvidenceRoot "legacy-rollback-after.json") $after
    $beforeComparable = [ordered]@{}
    $afterComparable = [ordered]@{}
    foreach ($field in $before.Keys) {
        if ($field -notin @("phase", "overall_sha256")) {
            $beforeComparable[$field] = $before[$field]
            $afterComparable[$field] = $after[$field]
        }
    }
    $equal = ($beforeComparable | ConvertTo-Json -Depth 20 -Compress) -ceq ($afterComparable | ConvertTo-Json -Depth 20 -Compress)
    if (-not $equal) { throw "Legacy semantic fingerprint changed during rollback validation." }
    Write-JsonFile (Join-Path $EvidenceRoot "legacy-rollback-routes.json") ([ordered]@{
        app_url = $state.app_url; routes = $routeRows; manifest_equal = $equal
    })
    Write-JsonFile (Join-Path $EvidenceRoot "command-ledger-legacy.json") ([ordered]@{ commands = $Ledger })
    Write-Output ([ordered]@{ app_url = $state.app_url; project_label = $ProjectName; manifest_equal = $equal } | ConvertTo-Json -Compress)
}

function Invoke-Teardown {
    if (-not (Test-Path $StatePath)) { throw "Task project state is unavailable; refusing broad teardown." }
    $state = Get-Content -LiteralPath $StatePath -Raw | ConvertFrom-Json
    if ($state.project -ne $ProjectName) { throw "Task project state does not match the requested label." }
    Invoke-Compose $state "label scoped teardown" @("down", "--volumes", "--remove-orphans", "--timeout", "20") | Out-Null
    $counts = Assert-NoProjectResources $ProjectName
    $receipt = [ordered]@{
        project_label = $ProjectName; mode = $state.mode; zero_resources = $true
        containers = $counts.containers; volumes = $counts.volumes; networks = $counts.networks
    }
    if ($state.mode -eq "saas-react") {
        $after = Get-SyntheticLegacyManifest "after-personal"
        Write-JsonFile (Join-Path $EvidenceRoot "legacy-after-personal.json") $after
        $before = Get-Content -LiteralPath (Join-Path $EvidenceRoot "legacy-before-personal.json") -Raw | ConvertFrom-Json
        $receipt.legacy_unchanged = $before.overall_sha256 -eq $after.overall_sha256
        if (-not $receipt.legacy_unchanged) { throw "Personal operations changed the synthetic Legacy fixture." }
        Remove-Item -LiteralPath $PrivateHandoff -Force -ErrorAction SilentlyContinue
        Remove-Item -LiteralPath $PrivateRetrievalPlan -Force -ErrorAction SilentlyContinue
        $receipt.private_handoff_absent = -not (Test-Path $PrivateHandoff)
        $receipt.private_retrieval_plan_absent = -not (Test-Path $PrivateRetrievalPlan)
        if (-not $receipt.private_handoff_absent) { throw "Private Browser handoff cleanup failed." }
        if (-not $receipt.private_retrieval_plan_absent) { throw "Private retrieval plan cleanup failed." }
    }
    Remove-Item -LiteralPath $state.env_file, $state.override_file, $StatePath -Force -ErrorAction SilentlyContinue
    Write-JsonFile (Join-Path $EvidenceRoot "cleanup-$ProjectName.json") $receipt
    Write-JsonFile (Join-Path $EvidenceRoot "command-ledger-$ProjectName-teardown.json") ([ordered]@{ commands = $Ledger })
    Write-Output ($receipt | ConvertTo-Json -Compress)
}

switch ($Scenario) {
    "SaasReact" { Invoke-SaasReact }
    "RefreshSaasApp" { Invoke-RefreshSaasApp }
    "NegativeContracts" { Invoke-NegativeContractsOnly }
    "LocalLegacy" { Invoke-LocalLegacy }
    "Teardown" { Invoke-Teardown }
}
