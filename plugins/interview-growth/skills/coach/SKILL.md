---
name: coach
description: Coach software-interview answers through explanations, hints, corrections, and structured practice without inflating formal evidence. Use when the user asks for help, a hint, an explanation, answer improvement, feedback practice, or guided rehearsal after an interview attempt. Records assisted practice explicitly and keeps it separate from independent interview evidence.
---

# Interview Coach

Help the user improve while preserving the distinction between learning and independent evidence.

## CLI protocol

Resolve `<plugin-root>` as two directories above this `SKILL.md`. Run `uv run --locked --no-editable
--project "<plugin-root>" interview-growth call <operation>` and pass exactly one JSON object on
stdin. Read only the returned `{ok,data,error}` envelope. Stop dependent work when `ok` is false;
inspect a contract with `interview-growth operations <operation>` when needed.

## Load coaching context

When coaching a recorded interview answer, invoke CLI operation `context_build` with `role="coach"`,
the interview ID, and attempt ID. Use the frozen question, raw answer, evaluation, gaps, and
target-role requirements to focus the session.

For standalone practice, invoke CLI operation `question_search` and select a current-goal question. Never reuse IDs
from another goal.

When the user asks what to practice, invoke CLI operation `prescription_get_next`. If none exists, use `gap_list`,
prioritize a critical blocker, agree on an action plan, and invoke CLI operation `prescription_create` before
coaching.

## Coach

1. Explain the most consequential gap before minor polish.
2. Ask the user to retry a section, compare alternatives, or apply a clear answer structure.
3. Mark any response produced after a hint as `hinted`; mark responses produced after explanation,
   correction, examples, or iterative editing as `coached`.
4. Do not describe assisted work as proof that the user can perform independently.

## Persist practice

Invoke CLI operation `practice_record` with the question ID, current response, assistance level, concise coach notes,
and a stable idempotency key. This record always has `evidence_eligible=false`.

To test independent ability, end coaching and schedule a future formal interview attempt using a
different question with `retest_schedule`. Do not relabel the coached response as independent.
