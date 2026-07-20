# Interview Growth

一个面向程序员求职面试的 Agent-native 成长系统。系统以“成长目标”为最大隔离容器，
通过 Skill、结构化 CLI、Hook 和按需 Context Packet 帮助用户持续练习，并逐步积累可审计的能力证据。
同一套领域核心可作为 Codex 或 Claude Code 插件安装。

当前已完成 M0–M4 的本地 MVP：

- Codex／Claude Code 双宿主插件骨架与面向 Agent 的结构化 JSON CLI；
- Registry SQLite 与每目标独立 SQLite 数据库；
- 会话到当前目标的显式绑定；
- 目标生命周期、幂等创建和存储健康检查；
- 最小、角色化且不跨目标的 Context Packet；
- SessionStart 确定性 Hook，不让 Hook 承担面试业务语义。
- JD／用户约束、目标岗位画像和用户批准的不可变标准版本；
- 单父级主题树、别名、重复建议和独立能力维度；
- 目标内隔离题库、不可变题目版本、评价规约、搜索和停用；
- `goal-manager` 与 `question-bank` 两个场景化 Skill。
- 冻结标准与题目版本的模拟面试计划和状态机；
- 主问题、基于原回答的第一等追问题目及版本化检查点；
- 原始回答优先落库，以及独立、提示、教练辅助状态；
- 0–4／N/A 多维评价、回答证据、缺漏、建议、置信度与来源信息；
- 面试官、评价者和教练 Context 隔离；
- `interview`、内部 `evaluator` 与 `coach` Skill；
- 压缩前仅依据结构化 session ID 保存活动面试检查点的 Hook 守卫。
- 证据资格、近期性、覆盖门槛、关键阻塞项和能力面板；
- 评价争议、盲重评、训练处方和不同题复测；
- 真实面试复盘、覆盖盲区、备份恢复、`.igx` 导入导出和可恢复删除；
- GitHub marketplace 安装、四周试用指南和七个场景化 Skill。

项目白皮书和关键决策见 [docs/WHITEPAPER.md](docs/WHITEPAPER.md) 与
[docs/adr](docs/adr)。可运行插件位于 [plugins/interview-growth](plugins/interview-growth)。

## 快速安装

系统只要求本机已有 `uv`；缺少兼容的 Python 3.12 时，`uv` 会在首次运行时自动下载和管理。

Claude Code：

```bash
claude plugin marketplace add MaybeLL/interview-growth && claude plugin install interview-growth@maybell-plugins --scope user
```

Codex：

```bash
codex plugin marketplace add MaybeLL/interview-growth --ref main && codex plugin add interview-growth@maybell-plugins
```

安装后新开会话即可开始创建成长目标。Codex 用户还需通过 `/hooks` 审查并信任插件 Hook。
完整说明见 [安装文档](plugins/interview-growth/docs/INSTALLATION.md)。

## 本地验证

```bash
cd plugins/interview-growth
uv sync --dev --no-editable
uv run --locked --no-editable pytest
uv run --locked --no-editable ruff check .
uv run --locked --no-editable pyright
```

架构自 0.6.0 起只使用 Skill、结构化 CLI 与 Hook，不再启动或分发 MCP Server。

## 许可证

[MIT](LICENSE)
