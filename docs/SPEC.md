# Goal Optimization System — v1 Spec

> 状态:Draft(待评审)
> 版本:spec-v0.1

---

## 1. 定位

**一个以"目标"为中心、以"能力"为状态、以"证据"为依据、以"优化"为核心循环的个人能力操作系统(Personal Capability Operating System)。**

它不关心用户学了什么,而关心:

> 用户距离目标还有多远,以及下一单位时间投入在哪里,能最大幅度缩小与目标之间的差距?

系统本质是一个作用于人的优化循环:

```
Observe(记录表现) → Evaluate(评估能力) → Optimize(找最优行动) → Execute(执行) → Observe...
```

### 1.1 核心原则

1. **目标驱动** — 一切围绕目标,而不是围绕知识点。
2. **能力建模** — 能力被显式表示为可观测的状态向量,不是黑盒。
3. **证据更新** — 能力分数不能主观填写,必须由表现证据驱动更新。
4. **优化优先** — 系统始终回答:下一步投入在哪里收益最大?
5. **本地优先** — 纯文本文件 + Git 即是全部事实源;Agent 只负责分析和更新;任何 Agent(Claude Code / Codex / Cursor)都可接入;用户拥有完整数据主权。

### 1.2 架构定性

**本地优先、事件溯源式的能力证据系统:原始表现不可覆盖,能力状态可以重新计算,任何能力判断都能追溯到具体证据。**

三个概念严格分离:

- **历史表现是事实**(Event + Artifact)
- **能力评估是对事实的推断**(Observation → Capability Projection)
- **下一步计划是基于推断做出的决策**(Gap → Plan)

### 1.3 v1 场景

只做一个极窄场景:**后端工程师系统设计面试**。不做通用考试、不做通用求职、不做能力本体。

---

## 2. 系统不变量(架构验收标准)

以下不变量必须始终成立,违反任何一条即为架构级 bug:

- **INV-1(事实不可变)** `artifacts/` 与 `data/events.jsonl` 只允许追加,永不覆盖、永不删除、永不改写。纠错的唯一路径是追加 `retraction` 事件(§4.4.3),而非修改历史。
- **INV-2(投影可再生)** `state/` 中的**确定性投影**(`capability.json`、`gap.json`)整体可再生:`rm -rf state/ && goal assess` 必须从 events + observations 完整重建,结果逐字节一致(确定性)。`state/plan.json` 是 Agent 决策产物(§1.2 Gap→Plan),由 `goal next` 重建而非 assess,**不在逐字节保证范围内**。
- **INV-3(证据链完整)** 每条 Observation 必须引用一个 event_id;每个 event 必须引用 artifact 路径并记录其内容哈希(`artifact_sha256`)。Observation 的 `artifact_ref` 在 `observe --write` 时被校验为指向**该 event artifact 内真实存在、非空的行段**(不仅格式合法),引用无法凭空捏造。任何能力结论都能沿链回溯到原始表现文本,且原文被篡改时可被发现(读取时校验哈希,不匹配即报错)。
- **INV-4(推断与事实皆带版本)** 每条 event 记录 schema 版本;每条 Observation 记录 rubric 版本 + 提取模型 + prompt 版本;每份 Projection 记录 estimator 版本 + 截止 event。能力数值变化必须能区分"用户变了"还是"评估标准变了"。event schema **只加字段、只加版本,永不改变旧字段语义**;旧数据就地保留原版本,永不迁移。
- **INV-5(职责分离)** LLM 负责理解、结构化、解释;确定性引擎负责权重、聚合、衰减、置信度计算。LLM 永远不直接产出能力分数。
- **INV-6(无外部依赖)** 全部状态存在纯文本文件(JSONL / YAML / JSON / Markdown)中。无数据库、无账号、无云同步。Git 即同步机制。

---

## 3. Workspace 布局

每个目标一个独立目录(workspace),互不影响。所有命令通过显式 `--workspace <dir>` 指向它——CLI **位置无关**,不探测"项目根",不硬编码存储位置。workspace 放哪由用户决定:

