param(
    [Parameter(Mandatory = $true)][string]$EvidenceDir,
    [string]$BaseUrl = "http://127.0.0.1:8029",
    [string]$Container = "rag-studio-stage2-fr012-final",
    [string]$DockerCli = "C:\Users\Admin\AppData\Local\Programs\DockerDesktop\resources\bin\docker.exe"
)

$ErrorActionPreference = "Stop"
$rawDir = Join-Path $EvidenceDir "raw"
New-Item -ItemType Directory -Force -Path $rawDir | Out-Null
$started = [DateTimeOffset]::UtcNow
$createdSessions = [System.Collections.Generic.List[string]]::new()
$uploadedDocId = $null
$restoreBody = $null
$records = [ordered]@{ invocation = $MyInvocation.Line; started_utc = $started.ToString("o") }

function Invoke-JsonRequest {
    param([string]$Method, [string]$Path, [object]$Body = $null)
    $params = @{ Uri = "$BaseUrl$Path"; Method = $Method; TimeoutSec = 30; SkipHttpErrorCheck = $true }
    if ($null -ne $Body) {
        $params.ContentType = "application/json"
        $params.Body = $Body | ConvertTo-Json -Depth 20 -Compress
    }
    Invoke-WebRequest @params
}

function Get-CanonicalSnapshot {
    $settings = (Invoke-JsonRequest GET "/api/settings").Content | ConvertFrom-Json
    $documents = (Invoke-JsonRequest GET "/api/ingest/documents").Content | ConvertFrom-Json
    $sessions = (Invoke-JsonRequest GET "/api/chat/sessions").Content | ConvertFrom-Json
    [ordered]@{ settings = $settings; documents = $documents; sessions = $sessions } | ConvertTo-Json -Depth 20 -Compress
}

function Get-Sha256Text {
    param([string]$Text)
    $bytes = [Text.Encoding]::UTF8.GetBytes($Text)
    [Convert]::ToHexString([Security.Cryptography.SHA256]::HashData($bytes)).ToLowerInvariant()
}

