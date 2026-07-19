# Interview Growth

Local Codex plugin foundation for evidence-based software interview growth.

Version 0.5.0 provides:

- a FastMCP STDIO server;
- a minimal goal registry;
- one physically separate SQLite database per growth goal;
- one current goal binding per Codex session;
- explicit goal lifecycle transitions;
- idempotent goal creation;
- a minimal, role-scoped Context Packet;
- storage health checks suitable for lifecycle hooks.
- JD and user-constraint sources plus immutable approved target-standard versions;
- goal-local topic trees, aliases, duplicate suggestions, and capability dimensions;
- goal-local questions, immutable question versions, complete rubrics, search, and retirement;
- focused `goal-manager` and `question-bank` skills.
- formal interview plans with frozen standard and question versions;
- first-class main questions and adaptive follow-ups;
- raw-answer-first persistence, checkpoints, pause, resume, completion, and abort;
- rubric-bound 0-4/N/A dimension evaluations with evidence and provenance;
- strict interviewer, evaluator, and coach context separation;
- coached practice that is permanently ineligible as independent evidence;
- `interview`, internal `evaluator`, and `coach` skills.
- evidence eligibility, recency weighting, coverage gates, and critical blockers;
- topic and capability readiness without a synthetic percentage score;
- append-only evaluation disputes, blind reassessments, and explicit resolution;
- gap snapshots, training prescriptions, and different-question retest schedules;
- the `capability-dashboard` skill and nine M3 MCP tools.
- real interview reviews with question-bank candidates and coverage blind spots;
- verified goal backups, safety-first restore, portable `.igx` export/import, and app-trash delete;
- a repo-local Codex marketplace plus installation and four-week product-trial guides;
- the `real-interview-review` skill and nine M4 MCP tools.

See [installation](docs/INSTALLATION.md) and the [four-week trial](docs/FOUR_WEEK_TRIAL.md).

## Development

```bash
uv sync --dev --no-editable
uv run --no-editable pytest
uv run --no-editable ruff check .
uv run --no-editable pyright
uv run --no-editable interview-growth --data-dir .interview-growth-data doctor
```

For a local end-to-end check:

```bash
DATA_DIR=.interview-growth-data
uv run --no-editable interview-growth --data-dir "$DATA_DIR" create \
  --name "Agent Engineer" \
  --idempotency-key "agent-engineer-v1"
uv run --no-editable interview-growth --data-dir "$DATA_DIR" list
```

Use the returned goal ID with `select --session-id <session> --goal-id <goal>`.
Selection is deliberately explicit: goal-scoped operations fail when a session
has no current goal.

The MCP server uses `INTERVIEW_GROWTH_DATA_DIR`, then `PLUGIN_DATA`, then
`CLAUDE_PLUGIN_DATA` to locate persistent data. The CLI also accepts an explicit
`--data-dir` for development and tests.

## Data layout

```text
data/
├── registry.sqlite
└── goals/
    └── <goal-uuid>/goal.sqlite
```

The registry contains only goal identity, lifecycle, path, timestamps, session
bindings, and idempotency records. Domain data never shares a goal database.

## Current boundary

M0 through M4 establish isolation, target standards, question versions,
interview orchestration, raw attempts, evaluations, evidence aggregation, the
capability dashboard, disputes, prescriptions, retests, Skills, deterministic
Hook guards, real interview review, portable archives, backup/restore, recoverable
deletion, release documentation, and role-scoped context.