```
<workspace>/                  # --workspace 指向的任意目录
  goal.yaml                   # 目标定义 + Requirement Model(人工编辑,git 版本化)
  rubric/
    system-design-v0.1.yaml   # 评估规约,不可变;修订=新文件 v0.2
  artifacts/                  # 原始表现文本文件,只增不改(INV-1)
    interviews/
    answers/
  data/
    events.jsonl              # Event Store,append-only(INV-1)
    observations.jsonl        # 结构化观测,append-only
  state/                      # 派生,可随时重建;gitignore 可选
    capability.json           #   ↳ assess 确定性重建,逐字节一致(INV-2)
    gap.json                  #   ↳ 同上
    plan.json                 #   ↳ next 依据 gap + Agent 设计重建(决策产物,非逐字节)
  reports/                    # goal explain / progress 的人类可读输出
```

存储位置是**约定,不是行为**。两种典型摆法(工具都不关心,只认 `--workspace`):

- **独立成长仓库(推荐默认):** 数据即主角,goal 可见地放在根部,便于 git 追踪与浏览。
  ```
  my-growth/                  # 自身是一个 git 仓库
    backend-system-design/    # --workspace my-growth/backend-system-design
    toefl/                    # --workspace my-growth/toefl
  ```
- **寄居在宿主代码项目里:** 数据是配套,用 dotdir 收纳。
  ```
  some-code-repo/
    .goal-optimizer/backend-system-design/   # --workspace .goal-optimizer/backend-system-design
  ```

多个 goal 共享一个父目录是可以的(便于 `goal list` 枚举,§6.8),但每个 goal 仍是独立、可单独 commit 的单元。

---

## 4. 数据契约

### 4.1 能力维度(三维向量)

每项能力 `k` 的状态是一个三维向量,不是单一分数:

| 维度 | key | 含义 | 典型证据 |
|---|---|---|---|
| 回忆 | `recall` | 无提示能解释 | 口头/书面解释概念 |
| 应用 | `application` | 已知类型任务中能用 | 熟悉场景任务完成 |
| 迁移 | `transfer` | 陌生场景中能用 | 变式/跨业务任务 |

> `dimension` 在引擎中是开放字符串(rubric 定义什么维度就认什么维度,引擎不写死枚举)。v1 只用上表三维——它们正是系统设计面试真正考的层级;`exposure`/`recognition`/`automaticity` 属行为日志或需限时数据校准的维度,推迟到 v2 且不预置锚点。

约束:

- 维度间存在递进倾向但**不实现为硬约束**;v1 每条 Observation 只更新其显式声明的维度(跨维度软推断为 v2+)。
- 每个 `(capability, dimension)` 对独立维护 `score`(0–1)与 `confidence`(0–1)。低分 ≠ 低置信度:`score 0.3 / confidence 0.9` 表示"确定较弱";`score 0.3 / confidence 0.15` 表示"证据不足",此时最优行动是诊断而非训练。

### 4.2 goal.yaml — 目标与 Requirement Model

```yaml
goal_id: backend-system-design
title: 后端系统设计面试
created_at: 2026-07-01
target_date: 2026-10-01          # 可选

# Requirement Model:目标对每个 (capability, dimension) 的要求与权重
requirements:
  - capability: idempotency
    dimension: transfer
    required: 0.75               # 目标水平 (0-1)
    weight: 0.9                  # 该项对目标的重要度 (0-1)
    critical: true               # 门槛项:不达标则目标整体不达标
  - capability: communication_structure
    dimension: application
    required: 0.70
    weight: 0.7
    critical: false
  # ...

rubric_version: system-design-v0.1   # 当前使用的 rubric
```

规则:

- `requirements` 是人工定义并 git 版本化的(v1 由 Agent 辅助起草、用户批准);它就是优化问题中的目标状态 x*。
- 修改 requirements 直接 git commit,历史由 git 承载,不需要额外版本机制。

### 4.3 rubric/*.yaml — 评估规约(不可变)

Rubric 是 Observation 提取的依据,必须具体到**可判定的行为锚点**,不给 LLM 自由发挥空间:

