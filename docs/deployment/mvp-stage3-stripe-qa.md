# MVP Stage3 and Stripe test QA

This runbook provisions only the Compose project named on the command line. It
uses the existing deterministic Stage3 migrations, two synthetic Personal Lab
identities, indexed fixture documents, and the local fake streaming provider.
All Docker work is serialized with `COMPOSE_PARALLEL_LIMIT=1`; teardown is
label-scoped through the Group 2 harness. Never restart Docker Desktop, prune,
or point this workflow at production credentials or data.

## Deterministic checks

Run the credential-free preflight and signed raw-webhook fixture first:

```powershell
scripts/qa/mvp_stage3_stripe_qa.ps1 -Scenario Preflight -StripeMode SignedFixture
scripts/qa/mvp_stage3_stripe_qa.ps1 -Scenario SignedFixture
```

These checks use synthetic signing material inside the focused API test. They
make no Stripe network request and do not mutate app data. A real public API
preflight authorizes `http://widget-approved.test:8033` with status 204 and
rejects `http://widget-rejected.test:8034` with status 403 and no CORS
authority. Both reserved `.test` names are intended to be served locally; add
them to the QA machine's hosts mapping when loading the browser fixtures.

Start the isolated Stage3 fixture only after the deterministic checks pass:

```powershell
scripts/qa/mvp_stage3_stripe_qa.ps1 -Scenario Stage3Fixture -ProjectName ragstudio-g2-mvp13
```

Use PowerShell 7 (`pwsh`) because the HTTP harness requires modern web-request
status handling. If the shell is interrupted after the scoped stack becomes
healthy, rerun the same command with `-ResumeExisting`; it refuses mismatched
or absent task state.

The receipt names `stage3-db`, `stage3-db-bootstrap`, `stage3-mail`,
`stage3-auth`, `stage3-qdrant`, `stage3-fake-deepseek`, and
`rag-studio-saas`, and captures Compose `ps` plus bounded `stats --no-stream`.
The bootstrap service applies checked-in migrations in filename order before
auth or the app becomes healthy.

## Optional live Stripe test proof

`LiveTest` is optional and test-mode only. Export all six blank Stripe values
documented in `.env.example` from operator-owned secret storage. Run preflight
before the stack exists or before changing its configuration:

```powershell
scripts/qa/mvp_stage3_stripe_qa.ps1 -Scenario Preflight -StripeMode LiveTest
scripts/qa/mvp_stage3_stripe_qa.ps1 -Scenario LiveTest -LiveAction Checkout
scripts/qa/mvp_stage3_stripe_qa.ps1 -Scenario LiveTest -LiveAction Portal
```

Missing, live-mode, malformed, or mismatched values exit with code `2` after a
redacted `preflight.json` receipt and before Docker, app, or data mutation.
Checkout must be completed in Stripe test mode and its signed webhook delivered
before Portal can succeed. Hosted session URLs, cookies, CSRF values, customer
identifiers, keys, and webhook secrets are never written to evidence.

Use only the configured `playwright_qa_2` structured interactions for the
optional browser journey. Record the app URL, action, observed state, viewport,
and screenshot; do not record redirects containing hosted-session tokens.

## Cleanup

```powershell
scripts/qa/mvp_stage3_stripe_qa.ps1 -Scenario Teardown -ProjectName ragstudio-g2-mvp13
```

Cleanup refuses missing or mismatched task state and removes only resources for
the explicit Compose project. It does not touch unrelated containers, volumes,
networks, images, or local Legacy data.
