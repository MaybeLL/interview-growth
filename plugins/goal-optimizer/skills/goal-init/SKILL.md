---
name: goal-init
description: 为一个新目标搭建 workspace,并陪用户把 goal.yaml 的 requirements 和 rubric 行为锚点起草成真实内容(用户拍板)。当用户想开始练一个新方向、建立/初始化一个目标、定义要评估的能力维度和评分标准时使用。每个目标仅首次用一次;workspace 建好后,记录表现/纠错用 goal-log,看能力差距与定下一步用 goal-review。
---

# Goal Init(为一个新目标搭 workspace)

一次性的协同建标:`scaffold → 起草 requirements → 起草 rubric 锚点 → 用户确认 → commit`。
建好后,后续 record / observe / retract 交给 **goal-log**(写入侧),assess / explain / next / list 交给 **goal-review**(读取侧)。

**INV-5 分工红线:** `init` 只搭出中立骨架。**难度、目标值、权重、是否 critical 都是用户的决策**——
你(Agent)负责起草、解释取舍、追问,但**不替用户拍板**。用户确认后才定稿。

## CLI 协议

把 `<scripts>` 解析为**本 SKILL.md 上两级(插件根)的 `scripts/` 目录**(即 `<此文件所在目录>/../../scripts`),
脚本为 `<scripts>/goal.mjs`,用 `node` 运行。前置依赖只有 Node(无 npm 安装、零依赖)。

```
node <scripts>/goal.mjs init --workspace <新目录> [--title <t>] [--goal-id <id>] [--rubric <rubric-id>] [--created-at <YYYY-MM-DD>]
```

- `--workspace` 是要搭建的目标目录(可尚不存在);`--goal-id` 默认取目录名,`--rubric` 默认 `<goal-id>-v0.1`。
- 若目标目录已存在 `goal.yaml`,CLI **拒绝覆盖**——说明该 workspace 已建好,应改用 goal-log(记录)/ goal-review(查看),而不是重跑 init。

## 工作流

### 1. scaffold —— 建骨架(确定性)
运行 `init --workspace <新目录>`,建出 `goal.yaml` + `rubric/<id>.yaml` 模板 + `artifacts/` `data/` 目录。
模板是**语法有效、含中立占位 `example_capability` 的可运行骨架**;`state/` 由后续 assess 自动创建。

### 2. 陪用户起草 requirements(goal.yaml)
和用户一起把 `goal.yaml` 的 requirements 填成真实内容:要练哪些 `capability × dimension`、每个的目标值、
权重、是否 `critical`。你可以基于用户描述的目标提出草案并解释每个取舍,但**目标值/权重/critical 由用户定**。
删掉 `example_capability` 占位。

### 3. 陪用户起草 rubric 行为锚点
把 `rubric/<id>.yaml` 里每个 `capability × dimension` 的 `pass / partial / fail` 写成**可判定的行为描述**
(observe 阶段就靠这些锚点对照原文判分)。锚点越具体、越可观测越好;含糊的锚点会让日后提取不稳定。
同样是你起草、用户确认。

### 4. 定稿并 commit
用户确认后,`git add` 该 workspace 并提交。这是一个目标的起点——事实层(events/artifacts)从此只追加。

### 5. 交接
告诉用户:workspace 已就绪,之后**记录表现**用 **goal-log**、**看能力/差距/定下一步**用 **goal-review**;
不要再回到 goal-init(除非要另建一个全新目标)。

## 不做
本 skill 只负责建标与协同起草。**不要在这里 record / observe / assess**——record/observe 是 goal-log 的职责、assess 是 goal-review 的职责,
且此时 workspace 尚无任何真实表现可评。
