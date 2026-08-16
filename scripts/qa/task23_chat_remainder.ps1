param(
    [Parameter(Mandatory = $true)][string]$EvidenceDir,
    [string]$BaseUrl = "http://127.0.0.1:8029",
    [string]$Container = "rag-studio-stage2-fr012-final",
    [string]$Network = "rag-studio-stage2-fr012-final_default",
    [string]$DockerCli = "C:\Users\Admin\AppData\Local\Programs\DockerDesktop\resources\bin\docker.exe"
)

$ErrorActionPreference = "Stop"
$provider = "rag-studio-stage2-fake-provider"
$sessions = [System.Collections.Generic.List[string]]::new()
$uploadedDocId = $null
$restoreBody = $null
$result = [ordered]@{
    invocation = "pwsh -NoProfile -File scripts/qa/task23_chat_remainder.ps1 -EvidenceDir <attempt-local-path>"
    started_utc = [DateTimeOffset]::UtcNow.ToString("o")
}

function Invoke-Api {
    param([string]$Method, [string]$Path, [object]$Body = $null)
    $parameters = @{ Uri = "$BaseUrl$Path"; Method = $Method; TimeoutSec = 30; SkipHttpErrorCheck = $true }
    if ($null -ne $Body) {
        $parameters.ContentType = "application/json"
        $parameters.Body = $Body | ConvertTo-Json -Depth 12 -Compress
    }
    Invoke-WebRequest @parameters
}

function New-Session {
    param([string]$Title)
    $response = Invoke-Api POST "/api/chat/sessions" @{ title = $Title }
    $id = ($response.Content | ConvertFrom-Json).id
    $sessions.Add($id)
    $id
}

