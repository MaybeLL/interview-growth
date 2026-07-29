---
name: goal-log
description: 摄取管道(capture)。把一次面试/练习表现登记为不可变事实、按 rubric 盲提取成结构化 observation、再确定性重算能力状态。当用户想记录/登记刚完成的表现、把一份面试或练习稿存档并打分、或纠正记错的记录时使用;mock-drill 产出 transcript 后也必经此 skill 入管。本 skill 只摄取与打分,不展示差距、不定计划(那是 goal-review)。
---

# Goal Log(capture:表现 → 事实 → 盲打分 → 重算)

任何 artifact 的**唯一入管口**——不论它来自 mock-drill 的模拟面试,还是你手头的真实面试/项目稿。
职责三步:`record(记为事实)→ observe(盲打分)→ assess(重算状态)`,外加纠错支线 `retract`。

**前置:** 目标 workspace 已由 **goal-init** 建好。看结果(能力/差距/下一步)去 **goal-review**,别在这里做。

**INV-5 分工红线:** 你(Agent)只做语义理解——按 rubric 判 pass/partial/fail、摘录证据。
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
node <scripts>/goal.mjs assess   --workspace <ws> [--as-of <ISO>]      # 纯确定性,重算 state/
```

## 工作流

摄取一份 artifact 走 record → observe → assess 三步,一气呵成(这三步不可选:每份表现都应成为事实并被打分)。

### 1. record —— 记录事实(不含任何评价)
把**一个任务**登记为一个 event(粒度规则:一场 5 道题的面试记 5 个 event,共享同一个 `--session`;
单题练习不用填 session)。artifact 必须已存在;record 会对它计算 SHA-256 公证,事后改动会被读取端拒绝。

- **不要传 novelty**——它由引擎从历史派生(同 topic 出现过→familiar/repeat,首次→unseen);
  只有当任务是已知题型的变式时,显式传 `--variant true`。
- `--topic` 命名必须与该 workspace 的既有 topic 一致(派生依赖精确匹配),记录前先看一眼 events.jsonl 里的 topic 用词。
- `--difficulty` 是记录时声明(0–1),如实填;`--duration` 填实际耗时。
- `--type`:agent 主持的定向陪练用 `practice`(可靠性较低);真人主持才用 `mock_interview`/`real_interview`。
- **来自 mock-drill 时**:用它交接过来的诚实条件(topic/难度/是否限时/是否给过提示/evaluator=agent),照实填,不要美化。

### 1b. retract —— 记错了怎么办
事实层永不改写。记错(难度打错/忘了 --hints/artifact 贴错)就撤销重录:
`retract <event_id> --reason "..."`,然后重新 record 一条正确的。被撤销 event 的全部 observations 自动不再参与计算。

### 2. observe —— 你按 rubric 盲提取(这是本 skill 唯一需要你判断的一步)
1. 运行 `observe <event_id>`,拿到该 event 的**原始 artifact 全文** + **当前 rubric**(CLI 会先校验 artifact 哈希与撤销状态)。
2. **你看不到、也不要索取任何历史分数或既有能力估计**(反锚定)。即便这份 transcript 是刚由 mock-drill 主持产生的,
   打分时也只依据 artifact 原文 + rubric 锚点,不带入主持时的印象。
3. 对 rubric 里该场景**实际能判定**的每个 `(capability, dimension)`:
   - 对照 anchor 判 `pass=1.0 / partial=0.5 / fail=0.0`(有充分理由可在 ±0.2 内微调);
   - 若 artifact 没有任何依据判定某维度,**跳过它**(宁缺毋滥,别硬凑);
   - `evidence` 用一句话摘录/概括你判断所依据的原话;
   - `artifact_ref` 必须精确指向 artifact 内的行号,格式 `<path>#L<起>-L<止>`。
4. 把结果作为 JSON 数组从 stdin 传给 `observe <event_id> --write`。CLI 会校验
   (capability/dimension 必须在 rubric 内、result∈[0,1]、artifact_ref 格式合法),不合格直接拒收。

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

### 3. assess —— 确定性重算(无 LLM)
读全部 events + observations,按公式算出每个 `(capability,dimension)` 的 score/confidence,
并对比 `goal.yaml` 算出 gap,写入 `state/capability.json`、`state/gap.json`。
幂等:`rm -rf state/ && assess` 结果逐字节一致(INV-2)。recency 的"now"取 events 里最大的 occurred_at
(可用 `--as-of` 覆盖),因此 assess 是纯函数,不依赖运行时钟。

摄取完成后**不要**主动展示能力/差距长篇报告——用户想看时会用 **goal-review**。这里只需简报"已记录并打分,状态已更新"。

## 不做
- **不展示差距、不设计下一步计划**——那是 goal-review 的职责。
- **不建标、不改 goal.yaml/rubric**——那是 goal-init 的职责。
- observe 不加载历史分数(反锚定);数值一律由 CLI 计算(INV-5)。