```yaml
rubric_id: system-design-v0.1
capabilities:
  - id: idempotency
    name: 幂等设计
    anchors:
      - dimension: recall
        pass: 无提示说明幂等键的作用与实现方式
        partial: 提示后能解释
        fail: 无法解释或解释错误
      - dimension: transfer
        pass: 在陌生业务中主动识别重复提交风险并给出正确方案(含并发窗口)
        partial: 识别风险但方案有漏洞(如未区分 request_id 与业务意图)
        fail: 未识别风险
  # ...
```

规则:

- Rubric 文件一经引用即不可变;修订产生新文件(`v0.2`),旧 Observation 保留旧版本引用(INV-4)。
- 每个 anchor 的 pass/partial/fail 映射为 result 数值:pass=1.0,partial=0.5,fail=0.0(LLM 可在 ±0.2 内微调并说明理由)。

### 4.4 events.jsonl — 表现事件(第一层:事实)

事件层的准确定性是:**客观条件 + 明示的声明(claims)**。可测量的部分(时间、时长、conditions、artifact 哈希)是事实;无客观来源的部分(difficulty)以"记录时声明"的身份存在,SPEC 不假装它是事实。

**粒度规则:event = 一个任务(task),不是一场会话。** 一场 60 分钟、5 道题的模拟面试记 5 个 event——因为 difficulty/novelty/duration 都是任务级属性,压平到场次会失真。同场的 event 用可选的 `session_id` 关联(单题练习可不填);同场各 event 的 `conditions` 由记录方保持一致。artifact 可整场一份,不同 event 的 observation 引用不同行段。

每行一个 JSON 对象(schema `event-v2`):

```json
{
  "schema": "event-v2",
  "event_id": "evt_000042",
  "type": "mock_interview",
  "occurred_at": "2026-07-28T20:30:00+08:00",
  "session_id": "ses_2026-07-28-mock",
  "task": {
    "topic": "design_a_payment_system",
    "difficulty": 0.6,
    "duration_minutes": 45,
    "novelty": "unseen"
  },
  "conditions": {
    "time_limit": true,
    "hints": false,
    "external_materials": false,
    "evaluator": "agent"
  },
  "artifacts": ["artifacts/interviews/2026-07-28-payment.md"],
  "artifact_sha256": ["<sha256-of-file-content>"]
}
```

字段约束:

- `schema`:事件结构版本,当前 `event-v2`。引擎按版本分支解读;**只加字段、只加版本,永不改旧字段语义**。无 `schema` 字段的历史数据按 v1 语义解读(novelty 视为自报声明、无哈希则跳过校验),就地保留,永不迁移。
- `event_id`:单调递增,格式 `evt_` + 6 位零填充序号。
- `type` 枚举(v1):`mock_interview` | `practice` | `explanation` | `quiz` | `reading` | `real_interview` | `project_work` | `retraction`(见 §4.4.3)。
- `session_id`:可选。同一场次(一场面试/一次练习会话)的多个 event 共享同一值;置信度的场景多样性按 session 去重(§5.3),防止同场多题虚增多样性。
- `task.difficulty`:**记录时声明**(0–1)。v1 无客观标定来源,如实以声明身份参与权重;客观标定(题库/出题方随题带难度)推迟 v2。
- `task.novelty`:**引擎派生,record 不接受自报**(见 §4.4.2)。
- `task.duration_minutes`:**实际耗时**(客观事实)。任务是否限时属于 `conditions.time_limit`。v1 权重不消费它;它是 `automaticity` 维度(限时低错误率)的未来燃料——便宜且事后不可补的数据,倾向于记。
- `conditions` 记录独立性条件(是否限时/提示/查资料),供权重计算使用。`evaluator`(agent/human)v1 不参与计算,是 v2 evaluator_diversity 的预留。
- `artifact_sha256`:record 时对每个 artifact 内容计算 SHA-256,与 `artifacts` 一一对应。`observe`/`explain` 读取 artifact 时重算比对,**不匹配直接报错**(证据链公证,INV-3);救济路径是撤销后重录。
- **事件不含任何评价**。评价属于 Observation 层。
- 行为日志(如"阅读 30 分钟")可以记录为 `reading` 事件,但其证据权重天然极低(见 §5.1),系统关心的是表现证据而非行为日志。

