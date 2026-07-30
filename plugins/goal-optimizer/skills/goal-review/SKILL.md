---
name: goal-review
description: 复盘(review)。查看当前能力估计与置信度、离目标还有多远、每个数字背后的证据链，并据最高优先级缺口设计下一步该练什么。当用户想看自己现在什么水平、离目标差距、为什么某个分数是这样、下一步练什么时使用。本 skill 只读事实 + 定计划,不摄取新表现(那是 goal-log);跨目标总览去 goal-manage。
---

# Goal Review(review:看现状 → 解释证据 → 定下一步)

只在**用户想看/想规划时**才用——它不摄取新表现,只读既有事实,呈现结论并设计行动。
职责:`assess(刷新投影)→ explain(证据链)→ next(下一步计划)`。
本 skill 是事件溯源的**读取侧**:`assess` 的全量重算归这里(摄取侧 goal-log 不再跑),在读结果前把派生投影刷新到最新。

**前置:** 目标 workspace 已建好且已有摄取数据(record→observe 由 **goal-log** 完成)。
若还没有任何表现,先用 goal-log 摄取一份;此时 review 会显示冷启动基线(全 0 / 低置信 / diagnose)。

**分工红线(职责分离):** 展示与排序的每个数字都由 `goal.mjs` 确定性计算,你只做措辞与任务设计,**不直接产出能力分数、不编造提升幅度**。

## CLI 协议

把 `<scripts>` 解析为**本 SKILL.md 上两级(插件根)的 `scripts/` 目录**(即 `<此文件所在目录>/../../scripts`),脚本为
`<scripts>/goal.mjs`,用 `node` 运行。所有命令都要 `--workspace <目标数据目录>`。

```
node <scripts>/goal.mjs assess   --workspace <ws> [--as-of <ISO>]      # 先刷新,保证读到最新状态(幂等)
node <scripts>/goal.mjs explain  <capability>.<dimension> --workspace <ws>
node <scripts>/goal.mjs next     --workspace <ws> [--top <n>]          # 打印排序好的可行动 gap 短名单
node <scripts>/goal.mjs next     --workspace <ws> --write              # 从 stdin 读你设计的任务(≤3),校验后写 plan.json
```

## 工作流

进来先跑一次 `assess`(幂等、便宜)保证 state 新鲜,再按用户想看的东西选下面的步骤。
这一步是读模型刷新:goal-log 摄取时只追加事实、不重算,所以看结果前在这里统一刷新一次(N 份摄取也只此一次全量重算)。

### 1. explain —— 证据链可观测(系统不黑盒的证明)
用户问"我现在什么水平""为什么这个分数"时:`explain <cap>.<dim>` 输出当前 score/confidence、离目标差距与 mode、
按权重排序的每条证据(日期/类型/权重逐因子拆解/原话/行号)、以及置信度为什么不更高。全部由确定性引擎从事实生成,你只做措辞润色。

### 2. next —— 设计下一步(这是你需要判断的一步)
用户问"接下来该练什么"时:
1. 运行 `next`,拿到确定性排序好的**可行动 gap 短名单**(critical 优先、priority 降序、gap>0)。每条带 `mode`:
   `diagnose`(置信度<0.4,证据不足,先设计**诊断型**任务补证据)/ `train`(证据够,设计**训练型**任务补分数)。
2. 依短名单设计**至多 3 个**具体任务,每个含:`task`(做什么)、`targets`(冲哪些 capability×dimension,必须是 goal.yaml 里的 requirement)、`mode`、`rationale`(为什么是它、为什么这个 mode)、可选 `estimated_minutes`。
3. 作为 JSON 数组从 stdin 传给 `next --write`,CLI 校验后写 `state/plan.json`。**不要编造"预计提升 +X"这类数值**——只排序 + 文字理由。
4. 若某任务需要现场做一场模拟面试来采证据,提示用户可用 **goal-grill**(它会主持并自动交接 goal-log 入管)。

### 3. 跨目标总览
用户问"我几个目标都啥情况"时,跨目标枚举与 gap 概览归 **goal-manage** 的 `list`(只读、不触发 assess)。
若要看某个目标的最新能力数值/证据链,回到本 skill 对该目标 `assess` 后走 explain/next。

## 不做
- **不摄取新表现**(record/observe)——那是 goal-log 的职责。
- **不建标、不改 goal.yaml/rubric**——那是 goal-manage 的职责。
- 不直接写能力分数、不编造 ΔCapability 数值。
