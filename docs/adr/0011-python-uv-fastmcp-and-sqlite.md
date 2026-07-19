# MCP 核心采用 uv 管理的 Python 技术栈

MVP 使用 uv 管理 Python 3.12 环境，以官方 FastMCP v1 构建 STDIO MCP Server，以 Pydantic 校验结构化契约，并使用标准库 `sqlite3` 持久化。MCP 依赖固定在稳定 v1 且设置 `<2` 上限，待 v2 稳定并完成兼容验证后再迁移。相比 TypeScript 原生 SQLite 驱动或 Go／Rust 单文件方案，这一选择更适合快速实现和测试本地数据密集型 MVP，也避免额外 SQLite 原生依赖。
