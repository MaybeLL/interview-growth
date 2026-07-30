#!/usr/bin/env node
// goal-optimizer CLI — deterministic core (INV-5: no LLM here, numbers only).
// Subcommands: init | list | record | retract | observe | assess | explain | next
//
// Design notes:
// - Facts (events.jsonl, observations.jsonl, artifacts/) are append-only (INV-1).
//   Corrections are retraction events (§4.4.3), never edits.
// - Events carry schema: "event-v2". Legacy events without a schema field are
//   read under v1 semantics (novelty as self-reported claim, no hash check) and
//   are never migrated (INV-4: additive only).
// - novelty is derived from history at record time; artifacts are notarized by
//   sha256 at record time and verified on every read (hard fail on mismatch).
// - state/ (capability.json, gap.json) is fully derived and recomputable (INV-2):
//     rm -rf state/ && node goal.mjs assess  must reproduce byte-identical output.
//   To make assess a pure function of its inputs, "now" for recency decay is NOT
//   wall-clock; it is max(occurred_at) across events (override with --as-of).

import { readFileSync, writeFileSync, existsSync, mkdirSync, appendFileSync, readdirSync } from "node:fs";
import { join, resolve, dirname, basename } from "node:path";
import { createHash } from "node:crypto";

// ---------------------------------------------------------------------------
// arg parsing
// ---------------------------------------------------------------------------
function parseArgs(argv) {
  const positional = [];
  const flags = {};
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a.startsWith("--")) {
      const key = a.slice(2);
      const next = argv[i + 1];
      if (next === undefined || next.startsWith("--")) {
        flags[key] = true;
      } else {
        flags[key] = next;
        i++;
      }
    } else {
      positional.push(a);
    }
  }
  return { positional, flags };
}

function die(msg) {
  process.stderr.write(`error: ${msg}\n`);
  process.exit(1);
}

// ---------------------------------------------------------------------------
// minimal YAML loader (indentation-based; supports the subset used by
// goal.yaml and rubric/*.yaml: nested maps, lists of maps, scalars, comments)
// ---------------------------------------------------------------------------
function parseScalar(raw) {
  let s = raw.trim();
  if (s === "") return null;
  if ((s.startsWith('"') && s.endsWith('"')) || (s.startsWith("'") && s.endsWith("'"))) {
    return s.slice(1, -1);
  }
  if (s === "true") return true;
  if (s === "false") return false;
  if (s === "null" || s === "~") return null;
  if (/^-?\d+$/.test(s)) return parseInt(s, 10);
  if (/^-?\d*\.\d+$/.test(s)) return parseFloat(s);
  return s;
}

function loadYaml(text) {
  // Tokenize into lines with indent level, dropping blanks and comments.
  const lines = [];
  for (const rawLine of text.split("\n")) {
    const noComment = stripComment(rawLine);
    if (noComment.trim() === "") continue;
    const indent = noComment.length - noComment.trimStart().length;
    lines.push({ indent, content: noComment.trim() });
  }
  let pos = 0;

  function parseBlock(minIndent) {
    // Decide map vs list by first line at this indent.
    if (pos >= lines.length) return null;
    const first = lines[pos];
    if (first.indent < minIndent) return null;
    if (first.content.startsWith("- ")) return parseList(first.indent);
    return parseMap(first.indent);
  }

  function parseMap(indent) {
    const obj = {};
    while (pos < lines.length && lines[pos].indent === indent && !lines[pos].content.startsWith("- ")) {
      const { content } = lines[pos];
      const idx = content.indexOf(":");
      if (idx === -1) die(`YAML: expected key: value, got "${content}"`);
      const key = content.slice(0, idx).trim();
      const rest = content.slice(idx + 1).trim();
      pos++;
      if (rest === "") {
        // nested block
        const child = pos < lines.length && lines[pos].indent > indent ? parseBlock(indent + 1) : null;
        obj[key] = child;
      } else {
        obj[key] = parseScalar(rest);
      }
    }
    return obj;
  }

  function parseList(indent) {
    const arr = [];
    while (pos < lines.length && lines[pos].indent === indent && lines[pos].content.startsWith("- ")) {
      const { content } = lines[pos];
      const afterDash = content.slice(2);
      const idx = afterDash.indexOf(":");
      if (idx === -1) {
        // scalar list item
        arr.push(parseScalar(afterDash));
        pos++;
        continue;
      }
      // map item: first key sits on the dash line; remaining keys are indented
      // by (indent + 2). Rewrite current line as a plain key at that indent and
      // parse a map.
      const itemIndent = indent + 2;
      lines[pos] = { indent: itemIndent, content: afterDash };
      const item = parseMap(itemIndent);
      arr.push(item);
    }
    return arr;
  }

  return parseBlock(0) ?? {};
}

function stripComment(line) {
  // Remove trailing # comment not inside quotes.
  let inS = false, inD = false;
  for (let i = 0; i < line.length; i++) {
    const c = line[i];
    if (c === "'" && !inD) inS = !inS;
    else if (c === '"' && !inS) inD = !inD;
    else if (c === "#" && !inS && !inD) return line.slice(0, i);
  }
  return line;
}

// ---------------------------------------------------------------------------
// workspace helpers
// ---------------------------------------------------------------------------
function ws(flags) {
  const dir = flags.workspace || flags.w;
  if (!dir) die("--workspace <dir> is required");
  const abs = resolve(String(dir));
  if (!existsSync(abs)) die(`workspace not found: ${abs}`);
  return abs;
}

