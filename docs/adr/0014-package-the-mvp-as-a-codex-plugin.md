# MVP 作为单个 Codex Plugin 交付

MVP 将 Skills、Hook、结构化 CLI 和 uv 管理的 Python 核心打包为一个可安装 Codex Plugin，插件代码与用户数据分离，目标注册表及各目标数据库保存在宿主无关的应用数据目录中，避免升级覆盖数据并确保 Skill 与 Hook 使用同一位置。插件可以在任意工作目录使用而不绑定某个项目仓库；当前仓库只承担插件开发与项目文档，Claude Code 后续通过独立清单和 Hook 适配复用领域核心。

该首发打包决策已由 [0016](0016-package-thin-adapters-for-codex-and-claude-code.md) 扩展为同一插件目录的双宿主分发。
