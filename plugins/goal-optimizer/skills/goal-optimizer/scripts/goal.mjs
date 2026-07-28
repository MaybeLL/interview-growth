#!/usr/bin/env node
// goal-optimizer demo CLI — deterministic core (INV-5: no LLM here, numbers only).
// Subcommands: record | observe | assess | explain
//
// Design notes:
// - Facts (events.jsonl, observations.jsonl, artifacts/) are append-only (INV-1).
// - state/ (capability.json, gap.json) is fully derived and recomputable (INV-2):
//     rm -rf state/ && node goal.mjs assess  must reproduce byte-identical output.
//   To make assess a pure function of its inputs, "now" for recency decay is NOT
//   wall-clock; it is max(occurred_at) across events (override with --as-of).

import { readFileSync, writeFileSync, existsSync, mkdirSync, appendFileSync, readdirSync } from "node:fs";
import { join, resolve, dirname } from "node:path";

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
function cmdRecord(flags) {
  const wsDir = ws(flags);
  const dataDir = join(wsDir, "data");
  mkdirSync(dataDir, { recursive: true });
  const events = readJsonl(join(dataDir, "events.jsonl"));

  const artifact = flags.artifact;
  if (!artifact) die("--artifact <path relative to workspace> is required");
  const artAbs = join(wsDir, String(artifact));
  if (!existsSync(artAbs)) die(`artifact not found: ${artAbs}`);

  if (!flags.type) die("--type is required");
  if (!flags["occurred-at"]) die("--occurred-at <ISO8601> is required");

  const ev = {
    event_id: nextId(events, "event_id", "evt_"),
    type: String(flags.type),
    occurred_at: String(flags["occurred-at"]),
    task: {
      topic: String(flags.topic ?? ""),
      difficulty: flags.difficulty !== undefined ? Number(flags.difficulty) : 0.5,
      duration_minutes: flags.duration !== undefined ? Number(flags.duration) : null,
      novelty: String(flags.novelty ?? "familiar"),
    },
    conditions: {
      time_limit: flags["time-limit"] === true || flags["time-limit"] === "true",
      hints: flags.hints === true || flags.hints === "true",
      external_materials: flags.materials === true || flags.materials === "true",
      evaluator: String(flags.evaluator ?? "agent"),
    },
    artifacts: [String(artifact)],
  };
  appendFileSync(join(dataDir, "events.jsonl"), JSON.stringify(ev) + "\n");
  process.stdout.write(`${ev.event_id}\n`);
}

function cmdObserve(positional, flags) {
  const wsDir = ws(flags);
  const eventId = positional[0];
  if (!eventId) die("usage: observe <event_id> [--write]");
  const dataDir = join(wsDir, "data");
  const events = readJsonl(join(dataDir, "events.jsonl"));
  const ev = events.find((e) => e.event_id === eventId);
  if (!ev) die(`event not found: ${eventId}`);

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
    if (!/#L\d+(-L\d+)?$/.test(String(d.artifact_ref || "")))
      die(`artifact_ref must end with #L<n> or #L<n>-L<m>, got ${JSON.stringify(d.artifact_ref)}`);

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
  // In the demo all observations share one rubric version; this future-proofs it.
  const latest = new Map();
  for (const o of observations) {
    const key = `${o.event_id}|${o.capability}|${o.dimension}`;
    const prev = latest.get(key);
    if (!prev || String(o.rubric_version) >= String(prev.rubric_version)) latest.set(key, o);
  }
  return [...latest.values()];
}

function cmdAssess(flags) {
  const wsDir = ws(flags);
  const dataDir = join(wsDir, "data");
  const events = readJsonl(join(dataDir, "events.jsonl"));
  const observations = activeObservations(
    readJsonl(join(dataDir, "observations.jsonl")),
    null
  );
  const goal = loadGoal(wsDir);
  const eventById = new Map(events.map((e) => [e.event_id, e]));

  // Deterministic "now": max occurred_at across events, or --as-of override.
  let nowISO = flags["as-of"] ? String(flags["as-of"]) : null;
  if (!nowISO) {
    nowISO = events.reduce((acc, e) => (e.occurred_at > acc ? e.occurred_at : acc), events[0]?.occurred_at ?? "1970-01-01T00:00:00Z");
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
  for (const e of events) if (e.event_id > latestEvent) latestEvent = e.event_id;

  for (const [key, obsList] of groups) {
    const [capability, dimension] = key.split("|");
    let sumW = 0;
    let sumWR = 0;
    const contexts = new Set();
    for (const o of obsList) {
      const ev = eventById.get(o.event_id);
      if (!ev) continue;
      const w = weight(ev, nowISO);
      sumW += w;
      sumWR += w * o.result;
      contexts.add(ev.task?.topic ?? "");
    }
    const score = sumW > 0 ? sumWR / sumW : 0;
    const confidence = saturation(sumW) * diversity(contexts.size);
    if (!capabilities[capability]) capabilities[capability] = {};
    capabilities[capability][dimension] = {
      score: round(score),
      confidence: round(confidence),
      observation_count: obsList.length,
    };
  }

  const capability = {
    estimator_version: "weighted-evidence-v0.1",
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

  const events = readJsonl(join(dataDir, "events.jsonl"));
  const eventById = new Map(events.map((e) => [e.event_id, e]));
  const observations = activeObservations(readJsonl(join(dataDir, "observations.jsonl")), null).filter(
    (o) => o.capability === capability && o.dimension === dimension
  );
  const nowISO = capDoc.as_of;

  const rows = observations
    .map((o) => {
      const ev = eventById.get(o.event_id);
      return { o, ev, w: ev ? weight(ev, nowISO) : 0 };
    })
    .sort((a, b) => b.w - a.w);

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
  // Confidence explanation
  const sumW = rows.reduce((a, r) => a + r.w, 0);
  const contexts = new Set(rows.map((r) => r.ev?.task?.topic));
  L.push("置信度为何不是更高?");
  L.push(`  • 有效证据量 Σw = ${round(sumW, 3)}  →  saturation = ${round(saturation(sumW), 3)}`);
  L.push(`  • 场景多样性 = ${contexts.size} 个不同 topic (${[...contexts].join(", ")})  →  diversity = ${round(diversity(contexts.size), 3)}`);
  L.push(`  • confidence = saturation × diversity = ${cur.confidence}`);
  if (gapRow && gapRow.mode === "diagnose") {
    L.push(`  ⚠ confidence < 0.4:建议先做诊断型任务补证据,而非直接训练。`);
  }
  process.stdout.write(L.join("\n") + "\n");
}

// ---------------------------------------------------------------------------
// dispatch
// ---------------------------------------------------------------------------
const { positional, flags } = parseArgs(process.argv.slice(2));
const sub = positional.shift();
switch (sub) {
  case "record":
    cmdRecord(flags);
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
  default:
    die(`unknown subcommand: ${sub ?? "(none)"}\nusage: goal.mjs <record|observe|assess|explain> --workspace <dir> ...`);
}