function readJsonl(path) {
  if (!existsSync(path)) return [];
  return readFileSync(path, "utf8")
    .split("\n")
    .filter((l) => l.trim() !== "")
    .map((l) => JSON.parse(l));
}

// --- event-v2 helpers -------------------------------------------------------
// Events without a `schema` field are v1 (legacy): novelty was self-reported,
// no artifact hash. They are read as-is, never migrated (INV-4: additive only).

function sha256File(path) {
  return createHash("sha256").update(readFileSync(path)).digest("hex");
}

// Facts split: retractions are meta-events; active events are performance
// events not covered by any retraction (§4.4.3).
function splitEvents(allEvents) {
  const retracted = new Set(
    allEvents.filter((e) => e.type === "retraction").map((e) => e.refers_to)
  );
  const active = allEvents.filter((e) => e.type !== "retraction" && !retracted.has(e.event_id));
  const retractions = allEvents.filter((e) => e.type === "retraction");
  return { active, retractions, retracted };
}

// Verify each artifact of a v2 event against its recorded hash; hard fail on
// mismatch (INV-3 notarization). v1 events (no schema/hash) are skipped.
function verifyArtifacts(wsDir, ev) {
  if (!ev.schema || !Array.isArray(ev.artifact_sha256)) return;
  ev.artifacts.forEach((rel, i) => {
    const expected = ev.artifact_sha256[i];
    if (!expected) return;
    const actual = sha256File(join(wsDir, rel));
    if (actual !== expected) {
      die(
        `artifact hash mismatch for ${ev.event_id}: ${rel}\n` +
          `  recorded ${expected}\n  actual   ${actual}\n` +
          `The artifact was modified after recording (INV-1 violation). ` +
          `Remedy: goal.mjs retract ${ev.event_id} --reason "..." and re-record.`
      );
    }
  });
}

// Derive novelty from history (§4.4.2): count prior active events with the
// same topic. Self-reporting is not accepted; --variant is an explicit claim.
function deriveNovelty(activeEvents, topic, variantClaimed) {
  if (variantClaimed) return "variant";
  const prior = activeEvents.filter((e) => (e.task?.topic ?? "") === topic).length;
  if (prior === 0) return "unseen";
  if (prior === 1) return "familiar";
  return "repeat";
}

function loadGoal(wsDir) {
  const p = join(wsDir, "goal.yaml");
  if (!existsSync(p)) die(`goal.yaml not found in ${wsDir}`);
  return loadYaml(readFileSync(p, "utf8"));
}

function loadRubric(wsDir, version) {
  const p = join(wsDir, "rubric", `${version}.yaml`);
  if (!existsSync(p)) die(`rubric not found: ${p}`);
  return loadYaml(readFileSync(p, "utf8"));
}

function round(x, n = 4) {
  return Number(x.toFixed(n));
}

function nextId(items, key, prefix) {
  let max = 0;
  for (const it of items) {
    const m = String(it[key] || "").match(/(\d+)$/);
    if (m) max = Math.max(max, parseInt(m[1], 10));
  }
  return `${prefix}${String(max + 1).padStart(6, "0")}`;
}

// ---------------------------------------------------------------------------
// §5 deterministic estimator
// ---------------------------------------------------------------------------
function factorDifficulty(ev) {
  return Math.max(0.2, Number(ev.task?.difficulty ?? 0.5));
}
function factorIndependence(ev) {
  const c = ev.conditions || {};
  if (c.external_materials) return 0.2;
  if (c.hints) return 0.5;
  return 1.0;
}
function factorNovelty(ev) {
  return { unseen: 1.0, variant: 0.8, familiar: 0.5, repeat: 0.25 }[ev.task?.novelty] ?? 0.5;
}
function factorReliability(ev) {
  return (
    {
      mock_interview: 0.9,
      real_interview: 0.9,
      practice: 0.7,
      explanation: 0.7,
      quiz: 0.5,
      reading: 0.1,
      project_work: 0.7,
    }[ev.type] ?? 0.5
  );
}
function daysBetween(fromISO, toISO) {
  const a = new Date(fromISO).getTime();
  const b = new Date(toISO).getTime();
  return (b - a) / 86400000;
}
function factorRecency(ev, nowISO) {
  const dd = Math.max(0, daysBetween(ev.occurred_at, nowISO));
  return Math.max(0.3, Math.exp(-dd / 90));
}

function weight(ev, nowISO) {
  return (
    factorDifficulty(ev) *
    factorIndependence(ev) *
    factorNovelty(ev) *
    factorReliability(ev) *
    factorRecency(ev, nowISO)
  );
}

// 校准锚点:~5 条扎实的独立证据(每条 w≈0.5,Σw≈2.5)、跨 ≥3 个场景 → confidence ≈ 0.70。
// k 越小,置信度随证据量上升越快。半饱和权重 k=1.5:saturation(1.5)≈0.63,saturation(3)≈0.86。
const SATURATION_HALF_WEIGHT = 1.5;
function saturation(W) {
  return 1 - Math.exp(-W / SATURATION_HALF_WEIGHT);
}
function diversity(uniqueContexts) {
  return 0.5 + 0.5 * (Math.min(uniqueContexts, 4) / 4);
}

