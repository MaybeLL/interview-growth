# Install Interview Growth

This repository exposes Interview Growth through repo-scoped Codex and Claude Code marketplaces.
Codex, Claude Code, and Pi reuse the same Skills, structured JSON CLI, lifecycle guards, and local
SQLite storage; no MCP server is required.

## Prerequisites

- Codex, the ChatGPT desktop app with Plugins support, or Claude Code;
- `uv` available on `PATH`;
- network access on first use so `uv` can obtain Python 3.12 and the locked dependencies when they
  are not already cached.

## Install in Codex from GitHub

Register the GitHub repository as a marketplace and install the plugin:

```bash
codex plugin marketplace add MaybeLL/interview-growth --ref main
codex plugin add interview-growth@maybell-plugins
```

Restart the ChatGPT desktop app or Codex and begin in a new chat. Review and trust the bundled hooks
before enabling them; Codex does not automatically trust plugin hooks. The first CLI invocation may
download a managed Python 3.12 runtime and the locked dependencies through `uv`.

## Install in Claude Code from GitHub

Register the same repository as a Claude Code marketplace, then install the plugin for the current
user:

```bash
claude plugin marketplace add MaybeLL/interview-growth
claude plugin install interview-growth@maybell-plugins --scope user
```

Start a new Claude Code session after installation. Claude Code discovers the seven Skills and
lifecycle hooks from the installed plugin automatically. The first CLI invocation may download a
managed Python 3.12 runtime and the locked dependencies through `uv`.

## Install in Pi from GitHub

Install the repository as a Pi package:

```bash
pi install git:github.com/MaybeLL/interview-growth
```

Start a new Pi session after installation. The package loads the same seven Skills plus a thin Pi
extension that injects the current Pi session UUID for goal binding, checks storage on session
startup, and checkpoints an active interview before context compaction. Invoke a Skill explicitly
with `/skill:goal-manager`, `/skill:interview`, or another installed Skill when needed.

For a project-local installation shared through `.pi/settings.json`, run:

```bash
pi install -l git:github.com/MaybeLL/interview-growth
```

The project must be trusted before Pi loads or installs project-local resources.

## Install from a local checkout

For plugin development, prepare the environment from `plugins/interview-growth`:

```bash
uv sync --dev --no-editable
uv run --locked --no-editable pytest -q
```

Then register the repository root as a local marketplace in either host:

```bash
codex plugin marketplace add /absolute/path/to/interview-growth-repository
codex plugin add interview-growth@maybell-plugins
```

```bash
claude plugin marketplace add /absolute/path/to/interview-growth-repository
claude plugin install interview-growth@maybell-plugins --scope user
```

Alternatively, restart the ChatGPT desktop app, open Plugins in Work mode or Codex, select the
`MaybeLL Plugins` source, and install **Interview Growth** there.

## Smoke test

Ask the plugin to create and select a goal, then request its current capability dashboard. For a
terminal-only storage check:

```bash
uv run --locked --no-editable interview-growth --data-dir /private/path/interview-growth doctor
```

Inspect the agent-facing CLI contract with:

```bash
uv run --locked --no-editable interview-growth operations
uv run --locked --no-editable interview-growth operations interview_start
```

The default runtime data directory is host-specific. `INTERVIEW_GROWTH_DATA_DIR` overrides it for
development. The plugin never needs an API key in its SQLite database.

## Updating

Refresh the relevant marketplace snapshot, then restart or reload the host so the installed plugin
copy is reloaded:

```bash
codex plugin marketplace upgrade maybell-plugins
```

```bash
claude plugin marketplace update maybell-plugins
```

```bash
pi update git:github.com/MaybeLL/interview-growth
```

Pi Git installs without an `@ref` follow the repository's default branch when explicitly updated.
Use `pi update --extensions` to update all unpinned Pi packages. If a Git source was installed with a
tag or commit ref, reinstall it with the desired new ref instead.

If this repository was previously registered under the old `personal` marketplace name, migrate it
once before reinstalling:

```bash
codex plugin marketplace remove personal
codex plugin marketplace add MaybeLL/interview-growth --ref main
codex plugin add interview-growth@maybell-plugins
```

For a local checkout, update the source, run `uv sync --dev --no-editable`, validate the plugin, and
restart the host. Use `codex plugin marketplace list` to confirm which marketplace root Codex
resolved, or `pi list` to confirm the Pi package source.

## Uninstall from Pi

Remove the global package without deleting Interview Growth's application data:

```bash
pi remove git:github.com/MaybeLL/interview-growth
```

For a project-local installation, add `-l`. Goal databases remain in the host-independent data
directory described below.

## Privacy

Goal databases, internal backups, and exported `.igx` packages contain private interview content.
Keep them on encrypted storage. Export is explicit; `.igx` packages contain SQLite plus readable
JSON and Markdown. Deleting a goal moves its directory to the application trash and cannot remove
copies held by operating-system or external backups.
