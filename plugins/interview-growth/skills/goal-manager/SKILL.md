---
name: goal-manager
description: Configure and safely administer isolated software-interview growth goals and their versioned target-role standards. Use when the user wants to create, list, select, pause, resume, export, import, back up, restore, archive, or delete a growth goal; provide a JD or target-role constraint; define topics or capability dimensions; review a standard draft; approve a standard version; or compare approved standards.
---

# Goal Manager

Manage the current growth goal through the structured `interview-growth` CLI. Keep goal selection,
assumptions, and user approval explicit.

## CLI protocol

Resolve `<plugin-root>` as two directories above this `SKILL.md`. Run `uv run --no-editable
--project "<plugin-root>" interview-growth call <operation>` and pass exactly one JSON object on
stdin. Read only the returned `{ok,data,error}` envelope. Stop dependent work when `ok` is false;
inspect a contract with `interview-growth operations <operation>` when needed.

## Establish scope

1. Invoke CLI operation `goal_get_current` with the host session ID.
2. If no goal is bound, invoke CLI operation `goal_list` and ask the user to choose, or invoke CLI operation `goal_create` when
   they asked for a new goal. Then invoke CLI operation `goal_select` explicitly.
3. Never infer a goal from conversation text. Never combine standards or IDs from two goals.
4. Re-check the current goal after the user switches targets or the session resumes.

## Build a target standard

1. Record each JD with `source_material_add(kind="job_description")` and each explicit user
   constraint with `source_material_add(kind="user_constraint")`.
2. Extract a role profile containing at least `role` and `level`. Preserve uncertainties as
   assumptions in the profile instead of silently inventing requirements.
3. Before creating a topic, invoke CLI operation `topic_suggest_duplicates`. Reuse the returned topic when it is
   semantically the same; invoke CLI operation `topic_create` only for a distinct concept. Use a parent ID to form
   the single-parent topic tree.
4. Keep topics and capabilities separate: topics describe what is discussed; capabilities describe
   transferable performance such as system design or trade-off analysis.
5. Create requirements with target level 0–4, positive weight, minimum independent evidence count,
   and `critical=true` only when the requirement cannot be offset by strengths elsewhere.
6. Invoke CLI operation `standard_create_draft`. Present the role profile, assumptions, source coverage, requirements,
   weights, and critical gates to the user.
7. Invoke CLI operation `standard_approve` only after an explicit approval. Pass the draft's exact revision. A later
   material change requires a new draft and a new approved version.

## Change lifecycle

Use `goal_change_lifecycle` only on explicit user intent. Target readiness never automatically ends
or archives a goal.

## Protect and move goal data

- Use `goal_backup` before risky maintenance and `goal_list_backups` to verify the returned backup
  ID. Backups stay in the private application data directory.
- Use `goal_export` only after the user explicitly chooses a `.igx` destination. Warn that the
  package contains private SQLite data plus readable JSON and Markdown manifests.
- Use `goal_import` to create a new isolated goal. Never merge an imported database into the
  current goal.
- Before `goal_restore`, pause, end, or archive the goal; state that current state will be replaced;
  obtain the exact goal ID as confirmation. The restore tool creates a safety backup automatically.
- Before `goal_delete`, require an archived goal, a verified backup ID, and exact goal-ID
  confirmation. Explain that deletion removes the goal from the app and moves its database to the
  application trash; operating-system or external backups may still retain copies.

## Write discipline

- Use one stable idempotency key per intended domain action and reuse it only for exact retries.
- Treat version conflicts as a signal to reload and re-present the changed data.
- Do not write SQLite directly. All domain writes go through the structured CLI.
- Do not copy source text, taxonomies, or standards into another goal unless the user explicitly
  asks; create independent records with new identities when copying is requested.
