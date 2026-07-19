# 平台中立核心并以 Codex 作为首个宿主

领域模型、SQLite 存储、CLI JSON 契约、评价与聚合算法保持宿主无关，Codex 与 Claude Code 的插件清单、Skill 触发和 Hook 配置放入独立适配层。MVP 只交付 Codex 适配，Claude Code 在核心行为稳定后通过同一套契约测试接入。这样放弃双平台同时发布，但避免把业务正确性绑定到任一宿主独有的 Hook 能力，并显著减少首期组合测试成本。
