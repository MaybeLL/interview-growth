# 使用 Skill 与结构化 CLI，不提供 MCP

MVP 由场景化 Skill 负责角色、推理和工作流，由 Python 应用核心负责领域规则，并以
`interview-growth call <operation>` 作为唯一 Agent 操作入口。CLI 从 stdin 接收一个 JSON
对象，使用 Pydantic 校验类型，返回稳定的 `{ok,data,error}` 信封，并允许通过
`interview-growth operations <operation>` 查询契约。Hook 只调用确定性 CLI，不解析聊天。

这一决策删除 FastMCP、STDIO Server 和 `.mcp.json`，避免大量 Tool schema 占用上下文，减少
安装依赖，并让 Codex、Claude Code 和普通终端复用同一执行方式。代价是失去宿主原生 Tool
发现和逐工具权限界面；通过可查询契约、严格 JSON 校验、幂等键、版本检查及 CLI 契约测试
缓解。Skill 和 Hook 不得直接读写 SQLite。