try {
    $inspect = & $DockerCli inspect $Container | ConvertFrom-Json
    $target = $inspect[0]
    $mount = @($target.Mounts | Where-Object Destination -eq "/app/data")
    if ($target.Image -ne "sha256:650ae3cb911046701462b536bbe9743cb90e7990c0836b708fcd726981881a89" -or $mount.Count -ne 1) {
        throw "Exact image or isolated bind verification failed"
    }
    $records.target = [ordered]@{
        id = $target.Id; image = $target.Image; health = $target.State.Health.Status
        bind_source = $mount[0].Source; memory_bytes = $target.HostConfig.Memory; nano_cpus = $target.HostConfig.NanoCpus
    }

    $snapshotBefore = Get-CanonicalSnapshot
    $routeRows = [System.Collections.Generic.List[object]]::new()
    foreach ($path in @("/", "/app", "/settings", "/app/settings", "/chat", "/app/chat", "/legacy", "/legacy/settings", "/legacy/chat")) {
        $response = Invoke-WebRequest -Uri "$BaseUrl$path" -TimeoutSec 20 -SkipHttpErrorCheck
        $routeRows.Add([ordered]@{ path = $path; status = [int]$response.StatusCode; sha256 = Get-Sha256Text $response.Content; bytes = $response.RawContentLength })
    }
    $snapshotAfterRoutes = Get-CanonicalSnapshot
    $records.rollback = [ordered]@{
        before_sha256 = Get-Sha256Text $snapshotBefore
        after_sha256 = Get-Sha256Text $snapshotAfterRoutes
        equal = $snapshotBefore -ceq $snapshotAfterRoutes
        routes = $routeRows
        twin_root_equal = $routeRows[0].sha256 -eq $routeRows[1].sha256
        twin_settings_equal = $routeRows[2].sha256 -eq $routeRows[3].sha256
        twin_chat_equal = $routeRows[4].sha256 -eq $routeRows[5].sha256
    }

    $baseline = (Invoke-JsonRequest GET "/api/settings").Content | ConvertFrom-Json
    $changed = [ordered]@{
        provider = $baseline.provider; model = "stage2-persistence-probe"; temperature = 0.7
        max_tokens = 1024; system_prompt = "Task 23 persistence probe."; top_k = 10
        chunk_size = $baseline.chunk_size; chunk_overlap = $baseline.chunk_overlap; chunking = $baseline.chunking
    }
    $saveChanged = Invoke-JsonRequest POST "/api/settings" $changed
    $restartAt = [Diagnostics.Stopwatch]::StartNew()
    & $DockerCli restart $Container | Out-File -LiteralPath (Join-Path $rawDir "restart.txt") -Encoding utf8
    $healthy = $false
    for ($attempt = 1; $attempt -le 30; $attempt++) {
        try {
            $health = Invoke-WebRequest -Uri "$BaseUrl/health" -TimeoutSec 3 -SkipHttpErrorCheck
            if ($health.StatusCode -eq 200) { $healthy = $true; break }
        }
        catch [System.Net.Http.HttpRequestException] {
            $health = $null
        }
        catch [System.IO.IOException] {
            $health = $null
        }
        Start-Sleep -Milliseconds 250
    }
    $restartAt.Stop()
    $persisted = (Invoke-JsonRequest GET "/api/settings").Content | ConvertFrom-Json
    $restoreBody = [ordered]@{
        provider = $baseline.provider; model = $baseline.model; temperature = $baseline.temperature
        max_tokens = $baseline.max_tokens; system_prompt = $baseline.system_prompt; top_k = $baseline.top_k
        chunk_size = $baseline.chunk_size; chunk_overlap = $baseline.chunk_overlap; chunking = $baseline.chunking
    }
    $restore = Invoke-JsonRequest POST "/api/settings" $restoreBody
    $restored = (Invoke-JsonRequest GET "/api/settings").Content | ConvertFrom-Json
    $records.persistence = [ordered]@{
        mutation_status = [int]$saveChanged.StatusCode; restart_ms = $restartAt.Elapsed.TotalMilliseconds; healthy = $healthy
        persisted_exact = $persisted.model -eq $changed.model -and $persisted.top_k -eq 10 -and $persisted.temperature -eq 0.7
        restore_status = [int]$restore.StatusCode
        restored_exact = ($restored | ConvertTo-Json -Depth 20 -Compress) -ceq ($baseline | ConvertTo-Json -Depth 20 -Compress)
    }

    $sessionRows = [System.Collections.Generic.List[object]]::new()
    for ($i = 0; $i -lt 10; $i++) {
        $created = Invoke-JsonRequest POST "/api/chat/sessions" @{ title = "task23-isolated-$i" }
        $session = $created.Content | ConvertFrom-Json
        $createdSessions.Add($session.id)
        $messageId = "task23-message-$i"
        $commit = Invoke-JsonRequest POST "/api/chat/sessions/$($session.id)/messages" @{ content = "isolated-message-$i"; message_id = $messageId }
        $messages = (Invoke-JsonRequest GET "/api/chat/sessions/$($session.id)/messages").Content | ConvertFrom-Json
        $sessionRows.Add([ordered]@{ ordinal = $i; create = [int]$created.StatusCode; commit = [int]$commit.StatusCode; count = @($messages).Count; isolated = @($messages)[0].content -eq "isolated-message-$i" })
    }
    $competitor = Invoke-JsonRequest POST "/api/chat/sessions/$($createdSessions[0])/messages" @{ content = "competing-content"; message_id = "task23-message-0" }
    $records.sessions = [ordered]@{
        unique_ids = @($createdSessions | Select-Object -Unique).Count -eq 10
        all_isolated = @($sessionRows | Where-Object isolated -eq $false).Count -eq 0
        rows = $sessionRows; same_session_competitor_status = [int]$competitor.StatusCode
    }

    $streamDir = Join-Path $rawDir "streams"
    New-Item -ItemType Directory -Force -Path $streamDir | Out-Null
    $streamProcesses = [System.Collections.Generic.List[Diagnostics.Process]]::new()
    for ($i = 0; $i -lt 10; $i++) {
        $payloadPath = Join-Path $streamDir "payload-$i.json"
        @{ content = "bounded stream probe $i"; session_id = $createdSessions[$i]; message_id = "task23-stream-$i" } | ConvertTo-Json -Compress | Set-Content -LiteralPath $payloadPath -Encoding UTF8
        $outputPath = Join-Path $streamDir "stream-$i.txt"
        $args = @("-sS", "--max-time", "30", "-o", $outputPath, "-w", "%{http_code}", "-H", "Content-Type: application/json", "--data-binary", "@$payloadPath", "$BaseUrl/api/chat/send")
        $streamProcesses.Add((Start-Process -FilePath "curl.exe" -ArgumentList $args -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $streamDir "status-$i.txt")))
    }
    Start-Sleep -Milliseconds 20
    $eleventh = Invoke-JsonRequest POST "/api/chat/send" @{ content = "eleventh bounded probe"; session_id = $createdSessions[0]; message_id = "task23-eleventh" }
    foreach ($process in $streamProcesses) { $process.WaitForExit(35000) | Out-Null }
    $streamStatuses = 0..9 | ForEach-Object { (Get-Content -LiteralPath (Join-Path $streamDir "status-$_.txt") -Raw).Trim() }
    $records.concurrency = [ordered]@{ ten_statuses = $streamStatuses; eleventh_status = [int]$eleventh.StatusCode; eleventh_retry_after = $eleventh.Headers["Retry-After"] }

    $latencies = [System.Collections.Generic.List[double]]::new()
    $statusCodes = [System.Collections.Generic.List[int]]::new()
    for ($round = 0; $round -lt 10; $round++) {
        $jobs = 1..5 | ForEach-Object { Start-Job -ScriptBlock { param($url) $sw=[Diagnostics.Stopwatch]::StartNew(); $r=Invoke-WebRequest -Uri "$url/health" -TimeoutSec 5 -SkipHttpErrorCheck; $sw.Stop(); [pscustomobject]@{ms=$sw.Elapsed.TotalMilliseconds; status=[int]$r.StatusCode} } -ArgumentList $BaseUrl }
        $results = $jobs | Receive-Job -Wait -AutoRemoveJob
        foreach ($result in $results) { $latencies.Add($result.ms); $statusCodes.Add($result.status) }
    }
    $sorted = @($latencies | Sort-Object)
    $stats = & $DockerCli stats --no-stream --format '{{json .}}' $Container | ConvertFrom-Json
    $records.sustained = [ordered]@{
        users = 5; requests = 50; statuses = @($statusCodes | Group-Object | ForEach-Object { [ordered]@{ status = $_.Name; count = $_.Count } })
        p50_ms = $sorted[[Math]::Floor($sorted.Count * 0.50)]; p95_ms = $sorted[[Math]::Min($sorted.Count - 1, [Math]::Ceiling($sorted.Count * 0.95) - 1)]
        max_ms = ($sorted | Measure-Object -Maximum).Maximum; docker_stats = $stats
    }

    $fixture = Resolve-Path "scripts/qa/stage2_sample_ready.txt"
    $uploadRaw = Join-Path $rawDir "upload.txt"
    $uploadStatus = & curl.exe -sS -o $uploadRaw -w '%{http_code}' -F "file=@$fixture;type=text/plain" "$BaseUrl/api/ingest/upload"
    $upload = Get-Content -LiteralPath $uploadRaw -Raw | ConvertFrom-Json
    $progressRows = [System.Collections.Generic.List[object]]::new()
    for ($attempt = 1; $attempt -le 80; $attempt++) {
        $progress = (Invoke-JsonRequest GET "/api/ingest/progress/$($upload.file_id)").Content | ConvertFrom-Json
        $progressRows.Add([ordered]@{ attempt = $attempt; status = $progress.status; chunks = $progress.chunks_count })
        if ($progress.status -in @("done", "failed")) { break }
        Start-Sleep -Milliseconds 250
    }
    $documentsAfterUpload = (Invoke-JsonRequest GET "/api/ingest/documents").Content | ConvertFrom-Json
    $uploaded = @($documentsAfterUpload.documents | Where-Object filename -eq "stage2_sample_ready.txt")[0]
    $uploadedDocId = $uploaded.doc_id
    $journeySession = Invoke-JsonRequest POST "/api/chat/sessions" @{ title = "task23-upload-ask" }
    $journeySessionId = ($journeySession.Content | ConvertFrom-Json).id
    $createdSessions.Add($journeySessionId)
    $askPayload = Join-Path $rawDir "ask.json"
    @{ content = "What does the indexed QA fixture confirm?"; session_id = $journeySessionId; message_id = "task23-ask" } | ConvertTo-Json -Compress | Set-Content -LiteralPath $askPayload -Encoding UTF8
    $askRaw = Join-Path $rawDir "ask-sse.txt"
    $askStatus = & curl.exe -sS --max-time 30 -o $askRaw -w '%{http_code}' -H 'Content-Type: application/json' --data-binary "@$askPayload" "$BaseUrl/api/chat/send"
    $askText = Get-Content -LiteralPath $askRaw -Raw
    $records.visible_http_journey = [ordered]@{
        upload_status = [int]$uploadStatus; progress = $progressRows; ready = $progress.status -eq "done"
        visible_in_list = $null -ne $uploadedDocId; ask_status = [int]$askStatus; stream_has_done = $askText -match 'event: done'
        document_content_captured = $false
    }

    $deadlinePayload = Join-Path $rawDir "deadline.json"
    @{ content = "deadline disconnect probe"; session_id = $createdSessions[1]; message_id = "task23-deadline" } | ConvertTo-Json -Compress | Set-Content -LiteralPath $deadlinePayload -Encoding UTF8
    & curl.exe -sS --max-time 0.001 -o NUL -H 'Content-Type: application/json' --data-binary "@$deadlinePayload" "$BaseUrl/api/chat/send"
    $deadlineExit = $LASTEXITCODE
    $cancel = Invoke-JsonRequest POST "/api/chat/sessions/$($createdSessions[1])/cancel"
    $healthAfterDisconnect = Invoke-JsonRequest GET "/health"
    $records.disconnect = [ordered]@{ curl_exit = $deadlineExit; cancel_status = [int]$cancel.StatusCode; health_status = [int]$healthAfterDisconnect.StatusCode }

    $rateStatuses = [System.Collections.Generic.List[int]]::new()
    $retryAfter = $null
    for ($i = 0; $i -lt 70; $i++) {
        $rate = Invoke-WebRequest -Uri "$BaseUrl/api/settings" -TimeoutSec 5 -SkipHttpErrorCheck
        $rateStatuses.Add([int]$rate.StatusCode)
        if ($rate.StatusCode -eq 429) { $retryAfter = $rate.Headers["Retry-After"]; break }
    }
    $records.rate_limit = [ordered]@{ attempts = $rateStatuses.Count; statuses = @($rateStatuses | Group-Object | ForEach-Object { [ordered]@{ status = $_.Name; count = $_.Count } }); retry_after = $retryAfter }
}
finally {
    if ($null -ne $restoreBody) {
        Invoke-JsonRequest POST "/api/settings" $restoreBody | Out-Null
    }
    foreach ($sessionId in $createdSessions) {
        Invoke-WebRequest -Uri "$BaseUrl/api/chat/sessions/$sessionId" -Method DELETE -TimeoutSec 10 -SkipHttpErrorCheck | Out-Null
    }
    if ($null -ne $uploadedDocId) {
        Invoke-WebRequest -Uri "$BaseUrl/api/ingest/documents/$uploadedDocId" -Method DELETE -TimeoutSec 30 -SkipHttpErrorCheck | Out-Null
    }
    $records.cleanup = [ordered]@{
        sessions_deleted = $createdSessions.Count; uploaded_document_deleted = $null -ne $uploadedDocId
        target_kept_running = (& $DockerCli inspect -f '{{.State.Running}}' $Container).Trim() -eq "true"
        target_health = (& $DockerCli inspect -f '{{.State.Health.Status}}' $Container).Trim()
    }
    $records.finished_utc = [DateTimeOffset]::UtcNow.ToString("o")
    $records | ConvertTo-Json -Depth 30 | Set-Content -LiteralPath (Join-Path $EvidenceDir "task-23-live.json") -Encoding UTF8
}