// ---------------------------------------------------------------------------
// commands
// ---------------------------------------------------------------------------
function goalTemplate(goalId, title, createdAt, rubricId) {
  return `# goal.yaml — 目标定义 + Requirement Model(优化问题里的目标状态 x*)
# requirements 由 Agent 协助起草、你确认后生效;每条 (capability, dimension) 一行。
goal_id: ${goalId}
title: ${title}
created_at: ${createdAt}
target_date:            # 可选,YYYY-MM-DD

rubric_version: ${rubricId}   # 指向 rubric/${rubricId}.yaml

requirements:
  # 占位示例,请替换成你的真实目标(capability 必须在 rubric 中定义):
  - capability: example_capability
    dimension: transfer        # recall|application|transfer
    required: 0.75             # 目标水平 0-1
    weight: 0.9                # 重要度 0-1
    critical: true             # 门槛项:不达标则整体不达标
`;
}

function rubricTemplate(rubricId) {
  return `# rubric/${rubricId}.yaml — 评估规约(Observation 提取的唯一依据)
# 锚点要具体到"可判定的行为",不给 LLM 自由发挥。result: pass=1.0 partial=0.5 fail=0.0(±0.2 可微调)
rubric_id: ${rubricId}
capabilities:
  # 占位示例,请替换成你的真实能力与行为锚点:
  - id: example_capability
    name: 示例能力
    anchors:
      - dimension: recall
        pass: 无提示即能准确解释该能力的核心概念与关键机制
        partial: 提示后能解释,或解释遗漏关键点
        fail: 无法解释或存在原理性错误
      - dimension: application
        pass: 在熟悉/已知类型的场景中能正确运用并完成任务
        partial: 能运用但有明显缺漏
        fail: 熟悉场景中也无法正确运用
      - dimension: transfer
        pass: 在陌生场景中主动运用并给出正确方案
        partial: 能运用但方案有明显漏洞
        fail: 未能识别可运用之处
`;
}

function cmdInit(positional, flags) {
  // --workspace <dir> is the target to scaffold; unlike other commands it may
  // not exist yet, so init resolves the path itself rather than via ws().
  const dir = flags.workspace || flags.w || positional[0];
  if (!dir) die("usage: init --workspace <dir> [--title <t>] [--goal-id <id>] [--rubric <rubric-id>] [--created-at <YYYY-MM-DD>]");
  const abs = resolve(String(dir));
  const goalId = flags["goal-id"] ? String(flags["goal-id"]) : basename(abs);
  const rubricId = flags.rubric ? String(flags.rubric) : `${goalId}-v0.1`;
  const title = flags.title ? String(flags.title) : goalId;
  const createdAt = flags["created-at"] ? String(flags["created-at"]) : new Date().toISOString().slice(0, 10);

  const goalPath = join(abs, "goal.yaml");
  if (existsSync(goalPath)) die(`refusing to overwrite existing workspace: ${goalPath} already exists`);

  mkdirSync(join(abs, "rubric"), { recursive: true });
  mkdirSync(join(abs, "artifacts"), { recursive: true });
  mkdirSync(join(abs, "data"), { recursive: true });
  writeFileSync(join(abs, "artifacts", ".gitkeep"), "");
  writeFileSync(join(abs, "rubric", `${rubricId}.yaml`), rubricTemplate(rubricId));
  writeFileSync(goalPath, goalTemplate(goalId, title, createdAt, rubricId));

  process.stdout.write(
    `initialized workspace at ${abs}\n` +
      `  goal.yaml                 编辑 title/target_date,填写真实 requirements\n` +
      `  rubric/${rubricId}.yaml   定义 capabilities × dimension 行为锚点\n` +
      `  artifacts/                把原始表现文件放这里\n` +
      `  (data/ state/ 由 record/assess 自动创建)\n` +
      `next: 与 Agent 一起起草 goal.yaml 的 requirements 和 rubric 锚点(你确认后生效),再 record 第一次表现。\n`
  );
}

