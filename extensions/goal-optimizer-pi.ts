// Pi extension for the goal-optimizer package.
//
// v1 uses no lifecycle hooks (see docs/SPEC.md §7 — the system is a deterministic
// CLI + Skill, no MCP/UI/Hook). Pi auto-loads the skills declared in package.json's
// `pi.skills`; this extension registers no listeners and exists only to satisfy the
// `pi.extensions` contract. Deliberately minimal — no Python, no shelling out.
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

export default function (_pi: ExtensionAPI) {
	// Intentionally empty. Skills are loaded via `pi.skills`; the goal.mjs CLI is
	// driven directly by the agent per skills/goal-optimizer/SKILL.md.
}
