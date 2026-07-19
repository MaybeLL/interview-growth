# Interview Growth

一个面向程序员求职面试的 Agent-native 成长系统。系统以“成长目标”为最大隔离容器，
通过 Skill、MCP、Hook 和按需 Context Packet 帮助用户持续练习，并逐步积累可审计的能力证据。

当前完成 M0 基础层、M1 目标标准／题库层与 M2 模拟面试／评价层：

- Codex 插件骨架与 FastMCP STDIO 服务；
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

项目白皮书和关键决策见 [docs/WHITEPAPER.md](docs/WHITEPAPER.md) 与
[docs/adr](docs/adr)。可运行插件位于 [plugins/interview-growth](plugins/interview-growth)。

## 本地验证

```bash
cd plugins/interview-growth
uv sync --dev --no-editable
uv run --no-editable pytest
uv run --no-editable ruff check .
uv run --no-editable pyright
```

M3 将在这一基础上加入证据资格聚合、主题／能力面板、关键门槛、能力缺口、训练处方
与不同题复测。
