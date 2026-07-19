---
name: interview
description: Run, pause, resume, and finish adaptive software mock interviews for the explicitly selected growth goal. Use when the user asks to start or continue a mock interview, answer interview questions, change interview scope, receive adaptive follow-ups, pause, resume, checkpoint, or end an interview. Coordinates the interviewer and evaluator roles while recording every raw answer before evaluation.
---

# Mock Interview

Run the interview through the `interview-growth` MCP server. Keep interviewing, evaluation, and
coaching as separate steps.

## Start safely

1. Call `goal_get_current`. Require explicit selection when no goal is bound.
2. Call `standard_list_versions`; a formal interview requires an approved standard.
3. Search assessable questions with `question_search`. If coverage is missing, use the
   `question-bank` workflow to capture and prepare a rubric before asking the question.
4. Present a plan containing `scope`, `difficulty`, `question_budget`, `time_budget_minutes`,
   `source_strategy`, and `feedback_timing`. Respect user-specified values and state defaults.
5. Call `interview_start` with the accepted plan and initial question IDs. Treat the returned
   standard version, question versions, and revision as frozen state.

## Ask and record

1. Call `context_build(role="interviewer", interview_id=...)` before asking. Use only the returned
   prompt and limited follow-up directions; do not fetch or reveal the full rubric or answer anchors.
2. Ask one question at a time without hints, corrections, or evaluation in formal mode.
3. Immediately call `attempt_record` with the user's verbatim substantive answer before invoking
   evaluation. Use `independent` only when no hint, reference answer, or correction was provided.
4. If persistence fails, stop and retry the same write with the same idempotency key. Never evaluate
   an answer that has not been stored.
5. Invoke the `evaluator` workflow with the recorded attempt ID. Follow the plan's feedback timing;
   do not let evaluator output leak into the interviewer role.

## Add a follow-up

Generate a follow-up only to verify or deepen something in the recorded answer. Before asking it:

1. Capture and prepare it as an assessable question through the `question-bank` workflow.
2. Call `followup_register` with its question ID, the parent item ID, triggering attempt ID, current
   interview revision, and a stable idempotency key.
3. Rebuild interviewer context, then ask the registered prompt.

## Maintain state

- Reload with `interview_get_state` before every write and pass its exact revision.
- Call `interview_checkpoint` at meaningful boundaries.
- Call `interview_pause` or `interview_resume` on user intent.
- Call `interview_finish` with a concise outcome summary. Use `aborted=true` only for an interrupted
  or invalid session. Unasked queued items become skipped; history remains intact.

## Boundaries

- Never teach or reveal evaluation during the interviewer step.
- Never modify a frozen question rubric after seeing the answer.
- Never reuse interview, item, attempt, question, or standard IDs after switching goals.
- Route assisted improvement to the `coach` workflow, where it cannot become independent evidence.