#### 4.4.2 novelty 的派生规则

"见没见过"是用户历史的函数,系统持有全部历史,自报既多余又可污染(自报 unseen 权重 ×1.0 vs repeat ×0.25)。因此 novelty 由 `record` 从既有 events 确定性推导:

```
同 topic 的既往 event 数(不含 retraction、不含被撤销者):
  0 次        → unseen
  1 次        → familiar
  ≥2 次       → repeat
记录方可显式声明 --variant(题型是已知类型的变式)覆盖为 variant。
```

推导只依据 `task.topic` 精确匹配——这要求同一 workspace 内 topic 命名一致(由驱动 record 的 agent 负责规整)。

#### 4.4.3 retraction — 事实层的纠错路径

录入错误必然发生(难度打错、忘记 `--hints`、artifact 贴错)。INV-1 禁止改写,纠错的唯一方式是**追加撤销事件**:

```json
{
  "schema": "event-v2",
  "event_id": "evt_000043",
  "type": "retraction",
  "occurred_at": "2026-07-29T10:00:00+08:00",
  "refers_to": "evt_000042",
  "reason": "难度记错:实际应为 0.5"
}
```

语义:

- 聚合与解释时,被撤销的 event 及其**全部 observations** 不参与计算;`explain` 可展示撤销记录。
- 纠错流程 = `retract` + 重新 `record` 一条正确的。不支持字段级 patch,不支持撤销的撤销。
- 撤销本身也是一条事实("我在某时声明 evt_42 记错了"),append-only 完好。

### 4.5 observations.jsonl — 结构化观测(第二层:推断的中间产物)

每行一个 JSON 对象,由 LLM 按 rubric 从 event 的 artifact 中提取:

```json
{
  "obs_id": "obs_000107",
  "event_id": "evt_000042",
  "capability": "idempotency",
  "dimension": "transfer",
  "result": 0.4,
  "evidence": "未处理同一支付意图使用不同 request_id 的情况",
  "artifact_ref": "artifacts/interviews/2026-07-28-payment.md#L120-L145",
  "rubric_version": "system-design-v0.1",
  "extractor": {
    "model": "claude-sonnet-4-5",
    "prompt_version": "observe-v0.1"
  },
  "extracted_at": "2026-07-28T21:00:00+08:00"
}
```

字段约束:

- `result` ∈ [0, 1],由 rubric anchor 映射而来。
- `evidence` 为一句话摘录/概括;`artifact_ref` 必须指向 artifact 内具体位置(INV-3)。
- 同一 event 可产生多条 Observation(不同 capability × dimension)。
- Observation append-only:用新 rubric 重新提取时追加新记录,旧记录保留;聚合时同一 `(event_id, capability, dimension)` 只取最新 rubric 版本的记录。

### 4.6 state/capability.json — 能力投影(第三层:完全派生)

```json
{
  "estimator_version": "weighted-evidence-v0.2",
  "generated_at": "2026-07-28T21:05:00+08:00",
  "source_event_until": "evt_000042",
  "rubric_version": "system-design-v0.1",
  "capabilities": {
    "idempotency": {
      "recall":   { "score": 0.82, "confidence": 0.79, "observation_count": 4 },
      "transfer": { "score": 0.38, "confidence": 0.54, "observation_count": 3 }
    }
  }
}
```

### 4.7 state/gap.json — 差距分析(派生)

```json
{
  "generated_at": "2026-07-28T21:05:00+08:00",
  "against": "goal.yaml@<git-sha>",
  "gaps": [
    {
      "capability": "idempotency",
      "dimension": "transfer",
      "current": 0.38,
      "required": 0.75,
      "gap": 0.37,
      "weight": 0.9,
      "critical": true,
      "confidence": 0.54,
      "priority": 0.333,
      "mode": "train"
    }
  ]
}
```

