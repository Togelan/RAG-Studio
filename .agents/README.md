# Codex project setup

`AGENTS.md` contains durable repository guidance. Reusable, task-specific
workflows live in `skills/`; Codex discovers them automatically from this
directory.

The `ba`, `architect`, `dev`, and `qa` skills preserve the former role workflow.
They are invokable skills, not permanently running named subagents: an
architect task can delegate implementation and verification as bounded
subtasks, but it cannot assume an `@dev` or `@qa` process already exists.

Start with a goal and scope. Use `/plan` for a proposed implementation approach,
`/review` for a read-only Git review, and delegation only for independent
bounded work.

## Recommended task loop

For substantial tasks, combine optional LazyCodex orchestration with the
repository skills and Graphity:

`understand → plan → implement → test → review → update graph → commit`

Use `ba`, `architect`, `dev`, and `qa` for their respective stages. They are
invokable skills, not permanent agents. Run `.\scripts\update_graph.ps1`
after tests pass and before staging or committing; include `graphify-out/` in
the same commit. LazyCodex can orchestrate or repeat these steps, but project
acceptance criteria and test commands must remain explicit.

### Shorthand

**“create task <name>”** means: create `codex/<task-name>` from `develop`,
run `architect`, implement with `dev` if ready, verify with `qa`, update
Graphity, and report evidence and risks. Always wait for explicit approval
before staging, committing, pushing, or merging.
