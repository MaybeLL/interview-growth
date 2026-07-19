# 为 Codex 与 Claude Code 打包薄适配层

在保持一个插件目录和一套业务实现的前提下，同时交付 Codex 与 Claude Code 适配。仓库根目录分别提供 `.agents/plugins/marketplace.json` 与 `.claude-plugin/marketplace.json`，插件根目录分别提供 `.codex-plugin/plugin.json` 与 `.claude-plugin/plugin.json`；七个 Skills、`hooks/hooks.json`、结构化 CLI、SQLite 存储和 Context Packet 完全共享。Hook 只使用两个宿主共同支持的命令型事件与 `CLAUDE_PLUGIN_ROOT` 环境变量。该方案增加了两份清单及双重验证成本，但避免复制 Skill 或 Python 代码，也不引入 MCP；任一宿主特有能力只有在不影响另一个宿主的共享核心时才允许加入。
