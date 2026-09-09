---
name: lavish-plan-review
description: Create one local, annotatable visual companion for every human-reviewable version of a non-trivial plan. The Markdown draft/plan stays canonical; this is a bounded comprehension companion, not another planning loop.
---

# Lavish plan review

Use this companion whenever a non-trivial Markdown plan version is ready for
human review: the grounded/approach draft, a materially revised draft returned
for another review, and the final executable plan before `$start-work`. The
Markdown draft or plan remains canonical; `.omo/plans/...md` is the
authoritative executable artifact.

## When to use

Use for every non-trivial plan. A plan is non-trivial when it is multi-task,
migration-related, architecture-changing, dependency-heavy, concurrency- or
transaction-sensitive, or otherwise materially easier to understand visually.
Trivial one-step or mechanical plans may skip it to avoid workflow overhead.
The user may explicitly opt out for one plan by stating
`SKIP LAVISH FOR THIS PLAN`.

Do not use it during `feature-discussion`: decisions are still being made there.
Maintain one local artifact per plan and update it in place. Do not refresh it
for internal edits, Metis findings, structural corrections, typos, or agent
messages; refresh once when the resulting version is ready for human review.

## Workflow

1. Read the current human-reviewable Markdown draft/plan and the installed `lavish` skill.
2. Fetch the current Lavish CLI guidance and each applicable playbook before authoring the artifact.
3. Create a sanitized self-contained review page under `.lavish/`, mirroring this dashboard's visual language where the artifact represents its UI.
4. Visualize at minimum: stage goal; architecture/component topology; main data/control pipeline; task dependency graph; transaction/publication boundaries when applicable; important failure paths; scope IN/OUT; test budget; verification budget; and human gates.
5. Open the page locally with Lavish. During a human review, keep Lavish interactive and poll normally, attached to the active Codex turn, until the user sends feedback or ends the session.
6. Classify returned feedback as `DECISION-BLOCKING`, `LOCAL PLAN DEFECT`, or `NON-BLOCKING PLAN QUALITY` and apply the project PLANNING BUDGET POLICY. Apply only explicitly accepted, causally bounded corrections to the Markdown plan, then present that canonical plan for explicit approval.

Lavish visualization and feedback are part of the existing human approval gate.
They do not start another gap-analysis, structural-validation, or complete plan
generation loop.

## Execution-status refresh

During `$start-work`, Lavish is not an execution-status or QA surface. Do not
refresh it per task, task blocker, environment repair, implementation defect,
responsive/theme/contrast review, or polish loop. Refresh the existing artifact
only when a human-visible material plan/scope revision is ready for review;
that refresh remains a planning human gate, not execution control. Do not
continuously poll Lavish feedback while implementation tasks are running.

At a human approval gate, or when the user explicitly requests interactive
Lavish feedback, start `lavish-axi poll` attached to the active Codex turn,
retrieve queued annotations, and classify them under the project workflow.
Never apply architecture or plan changes from annotations without explicit
human approval.

## Safety boundaries

- Keep artifacts local. Do not use Lavish sharing or export external URLs unless the user explicitly authorizes it.
- Never include 1C credentials, production URLs, raw 1C report rows, GUIDs, customer/employee data, or diagnostic records.
- Do not change application code, tests, cache files, or deployment configuration as part of the review.
- Treat annotations as feedback, not approval. Never let Lavish rewrite or approve the Markdown plan, run `$start-work`, change production code, or turn annotations into implementation. Implementation starts only after the user explicitly approves the canonical Markdown plan.
