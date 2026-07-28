---
name: goal-optimizer
description: 目标优化系统。把一次面试/练习表现,按 rubric 提取成结构化 observation,再由确定性引擎聚合成可追溯、可重算的能力估计,并对比目标算出差距。当用户想记录表现、评估能力、看离目标还差多远、或问下一步该练什么时使用。
---

# Goal Optimizer(证据 → 能力 → 差距 三层管道)

一个作用于人的优化循环:`record → observe → assess → explain`。

**INV-5 分工红线:** 你(Agent)只做语义理解——按 rubric 判 pass/partial/fail、摘录证据。
所有数值(权重、聚合、置信度、差距)由 `goal.mjs` 确定性计算。**你永远不直接产出能力分数。**

## CLI 协议

把 `<scripts>` 解析为**本 SKILL.md 同级的 `scripts/` 目录**(即 `<此文件所在目录>/scripts`),脚本为
`<scripts>/goal.mjs`,用 `node` 运行。前置依赖只有 Node(无 npm 安装、零依赖)。所有命令都要
`--workspace <目标数据目录>`(用户的某个目标 workspace;可参考 `../../examples/backend-system-design`)。

```
node <scripts>/goal.mjs record   --workspace <ws> --type <t> --occurred-at <ISO> \
                                  --topic <s> --difficulty <0-1> --novelty <unseen|variant|familiar|repeat> \
                                  --duration <min> [--time-limit true] [--hints true] [--materials true] \
                                  --evaluator <agent|human> --artifact <相对 ws 的路径>
node <scripts>/goal.mjs observe <event_id> --workspace <ws>            # 打印原文+rubric 给你
node <scripts>/goal.mjs observe <event_id> --workspace <ws> --write    # 从 stdin 读你的 observation JSON,校验后追加
node <scripts>/goal.mjs assess   --workspace <ws> [--as-of <ISO>]      # 纯确定性,重算 state/
node <scripts>/goal.mjs explain  <capability>.<dimension> --workspace <ws>
```

## 工作流

### 1. record —— 记录事实(不含任何评价)
把一次表现登记为一个 event。artifact 必须已存在。事件只记"发生了什么、什么条件下",绝不含分数。

### 2. observe —— 你按 rubric 提取(这是本 skill 唯一需要你判断的一步)
1. 运行 `observe <event_id>`,拿到该 event 的**原始 artifact 全文** + **当前 rubric**。
2. **你看不到、也不要索取任何历史分数或既有能力估计**(防锚定,继承自旧 evaluator 纪律)。
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
读全部 events + observations,按 §5 公式算出每个 `(capability,dimension)` 的 score/confidence,
并对比 `goal.yaml` 算出 gap,写入 `state/capability.json`、`state/gap.json`。
幂等:`rm -rf state/ && assess` 结果逐字节一致(INV-2)。recency 的"now"取 events 里最大的 occurred_at
(可用 `--as-of` 覆盖),因此 assess 是纯函数,不依赖运行时钟。

### 4. explain —— 证据链可观测(系统不黑盒的证明)
`explain <cap>.<dim>` 输出:当前 score/confidence、离目标差距与 mode、按权重排序的每条证据
(日期/类型/权重逐因子拆解/原话/行号)、以及置信度为什么不更高。全部由确定性引擎从事实生成。

## 不做(v1 已明确推迟)
跨维度软推断、evaluator/time_span 等额外置信度因子、ΔCapability 数值预估、next 任务设计。