### 4.8 state/plan.json — 行动计划(决策产物)

```json
{
  "generated_at": "2026-07-28T21:06:00+08:00",
  "against": "gap.json",
  "actions": [
    {
      "rank": 1,
      "task": "设计优惠券领取接口的重复提交保护",
      "targets": [{ "capability": "idempotency", "dimension": "transfer" }],
      "mode": "train",
      "rationale": "recall 已较高(0.82),缺口集中在 transfer;优惠券场景可验证跨业务迁移;兼具训练与诊断价值",
      "estimated_minutes": 20
    }
  ]
}
```

- 由 `goal next` 写入(Agent 设计、CLI 校验),**不由 assess 生成**;属于 §1.2 的"决策"层,不在 INV-2 逐字节保证内。
- `targets` 的每个 `(capability, dimension)` 必须是 goal.yaml 的 requirement;`mode ∈ {diagnose, train}`;至多 3 条 action。
- **v1 明确不输出 "预计提升 +0.8" 这类 ΔCapability 数值**——没有历史数据支撑,假精确破坏可信度。只做排序 + 文字理由。

---

## 5. 确定性估计引擎(estimator: weighted-evidence-v0.2)

### 5.1 单条证据权重

```
w = difficulty × independence × novelty × reliability × recency
```

各因子取值(全部 ∈ (0, 1],由 event 字段确定性映射,不经 LLM):

| 因子 | 来源 | 映射 |
|---|---|---|
| `difficulty` | event.task.difficulty | 直接取值,下限 0.2 |
| `independence` | event.conditions | 无提示且不查资料=1.0;有提示=0.5;跟随材料=0.2 |
| `novelty` | event.task.novelty(v2 起由 record 派生,§4.4.2) | unseen=1.0,variant=0.8,familiar=0.5,repeat=0.25 |
| `reliability` | event.type | mock_interview/real_interview=0.9,practice/explanation=0.7,quiz=0.5,reading=0.1 |
| `recency` | occurred_at | 指数衰减 `exp(-Δdays / 90)`,下限 0.3 |

### 5.2 分数聚合

对每个 `(capability, dimension)`,取全部有效 Observation(被撤销 event 的 observations 不参与,§4.4.3):

```
score = Σ(wᵢ × rᵢ) / Σ(wᵢ)
```

### 5.3 置信度(v1 从简,只用两个因子)

```
confidence = saturation(Σwᵢ) × diversity

saturation(W) = 1 − exp(−W / 1.5)      # 有效证据量:权重和越大越确定,边际递减
diversity     = 0.5 + 0.5 × min(unique_contexts, 4) / 4
                                        # 场景多样性,1 个场景封顶 0.625
unique_contexts = min(unique_topics, unique_sessions)
                                        # topic 去重 × 场次去重,取小
```

`unique_topics` = 不同 `task.topic` 数;`unique_sessions` = 不同场次数(场次键 = `session_id`,缺省时退化为 `event_id`)。取 min 的含义:同一场面试答 5 道不同题,不构成 5 个独立验证场景(session 压住);同一 topic 练两次,也不构成 2 个场景(topic 压住)。无 `session_id` 的旧数据行为与原公式完全一致(§4.4 粒度规则的配套)。

**校准锚点(demo 标定):** 半饱和权重 `k=1.5` 使"~5 条扎实的独立证据(每条 w≈0.5,Σwᵢ≈2.5)、跨 ≥3 个场景 → confidence ≈ 0.70";`diagnose→train` 边界(0.4)约在第 3 条扎实证据跨过。`k` 越小,置信度随证据量上升越快。

**乘积结构是刻意的,不是简化:** confidence 是 saturation 与 diversity 的乘积,因此"数量"无法单独顶上去——5 条证据若全挤在同一场景,diversity 封顶 0.625,confidence 最高只到 ~0.51。即"在单一场景刷 5 次" ≠ "对该能力的迁移已有把握"。多场景验证不足就不给高置信度,这是 transfer 维度应有的严格性。

evaluator_diversity、time_span 等因子推迟到 v2,待有真实数据校准。

