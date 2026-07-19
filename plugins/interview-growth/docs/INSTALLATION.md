# Install Interview Growth

This repository exposes Interview Growth through a repo-scoped Codex marketplace. Runtime behavior
uses Skills, a structured JSON CLI, deterministic hooks, and local SQLite storage; no MCP server is
required.

## Prerequisites

- Codex or the ChatGPT desktop app with Plugins support;
- Python 3.12;
- `uv` available on `PATH`;
- network access for the first dependency sync.

## Install from GitHub

Register the GitHub repository as a marketplace and install the plugin:

```bash
codex plugin marketplace add MaybeLL/interview-growth --ref main
codex plugin add interview-growth@personal
```

The repository is currently private, so Git credentials must grant access to
`MaybeLL/interview-growth`. Restart the ChatGPT desktop app or Codex and begin in a new chat. Review
and trust the bundled hooks before enabling them; Codex does not automatically trust plugin hooks.
The first CLI invocation may download the locked Python dependencies through `uv`.

## Install from a local checkout

For plugin development, prepare the environment from `plugins/interview-growth`:

```bash
uv sync --dev --no-editable
uv run --no-editable pytest -q
```

Then register the repository root as a local marketplace:

```bash
codex plugin marketplace add /absolute/path/to/interview-growth-repository
codex plugin add interview-growth@personal
```

Alternatively, restart the ChatGPT desktop app, open Plugins in Work mode or Codex, select the
`Personal` source, and install **Interview Growth** there.

## Smoke test

Ask the plugin to create and select a goal, then request its current capability dashboard. For a
terminal-only storage check:

```bash
uv run --no-editable interview-growth --data-dir /private/path/interview-growth doctor
```

Inspect the agent-facing CLI contract with:

```bash
uv run --no-editable interview-growth operations
uv run --no-editable interview-growth operations interview_start
```

The default runtime data directory is host-specific. `INTERVIEW_GROWTH_DATA_DIR` overrides it for
development. The plugin never needs an API key in its SQLite database.

## Updating

Refresh the marketplace snapshot, then restart the desktop app so the installed plugin copy is
reloaded:

```bash
codex plugin marketplace upgrade personal
```

For a local checkout, update the source, run `uv sync --dev --no-editable`, validate the plugin, and
restart the desktop app. Use `codex plugin marketplace list` to confirm which marketplace root Codex
resolved.

## Privacy

Goal databases, internal backups, and exported `.igx` packages contain private interview content.
Keep them on encrypted storage. Export is explicit; `.igx` packages contain SQLite plus readable
JSON and Markdown. Deleting a goal moves its directory to the application trash and cannot remove
copies held by operating-system or external backups.
