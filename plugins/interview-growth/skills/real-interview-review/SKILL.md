---
name: real-interview-review
description: Capture and analyze a real software job interview for the explicitly selected growth goal. Use when the user wants to debrief an actual interview, remember questions and answer summaries, record interviewer feedback or round results, add recalled questions to the question bank, or identify gaps between real interviews and simulated coverage. Real-interview memories are always low-confidence and never count as formal readiness evidence.
---

# Real Interview Review

Turn an imperfect memory into useful coverage feedback without pretending it is formal evidence.

## Establish scope

1. Call `goal_get_current`; require explicit selection if no goal is bound.
2. Ask for company, role, round, approximate time, and result. Accept `unknown` where memory is
   incomplete.
3. Collect each recalled question separately with the answer summary, any interviewer feedback,
   relevant topic/capability IDs, and recall confidence from 0 to 1.
4. Preserve uncertainty. Do not improve the remembered answer before recording it.

## Record the review

Call `real_interview_record` once with a stable idempotency key. Every recalled question becomes a
pending question-bank candidate in the current goal. Explain its coverage status:

- `mapped`: an assessable simulated question already covers a related topic or capability;
- `blind_spot`: the memory is mapped, but the assessable question bank lacks related coverage;
- `unmapped`: the memory still needs topic and capability classification.

The complete review has `evidence_eligible=false`. Never submit its answer summary through
`attempt_record` or `evaluation_submit`.

## Turn findings into action

1. For `unmapped` questions, use the `question-bank` workflow to classify and prepare a rubric.
2. For `blind_spot` questions, prepare a distinct assessable simulation question.
3. Use `gap_list` to distinguish a question-bank coverage gap from an observed capability gap.
4. Create a training prescription only when the current evidence panel supports a capability gap.
5. Use an independent future mock-interview attempt to establish evidence; do not reuse the real
   interview recollection as proof.

Use `real_interview_list` for longitudinal review and `real_interview_get` when explaining one
round. Compare recurring blind spots, not raw pass rates, until real-world calibration is available.
