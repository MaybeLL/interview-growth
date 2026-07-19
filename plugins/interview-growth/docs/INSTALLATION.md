# Install Interview Growth locally

This repository includes a repo-scoped Codex marketplace at
`../../.agents/plugins/marketplace.json`. The layout follows the current
[Codex plugin documentation](https://developers.openai.com/codex/plugins/build): plugins live under
`plugins/`, and marketplace paths are relative to the repository root.

## Prerequisites

- Codex or the ChatGPT desktop app with Plugins support;
- Python 3.12;
- `uv` available on `PATH`;
- network access for the first dependency sync.

## Prepare the local environment

From `plugins/interview-growth`:

```bash
uv sync --dev --no-editable
uv run --no-editable pytest -q
```

## Register and install

From any directory, register this repository as a local marketplace:

```bash
codex plugin marketplace add /absolute/path/to/improve
codex plugin list --marketplace personal --available --json
codex plugin add interview-growth@personal
```

Alternatively, restart the ChatGPT desktop app, open Plugins in Work mode or Codex, select the
`Personal` local source, and install **Interview Growth** there.

After installation or an update, restart the desktop app and begin in a new chat. Review and trust
the bundled hooks before enabling them; Codex does not automatically trust plugin hooks.

## Smoke test

Ask the plugin to create and select a goal, then request its current capability dashboard. For a
terminal-only storage check:

```bash
uv run --no-editable interview-growth --data-dir /private/path/interview-growth doctor
```

The default runtime data directory is host-specific. `INTERVIEW_GROWTH_DATA_DIR` overrides it for
development. The plugin never needs an API key in its SQLite database.

## Updating

Update the source checkout, run `uv sync --dev --no-editable`, validate the plugin, then restart the
desktop app so the local installed copy is refreshed. Use `codex plugin marketplace list` to confirm
which marketplace root Codex resolved.

## Privacy

Goal databases, internal backups, and exported `.igx` packages contain private interview content.
Keep them on encrypted storage. Export is explicit; `.igx` packages contain SQLite plus readable
JSON and Markdown. Deleting a goal moves its directory to the application trash and cannot remove
copies held by operating-system or external backups.
