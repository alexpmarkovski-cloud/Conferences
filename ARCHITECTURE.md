# Architecture

## Overview

```
 launchd (Mon 08:00, catches up after sleep)            Claude Cowork (optional, weekly)
        │                                                        │ writes
        ▼                                                        ▼
 conferences.updater                                   data/inbox/cowork-*.json
        │
        ├──► discovery.read_inbox()             import inbox files, then move them to inbox/processed/
        ├──► discovery.fetch_confs_tech()       open dataset (GitHub), US + online events
        ├──► discovery.discover()               1 call per page in sources.json, via LLM_PROVIDER:
        │        │   gemini  model fetches the page   (url_context tool)
        │        │   claude  model fetches the page   (web_fetch tool)
        │        │   ollama  we fetch → HTML to text → chunks → local model
        │        │   mlx     same, served by mlx_lm.server (Apple Silicon)
        │        │   none    skipped
        │        ├─ record token usage per call  → data/logs/token_usage.csv
        │        └─ 429/503/529 → wait 60 s, retry once; repeated 429 → keep what we have
        │
        ├──► discovery.clean()                  validate fields + dates, check URL is reachable
        ├──► db.prune()                         delete events whose end_date < today
        ├──► geo.classify()                     city → county → location tier
        └──► db.upsert()                        dedupe on normalized name + year
                        │
                        ▼
                 data/conferences.db (SQLite)
                        │
                        ▼
 conferences.app (Flask, localhost:5050)
        ├─ prune on startup
        ├─ GET  /                               HTML page
        ├─ GET  /api/conferences                ranked JSON (filters: category, region)
        └─ POST /api/conferences/<id>/hide      dismiss an event
                        │
                        ▼
 templates/index.html + static/app.js           cards grouped by region
```

## Components

| Module | Responsibility |
|---|---|
| `conferences/config.py` | Paths, weights, `.env` loading |
| `conferences/schema.sql` | Table definition |
| `conferences/db.py` | Connection, init, upsert, prune, ranked query, hide |
| `conferences/geo.py` | Maps Utah cities to counties; assigns location tier |
| `conferences/ranking.py` | Priority score and sort key |
| `conferences/sources.json` | Calendar pages the model reads each week (editable) |
| `conferences/discovery.py` | Inbox + confs.tech import, provider calls, HTML→text and chunking for local models, token usage, parsing, validation, URL check |
| `conferences/updater.py` | CLI entry point used by launchd; writes the token usage CSV |
| `COWORK.md` | Prompt and setup for running discovery in Claude Cowork |
| `conferences/app.py` | Flask web server and JSON API |
| `launchd/*.plist.template` + `scripts/` | Weekly schedule install/uninstall |

## Data model

`conferences` table:

| Column | Type | Notes |
|---|---|---|
| id | INTEGER PK | |
| name | TEXT | |
| category | TEXT | `ai`, `tech`, or `finance` |
| start_date, end_date | TEXT | ISO `YYYY-MM-DD` |
| city, state, county | TEXT | `county` is set by `geo.py`, not trusted from the model |
| is_virtual | INTEGER | 0/1 |
| venue, url, description | TEXT | |
| source | TEXT | `gemini`, `claude`, `ollama`, `mlx`, `confs.tech`, `cowork`, `inbox`, or `fixture` |
| dedupe_key | TEXT UNIQUE | normalized name + start year |
| first_seen, last_seen | TEXT | ISO timestamps |
| hidden | INTEGER | 0/1, set from the UI |

On a conflict with `dedupe_key`, an upsert refreshes the details and `last_seen`, and keeps `first_seen` and `hidden`.

## Ranking

Conferences sort by these keys, in order:

1. **Location tier:** Salt Lake / Utah County = 3, other Utah = 2, US / virtual = 1
2. **Category:** AI = 3, tech = 2, finance = 1
3. **Start date:** soonest first

The UI groups cards by location tier, so the first two keys decide the order inside each group.

## Providers

All providers share one prompt (`discovery.INSTRUCTIONS`) and one output contract (see [AGENTS.md](AGENTS.md)), and every result goes through the same validation. They differ only in how the page reaches the model.

| Provider | Page access | Function | Default model |
|---|---|---|---|
| `gemini` | Model fetches the URL with the `url_context` tool | `ask_gemini` | `gemini-3.8-flash` |
| `claude` | Model fetches the URL with the server-side `web_fetch_20260209` tool. Handles `pause_turn`; uses `fallbacks: "default"` (beta `server-side-fallback-2026-07-01`) | `ask_claude` | `claude-sonnet-5-5` |
| `ollama` | `fetch_page_text()` → `html_to_text()` (links kept as `text (url)`) → `chunk_text()` (`LOCAL_CHUNK_CHARS`, 400-char overlap) → `POST /api/chat` | `ask_ollama` | `gemma3:12b` |
| `mlx` | Same pipeline → `POST /v1/chat/completions` on `mlx_lm.server` | `ask_mlx` | `mlx-community/gemma-3-12b-it-4bit` |
| `none` | Skipped; only confs.tech + inbox | (none) | (none) |

Hosted providers fetch pages themselves, so one call covers one page. Local models can't browse, so the app downloads the page and sends it in chunks. A long page becomes several calls, and the same event may appear in two overlapping chunks; `clean()` drops those duplicates.

A provider that can't run at all (missing key, server not started, unknown model) raises `ProviderUnavailable`. The run then logs one clear error and still saves the inbox and confs.tech results.

### Token usage

Every call goes through `record_usage()`, which stores provider, model, source, chunk, input/output tokens, seconds and output tokens/second.

| Provider | Input tokens | Output tokens | Seconds |
|---|---|---|---|
| gemini | `prompt_token_count` + `tool_use_prompt_token_count` (fetched page) | `candidates_token_count` + `thoughts_token_count` | wall clock |
| claude | `usage.input_tokens`, summed across `pause_turn` continuations | `usage.output_tokens` | wall clock |
| ollama | `prompt_eval_count` | `eval_count` | `total_duration` (server-reported) |
| mlx | `usage.prompt_tokens` | `usage.completion_tokens` | wall clock |

At the end of a run, `updater.write_usage()` appends every call to `data/logs/token_usage.csv`, and the summary log line shows the totals.

### Inbox

Any `data/inbox/*.json` file holding an array in the output contract is imported on the next run (or right away with `--inbox-only`), validated like model output, and moved to `data/inbox/processed/`. Files named `cowork-*` get source `cowork`; others get `inbox`. This is how [Claude Cowork](COWORK.md) feeds the app without an API key.

## Scheduling

`launchd` was picked over `cron` because it runs a missed `StartCalendarInterval` job once the Mac wakes. `scripts/install_schedule.sh` fills the template with absolute paths (repo and venv Python), installs it to `~/Library/LaunchAgents/com.conferences.weekly.plist`, and loads it with `launchctl bootstrap`.

## Deleting past events

`db.prune()` deletes rows whose `end_date` is before today. It runs on every update (after discovery, when the database is opened) and every time the app starts, so a missed weekly run never leaves stale events showing.

The database is opened only after discovery finishes. Discovery can take a long time on the free tier or with local models, and holding a connection that long breaks if the file is replaced mid-run.
