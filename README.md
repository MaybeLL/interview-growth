# Goal Optimizer

[![CI](https://github.com/MaybeLL/interview-growth/actions/workflows/ci.yml/badge.svg)](https://github.com/MaybeLL/interview-growth/actions/workflows/ci.yml)

一个以“目标”为中心、以“能力”为状态、以“证据”为依据、以“优化”为核心循环的
**个人能力操作系统(Goal Optimization System)**。

它不关心你学了什么,而关心:**你距离目标还有多远,以及下一单位时间投入在哪里,能最大幅度缩小差距?**

核心循环:

```
record → observe → assess → explain
记录表现   提取观测   聚合能力   解释证据链
```

- **record** — 把一次表现(模拟面试、练习作答)登记为不可变的事实,不含任何评价。
- **observe** — 宿主 Agent 读原始 artifact,按 rubric 提取结构化观测(pass/partial/fail + 指向具体行号的证据摘录);提取时看不到历史分数(防锚定)。
- **assess** — 确定性引擎把观测聚合成每个 `(能力, 维度)` 的 **score** 与 **confidence**,再对比目标算出按优先级排序的差距。无 LLM 参与。
- **explain** — 展示某个能力数字为什么是这个值:每条支撑证据、其权重的逐因子拆解、以及它出自 artifact 的哪一行。

### 系统不变量

- **事实不可变** — `artifacts/` 与 `data/events.jsonl` 只增不改。
- **推断可再生** — `state/` 完全派生:`rm -rf state/ && assess` 逐字节重建(recency 用数据自身时钟而非运行时钟)。
- **证据链完整** — 任何能力结论都能回溯到 artifact 里的具体行。
- **职责分离** — Agent 判断语义,CLI 计算每一个数字。

设计全文见 [docs/SPEC.md](docs/SPEC.md)。可运行插件位于 [plugins/goal-optimizer](plugins/goal-optimizer)。

## 前置依赖

只需要 **Node.js**(CLI 是单文件、零依赖的 `goal.mjs`)。无数据库、无账号、无云同步。Git 即同步机制。

## 安装

插件随 `maybell-plugins` marketplace 分发,可在三个宿主加载:

Claude Code:

```bash
claude plugin marketplace add MaybeLL/interview-growth && claude plugin install goal-optimizer@maybell-plugins --scope user
```

Codex:

```bash
codex plugin marketplace add MaybeLL/interview-growth --ref release-v1 && codex plugin add goal-optimizer@maybell-plugins
```

Pi:

```bash
pi install git:github.com/MaybeLL/interview-growth
```

Claude Code 与 Codex 会自动发现 skill;Pi 通过 `pi.skills` 加载 skill。安装后新开会话即可开始。

## 试用 worked example

仓库自带一个完整示例 workspace:[`plugins/goal-optimizer/examples/backend-system-design`](plugins/goal-optimizer/examples/backend-system-design)——三份面试逐字稿、提取出的观测、以及派生的能力/差距状态。

```bash
cd plugins/goal-optimizer/skills/goal-optimizer/scripts
WS=../../../examples/backend-system-design
node goal.mjs explain idempotency.transfer --workspace "$WS"
# 从事实重算,验证逐字节一致(INV-2):
rm -rf "$WS/state" && node goal.mjs assess --workspace "$WS"
```

## 卸载

数据由用户自持(就在你指定的 workspace 目录里),卸载插件不会删除任何目标数据。

- Codex:`codex plugin remove goal-optimizer@maybell-plugins`
- Claude Code:`claude plugin uninstall goal-optimizer@maybell-plugins --scope user`

如果不再使用本仓库任何插件,可继续 `... plugin marketplace remove maybell-plugins`。

## 本地验证

```bash
node --check plugins/goal-optimizer/skills/goal-optimizer/scripts/goal.mjs
node scripts/validate-plugin-metadata.mjs
```

## 许可证

[MIT](LICENSE)
