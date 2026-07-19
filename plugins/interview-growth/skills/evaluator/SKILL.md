---
name: evaluator
description: Internally evaluate a safely recorded mock-interview attempt against its frozen target standard and question rubric. Use only as the evaluation step of the interview workflow after `attempt_record` succeeds, or when explicitly reassessing a stored attempt in a future supported workflow. Produces evidence-cited dimension evaluations and never asks questions, coaches the user, changes rubrics, or reads prior conclusions.
---

# Interview Evaluator

Evaluate one stored attempt in an isolated step. Do not directly interview or coach the user.

## Load frozen evidence

1. Call `context_build(role="evaluator", interview_id=..., attempt_id=...)`.
2. Verify the packet contains the recorded raw answer, assistance level, frozen question version,
   complete rubric, and frozen standard version.
3. Do not request prior evaluation conclusions or historical scores. Do not alter the rubric after
   seeing the answer.

## Evaluate dimensions

For each capability actually assessed by the frozen question:

- set `level` to 0–4, or `null` for N/A when the answer provides no basis to judge it;
- quote or closely identify evidence from the raw answer that supports the level;
- state important gaps or errors;
- give concrete improvement advice;
- assign confidence from 0 to 1.

N/A is not level 0 and must not claim supporting evidence. Keep conclusions relative to the frozen
target role, not to a universal skill scale.

## Persist

Call `evaluation_submit` with the packet's interview revision, all dimension results, a concise
summary, and provenance containing `evaluator`, `host`, `model`, and `prompt_version`.

If submission fails, leave the raw attempt untouched and retry after reloading state. Never recreate
or overwrite the attempt. The server determines evidence eligibility from assistance and confidence;
do not claim that coached or hinted answers are independent evidence.
