# Local Compose and hosting readiness

This FR-019 runbook covers local evaluation and hosting preparation. It does
not provision production infrastructure, enable real billing, or migrate
legacy data.

## Prerequisites and clean state

Use Docker Desktop with 6 GiB available memory, 4 CPUs, and 10 GiB free disk.
Stage 3 itself is limited to 4 GiB and 2 CPUs. On Windows, use the full Docker
CLI path and set `COMPOSE_PARALLEL_LIMIT=1`.

A clean state means a known checkout, an operator-owned env file outside
version control, free ports 8013 and 8025, and no resources for the selected
Compose project name. It does not mean deleting `rag-data`, cleaning a dirty
Git worktree, pruning Docker, or touching another project.

Copy `.env.example` to an operator-owned file outside the repository. Set new
local-only values for `STAGE3_POSTGRES_PASSWORD`,
`STAGE3_GOTRUE_JWT_SECRET`, and `RAG_STUDIO_SESSION_SIGNING_KEY` (at least 32
characters). Set `STAGE3_SITE_URL` to the exact trusted origin, such as
`http://127.0.0.1:8013`. Leave real provider and billing credentials empty.

## Start Stage 3

The canonical startup command is:

```text
docker compose --env-file <operator-file> --profile stage3 up -d --build --wait
```

Validate and start one uniquely named project sequentially:

```powershell
$Docker = 'C:\Program Files\Docker\Docker\resources\bin\docker.exe'
$env:COMPOSE_PARALLEL_LIMIT = '1'
& $Docker version
& $Docker ps -a
& $Docker compose --project-name ragstudio-group1-local --env-file <operator-file> --profile stage3 config --quiet
& $Docker compose --project-name ragstudio-group1-local --env-file <operator-file> --profile stage3 up -d --build --wait
& $Docker compose --project-name ragstudio-group1-local --env-file <operator-file> --profile stage3 ps
& $Docker stats --no-stream
```

`/health` is process liveness. `/api/health/status`, `/api/saas/runtime`, and
protected tenant-storage readiness return HTTP 503 when a checked dependency
is unavailable. Failures are bounded and omit credentials, URLs, collection
identifiers, filesystem paths, and raw provider or SDK errors.

## Restart without deleting data

Stop and start without `--volumes`. The Postgres, Qdrant, and app/checkpoint
named volumes remain attached.

```powershell
& $Docker compose --project-name ragstudio-group1-local --env-file <operator-file> --profile stage3 stop
& $Docker compose --project-name ragstudio-group1-local --env-file <operator-file> --profile stage3 start --wait
```

Never use `down --volumes` for a persistence or restart check.

## Backup and restore

Write backups to a restricted operator directory. Use `pg_dump -Fc` for
Postgres, the Qdrant collection snapshot API for vectors, and a tar archive of
the `checkpoints` and `tenant-chat` directories in the app volume. Never print
the operator env file or embed its values in a command line.

Restore into a stopped, separately named validation project: use
`pg_restore --clean --if-exists`, recover each Qdrant snapshot through the
snapshot recovery API, and extract the app archive into that validation
project's app volume. Start with `--wait`, compare authorized row, vector, and
checkpoint counts, then make a traffic decision. Verified billing-state
persistence is deferred to the billing group and must not be fabricated here.

## Dependency failure

In a disposable project, stop exactly one of `stage3-db`, `stage3-auth`, or
`stage3-qdrant`. Within the bounded health interval, app readiness must return
sanitized HTTP 503 while `/health` remains live. Start that dependency with
`start --wait` and verify readiness before the next scenario. Do not remove
volumes during failure isolation.

## Functional rollback

The `legacy` profile runs `rag-studio` with `RAG_STUDIO_UI_MODE=legacy` and
`RAG_STUDIO_RUNTIME_MODE=local`. Its Chat and Settings APIs remain active, and
it uses only the existing `./rag-data` boundary.

```powershell
& $Docker compose --project-name ragstudio-legacy --env-file <operator-file> --profile legacy up -d --build --wait
```

Switch traffic only after `/legacy`, `/legacy/chat`, `/legacy/settings`, the
local Chat API, and the local Settings API pass. Rollback is a profile and
traffic decision, not a database downgrade or data deletion.

## Hosting responsibility matrix

| Boundary | Local Compose owner | Hosting operator responsibility |
| --- | --- | --- |
| React/FastAPI app | Current-source build and app/checkpoint volume | Pin digest, TLS/proxy, scaling, app backup and restore |
| Postgres/GoTrue | Pinned services and Postgres volume | Managed lifecycle, migrations, encryption, HA, backups |
| Qdrant | Pinned service and Qdrant volume | Pin digest, private network, snapshots, capacity, recovery |
| Secrets/origins | Uncommitted operator env file | Secret manager, rotation, exact origins, least privilege |
| Observability | Sanitized health and logs | Retention, alerting, access control, redaction |
| Billing | Not provisioned; persistence deferred | Later billing group owns test/live separation and webhooks |

## Cleanup

Resolve the exact project name before teardown. Remove only the disposable
project; never prune Docker or delete unrelated volumes or images.

```powershell
& $Docker compose --project-name ragstudio-group1-local --env-file <operator-file> --profile stage3 down --volumes --remove-orphans
& $Docker ps -a --filter label=com.docker.compose.project=ragstudio-group1-local
& $Docker volume ls --filter label=com.docker.compose.project=ragstudio-group1-local
```