### 5.4 Gap 与优先级

```
gap      = max(0, required − score)
priority = gap × weight × (0.5 + 0.5 × confidence)
mode     = "diagnose"  if confidence < 0.4   # 证据不足→先安排诊断任务
           "train"     otherwise
critical 项排序时置顶。
```

---

## 6. 命令契约

命令分两侧,对应 §1.2 的事实/推断与决策:

- **写入侧(capture,只追加事实):** `record → observe`;纠错:`retract → record`。
- **读取侧(materialize + review,读派生视图):** `assess(刷新投影)→ explain → next`;跨目标总览:`list`。

**`assess` 是读模型刷新,不属于单次摄取事务(架构约束):** 它是对**全部** events + observations 的全量重算,产出 §4.6/§4.7 的派生投影,成本随总数据量增长而非随单份 artifact 增长。因此:

- `record`/`observe` 一提交,事实即安全;`assess` 由**读取侧懒触发**(explain/next 前)或**一批摄取完成后统一执行一次**,而非每份 artifact 都全量重算。N 份 artifact 的摄取是 `record+observe ×N` 后 `assess ×1`。
- `state/` 随时可 `rm -rf state/ && goal assess` 重建(INV-2),因此 `assess` 失败**绝不影响**已落地的事实——写入与投影解耦,是标准的事件溯源写入侧/读模型分离。

所有命令是确定性 CLI(除 observe 的提取步骤由 Agent 执行);输出为 JSON(机器)+ 简明文本(人)。

### 6.1 `goal record`

记录一次表现(一个任务,§4.4 粒度规则)。

- 输入:type、task 元数据(**不含 novelty**;可选 `--variant` 声明)、conditions、可选 session、artifact 文件路径(已有文件或从 stdin 写入)。
- 行为:校验 artifact 存在 → 计算 `artifact_sha256` → 按 §4.4.2 派生 novelty → 追加一行 `event-v2` 到 `events.jsonl` → 返回 event_id。
- 禁止:修改已有 event(INV-1);接受 novelty 自报。

### 6.2 `goal observe <event_id>`

从表现中提取结构化观测。

- 前置:校验 artifact 哈希与 event 记录一致(v2;不匹配即报错,INV-3),event 未被撤销。
- 分工:CLI 输出该 event 的 artifact 内容 + 当前 rubric,**Agent(LLM)** 按 rubric anchor 生成 Observation 草稿,CLI 校验 schema(capability/dimension 在 rubric 中存在、result ∈ [0,1];`artifact_ref` 指向本 event 的 artifact 且行号真实存在、非空行)后追加写入 `observations.jsonl`。
- LLM 不接触任何历史分数,只看本次 artifact + rubric(防锚定);且**必须在全新上下文执行**——不继承看过 `state/` 分数或主持过面试的上下文,否则反锚定失效(见 §7)。

### 6.3 `goal assess`

重算能力投影(读模型刷新)。

- 行为:读全部 events + observations → 排除被撤销 event 及其 observations(§4.4.3)→ 按 §5 公式计算 → 覆写 `state/capability.json`、`state/gap.json`。
- 纯确定性,无 LLM 参与(INV-5)。幂等:重复运行结果一致(INV-2)。
- **与摄取解耦**:`assess` 不由 `record`/`observe` 触发,不属于单份 artifact 的写入事务(见 §6 开头)。它在读取前由读取侧(§6.4 explain / §6.6 next)懒触发,或在一批摄取后统一执行一次。`list`(§6.8)是纯只读、**不触发** assess,故其展示的是最近一次 assess 的投影,可能滞后于最新摄取(读模型的预期延迟);需要最新数值时对该目标先 `assess` 或走 review。

### 6.4 `goal explain <capability>[.<dimension>]`

解释能力结论的证据链。系统可观测性的核心命令。

- 前置:展示证据前校验各 artifact 哈希(v2;不匹配即报错)。
- 输出:当前估计与置信度;按权重排序的正向/负向证据(每条含日期、event 类型、evidence 文本、权重、artifact_ref);置信度为什么不是更高(场景数、证据分布)。被撤销的证据不出现在证据链中(可附注撤销记录)。
- 全部内容由确定性引擎从 observations 生成,LLM 只做措辞润色(可选)。

