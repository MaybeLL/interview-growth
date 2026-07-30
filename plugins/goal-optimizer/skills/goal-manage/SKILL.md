---
name: goal-manage
description: 目标的全生命周期管理——新建、更新、删除、查看目标(goal.yaml 的 requirements 与 rubric 行为锚点)。当用户想开始练一个新方向、建立/初始化目标,或中途发现要补充/调整能力要求、修订评分标准、归档/删除某个目标、查看有哪些目标及其配置时使用。requirements 与 rubric 是长期演进的目标模型,由 git 承载历史;记录表现/纠错用 goal-log(写入侧),看能力差距与定下一步用 goal-review(读取侧)。
---

# Goal Manage(目标全生命周期:建 / 改 / 删 / 看)

`requirements` 是这个目标的**及格线清单**(优化问题里的目标状态 x*):要练哪些 `capability × dimension`、
每个要到多高(`required`)、多重要(`weight`)、是否一票否决(`critical`)。它和 rubric 都是**人工定义、git 版本化**的,
**本来就该边做边演进**——用户常在练的过程中才发现还需要补哪些能力。本 skill 就是所有"和目标定义打交道"的入口。

**分工红线(职责分离):** 工具只搭中立骨架、只做机械校验。**难度、目标值、权重、是否 critical 都是用户的决策**——
你(Agent)负责起草、解释取舍、追问,但**不替用户拍板**。用户确认后才 commit 定稿。

## CLI 协议

把 `<scripts>` 解析为**本 SKILL.md 上两级(插件根)的 `scripts/` 目录**(即 `<此文件所在目录>/../../scripts`),
脚本为 `<scripts>/goal.mjs`,用 `node` 运行。前置依赖只有 Node(无 npm 安装、零依赖)。

```
node <scripts>/goal.mjs init --workspace <新目录> [--title <t>] [--goal-id <id>] [--rubric <rubric-id>] [--created-at <YYYY-MM-DD>]
node <scripts>/goal.mjs list --root <父目录> [--json]     # 枚举父目录下所有 workspace 的 gap 概览(只读)
```

- 「改 / 删 / 看单个目标的配置」都是**直接编辑或读取纯文本文件 + git**,没有专用命令——这正是"文件即事实源"的设计。
- `init` 见到目标目录已存在 `goal.yaml` 会**拒绝覆盖**;要修改已建好的目标走下面的「更新」,不要重跑 init。

## 工作流

### 建 —— 新建一个目标

1. **scaffold(确定性)**:`init --workspace <新目录>`,建出 `goal.yaml` + `rubric/<id>.yaml` 模板 + `artifacts/` `data/` 目录。
   模板是**语法有效、含中立占位 `example_capability` 的可运行骨架**;`state/` 由后续 assess 自动创建。
2. **起草 requirements(goal.yaml)**:和用户一起把 requirements 填成真实内容——要练哪些 `capability × dimension`、
   每个的 `required` / `weight` / `critical`。你提草案并解释取舍,但**这几个数由用户定**。删掉 `example_capability` 占位。
3. **起草 rubric 行为锚点**:把每个 `capability × dimension` 的 `pass / partial / fail` 写成**可判定的行为描述**
   (observe 阶段靠这些锚点对照原文判分)。锚点越具体、越可观测越好;含糊的锚点会让日后提取不稳定。
   v1 只用三个维度:`recall`(无提示能解释)、`application`(熟悉场景能用)、`transfer`(陌生场景能用)——
   不要引入 exposure/recognition/automaticity。同样是你起草、用户确认。
4. **定稿并 commit**:用户确认后 `git add` 该 workspace 并提交。这是目标的起点——事实层(events/artifacts)从此只追加。

### 改 —— 更新已有目标(边做边演进)

用户中途发现"为了这个目标还得掌握 X"时,不重跑 init,直接改文件:

- **加/调 requirement**:编辑 `goal.yaml` 的 `requirements`(加一条、改 `required`/`weight`/`critical`)。
  依旧是你起草、用户拍板。改完 `git commit`;下次 `goal-review` 的 `assess` 会**自动纳入**新目标(gap.json 记录 `against: goal.yaml@<sha>`,始终知道对的是哪一版)。
- **改 rubric**,分两种:
  - **纯新增能力/维度**(此前从未被观测过):可直接**追加**到当前 rubric 文件。
  - **修改已有锚点的语义**:rubric 一经引用即不可变,**必须新建版本文件**(如 `system-design-v0.2.yaml`),
    并把 `goal.yaml` 的 `rubric_version` 指向新版;旧 observation 保留旧版本引用,永不就地改写。
- 新增 requirement 对应的能力**必须在 rubric 中有锚点**,否则 observe 无依据、assess 校验不过——加 requirement 时同步补锚点。

### 删 —— 删除/归档一个目标

一个目标就是一个 workspace 目录,由 git 管理、数据用户自持。删除即删目录:

- 归档(推荐):把 workspace 移出活跃父目录(或另建 `archive/` 收纳),`git commit`。
- 彻底删除:`git rm -r <workspace>` 后 `git commit`;git 历史仍保留,可恢复。
- **没有破坏性 CLI 命令**(事实不可变、文件即事实源):删的是"你不再练的目标",不是篡改历史。删前与用户确认。

### 看 —— 查看目标

- **跨目标总览**:`list --root <父目录>`,一屏看每个 workspace 的 requirements 数、未达标项、critical 未达标数、
  优先级最高的 top gap(critical 未达标者置顶)。纯只读、**不触发 assess**,显示的是最近一次 assess 的投影,可能略滞后于最新摄取;
  要看某目标最新能力数值/证据链,走 **goal-review**(explain/next)。
- **看单个目标的配置**:直接读该 workspace 的 `goal.yaml`(目标与 requirements)与 `rubric/*.yaml`(评分标准)。

## 不做
- **不 record / observe / assess**——record/observe 是 goal-log 的职责、assess/explain/next 是 goal-review 的职责,
  且建标时 workspace 尚无真实表现可评。
- **不直接产出能力分数、不编造提升幅度**:本 skill 只管目标定义与评分标准,不判分。
