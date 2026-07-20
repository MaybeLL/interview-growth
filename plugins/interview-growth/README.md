# Interview Growth

Local Codex and Claude Code plugin for evidence-based software interview growth.

Version 0.8.0 provides:

- a structured JSON CLI with discoverable operation contracts;
- a minimal goal registry;
- one physically separate SQLite database per growth goal;
- one current goal binding per Codex session;
- explicit goal lifecycle transitions;
- idempotent goal creation;
- a minimal, role-scoped Context Packet;
- storage health checks suitable for lifecycle hooks.
- JD and user-constraint sources plus immutable approved target-standard versions;
- structured target-role profiles with current-profile lookup, reviewable draft revisions, and field-level version comparison;
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
- the `capability-dashboard` skill and M3 CLI operations.
- real interview reviews with question-bank candidates and coverage blind spots;
- verified goal backups, safety-first restore, portable `.igx` export/import, and app-trash delete;
- repo-local Codex and Claude Code marketplaces plus installation and four-week product-trial guides;
- the `real-interview-review` skill and M4 CLI operations.

See [installation](docs/INSTALLATION.md) and the [four-week trial](docs/FOUR_WEEK_TRIAL.md).

## Development

```bash
uv sync --dev --no-editable
uv run --locked --no-editable pytest
uv run --locked --no-editable ruff check .
uv run --locked --no-editable pyright
uv run --locked --no-editable interview-growth --data-dir .interview-growth-data doctor
```

For a local end-to-end check:

```bash
DATA_DIR=.interview-growth-data
uv run --locked --no-editable interview-growth --data-dir "$DATA_DIR" create \
  --name "Agent Engineer" \
  --idempotency-key "agent-engineer-v1"
uv run --locked --no-editable interview-growth --data-dir "$DATA_DIR" list
```

Use the returned goal ID with `select --session-id <session> --goal-id <goal>`.
Selection is deliberately explicit: goal-scoped operations fail when a session
has no current goal.

The CLI uses one host-independent application-data location, with `INTERVIEW_GROWTH_DATA_DIR` or
`--data-dir` as explicit development overrides. This keeps Skill calls and Hook calls on the same
database even when the host exposes plugin-only environment variables. Skills invoke domain
operations through `interview-growth call`, passing one JSON object on stdin and receiving a stable
`{ok,data,error}` envelope.

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
