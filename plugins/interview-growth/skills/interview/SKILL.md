---
name: interview
description: Design, run, pause, resume, debrief, and finish structured adaptive software mock interviews for the explicitly selected growth goal. Use when the user asks to start or continue a mock interview, answer interview questions, change interview scope, receive adaptive follow-ups, pause, resume, checkpoint, debrief, or end an interview. Coordinates the interviewer and evaluator roles while recording every raw answer before evaluation.
---

# Mock Interview

Run the interview through the structured `interview-growth` CLI. Keep interviewing, evaluation,
and coaching as separate steps.

## CLI protocol

Resolve `<plugin-root>` as two directories above this `SKILL.md`. Run `uv run --locked --no-editable
--project "<plugin-root>" interview-growth call <operation>` and pass exactly one JSON object on
stdin. Read only the returned `{ok,data,error}` envelope. Stop dependent work when `ok` is false;
inspect a contract with `interview-growth operations <operation>` when needed.

## Interview design principles

- Structure the interview around capabilities from the approved target standard, not around an
  arbitrary list of interesting questions.
- At the role level, identify the 4-6 most consequential capabilities when available; select only a
  feasible subset for one session and prioritize every critical requirement in scope.
- Prefer questions that elicit observable evidence: past behavior, reasoning in a realistic
  situation, technical decisions, trade-offs, debugging steps, or concrete implementation work.
- Use an appropriate mix of `technical`, `behavioral`, `situational`, and `problem-solving` question
  formats. Do not force every format into a session when it does not fit the role or scope.
- Keep the accepted scope, main questions, frozen rubrics, and scoring anchors stable. Adapt only the
  order and registered follow-ups within the accepted budget.
- Evaluate against evidence and the frozen 0-4/N/A role-relative rubric. Never replace it with gut
  feeling, a generic 1-4 scorecard, answer count, or one synthetic overall score.

## Start safely

1. Invoke CLI operation `goal_get_current`. Require explicit selection when no goal is bound.
2. Invoke CLI operation `standard_list_versions`; a formal interview requires an approved standard.
   Use the latest approved version's capability and topic requirements to identify critical
   requirements and candidate coverage.
3. Search assessable questions with `question_search`. Build a coverage matrix mapping each proposed
   main question to its question format, assessed capability IDs, relevant critical requirements,
   and intended observable evidence. If coverage is missing, use the `question-bank` workflow to
   capture and prepare a rubric before asking the question.
4. Present one concise plan for acceptance. It must contain the CLI-required fields `scope`,
   `difficulty`, `question_budget`, `time_budget_minutes`, `source_strategy`, and `feedback_timing`,
   plus these frozen design fields:
   - `capability_coverage`: capability IDs selected for this session;
   - `critical_requirement_coverage`: critical topic or capability requirement IDs in scope;
   - `question_mix`: planned counts or labels for technical, behavioral, situational, and
     problem-solving formats;
   - `debrief_mode`: `structured` unless the user explicitly asks for a shorter close.
5. Respect user-specified values, state any defaults, and keep the plan within the available
   assessable-question coverage. Do not claim that one question fully covers a capability merely
   because it is mapped to it.
6. Invoke CLI operation `interview_start` with the accepted plan and initial question IDs. The plan
   accepts the additional design fields above. Treat the returned standard version, question
   versions, plan, and revision as frozen state.

## Ask and record

1. Invoke CLI operation `context_build` with `role="interviewer"` and the interview ID before
   asking. Use only the returned prompt and limited follow-up directions; do not fetch or reveal the
   full rubric or answer anchors.
2. Ask one question at a time without hints, corrections, or evaluation in formal mode.
3. Immediately invoke CLI operation `attempt_record` with the user's verbatim substantive answer before invoking
   evaluation. Use `independent` only when no hint, reference answer, or correction was provided.
4. If persistence fails, stop and retry the same write with the same idempotency key. Never evaluate
   an answer that has not been stored.
5. Invoke the `evaluator` workflow with the recorded attempt ID. Follow the plan's feedback timing;
   do not let evaluator output leak into the interviewer role.

## Add a follow-up

Generate a follow-up only to verify or deepen something in the recorded answer. Choose the smallest
useful probe, such as:

- `clarify`: establish the user's responsibility, context, or constraints;
- `evidence`: request a concrete result, metric, incident, artifact, or implementation detail;
- `reasoning`: examine alternatives, trade-offs, assumptions, or why one option was chosen;
- `depth`: test failure modes, edge cases, operational behavior, or technical consequences;
- `reflection`: ask what the user learned or would change, when relevant to a behavioral question.

Do not use a probe to hint at a missing answer or silently expand the accepted scope. Before asking
it:

1. Capture and prepare it as an assessable question through the `question-bank` workflow.
2. Invoke CLI operation `followup_register` with its question ID, the parent item ID, triggering attempt ID, current
   interview revision, and a stable idempotency key.
3. Rebuild interviewer context, then ask the registered prompt.

## Maintain state

- Reload with `interview_get_state` before every write and pass its exact revision.
- Invoke CLI operation `interview_checkpoint` at meaningful boundaries.
- Invoke CLI operation `interview_pause` or `interview_resume` on user intent.

## Finish and debrief

1. Honor `feedback_timing`; do not reveal evaluator conclusions early. At the end, include only
   successfully persisted attempts and evaluations, and mark unavailable or weakly supported areas
   as insufficient evidence.
2. Produce a structured debrief containing:
   - accepted scope and actual question completion;
   - capabilities and critical requirements actually assessed;
   - evidence-backed strengths;
   - important gaps and critical omissions;
   - planned capabilities left unassessed or with insufficient coverage;
   - recommended coaching focus and any need for a future different-question retest;
   - a clear separation between independent evidence and hinted or coached practice.
3. Keep derived readiness separate from this session debrief. Use the `capability-dashboard`
   workflow when the user asks for overall readiness; do not infer it from one interview.
4. Invoke CLI operation `interview_finish` with the concise structured debrief as the outcome summary.
   Use `aborted=true` only for an interrupted or invalid session. Unasked queued items become skipped;
   history remains intact.

## Boundaries

- Never teach or reveal evaluation during the interviewer step.
- Never modify a frozen question rubric after seeing the answer.
- Never improvise an unregistered formal question, even to satisfy a desired question mix.
- Never treat capability mapping as sufficient evidence or claim that an unasked question was
  assessed.
- Never reuse interview, item, attempt, question, or standard IDs after switching goals.
- Route assisted improvement to the `coach` workflow, where it cannot become independent evidence.
- Do not add hiring-panel assignment or candidate-comparison behavior; this skill serves the user's
  own growth goal rather than an employer's selection process.
