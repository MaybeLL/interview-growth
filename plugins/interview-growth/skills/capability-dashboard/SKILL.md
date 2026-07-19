---
name: capability-dashboard
description: Explain software-interview readiness from eligible evidence, including per-topic and per-capability levels, coverage, stale evidence, critical blockers, disputes, training prescriptions, and retests. Use when the user asks how ready they are for the selected target role, wants a capability panel or gap analysis, questions an evaluation, or asks what to practice next.
---

# Capability Dashboard

Explain what the evidence supports and what it does not. Never invent a percentage score or treat
coached practice as independent ability.

## Build the dashboard

1. Call `goal_get_current`. Stop goal-scoped work if the user has not explicitly selected a goal.
2. Call `dashboard_get` for the current approved target standard.
3. Lead with `readiness`, then explain critical blockers, evidence coverage, current levels, and the
   smallest useful next actions.
4. Say `evidence_insufficient` when coverage is missing. Do not translate it to a low ability score.
5. Treat `needs_revalidation` as stale evidence, not skill loss.

The default coverage gate is three eligible independent attempts across at least two distinct
questions, including one attempt in the last 30 days. The dashboard uses only the latest eligible
evidence per question under the current standard.

## Inspect evidence

Call `evidence_get` when a user asks why a level or status was produced. Explain the contributing
question versions, levels, confidence, recency, and gaps. Evidence is eligible only when it is:

- independent rather than hinted or coached;
- complete and at least 0.5 confidence;
- evaluated against the current approved standard; and
- not under an unresolved dispute.

## Handle a disputed evaluation

1. Call `evaluation_dispute` with the user's reason. The original evidence is immediately excluded.
2. Have a fresh evaluator assess the frozen question and raw answer without showing it the original
   score or critique.
3. Call `evaluation_submit_reassessment` with full evaluator provenance and rubric dimensions.
4. Present both outcomes to the user or designated resolver.
5. Call `evaluation_resolve_dispute` with `original`, `reassessment`, or `withdrawn` and record the
   reason. Only the selected outcome becomes effective evidence.

Do not silently overwrite either evaluation.

## Turn a gap into training

1. Call `gap_list` and choose one consequential gap, prioritizing critical requirements.
2. Agree on a small action plan with an observable outcome.
3. Call `prescription_create` to freeze the gap snapshot and action plan.
4. Coach with the `coach` skill. Store all assisted work using `practice_record`.
5. Choose an assessable question that covers the same topic or capability but was not used as prior
   eligible evidence.
6. Call `retest_schedule`. The future retest must be independent to affect readiness.

Call `prescription_get_next` when the user asks what to work on now.

## Presentation rules

- Separate measured level from coverage confidence.
- Name the exact critical gate that blocks readiness.
- For every gap, give one next action.
- Preserve goal isolation: never compare or combine data across goals.
- Never call assisted practice evidence, even if the answer becomes excellent.
