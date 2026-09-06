# Shopify Changelog

**Give your coding agent Shopify release context alongside the docs.**

A skill and local CLI for Codex and Claude Code. It searches Shopify's merchant and developer changelogs, reads complete announcements, and helps your agent check versions, rollouts, and breaking changes before implementing a feature.

Ask for normal Shopify development work. With automatic referencing enabled, your agent is instructed to check relevant announcements without you remembering a special command.

```text
You:   Build an order import that handles multiple tracking numbers.
Agent: Searches relevant Shopify announcements, reads the full entry,
       checks the project's API version, then chooses an implementation.
```

This illustrates the intended workflow; results depend on the agent and your project. Announcements supplement versioned documentation and schemas.

## Install with automatic referencing

Requires **Python 3.9+**, SQLite with **FTS5**, `curl`, and Git. Intended for macOS, Linux, and Windows through WSL. No API key, store credentials, Python packages, or server required.

```sh
git clone https://github.com/buildwithzach/shopify-changelog.git
cd shopify-changelog
python3 install.py --agent both --auto-reference
~/.local/bin/shopify-updates sync
```

Choose `--agent codex`, `--agent claude`, or `--agent both`. Start a new agent session after setup, then develop normally:

> Add subscription discounts to this Shopify app.

The installer creates links for the selected agents and the CLI. **`--auto-reference` also appends a Shopify instruction to their user instruction files**, preserving existing text. Omit that flag to leave global instructions unchanged. No background service or scheduled job is installed.

Keep your clone in place: the installed links point to it. The installer refuses to overwrite unrelated files. If you have an active Codex user `AGENTS.override.md`, setup explains how to add the standing instruction there instead.

## Install just the skill

Already manage your skills with the Skills CLI?

```sh
npx skills add buildwithzach/shopify-changelog --skill shopify-changelog -g -a codex claude-code
```

This installs the skill and its bundled scripts. It does **not** add the `shopify-updates` terminal command or edit user instruction files. Your agent can run the bundled Python CLI directly. Skills can be selected automatically for relevant tasks; selection is controlled by the agent.

For standing automatic-reference instructions after this method, tell your agent once:

> Set up the installed shopify-changelog skill for automatic use in Codex and Claude Code.

The skill includes the setup script. You can also invoke it explicitly with `$shopify-changelog` in Codex or `/shopify-changelog` in Claude Code.

## CLI

```sh
shopify-updates sync
shopify-updates status
shopify-updates search "checkout discounts" --sort recent
shopify-updates search "orderCreate" --source developer
shopify-updates recent --days 30 --limit 50
shopify-updates show 123
```

Use an ID from your results in place of `123`. `show` also accepts the original article URL.

| Option | Purpose |
| --- | --- |
| `search --sort recent` | Newest matching announcements first; default is text relevance |
| `search --any` | Match any word; default requires all words, with English stemming |
| `search --since YYYY-MM-DD` | Filter by publication date |
| `search/recent --limit N` | Control returned matches; total count is also reported |
| `show ID --history` | Read earlier observed versions of an edited entry |
| `--json` on search/recent/show/status | Structured output for agents and scripts |
| `sync --if-stale 24` | Download only feeds last checked at least 24 hours ago |

If the command is not on PATH, use `~/.local/bin/shopify-updates`. With skill-only installation, your agent uses `python3 /path/to/skill/scripts/shopify_updates.py`.

## What it does

- Imports every entry returned by the official [merchant RSS feed](https://changelog.shopify.com/feed) and [developer RSS feed](https://shopify.dev/changelog/feed.xml).
- Keeps original article HTML, readable text, dates, categories, source URLs, and linked resources.
- Deduplicates repeat syncs, updates search when articles change, and retains earlier observed versions.
- Keeps archived entries even if they later disappear from a feed.
- Searches locally with SQLite full-text search. The skill reads relevant full entries and creates a task-specific digest.
- Refreshes on use when the archive is older than 24 hours; explicit requests for the latest information force a refresh.

## What it doesn't assume

Feed history is not guaranteed to include every historical announcement. `status` reports your archive's coverage and freshness. A failed download retains the cached data and does not advance the failed feed's freshness timestamp.

Search excerpts are not AI summaries. Linked documents are not crawled. A merchant feature announcement doesn't establish API availability, and a preview or future API version isn't automatically usable in your project. The skill instructs the agent to check those distinctions and cite the original sources.

It does not train the model, scan projects itself, or run in the background. Automatic referencing is agent guidance, not a deterministic hook on every message. No telemetry is implemented by this project's CLI; sync requests go to Shopify's public feeds. Third-party installation tools have their own policies.

## Storage, updates, and uninstall

New installations store data at `~/.local/share/shopify-changelog/changelog.sqlite3`, or `$XDG_DATA_HOME/shopify-changelog/changelog.sqlite3`. Both agents share it. Override it with `SHOPIFY_UPDATES_DB` or place `--db /path/to/archive.sqlite3` before a subcommand. The original local prototype's in-skill database remains supported when present; `status` shows the actual path.

Back up the database to preserve old entries and revision history. It is excluded from the published repo and releases.

For a Git clone installation, update with `git pull --ff-only`. For Skills CLI installs, use `npx skills update -g`. Updating the skill leaves the default external archive in place.

To remove a full installation, remove only the links setup created under `~/.codex/skills` (or `$CODEX_HOME/skills`), `~/.claude/skills`, and `~/.local/bin`. If enabled, also remove the `Shopify development context` section from the selected agents' user instruction files. The database stays until you choose to delete it. For a skill-only install, use `npx skills remove shopify-changelog -g`.

## Development

```sh
python3 -m unittest discover -s tests -v
```

Tests cover archive updates, search, version history, failure recovery, and isolated installation. Contributions and reproducible bug reports are welcome through [GitHub issues](https://github.com/buildwithzach/shopify-changelog/issues) and pull requests.

MIT licensed code. Shopify announcement content belongs to its respective owners. This is an independent community project, not an official Shopify product.