### 6.5 `goal retract <event_id> --reason <text>`

撤销一条记错的 event(§4.4.3)。

- 行为:校验目标 event 存在且非 retraction → 追加一条 `type: "retraction"` 事件 → 返回新 event_id。
- 后续:重新 `record` 正确版本;`assess` 自动排除被撤销者。

### 6.6 `goal next`

选择下一项最有价值的行动。两段式(同 observe):

- **`next`(打印)**:纯确定性,从 `gap.json` 取出按 priority 排序(critical 优先)、`gap > 0` 的**可行动缺口短名单**(默认前 3,`--top` 可调),输出 JSON。这是"该练什么"的候选。
- **`next --write`(写入)**:**Agent(LLM)** 依短名单设计 1–3 个具体任务从 stdin 传入;CLI 校验(每个 `targets` 的 `(capability,dimension)` 必须是 goal.yaml 的 requirement、`mode ∈ {diagnose,train}`、`task`/`rationale` 非空、至多 3 条),按序赋 `rank` 后写入 `state/plan.json`。
- 只排序,不给 ΔCapability 数值;plan.json 是决策产物,不在 INV-2 内(§4.8)。

### 6.7 `goal init --workspace <dir>`

创建 workspace 骨架(确定性),供 Agent 随后陪用户起草内容。

- 输入:`--workspace <dir>`(目标目录,可尚不存在);可选 `--title` / `--goal-id`(默认取目录名)/ `--rubric`(默认 `<goal-id>-v0.1`)/ `--created-at`。
- 行为:建 `rubric/` `artifacts/` `data/` 目录 → 写 `goal.yaml` 模板 + `rubric/<rubric-id>.yaml` 模板(均为语法有效、含中立占位 `example_capability` 的可运行骨架)。`state/` 由 assess 自动创建。
- 安全:若目标目录已存在 `goal.yaml`,**拒绝覆盖**。
- 分工(INV-5):init 只搭骨架;**Agent 陪用户起草真实 requirements 与 rubric 锚点,用户确认后生效**——难度/目标/权重是用户的决策,不由工具代填。

### 6.8 `goal list --root <dir>`

跨目标总览(§3):枚举一个父目录下的所有 workspace,给出每个目标的 gap 概览。这是唯一的"多目标管理"命令。

- 输入:`--root <dir>`——一个 goal workspace(自身含 `goal.yaml`)或多个 goal 的父目录;可选 `--json` 输出机器格式。
- 行为:扫描 `--root` 直属子目录中含 `goal.yaml` 者为 workspace(若 `--root` 自身含 `goal.yaml` 则视其为单一目标),对每个读 `goal.yaml` 元数据 + `state/gap.json`(若已 assess),汇总 `requirements` 数、未达标(gap>0)项数、critical 未达标数、优先级最高的 top gap。未 assess 的目标标记 `unassessed`。
- 排序:critical 未达标者置顶 → top gap priority 降序 → 未评估者垫底 → 按 `goal_id` 确定性 tiebreak。
- **纯读、纯确定性**:只读 `goal.yaml` 与既有 `state/`,不写任何文件、不触发 assess,不在 INV-2 投影范围内(不重算数值,只复述最近一次 assess 的结果)。无 LLM 参与(INV-5)。

---

## 7. Agent 接入方式

