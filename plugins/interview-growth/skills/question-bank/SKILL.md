---
name: question-bank
description: Capture, search, version, organize, and retire software-interview questions inside the explicitly selected growth goal. Use when the user clearly asks to record or add a question, search or inspect their question bank, view question history, complete an evaluation rubric, organize questions by topic or capability, find duplicates, or retire a question. Do not capture ordinary questions without clear recording intent.
---

# Question Bank

Manage questions through the structured `interview-growth` CLI. Preserve immutable question history
and keep every operation inside the current goal.

## CLI protocol

Resolve `<plugin-root>` as two directories above this `SKILL.md`. Run `uv run --locked --no-editable
--project "<plugin-root>" interview-growth call <operation>` and pass exactly one JSON object on
stdin. Read only the returned `{ok,data,error}` envelope. Stop dependent work when `ok` is false;
inspect a contract with `interview-growth operations <operation>` when needed.

## Confirm capture intent

- Treat “记录这道题”, “加入题库”, and equivalent explicit requests as capture intent.
- Treat a normal interview or technical question as conversation, not storage intent.
- Ask one short confirmation when intent is ambiguous. Do not use a Hook or transcript parsing to
  guess that a question should be stored.

## Capture a question

1. Invoke CLI operation `goal_get_current`. If no current goal exists, require `goal_select` before continuing.
2. Invoke CLI operation `question_suggest_duplicates` with the proposed prompt. If a strong candidate exists, show
   it and ask whether to reuse it or create a distinct question.
3. Resolve topics with `topic_list` and `topic_suggest_duplicates`; create a topic only when the
   concept is distinct. Resolve capabilities with `capability_list`.
4. Invoke CLI operation `question_capture` immediately after explicit capture intent. This creates a `pending`
   version even when taxonomy or rubric work is incomplete.
5. Use a stable idempotency key for exact retries.

## Make a question assessable

Invoke CLI operation `question_prepare_version` with the current expected version. Never overwrite the captured
version. Supply at least one topic and one capability plus a rubric containing:

- `evaluation_intent`: what the answer should demonstrate;
- `expected_evidence`: non-empty observable answer evidence;
- `critical_omissions`: mistakes or missing elements that matter;
- `level_anchors`: non-empty anchors for string keys `0`, `1`, `2`, `3`, and `4`;
- `follow_up_directions`: areas an interviewer may probe.

Keep anchors relative to the current target-role standard. If no approved standard exists, the
question may be captured and practiced, but explain that it cannot yet produce formal evidence.

## Search and history

- Use `question_search` for current versions and optional topic/status filters.
- Use `question_get_history` when the user asks how a prompt or rubric changed.
- Treat the returned current version as authoritative before preparing another version.

## Retire safely

Invoke CLI operation `question_retire` with the exact current version and explicit user intent. Retirement preserves
all versions and future answer references; never delete or rewrite question history.

## Isolation rules

- Never reuse question, topic, capability, or standard IDs after switching goals.
- Cross-goal copying creates an independent question through `question_capture`; it has no shared
  identity, status, answers, or scores.
- Do not write SQLite directly. All domain writes go through the structured CLI.