function cmdList(positional, flags) {
  // Cross-goal management view (SPEC §3): enumerate every workspace under a
  // parent directory and summarize its gaps. Read-only and deterministic; it
  // writes nothing and touches no state/ (outside INV-2's projection scope).
  // A workspace is any directory containing goal.yaml. --root may itself be a
  // single workspace (has goal.yaml) or the parent of several.
  const root = flags.root || flags.workspace || flags.w || positional[0];
  if (!root) die("usage: list --root <dir> [--json]   (dir = a goal workspace or the parent of several)");
  const rootAbs = resolve(String(root));
  if (!existsSync(rootAbs)) die(`directory not found: ${rootAbs}`);

  const wsDirs = [];
  if (existsSync(join(rootAbs, "goal.yaml"))) {
    wsDirs.push(rootAbs);
  } else {
    for (const ent of readdirSync(rootAbs, { withFileTypes: true })) {
      if (!ent.isDirectory()) continue;
      const child = join(rootAbs, ent.name);
      if (existsSync(join(child, "goal.yaml"))) wsDirs.push(child);
    }
  }
  if (wsDirs.length === 0) die(`no goals found under ${rootAbs} (looked for goal.yaml)`);

  const goals = wsDirs.map((dir) => summarizeGoal(dir));
  // Deterministic ordering that surfaces urgency: unmet-critical first, then
  // highest top-gap priority, unassessed last, tiebreak by goal_id.
  goals.sort((a, b) => {
    const ac = a.critical_unmet > 0 ? 1 : 0;
    const bc = b.critical_unmet > 0 ? 1 : 0;
    if (ac !== bc) return bc - ac;
    const ap = a.top_gap ? a.top_gap.priority : -1;
    const bp = b.top_gap ? b.top_gap.priority : -1;
    if (ap !== bp) return bp - ap;
    return String(a.goal_id).localeCompare(String(b.goal_id));
  });

  if (flags.json) {
    process.stdout.write(JSON.stringify({ root: rootAbs, goals }, null, 2) + "\n");
    return;
  }

  const todayISO = new Date().toISOString().slice(0, 10);
  const L = [];
  L.push(`goals under ${rootAbs} (${goals.length} found):`);
  for (const g of goals) {
    L.push("");
    L.push(`  ${g.goal_id}   ${g.title}`);
    const meta = [];
    if (g.target_date) {
      const dleft = Math.round(daysBetween(todayISO, g.target_date));
      meta.push(`target ${g.target_date}${Number.isFinite(dleft) ? ` (${dleft}d left)` : ""}`);
    }
    if (!g.assessed) {
      L.push(`    (unassessed — run: goal.mjs assess --workspace ${g.workspace})`);
      if (meta.length) L.push(`    ${meta.join("   ")}`);
      continue;
    }
    meta.push(`assessed as_of ${g.as_of}`);
    L.push(`    ${meta.join("   ")}`);
    L.push(`    requirements ${g.requirements} | open ${g.open_gaps} | critical unmet ${g.critical_unmet}`);
    if (g.top_gap) {
      const t = g.top_gap;
      L.push(`    top gap  ${t.capability}.${t.dimension}  gap ${t.gap}  priority ${t.priority}  [${t.mode}]`);
    } else {
      L.push(`    ✓ all requirements met`);
    }
  }
  process.stdout.write(L.join("\n") + "\n");
}

// Read-only summary of one workspace: goal metadata + gap overview from the
// last assess. Missing state/gap.json means it was never assessed.
function summarizeGoal(wsDir) {
  const goal = loadGoal(wsDir);
  const gapPath = join(wsDir, "state", "gap.json");
  const base = {
    goal_id: goal.goal_id ?? basename(wsDir),
    title: goal.title ?? goal.goal_id ?? basename(wsDir),
    workspace: wsDir,
    target_date: goal.target_date ?? null,
    requirements: (goal.requirements || []).length,
  };
  if (!existsSync(gapPath)) {
    return { ...base, assessed: false, as_of: null, open_gaps: 0, critical_unmet: 0, top_gap: null };
  }
  const gapDoc = JSON.parse(readFileSync(gapPath, "utf8"));
  const gaps = gapDoc.gaps || [];
  const open = gaps.filter((g) => g.gap > 0);
  const criticalUnmet = open.filter((g) => g.critical).length;
  // gaps are already sorted (critical first, then priority desc) by assess.
  const t = open[0];
  return {
    ...base,
    assessed: true,
    as_of: gapDoc.as_of ?? null,
    open_gaps: open.length,
    critical_unmet: criticalUnmet,
    top_gap: t
      ? { capability: t.capability, dimension: t.dimension, gap: t.gap, priority: t.priority, mode: t.mode }
      : null,
  };
}

function cmdRecord(flags) {
  const wsDir = ws(flags);
  const dataDir = join(wsDir, "data");
  mkdirSync(dataDir, { recursive: true });
  const events = readJsonl(join(dataDir, "events.jsonl"));
  const { active } = splitEvents(events);

  const artifact = flags.artifact;
  if (!artifact) die("--artifact <path relative to workspace> is required");
  const artAbs = join(wsDir, String(artifact));
  if (!existsSync(artAbs)) die(`artifact not found: ${artAbs}`);

  if (!flags.type) die("--type is required");
  if (flags.type === "retraction") die("use the retract subcommand, not record --type retraction");
  if (!flags["occurred-at"]) die("--occurred-at <ISO8601> is required");
  // novelty is derived from history (§4.4.2), never self-reported.
  if (flags.novelty) die("--novelty is not accepted: novelty is derived from history (use --variant to claim a variant task)");

  const topic = String(flags.topic ?? "");
  const ev = {
    schema: "event-v2",
    event_id: nextId(events, "event_id", "evt_"),
    type: String(flags.type),
    occurred_at: String(flags["occurred-at"]),
    ...(flags.session ? { session_id: String(flags.session) } : {}),
    task: {
      topic,
      difficulty: flags.difficulty !== undefined ? Number(flags.difficulty) : 0.5, // claim, not fact (§4.4)
      duration_minutes: flags.duration !== undefined ? Number(flags.duration) : null, // actual time spent
      novelty: deriveNovelty(active, topic, flags.variant === true || flags.variant === "true"),
    },
    conditions: {
      time_limit: flags["time-limit"] === true || flags["time-limit"] === "true",
      hints: flags.hints === true || flags.hints === "true",
      external_materials: flags.materials === true || flags.materials === "true",
      evaluator: String(flags.evaluator ?? "agent"),
    },
    artifacts: [String(artifact)],
    artifact_sha256: [sha256File(artAbs)],
  };
  appendFileSync(join(dataDir, "events.jsonl"), JSON.stringify(ev) + "\n");
  process.stdout.write(`${ev.event_id}\n`);
}