- 系统 = 结构化 CLI(确定性核心)+ Skill(场景 prompt)。不做 MCP Server,不做 UI。
- v1 Skills(四个):
  - `goal-manage`：目标全生命周期(建/改/删/看)——建时搭 workspace 骨架(§6.7)并陪用户起草 requirements 与 rubric 行为锚点(用户确认后定稿);中途可增删改 requirement / 修订 rubric(按 INV-4:纯新增可追加,改已有锚点语义开新版)/ 归档删除目标(删 workspace + git,无破坏性命令)/ 查看目标(`list` 跨目标总览,§6.8;及直接读 goal.yaml/rubric)。requirements/rubric 是 git 版本化、长期演进的目标模型。
  - `goal-grill`:主持一场模拟面试/自测,产出逐字、中立的 transcript,写进 `artifacts/` 后**强制交接 goal-log 入管**。是 §1 循环里 Execute 一步的落地。出题阶段不读 rubric 锚点/gap(防 teaching-to-test);**自身不判分**。
  - `goal-log`:capture 摄取管道(**写入侧,只追加事实**)——`record → observe`(外加纠错支线 `retract`)。任何 artifact(goal-grill 产的 / 用户贴的真实面试)的**唯一入管口**。其中 `observe` 是 §6.2 的盲提取角色(不加载历史分数)。**不跑 `assess`**——摄取只追加事实,全量重算属于读取侧(见 §6 开头的写入/读模型分离)。
  - `goal-review`:review 复盘(**读取侧,投影刷新落点**)——`assess(先刷新投影)→ explain(证据链)→ next(下一步计划)`。只在用户想看/想规划时才用,只读事实。`assess` 是 §6.3 的读模型刷新(幂等、便宜,保证读到最新状态);`next` 是 §6.6 的任务设计角色;`explain` 是确定性 CLI。跨目标总览 `list` 归 goal-manage。
- 职责划分:**采集(goal-grill)/ 摄取打分(goal-log,写入侧)/ 复盘规划(goal-review,读取侧)** 分立。能力投影的全量重算(assess)归读取侧:摄取只追加事实,看结果时才物化。真人主持的真实/模拟面试仍在 skill 之外发生,由用户直接喂给 goal-log 事后登记——本系统不出题。goal-grill 是一个**可选的面试来源**,但一旦主持就**必经 goal-log 入管**(每场面试都要成为事实,不可选)。goal-grill 与 goal-log 分开不是为了阻断入管,而是为了把"出题"与"盲打分"隔开。
- 反锚定(靠上下文边界,不靠口头约定):`observe` 与 `grill` 是盲步骤,必须在**全新上下文**执行——`observe` 只拿 artifact + rubric,不继承任何看过 `state/` 分数或主持过面试的上下文。CLI 的 `observe` 不打印历史分数,但那只挡住输入侧;真正的隔离要求调用方为这两步开 fresh-context(如 fresh 子代理)。否则单一 agent 在同一上下文里既出题、又打分、又看分,隔离形同虚设。
- 未来 UI(如有)只是本地文件的 Viewer,不持有状态。

---

## 8. v1 范围裁决

### 做

- 单场景:后端系统设计面试
- 三维能力向量(recall/application/transfer)+ 双值(score/confidence)
- JSONL 事件溯源 + 确定性 estimator + 证据链 explain
- 五命令闭环 + 四个 Skill(`goal-manage` 目标管理、`goal-grill` 产出表现、`goal-log` 摄取打分、`goal-review` 复盘规划)

### 不做(明确推迟)

| 项 | 推迟原因 |
|---|---|
| SQLite | 数据量不需要;将来只能作为 JSONL 的派生索引,永不做事实源 |
| 维度间软约束推断 | 需要贝叶斯建模,先积累真实数据 |
| ΔCapability 数值预估 | 无数据支撑,假精确 |
| 多因子置信度(evaluator/time_span) | 无法校准 |
| 盲重评、评价争议 | v2 校验机制 |
| 通用能力本体、多场景 | 先验证单场景闭环 |
| UI / Dashboard | 文件即接口 |

---

## 9. v1 要验证的三个假设(而非评分准确性)

1. **提取稳定性**:Agent 能否把一次复杂表现按 rubric 稳定拆解成结构化 Observation?(同一 artifact 重复提取,capability/dimension 判定一致率 > 80%)
2. **判断可认可性**:用户看到能力结论时,能否通过 `goal explain` 的证据链理解并认可判断?
3. **推荐针对性**:`goal next` 基于历史表现的推荐,是否比用户随意选择更有针对性?

验证优先级高于:精确评分模型、通用本体、RL、0–100 统一分。
