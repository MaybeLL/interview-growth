---
name: mock-drill
description: 主持一场模拟面试/自测,把完整问答逐字整理成一份干净、不含评价的 transcript 写进目标 workspace 的 artifacts/,然后必经 goal-log 入管(record→observe→assess)。当用户想做模拟面试、口头/系统设计自测、或需要一份可评估的表现记录却手头没有现成材料时使用。本 skill 主持面试并产出 artifact,但打分交给 goal-log 盲跑,自己绝不判分。
---

# Mock Drill(模拟陪练 —— 产出表现,必经 goal-log 入管)

SPEC §1 的优化循环是 `Observe → Evaluate → Optimize → Execute → Observe...`。
本 skill 负责 **Execute**:主持一场模拟面试/自测,产出一份**逐字、中立**的表现记录(artifact),
然后**强制交接 goal-log 入管**——每场面试都要成为不可变事实,这不是可选项。

## 边界:主持归我,打分归 goal-log(隔离红线)

如果同一个 agent 既知道你的评分锚点/差距、又主持面试,会往你的弱项和 rubric 上"定向出题",
导致陪练表现系统性地好于真实面试、证据被高估。真正要守的隔离只有两条(都与"要不要记录"无关):

- **主持时保持信息不对称。** 出题阶段**不要读、也不要向用户复述** `rubric/*.yaml` 的行为锚点、
  `state/gap.json`、`state/capability.json`。只按话题出题,像真面试(面试官不会先给你评分表)。
- **打分不由本 skill 做。** 你不生成 pass/partial/fail、不写 observation。打分是 goal-log 的 `observe` 盲跑步骤
  (只看 transcript + rubric,不带入你主持时的印象)。transcript 里也**绝不写评语/参考答案/对错标注**。

除此之外,本 skill **必须**触发 record 把这场面试记为事实(见第 4 步)——这是保证"每场都留痕"的必经步骤,而非越界。

## 前置

假设目标 workspace 已由 **goal-init** 建好(存在 `<ws>/goal.yaml` 与 `<ws>/artifacts/`)。
先与用户确认 workspace 路径。若尚未建目标,请改用 goal-init。

## 工作流

### 1. 选题(不读锚点/差距)
和用户确认这次练什么:
- **话题**:可以读 `<ws>/goal.yaml` 里的 **capability 名字**当话题词表,也可以扫一眼
  `<ws>/data/events.jsonl` 里**既有的 `task.topic` 用词**——目的是让本次 topic 命名与历史一致
  (record 靠精确匹配 topic 派生 novelty)。**仅取名字,不读 rubric 锚点、不读 gap。**
- **形态**:面试问答 / 系统设计口述 / 项目深挖 / coding 口述等,由用户定。
- **条件**:是否限时、是否允许提示——如实跟用户约定,稍后如实带给 goal-log(第 4 步)。

### 2. 主持(一问一答,像真面试)
以面试官身份提问、追问、施压,**默认不给提示、不给答案、不透露评分标准**。
- 用户明确要提示时可以给,但要记住"本次给过提示",第 4 步如实转达(影响权重)。
- 保持中立,不在过程中打分或说"这答得好/不好"。

### 3. 成稿(逐字、中立地写 artifact)
把完整问答整理成一份 markdown,**写入 `<ws>/artifacts/<YYYY-MM-DD>-<topic>.md`**(topic 用短横线命名,与话题一致)。
建议结构:

```markdown
# <话题> 模拟<面试/自测>  <日期>
> 形态: <面试问答 | 系统设计口述 | ...>  条件: <限时? 提示?>

## Q1: <面试官的问题/情境>
<候选人的回答,逐字或忠实转述>

### 追问: <追问内容>
<回答>

## Q2: ...
```

要点:逐字或忠实转述,**不加评语、不加"参考答案"、不标注对错**。这份文件将被 record 计算 SHA-256 公证,
之后不可篡改;所以确认成稿内容后再写盘。

### 4. 入管(必经,不可跳过)
artifact 写好后,**立即走 goal-log 的 capture 流程**(record → observe → assess),把这场面试变成事实并打分。
你**如实**提供本次条件,record 命令如下(observe 盲打分与 assess 由 goal-log 负责):

```
node <scripts>/goal.mjs record --workspace <ws> \
  --type practice \            # agent 定向陪练用 practice(可靠性低于真实/mock 面试);真人真面才用 mock_interview/real_interview
  --occurred-at <ISO8601> \
  --topic <与本次一致的 topic> \
  --difficulty <0-1 由用户如实声明> \
  [--time-limit true] [--hints true] \   # 按第 1/2 步实际约定如实填
  --evaluator agent \
  --artifact artifacts/<...>.md
```

(`<scripts>` = 本 SKILL.md 上两级插件根的 `scripts/goal.mjs`。)

- 默认 `--type practice`:本 skill 产出的是 agent 主持的定向陪练,estimator 会按较低 `reliability` 折算,
  避免陪练证据被当成真实面试。真人主持的真实/模拟面试才 record 为 `real_interview`/`mock_interview`。
- `--hints` / `--time-limit` 必须如实——它们直接进入证据权重(independence 因子)。
- 记录 + 盲打分完成后,只需简报"这场已留痕并打分"。**想看能力/差距/下一步用 goal-review**,别在这里长篇展示。

## 不做

- **出题阶段不读/不复述** rubric 锚点与 gap,避免 teaching-to-test。
- **不自己判分、不写 observation**——打分是 goal-log 的盲跑步骤。
- **不建标、不改 goal.yaml/rubric**——那是 goal-init 的职责;**不展示差距/不定计划**——那是 goal-review 的职责。
