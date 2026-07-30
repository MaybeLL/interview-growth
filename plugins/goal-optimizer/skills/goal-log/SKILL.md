---
name: goal-log
description: 摄取管道(capture,写入侧)。把一次面试/练习表现登记为不可变事实、按 rubric 盲提取成结构化 observation。当用户想记录/登记刚完成的表现、把一份面试或练习稿存档并打分、或纠正记错的记录时使用;goal-grill 产出 transcript 后也必经此 skill 入管。本 skill 只追加事实与盲打分,不重算能力状态、不展示差距、不定计划(那是 goal-review)。
---

# Goal Log(capture:表现 → 事实 → 盲打分)

任何 artifact 的**唯一入管口**——不论它来自 goal-grill 的模拟面试,还是你手头的真实面试/项目稿。
职责两步:`record(记为事实)→ observe(盲打分)`,外加纠错支线 `retract`。

**写入侧职责边界:** 本 skill 是事件溯源的**写入侧**——只往事实流里追加。能力状态的全量重算(`assess`)是读模型刷新,
**不在本 skill 的摄取事务里**——它归 **goal-review**(读取侧)在看结果前懒刷新。事实一经追加即安全,assess 晚点算、批量算都不影响已落地的事实。

**前置:** 目标 workspace 已由 **goal-manage** 建好。看结果(能力/差距/下一步)去 **goal-review**，别在这里做。

**分工红线(职责分离):** 你(Agent)只做语义理解——按 rubric 判 pass/partial/fail、摘录证据。
所有数值(权重、聚合、置信度、差距)由 `goal.mjs` 确定性计算。**你永远不直接产出能力分数。**

## CLI 协议

把 `<scripts>` 解析为**本 SKILL.md 上两级(插件根)的 `scripts/` 目录**(即 `<此文件所在目录>/../../scripts`),脚本为
`<scripts>/goal.mjs`,用 `node` 运行。前置依赖只有 Node(无 npm 安装、零依赖)。所有命令都要 `--workspace <目标数据目录>`。

```
node <scripts>/goal.mjs record   --workspace <ws> --type <t> --occurred-at <ISO> \
                                  --topic <s> --difficulty <0-1> [--variant true] \
                                  --duration <实际耗时min> [--session <场次id>] \
                                  [--time-limit true] [--hints true] [--materials true] \
                                  --evaluator <agent|human> --artifact <相对 ws 的路径>
node <scripts>/goal.mjs retract <event_id> --workspace <ws> --occurred-at <ISO> --reason <文字>
node <scripts>/goal.mjs observe <event_id> --workspace <ws>            # 打印原文+rubric 给你
node <scripts>/goal.mjs observe <event_id> --workspace <ws> --write    # 从 stdin 读你的 observation JSON,校验后追加
```

> `assess`(重算 `state/`)**不在本 skill**。它是读模型刷新,由 **goal-review** 在看结果前自动跑。

## 工作流

摄取一份 artifact 走 record → observe 两步(这两步不可选:每份表现都应成为事实并被打分)。全量重算(assess)不在这里做。

### 1. record —— 记录事实(不含任何评价)
把**一个任务**登记为一个 event(粒度规则:一场 5 道题的面试记 5 个 event,共享同一个 `--session`;
单题练习不用填 session)。artifact 必须已存在;record 会对它计算 SHA-256 公证,事后改动会被读取端拒绝。

- **不要传 novelty**——它由引擎从历史派生(同 topic 出现过→familiar/repeat,首次→unseen);
  只有当任务是已知题型的变式时,显式传 `--variant true`。
- `--topic` 命名必须与该 workspace 的既有 topic 一致(派生依赖精确匹配),记录前先看一眼 events.jsonl 里的 topic 用词。
- `--difficulty` 是记录时声明(0–1),如实填;`--duration` 填实际耗时。
- `--type`:agent 主持的定向陪练用 `practice`(可靠性较低);真人主持才用 `mock_interview`/`real_interview`。
- **来自 goal-grill 时**:用它交接过来的诚实条件(topic/难度/是否限时/是否给过提示/evaluator=agent),照实填,不要美化。

### 1b. retract —— 记错了怎么办
事实层永不改写。记错(难度打错/忘了 --hints/artifact 贴错)就撤销重录:
`retract <event_id> --workspace <ws> --occurred-at <ISO> --reason "..."`(两个旗标都必填),然后重新 record 一条正确的。被撤销 event 的全部 observations 自动不再参与计算。

### 2. observe —— 你按 rubric 盲提取(这是本 skill 唯一需要你判断的一步)

> **反锚定强制(靠上下文边界,不是口头约定):** observe 必须在**全新上下文**里跑。
> 若当前对话**已经看过分数**(跑过 assess/explain/next/list)、或**刚主持过这场面试**(goal-grill),
> 你脑子里已带着结论/印象——此时**不要**在本上下文直接打分,而要**起一个 fresh-context 子代理**专跑 observe:
> 它只拿到 artifact 原文 + rubric,看不到 `state/`、也不知道主持过程。
> CLI 的 `observe` 不打印任何历史分数,但那只挡住输入;真正的隔离靠上下文边界。

1. 运行 `observe <event_id>`,拿到该 event 的**原始 artifact 全文** + **当前 rubric**(CLI 会先校验 artifact 哈希与撤销状态)。
2. **打分只依据 artifact 原文 + rubric 锚点**;不读 `state/`、不带入任何历史分数或主持印象(反锚定)。
3. 对 rubric 里该场景**实际能判定**的每个 `(capability, dimension)`:
   - 对照 anchor 判 `pass=1.0 / partial=0.5 / fail=0.0`(有充分理由可在 ±0.2 内微调);
   - 若 artifact 没有任何依据判定某维度,**跳过它**(宁缺毋滥,别硬凑);
   - `evidence` 用一句话摘录/概括你判断所依据的原话;
   - `artifact_ref` 必须精确指向 artifact 内的行号,格式 `<path>#L<起>-L<止>`。
4. 把结果作为 JSON 数组从 stdin 传给 `observe <event_id> --write`。CLI 会校验
   (capability/dimension 必须在 rubric 内、result∈[0,1];**`artifact_ref` 指向的 path 必须是本 event 的 artifact、行号真实存在且非空行**——不再只查格式),不合格直接拒收。

observation JSON 形状:
```json
[
  {
    "event_id": "evt_000001",
    "capability": "idempotency",
    "dimension": "recall",
    "result": 1.0,
    "evidence": "无提示说明幂等键作用,并明确重试复用同键",
    "artifact_ref": "artifacts/2026-07-26-payment.md#L20-L24",
    "extractor": { "model": "claude", "prompt_version": "observe-v0.1" }
  }
]
```

### 3. 摄取完成 —— 不在这里重算
`record → observe` 跑完,事实已落地。**不要**在本 skill 跑 `assess`,也不要主动展示能力/差距长篇报告——
能力状态会在用户下次用 **goal-review** 查看时自动刷新(读模型刷新,与摄取解耦)。
这里只需简报:"已记录并打分(共 N 条 observation);看结果/下一步请用 goal-review"。

> 一次摄取多份 artifact 时,就是 `record+observe ×N`,**不要**每份都去全量重算;全量重算只在读取侧发生一次。

## 不做
- **不重算能力状态(assess)**——那是读取侧(goal-review)的职责;摄取只追加事实。
- **不展示差距、不设计下一步计划**——那是 goal-review 的职责。
- **不建标、不改 goal.yaml/rubric**——那是 goal-manage 的职责。
- observe 不加载历史分数(反锚定);数值一律由 CLI 计算。
