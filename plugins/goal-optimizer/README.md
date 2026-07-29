# Goal Optimizer

A local-first, event-sourced **goal optimization system**. It doesn't track what you
studied — it tracks *how far you are from your goal* and *where the next unit of effort
pays off most*.

The core loop:

```
record → observe → assess → explain → next
记录表现   提取观测   聚合能力   解释证据链   定下一步
```

- **record** — log a performance (a mock interview, a practice answer) as an immutable
  fact. No scores here.
- **observe** — the host agent reads the raw artifact and, guided by a rubric, extracts
  structured observations (pass/partial/fail + a line-referenced evidence quote). The
  agent never sees prior scores (anti-anchoring).
- **assess** — a deterministic engine aggregates observations into per-`(capability,
  dimension)` estimates with a **score** and a **confidence**, then compares against your
  goal to produce a prioritized gap list. No LLM here.
- **explain** — shows exactly why a number is what it is: every supporting piece of
  evidence, its weight broken down factor-by-factor, and the line in the raw artifact it
  came from.
- **next** — surfaces the highest-priority actionable gaps (deterministic); the agent
  designs up to 3 concrete diagnose/train tasks from them. Ranking, not fabricated deltas.

Four skills, one per moment of use:

- **`goal-init`** (one-time) scaffolds a new goal workspace and co-drafts its requirements
  and rubric with you (you confirm the numbers).
- **`mock-drill`** (optional) runs a mock interview / self-test, saves a clean, un-scored
  transcript into `artifacts/`, then **hands off to `goal-log` (mandatory)** — every drill
  becomes a recorded fact. It never reads the rubric or gaps while questioning
  (anti teaching-to-test) and never scores itself.
- **`goal-log`** (after each performance) is the capture pipeline — `record → observe →
  assess` — the single intake for any artifact (a drill's transcript or a real interview
  you paste in). `observe` scores blind (no prior estimates loaded).
- **`goal-review`** (when you want to look) reviews and plans — `explain` (evidence chain)
  + `next` (a plan for the highest-priority gap), plus `list` for a cross-goal overview.
  Read-only over facts; nothing is ingested here.

### Invariants

- **Facts are immutable.** `artifacts/` and `data/events.jsonl` are append-only.
- **Estimates are derived.** `state/` is fully recomputable: `rm -rf state/ && assess`
  reproduces byte-identical output (recency uses the data's own clock, not wall-time).
- **Every conclusion is traceable** to a line in a raw artifact.
- **LLM vs deterministic split:** the agent judges meaning; the CLI computes every number.

## Requirements

Only **Node.js** (the CLI is a single zero-dependency `goal.mjs`). No database, no account,
no cloud. Git is the sync mechanism.

## Install

This plugin ships in the `maybell-plugins` marketplace and loads in three hosts:

- **Claude Code:** `claude plugin marketplace add MaybeLL/interview-growth` then
  `claude plugin install goal-optimizer@maybell-plugins`. Skills are
  auto-discovered.
- **Codex:** `codex plugin marketplace add MaybeLL/interview-growth --ref release-v1` then
  `codex plugin add goal-optimizer@maybell-plugins`.
- **Pi:** `pi install git:github.com/MaybeLL/interview-growth` (add `-l` for project-local).
  Invoke a skill via e.g. `/skill:goal-log` or `/skill:goal-review`.

For a local checkout, register the repo root as a local marketplace.

## Try the worked example

A complete example workspace lives at
[`examples/backend-system-design/`](./examples/backend-system-design/) — three interview
transcripts, extracted observations, and the derived capability/gap state.

```sh
cd plugins/goal-optimizer/scripts
WS=../examples/backend-system-design
node goal.mjs explain idempotency.transfer --workspace "$WS"
# recompute from facts and confirm it's byte-identical:
rm -rf "$WS/state" && node goal.mjs assess --workspace "$WS"
```

See [`docs/SPEC.md`](../../docs/SPEC.md) for the full data contract, weight/confidence
formulas, and command semantics.