try {
    & $DockerCli restart $Container | Out-Null
    for ($attempt = 1; $attempt -le 40; $attempt++) {
        try {
            $health = Invoke-WebRequest -Uri "$BaseUrl/health" -TimeoutSec 3 -SkipHttpErrorCheck
            if ($health.StatusCode -eq 200) { break }
        }
        catch [System.Net.Http.HttpRequestException] {}
        Start-Sleep -Milliseconds 250
    }
    $scriptPath = (Resolve-Path ".omo/evidence/ulw/stage2-react-fr012-parity-01a000f9/G001-execute-the-approved-stage-2-plan-at/a1/task-23-fake-provider.py").Path
    $slowCommand = "sed '/for chunk in _chunks(payload):/i\            time.sleep(10.0)' /qa.py > /tmp/slow.py; exec python /tmp/slow.py"
    $providerId = (& $DockerCli run -d --rm --name $provider --network $Network --entrypoint sh -v "${scriptPath}:/qa.py:ro" rag-studio:stage2-fr012-final -c $slowCommand).Trim()
    Start-Sleep -Milliseconds 500
    & $DockerCli exec $Container curl -fsS http://$provider`:8080/v1/models | Out-Null
    $result.provider = [ordered]@{ container_id = $providerId; ready = $LASTEXITCODE -eq 0; network = $Network }

    $baseline = (Invoke-Api GET "/api/settings").Content | ConvertFrom-Json
    $restoreBody = [ordered]@{
        provider = $baseline.provider; model = $baseline.model; temperature = $baseline.temperature
        max_tokens = $baseline.max_tokens; system_prompt = $baseline.system_prompt; top_k = $baseline.top_k
        chunk_size = $baseline.chunk_size; chunk_overlap = $baseline.chunk_overlap; chunking = $baseline.chunking
    }
    $qaSettings = [ordered]@{
        provider = "ollama"; model = "stage2-deterministic"; temperature = $baseline.temperature
        max_tokens = $baseline.max_tokens; system_prompt = $baseline.system_prompt; top_k = $baseline.top_k
        chunk_size = $baseline.chunk_size; chunk_overlap = $baseline.chunk_overlap; chunking = $baseline.chunking
    }
    $settingsResponse = Invoke-Api POST "/api/settings" $qaSettings
    $result.provider.settings_status = [int]$settingsResponse.StatusCode

    $competitorSession = New-Session "task23-competitor"
    $first = Invoke-Api POST "/api/chat/sessions/$competitorSession/messages" @{ content = "first-content"; message_id = "task23-competitor-id" }
    $competitor = Invoke-Api POST "/api/chat/sessions/$competitorSession/messages" @{ content = "different-content"; message_id = "task23-competitor-id" }
    $result.same_session_competitor = [ordered]@{ first_status = [int]$first.StatusCode; competitor_status = [int]$competitor.StatusCode }

    $loadSessions = 0..9 | ForEach-Object { New-Session "task23-stream-$_" }
    $overflowSession = New-Session "task23-stream-overflow"
    $streamDir = Join-Path $EvidenceDir "streams"
    New-Item -ItemType Directory -Force -Path $streamDir | Out-Null
    $streamProcesses = [System.Collections.Generic.List[Diagnostics.Process]]::new()
    for ($i = 0; $i -lt 10; $i++) {
        $payloadPath = Join-Path $streamDir "payload-$i.json"
        @{ content = "bounded stream $i"; session_id = $loadSessions[$i]; message_id = "task23-live-stream-$i" } | ConvertTo-Json -Compress | Set-Content -LiteralPath $payloadPath -Encoding UTF8
        $outputPath = Join-Path $streamDir "stream-$i.txt"
        $statusPath = Join-Path $streamDir "status-$i.txt"
        $args = @("-sS", "--max-time", "30", "-o", $outputPath, "-w", "%{http_code}", "-H", "Content-Type: application/json", "--data-binary", "@$payloadPath", "$BaseUrl/api/chat/send")
        $streamProcesses.Add((Start-Process -FilePath "curl.exe" -ArgumentList $args -WindowStyle Hidden -PassThru -RedirectStandardOutput $statusPath))
    }
    $admitted = [System.Collections.Generic.HashSet[string]]::new()
    $admissionWatch = [Diagnostics.Stopwatch]::StartNew()
    while ($admitted.Count -lt 10 -and $admissionWatch.Elapsed.TotalSeconds -lt 5) {
        for ($i = 0; $i -lt 10; $i++) {
            if ($admitted.Contains("$i")) { continue }
            $outputPath = Join-Path $streamDir "stream-$i.txt"
            if (Test-Path -LiteralPath $outputPath) {
                $partial = Get-Content -LiteralPath $outputPath -Raw -ErrorAction SilentlyContinue
                if ($partial -match "(?m)^event:\s*start\s*$") { $admitted.Add("$i") | Out-Null }
            }
        }
        if ($admitted.Count -lt 10) { Start-Sleep -Milliseconds 50 }
    }
    $admissionWatch.Stop()
    if ($admitted.Count -ne 10) { throw "Only $($admitted.Count) of 10 stream producers reached the admission barrier." }
    $eleventh = Invoke-Api POST "/api/chat/send" @{ content = "eleventh bounded stream"; session_id = $overflowSession; message_id = "task23-live-eleventh" }
    foreach ($process in $streamProcesses) { $process.WaitForExit(35000) | Out-Null }
    $streamRows = @(0..9 | ForEach-Object {
        $streamText = Get-Content -LiteralPath (Join-Path $streamDir "stream-$_.txt") -Raw
        $events = @([regex]::Matches($streamText, "(?m)^event:\s*([^\r\n]+)") | ForEach-Object { $_.Groups[1].Value })
        [pscustomobject]@{
            status = [int](Get-Content -LiteralPath (Join-Path $streamDir "status-$_.txt") -Raw).Trim()
            milliseconds = $null; events = $events -join ","; done = $events -contains "done"
        }
    })
    $durations = @($streamRows.milliseconds | Sort-Object)
    $result.concurrency = [ordered]@{
        statuses = @($streamRows.status); events = @($streamRows.events); all_done = @($streamRows | Where-Object done -eq $false).Count -eq 0
        admitted_before_probe = $admitted.Count; admission_barrier_ms = $admissionWatch.Elapsed.TotalMilliseconds
        eleventh_status = [int]$eleventh.StatusCode; retry_after = $eleventh.Headers["Retry-After"]
        p95_ms = $null
    }

    & $DockerCli restart $Container | Out-Null
    for ($attempt = 1; $attempt -le 40; $attempt++) {
        try {
            $health = Invoke-WebRequest -Uri "$BaseUrl/health" -TimeoutSec 3 -SkipHttpErrorCheck
            if ($health.StatusCode -eq 200) { break }
        }
        catch [System.Net.Http.HttpRequestException] {}
        Start-Sleep -Milliseconds 250
    }

    foreach ($id in @($sessions)) { Invoke-Api DELETE "/api/chat/sessions/$id" | Out-Null }
    $sessions.Clear()
    $fixture = (Resolve-Path "scripts/qa/stage2_sample_ready.txt").Path
    $uploadBody = & curl.exe -sS -F "file=@$fixture;type=text/plain" "$BaseUrl/api/ingest/upload?action=replace"
    $upload = $uploadBody | ConvertFrom-Json
    for ($attempt = 1; $attempt -le 80; $attempt++) {
        $progress = (Invoke-Api GET "/api/ingest/progress/$($upload.file_id)").Content | ConvertFrom-Json
        if ($progress.status -in @("done", "failed")) { break }
        Start-Sleep -Milliseconds 250
    }
    $documents = (Invoke-Api GET "/api/ingest/documents").Content | ConvertFrom-Json
    $uploadedDocId = @($documents.documents | Where-Object filename -eq "stage2_sample_ready.txt")[0].doc_id
    $askSession = New-Session "task23-upload-ask"
    $ask = Invoke-Api POST "/api/chat/send" @{ content = "What does the indexed QA fixture confirm?"; session_id = $askSession; message_id = "task23-live-ask" }
    $result.visible_http_journey = [ordered]@{
        upload_accepted = $null -ne $upload.file_id; progress_status = $progress.status; visible = $null -ne $uploadedDocId
        ask_status = [int]$ask.StatusCode
        events = @([regex]::Matches($ask.Content, "(?m)^event:\s*([^\r\n]+)") | ForEach-Object { $_.Groups[1].Value })
        done = $ask.Content -match "(?m)^event:\s*done\s*$"; document_content_captured = $false
    }

    $deadlineSession = New-Session "task23-disconnect"
    $deadlinePath = Join-Path $EvidenceDir "deadline.json"
    @{ content = "deadline disconnect probe"; session_id = $deadlineSession; message_id = "task23-live-deadline" } | ConvertTo-Json -Compress | Set-Content -LiteralPath $deadlinePath -Encoding UTF8
    & curl.exe -sS --max-time 0.001 -o NUL -H "Content-Type: application/json" --data-binary "@$deadlinePath" "$BaseUrl/api/chat/send"
    $deadlineExit = $LASTEXITCODE
    $cancel = Invoke-Api POST "/api/chat/sessions/$deadlineSession/cancel"
    $result.disconnect = [ordered]@{ curl_exit = $deadlineExit; cancel_status = [int]$cancel.StatusCode; health_status = [int](Invoke-Api GET "/health").StatusCode }

    foreach ($id in @($sessions)) { Invoke-Api DELETE "/api/chat/sessions/$id" | Out-Null }
    $sessions.Clear()
    if ($null -ne $uploadedDocId) { Invoke-Api DELETE "/api/ingest/documents/$uploadedDocId" | Out-Null; $uploadedDocId = $null }

    $rateRows = [System.Collections.Generic.List[int]]::new()
    for ($i = 0; $i -lt 70; $i++) {
        $response = Invoke-Api GET "/api/settings"
        $rateRows.Add([int]$response.StatusCode)
        if ($response.StatusCode -eq 429) { $result.rate_limit = [ordered]@{ attempt = $i + 1; status = 429; retry_after = $response.Headers["Retry-After"] }; break }
    }
    $failures = [System.Collections.Generic.List[string]]::new()
    if (@($result.concurrency.statuses | Where-Object { $_ -ne 200 }).Count -ne 0) { $failures.Add("ten_stream_statuses") }
    if (-not $result.concurrency.all_done) { $failures.Add("ten_stream_terminal_done") }
    if ($result.concurrency.eleventh_status -ne 503 -or $null -eq $result.concurrency.retry_after) { $failures.Add("eleventh_bounded_503") }
    if ($result.visible_http_journey.progress_status -ne "done" -or -not $result.visible_http_journey.visible -or -not $result.visible_http_journey.done) { $failures.Add("upload_ready_ask_done") }
    if ($failures.Count -ne 0) { throw "Task 23 acceptance failed: $($failures -join ', ')" }
}
finally {
    if ($null -ne $restoreBody) { Invoke-Api POST "/api/settings" $restoreBody | Out-Null }
    foreach ($id in @($sessions)) { Invoke-Api DELETE "/api/chat/sessions/$id" | Out-Null }
    if ($null -ne $uploadedDocId) { Invoke-Api DELETE "/api/ingest/documents/$uploadedDocId" | Out-Null }
    & $DockerCli rm -f $provider | Out-Null
    $result.cleanup = [ordered]@{
        provider_absent = @(& $DockerCli ps -a --filter "name=^/$provider$" -q).Count -eq 0
        target_running = (& $DockerCli inspect -f '{{.State.Running}}' $Container).Trim() -eq "true"
        target_health = (& $DockerCli inspect -f '{{.State.Health.Status}}' $Container).Trim()
    }
    $result.finished_utc = [DateTimeOffset]::UtcNow.ToString("o")
    $result | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath (Join-Path $EvidenceDir "task-23-chat-remainder.json") -Encoding UTF8
}
