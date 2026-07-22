# 为 Codex、Claude Code 与 Pi 打包薄适配层

在保持一个插件目录和一套业务实现的前提下，同时交付 Codex、Claude Code 与 Pi 适配。仓库根目录分别提供 `.agents/plugins/marketplace.json`、`.claude-plugin/marketplace.json` 与声明 Pi resources 的 `package.json`；插件根目录继续提供 `.codex-plugin/plugin.json` 与 `.claude-plugin/plugin.json`。七个 Skills、结构化 CLI、SQLite 存储和 Context Packet 完全共享。

Codex 与 Claude Code 继续复用 `hooks/hooks.json` 中共同支持的命令型生命周期事件。Pi 通过一个薄 TypeScript extension 将真实 Pi session UUID 注入 Agent 上下文和 `INTERVIEW_GROWTH_SESSION_ID`，并把 `session_start` 与 `session_before_compact` 映射到同一个 Python hook CLI；hook CLI 同时接受原有 stdin payload 和 Pi 使用的显式参数。该方案增加了宿主清单与适配验证成本，但避免复制 Skill 或 Python 业务代码，也不引入 MCP；任一宿主特有能力只有在不改变共享领域语义时才允许加入。
