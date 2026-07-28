#!/usr/bin/env node
// Plugin metadata validator: name/version consistency across manifests, Pi
// resource paths, skill frontmatter, and marketplace entries.
// Run from the repo root: `node scripts/validate-plugin-metadata.mjs`
// Exits non-zero on the first failed assertion.
import { readFileSync, existsSync, readdirSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const repo = join(dirname(fileURLToPath(import.meta.url)), "..");
const plugin = join(repo, "plugins", "goal-optimizer");
const NAME = "goal-optimizer";

let failures = 0;
function check(cond, msg) {
  if (!cond) {
    console.error(`  ✗ ${msg}`);
    failures++;
  }
}
const readJson = (p) => JSON.parse(readFileSync(p, "utf8"));

const claude = readJson(join(plugin, ".claude-plugin/plugin.json"));
const codex = readJson(join(plugin, ".codex-plugin/plugin.json"));
const pkg = readJson(join(repo, "package.json"));

// name + version consistency (the hard invariant)
check(claude.name === NAME, `claude manifest name == ${NAME} (got ${claude.name})`);
check(codex.name === NAME, `codex manifest name == ${NAME} (got ${codex.name})`);
check(
  claude.version === codex.version && codex.version === pkg.version,
  `version identical across claude/codex/package.json (got ${claude.version}/${codex.version}/${pkg.version})`
);

// Pi package resources
check(Array.isArray(pkg.keywords) && pkg.keywords.includes("pi-package"), 'package.json keywords include "pi-package"');
check(
  JSON.stringify(pkg.pi?.skills) === JSON.stringify(["./plugins/goal-optimizer/skills"]),
  "pi.skills == ['./plugins/goal-optimizer/skills']"
);
check(
  JSON.stringify(pkg.pi?.extensions) === JSON.stringify(["./extensions/goal-optimizer-pi.ts"]),
  "pi.extensions == ['./extensions/goal-optimizer-pi.ts']"
);
for (const res of [...(pkg.pi?.skills ?? []), ...(pkg.pi?.extensions ?? [])]) {
  check(existsSync(join(repo, res)), `pi resource path exists: ${res}`);
}

// Skills: frontmatter name == dir name, has description, unique
const skillsDir = join(plugin, "skills");
const skillDirs = readdirSync(skillsDir, { withFileTypes: true }).filter((d) => d.isDirectory());
check(skillDirs.length > 0, "at least one skill");
const names = [];
for (const d of skillDirs) {
  const p = join(skillsDir, d.name, "SKILL.md");
  check(existsSync(p), `SKILL.md exists for ${d.name}`);
  if (!existsSync(p)) continue;
  const content = readFileSync(p, "utf8");
  check(content.startsWith("---\n"), `frontmatter starts for ${d.name}`);
  const body = content.slice(4);
  const end = body.indexOf("\n---");
  check(end !== -1, `frontmatter terminated for ${d.name}`);
  const fm = end === -1 ? "" : body.slice(0, end);
  const nameMatch = fm.match(/^name:\s*(\S+)\s*$/m);
  const descMatch = fm.match(/^description:\s*.+$/m);
  check(!!nameMatch, `frontmatter has name: for ${d.name}`);
  check(!!descMatch, `frontmatter has description: for ${d.name}`);
  if (nameMatch) {
    check(nameMatch[1] === d.name, `skill name matches dir: ${nameMatch[1]} == ${d.name}`);
    names.push(nameMatch[1]);
  }
}
check(names.length === new Set(names).size, "skill names unique");

// Marketplaces
for (const mp of [".agents/plugins/marketplace.json", ".claude-plugin/marketplace.json"]) {
  const m = readJson(join(repo, mp));
  check(m.name === "maybell-plugins", `${mp} name == maybell-plugins`);
  check(m.plugins?.some((it) => it.name === NAME), `${mp} lists ${NAME}`);
}

if (failures > 0) {
  console.error(`\n${failures} metadata check(s) failed.`);
  process.exit(1);
}
console.log(`✓ plugin metadata valid: ${skillDirs.length} skill(s), both marketplaces, Pi resources.`);