function cmdRetract(positional, flags) {
  const wsDir = ws(flags);
  const eventId = positional[0];
  if (!eventId) die("usage: retract <event_id> --reason <text>");
  if (!flags.reason) die("--reason <text> is required");
  const dataDir = join(wsDir, "data");
  const events = readJsonl(join(dataDir, "events.jsonl"));
  const target = events.find((e) => e.event_id === eventId);
  if (!target) die(`event not found: ${eventId}`);
  if (target.type === "retraction") die("cannot retract a retraction");
  const { retracted } = splitEvents(events);
  if (retracted.has(eventId)) die(`event already retracted: ${eventId}`);
  if (!flags["occurred-at"]) die("--occurred-at <ISO8601> is required");

  const ev = {
    schema: "event-v2",
    event_id: nextId(events, "event_id", "evt_"),
    type: "retraction",
    occurred_at: String(flags["occurred-at"]),
    refers_to: eventId,
    reason: String(flags.reason),
  };
  appendFileSync(join(dataDir, "events.jsonl"), JSON.stringify(ev) + "\n");
  process.stdout.write(`${ev.event_id} (retracts ${eventId}; its observations are now excluded)\n`);
}

function cmdObserve(positional, flags) {
  const wsDir = ws(flags);
  const eventId = positional[0];
  if (!eventId) die("usage: observe <event_id> [--write]");
  const dataDir = join(wsDir, "data");
  const events = readJsonl(join(dataDir, "events.jsonl"));
  const ev = events.find((e) => e.event_id === eventId);
  if (!ev) die(`event not found: ${eventId}`);
  if (ev.type === "retraction") die(`${eventId} is a retraction event; nothing to observe`);
  const { retracted } = splitEvents(events);
  if (retracted.has(eventId)) die(`event ${eventId} has been retracted; re-record before observing`);
  verifyArtifacts(wsDir, ev); // hard fail if the artifact changed since record (INV-3)

  const goal = loadGoal(wsDir);
  const rubricVersion = goal.rubric_version;
  const rubric = loadRubric(wsDir, rubricVersion);

  if (!flags.write) {
    // PRINT MODE: hand raw artifact + rubric to the agent (observer).
    // The agent sees NO prior scores (anti-anchoring, salvaged from old evaluator discipline).
    const out = {
      event: ev,
      rubric_version: rubricVersion,
      rubric,
      artifacts: ev.artifacts.map((rel) => ({
        path: rel,
        content: readFileSync(join(wsDir, rel), "utf8"),
      })),
    };
    process.stdout.write(JSON.stringify(out, null, 2) + "\n");
    return;
  }

  // WRITE MODE: read observation JSON (single object or array) from stdin,
  // validate against rubric, append with assigned obs_id.
  const stdin = readFileSync(0, "utf8");
  let payload;
  try {
    payload = JSON.parse(stdin);
  } catch (e) {
    die(`invalid JSON on stdin: ${e.message}`);
  }
  const drafts = Array.isArray(payload) ? payload : [payload];

  const rubricCaps = {};
  for (const cap of rubric.capabilities || []) {
    rubricCaps[cap.id] = new Set((cap.anchors || []).map((a) => a.dimension));
  }

  const obsPath = join(dataDir, "observations.jsonl");
  const existing = readJsonl(obsPath);
  const toAppend = [];
  for (const d of drafts) {
    if (d.event_id !== eventId) die(`observation event_id ${d.event_id} != ${eventId}`);
    if (!rubricCaps[d.capability]) die(`capability "${d.capability}" not in rubric ${rubricVersion}`);
    if (!rubricCaps[d.capability].has(d.dimension))
      die(`dimension "${d.dimension}" not defined for capability "${d.capability}" in rubric`);
    if (typeof d.result !== "number" || d.result < 0 || d.result > 1)
      die(`result must be a number in [0,1], got ${JSON.stringify(d.result)}`);
    if (!d.evidence || typeof d.evidence !== "string") die("evidence (string) is required");
    // INV-3: the citation must point at a real, non-empty location inside one of
    // this event's artifacts — not merely match a regex shape. We verify the path,
    // the line range, and that the cited span actually contains text. (We do NOT
    // force `evidence` to be a literal substring: §4.5 allows a paraphrase/概括.)
    const ref = String(d.artifact_ref || "");
    const rm = ref.match(/^(.*)#L(\d+)(?:-L(\d+))?$/);
    if (!rm) die(`artifact_ref must be "<path>#L<n>" or "<path>#L<n>-L<m>", got ${JSON.stringify(d.artifact_ref)}`);
    const refPath = rm[1];
    const refStart = parseInt(rm[2], 10);
    const refEnd = rm[3] ? parseInt(rm[3], 10) : refStart;
    if (!ev.artifacts.includes(refPath))
      die(`artifact_ref path "${refPath}" is not one of ${eventId}'s artifacts: ${ev.artifacts.join(", ")}`);
    if (refEnd < refStart) die(`artifact_ref range end < start: ${ref}`);
    const refLines = readFileSync(join(wsDir, refPath), "utf8").split("\n");
    if (refStart < 1 || refEnd > refLines.length)
      die(`artifact_ref lines ${refStart}-${refEnd} out of range (file has ${refLines.length} lines): ${ref}`);
    if (refLines.slice(refStart - 1, refEnd).join("\n").trim() === "")
      die(`artifact_ref ${ref} points at blank lines; cite the lines that actually contain the evidence`);

    const obs = {
      obs_id: nextId([...existing, ...toAppend], "obs_id", "obs_"),
      event_id: d.event_id,
      capability: d.capability,
      dimension: d.dimension,
      result: d.result,
      evidence: d.evidence,
      artifact_ref: d.artifact_ref,
      rubric_version: rubricVersion,
      extractor: {
        model: d.extractor?.model ?? "unknown",
        prompt_version: d.extractor?.prompt_version ?? "observe-v0.1",
      },
      extracted_at: d.extracted_at ?? ev.occurred_at,
    };
    toAppend.push(obs);
  }
  for (const obs of toAppend) appendFileSync(obsPath, JSON.stringify(obs) + "\n");
  process.stdout.write(toAppend.map((o) => o.obs_id).join("\n") + "\n");
}

function activeObservations(observations, rubricVersion) {
  // Keep only the latest rubric version per (event_id, capability, dimension).
  // "Latest" is compared NUMERICALLY (semver-ish), not lexically, so v0.10 > v0.2
  // (a lexical string compare gets this backwards). Ties on version fall back to
  // the later extracted_at, then to file order (append-only → deterministic).
  const latest = new Map();
  for (const o of observations) {
    const key = `${o.event_id}|${o.capability}|${o.dimension}`;
    const prev = latest.get(key);
    if (!prev) {
      latest.set(key, o);
      continue;
    }
    const c = cmpVersion(o.rubric_version, prev.rubric_version);
    if (c > 0 || (c === 0 && String(o.extracted_at ?? "") >= String(prev.extracted_at ?? ""))) {
      latest.set(key, o);
    }
  }
  return [...latest.values()];
}

// Compare two rubric-version strings by their trailing numeric components
// (e.g. "system-design-v0.10" → [0,10]). Returns >0 if a is newer than b.
function versionKey(v) {
  const m = String(v ?? "").match(/(\d+(?:\.\d+)*)\s*$/);
  return m ? m[1].split(".").map((n) => parseInt(n, 10)) : [];
}
function cmpVersion(a, b) {
  const ka = versionKey(a);
  const kb = versionKey(b);
  const n = Math.max(ka.length, kb.length);
  for (let i = 0; i < n; i++) {
    const x = ka[i] ?? 0;
    const y = kb[i] ?? 0;
    if (x !== y) return x - y;
  }
  return 0;
}

function cmdAssess(flags) {
  const wsDir = ws(flags);
  const dataDir = join(wsDir, "data");
  const allEvents = readJsonl(join(dataDir, "events.jsonl"));
  const { active } = splitEvents(allEvents); // retracted events (and their observations) drop out (§4.4.3)
  const observations = activeObservations(
    readJsonl(join(dataDir, "observations.jsonl")),
    null
  );
  const goal = loadGoal(wsDir);
  // Map only active events: observations of retracted events find no event and are skipped.
  const eventById = new Map(active.map((e) => [e.event_id, e]));

  // Deterministic "now": max occurred_at across all events (retractions included
  // — they are facts too and advance the data's clock), or --as-of override.
  let nowISO = flags["as-of"] ? String(flags["as-of"]) : null;
  if (!nowISO) {
    nowISO = allEvents.reduce((acc, e) => (e.occurred_at > acc ? e.occurred_at : acc), allEvents[0]?.occurred_at ?? "1970-01-01T00:00:00Z");
  }

  // Group observations by (capability, dimension).
  const groups = new Map();
  for (const o of observations) {
    const key = `${o.capability}|${o.dimension}`;
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(o);
  }

  const capabilities = {};
  let latestEvent = "";
  for (const e of allEvents) if (e.event_id > latestEvent) latestEvent = e.event_id;

  for (const [key, obsList] of groups) {
    const [capability, dimension] = key.split("|");
    let sumW = 0;
    let sumWR = 0;
    let counted = 0;
    // Diversity contexts (§5.3): unique_contexts = min(unique topics, unique
    // sessions). Session key falls back to event_id when no session_id, so
    // legacy single-task events behave exactly as before.
    const topics = new Set();
    const sessions = new Set();
    for (const o of obsList) {
      const ev = eventById.get(o.event_id);
      if (!ev) continue; // retracted or unknown event → excluded
      const w = weight(ev, nowISO);
      sumW += w;
      sumWR += w * o.result;
      counted++;
      topics.add(ev.task?.topic ?? "");
      sessions.add(ev.session_id ?? ev.event_id);
    }
    if (counted === 0) continue; // all evidence retracted → no estimate
    const score = sumW > 0 ? sumWR / sumW : 0;
    const confidence = saturation(sumW) * diversity(Math.min(topics.size, sessions.size));
    if (!capabilities[capability]) capabilities[capability] = {};
    capabilities[capability][dimension] = {
      score: round(score),
      confidence: round(confidence),
      observation_count: counted,
    };
  }

  const capability = {
    estimator_version: "weighted-evidence-v0.2",
    as_of: nowISO,
    source_event_until: latestEvent,
    rubric_version: goal.rubric_version,
    capabilities,
  };

  // gap.json
  const gaps = [];
  for (const req of goal.requirements || []) {
    const cur = capabilities[req.capability]?.[req.dimension];
    const score = cur ? cur.score : 0;
    const confidence = cur ? cur.confidence : 0;
    const gap = Math.max(0, Number(req.required) - score);
    const priority = gap * Number(req.weight) * (0.5 + 0.5 * confidence);
    gaps.push({
      capability: req.capability,
      dimension: req.dimension,
      current: score,
      required: Number(req.required),
      gap: round(gap),
      weight: Number(req.weight),
      critical: Boolean(req.critical),
      confidence,
      priority: round(priority),
      mode: confidence < 0.4 ? "diagnose" : "train",
    });
  }
  // Sort: critical first, then by priority desc. Deterministic tiebreak by key.
  gaps.sort((a, b) => {
    if (a.critical !== b.critical) return a.critical ? -1 : 1;
    if (b.priority !== a.priority) return b.priority - a.priority;
    return `${a.capability}.${a.dimension}`.localeCompare(`${b.capability}.${b.dimension}`);
  });

  const gapDoc = { as_of: nowISO, against: `goal.yaml`, gaps };

  const stateDir = join(wsDir, "state");
  mkdirSync(stateDir, { recursive: true });
  writeFileSync(join(stateDir, "capability.json"), JSON.stringify(capability, null, 2) + "\n");
  writeFileSync(join(stateDir, "gap.json"), JSON.stringify(gapDoc, null, 2) + "\n");
  process.stdout.write(
    `assessed ${groups.size} (capability,dimension) pairs; state written (as_of=${nowISO})\n`
  );
}

function cmdExplain(positional, flags) {
  const wsDir = ws(flags);
  const target = positional[0];
  if (!target || !target.includes(".")) die("usage: explain <capability>.<dimension>");
  const [capability, dimension] = target.split(".");
  const dataDir = join(wsDir, "data");
  const stateDir = join(wsDir, "state");

  const capPath = join(stateDir, "capability.json");
  if (!existsSync(capPath)) die("state/capability.json missing — run assess first");
  const capDoc = JSON.parse(readFileSync(capPath, "utf8"));
  const cur = capDoc.capabilities?.[capability]?.[dimension];
  if (!cur) die(`no estimate for ${target}`);

  const gapDoc = existsSync(join(stateDir, "gap.json"))
    ? JSON.parse(readFileSync(join(stateDir, "gap.json"), "utf8"))
    : { gaps: [] };
  const gapRow = gapDoc.gaps.find((g) => g.capability === capability && g.dimension === dimension);

  const allEvents = readJsonl(join(dataDir, "events.jsonl"));
  const { active, retractions } = splitEvents(allEvents);
  const eventById = new Map(active.map((e) => [e.event_id, e]));
  const observations = activeObservations(readJsonl(join(dataDir, "observations.jsonl")), null).filter(
    (o) => o.capability === capability && o.dimension === dimension
  );
  const nowISO = capDoc.as_of;

  const rows = observations
    .map((o) => {
      const ev = eventById.get(o.event_id);
      return { o, ev, w: ev ? weight(ev, nowISO) : 0 };
    })
    .filter((r) => r.ev) // observations of retracted events are excluded from the chain
    .sort((a, b) => b.w - a.w);
  for (const { ev } of rows) verifyArtifacts(wsDir, ev); // hard fail if any cited artifact was tampered with

  const L = [];
  L.push(`能力  ${capability}.${dimension}`);
  L.push(`估计  score ${cur.score}   confidence ${cur.confidence}   (${cur.observation_count} 条证据)`);
  if (gapRow) {
    L.push(
      `目标  required ${gapRow.required}${gapRow.critical ? " (critical 门槛)" : ""}  →  gap ${gapRow.gap}  |  mode: ${gapRow.mode}  |  priority ${gapRow.priority}`
    );
  }
  L.push("");
  L.push("支撑该判断的证据(按权重排序):");
  for (const { o, ev, w } of rows) {
    const dd = ev ? Math.max(0, daysBetween(ev.occurred_at, nowISO)).toFixed(0) : "?";
    L.push(
      `  • ${ev?.occurred_at?.slice(0, 10) ?? "?"}  [${ev?.type ?? "?"}]  result ${o.result}  weight ${round(w, 3)}`
    );
    L.push(`      w = difficulty ${round(factorDifficulty(ev), 2)} × independence ${round(factorIndependence(ev), 2)} × novelty ${round(factorNovelty(ev), 2)} × reliability ${round(factorReliability(ev), 2)} × recency ${round(factorRecency(ev, nowISO), 2)}  (${dd}d ago)`);
    L.push(`      “${o.evidence}”`);
    L.push(`      → ${o.artifact_ref}`);
  }
  L.push("");
  // Confidence explanation (§5.3: unique_contexts = min(topics, sessions))
  const sumW = rows.reduce((a, r) => a + r.w, 0);
  const topics = new Set(rows.map((r) => r.ev?.task?.topic));
  const sessions = new Set(rows.map((r) => r.ev?.session_id ?? r.ev?.event_id));
  const uniqueContexts = Math.min(topics.size, sessions.size);
  L.push("置信度为何不是更高?");
  L.push(`  • 有效证据量 Σw = ${round(sumW, 3)}  →  saturation = ${round(saturation(sumW), 3)}`);
  L.push(`  • 场景多样性 = min(${topics.size} topic, ${sessions.size} 场次) = ${uniqueContexts} (${[...topics].join(", ")})  →  diversity = ${round(diversity(uniqueContexts), 3)}`);
  L.push(`  • confidence = saturation × diversity = ${cur.confidence}`);
  if (gapRow && gapRow.mode === "diagnose") {
    L.push(`  ⚠ confidence < 0.4:建议先做诊断型任务补证据,而非直接训练。`);
  }
  // Surface retractions affecting this capability.dimension, if any.
  const retractedHere = retractions.filter((r) =>
    readJsonl(join(dataDir, "observations.jsonl")).some(
      (o) => o.event_id === r.refers_to && o.capability === capability && o.dimension === dimension
    )
  );
  if (retractedHere.length > 0) {
    L.push("");
    L.push("撤销记录(其证据已排除):");
    for (const r of retractedHere) {
      L.push(`  • ${r.occurred_at.slice(0, 10)}  ${r.refers_to} 被撤销:${r.reason ?? "(无理由)"}`);
    }
  }
  process.stdout.write(L.join("\n") + "\n");
}

function cmdNext(flags) {
  const wsDir = ws(flags);
  const stateDir = join(wsDir, "state");
  const gapPath = join(stateDir, "gap.json");
  if (!existsSync(gapPath)) die("state/gap.json missing — run assess first");
  const gapDoc = JSON.parse(readFileSync(gapPath, "utf8"));
  const goal = loadGoal(wsDir);
  const validTargets = new Set((goal.requirements || []).map((r) => `${r.capability}.${r.dimension}`));

  if (!flags.write) {
    // PRINT MODE: the deterministic half of `next` — the priority-sorted
    // shortlist of actionable gaps (gap > 0), already ranked by assess
    // (critical first, then priority desc). The agent designs tasks from this.
    const top = Number(flags.top ?? 3);
    const actionable = gapDoc.gaps.filter((g) => g.gap > 0).slice(0, top);
    process.stdout.write(
      JSON.stringify({ top, actionable_gaps: actionable }, null, 2) + "\n"
    );
    return;
  }

  // WRITE MODE: the agent's designed plan (array of actions) from stdin.
  // plan.json is a DECISION artifact (§1.2 Gap→Plan), not a projection — it is
  // written here, never by assess, and is NOT covered by INV-2's byte-identical
  // recompute (which is over capability.json + gap.json only).
  const stdin = readFileSync(0, "utf8");
  let payload;
  try {
    payload = JSON.parse(stdin);
  } catch (e) {
    die(`invalid JSON on stdin: ${e.message}`);
  }
  const actions = Array.isArray(payload) ? payload : [payload];
  if (actions.length < 1) die("plan must contain at least one action");
  if (actions.length > 3) die(`next designs at most 3 focused actions (got ${actions.length})`);

  const out = [];
  actions.forEach((a, i) => {
    if (!a.task || typeof a.task !== "string") die(`action ${i + 1}: task (string) is required`);
    if (!a.rationale || typeof a.rationale !== "string") die(`action ${i + 1}: rationale (string) is required`);
    if (a.mode !== "diagnose" && a.mode !== "train")
      die(`action ${i + 1}: mode must be "diagnose" or "train", got ${JSON.stringify(a.mode)}`);
    if (!Array.isArray(a.targets) || a.targets.length === 0)
      die(`action ${i + 1}: targets [{capability,dimension}] is required`);
    for (const t of a.targets) {
      const key = `${t.capability}.${t.dimension}`;
      if (!validTargets.has(key)) die(`action ${i + 1}: target ${key} is not a requirement in goal.yaml`);
    }
    if (a.estimated_minutes !== undefined && (typeof a.estimated_minutes !== "number" || a.estimated_minutes < 0))
      die(`action ${i + 1}: estimated_minutes must be a non-negative number`);
    // No ΔCapability / expected-gain field is accepted (§6.6: rank, don't fabricate deltas).
    out.push({
      rank: i + 1,
      task: a.task,
      targets: a.targets.map((t) => ({ capability: t.capability, dimension: t.dimension })),
      mode: a.mode,
      rationale: a.rationale,
      ...(a.estimated_minutes !== undefined ? { estimated_minutes: a.estimated_minutes } : {}),
    });
  });

  const planDoc = {
    generated_at: flags["generated-at"] ? String(flags["generated-at"]) : new Date().toISOString(),
    against: "gap.json",
    actions: out,
  };
  mkdirSync(stateDir, { recursive: true });
  writeFileSync(join(stateDir, "plan.json"), JSON.stringify(planDoc, null, 2) + "\n");
  process.stdout.write(`wrote ${out.length} action(s) to state/plan.json\n`);
}

// ---------------------------------------------------------------------------
// dispatch
// ---------------------------------------------------------------------------
const { positional, flags } = parseArgs(process.argv.slice(2));
const sub = positional.shift();
switch (sub) {
  case "init":
    cmdInit(positional, flags);
    break;
  case "list":
    cmdList(positional, flags);
    break;
  case "record":
    cmdRecord(flags);
    break;
  case "retract":
    cmdRetract(positional, flags);
    break;
  case "observe":
    cmdObserve(positional, flags);
    break;
  case "assess":
    cmdAssess(flags);
    break;
  case "explain":
    cmdExplain(positional, flags);
    break;
  case "next":
    cmdNext(flags);
    break;
  default:
    die(`unknown subcommand: ${sub ?? "(none)"}\nusage: goal.mjs <init|list|record|retract|observe|assess|explain|next> --workspace <dir> ...`);
}
