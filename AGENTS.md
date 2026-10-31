# Agents

This project involves three kinds of agents:

1. **The discovery agent:** the model the weekly job calls to read conference pages (Gemini, Claude, or a local model).
2. **The Cowork agent** (optional): Claude Cowork doing the research on a schedule and dropping results in the inbox.
3. **Coding agents:** AI assistants (Claude Code, Codex, Gemini CLI, etc.) that work on this repo.

---

## 1. Discovery agent

**Role:** a reader that pulls upcoming conferences out of known calendar pages and returns them as structured data. It only reports what the page says, not events from memory. It never writes to the database directly; `discovery.py` validates everything first.

**Model:** chosen with `LLM_PROVIDER` in `.env` (details in [ARCHITECTURE.md](ARCHITECTURE.md#providers)):

| Provider | Default model | How it reads the page |
|---|---|---|
| `gemini` (default) | `gemini-3.8-flash` | `url_context` tool (free tier; Google Search grounding isn't free) |
| `claude` | `claude-sonnet-5-5` | server-side `web_fetch` tool |
| `ollama` | `gemma3:12b` | the app downloads the page and sends its text in chunks |
| `mlx` | `mlx-community/gemma-3-12b-it-4bit` | same as Ollama, served by Apple MLX |

All of them get the same instructions and must return the same output contract below. Every call's token input/output is logged to `data/logs/token_usage.csv`.

**Sources:** one call per page in [`conferences/sources.json`](conferences/sources.json), 14 by default. Edit that file to add or remove pages. They include:

- Utah: Silicon Slopes, Utah Technology Council, Utah Tech Week, Visit Salt Lake convention calendar, dev.events Utah, Utah Business, CFA Society Utah
- National: dev.events US AI and fintech, Techmeme events, Money20/20, Finovate, CFA Institute

Separately, `fetch_confs_tech()` pulls US and online events from the open [confs.tech dataset](https://github.com/tech-conferences/conference-data). That needs no model, and events whose names mention AI/ML are tagged `ai`.

**Quota and outage handling:** on a 429, 503 or 529 the job waits 60 s and retries once. Repeated 429s skip the remaining pages and keep what the run already has. A provider that can't run at all (bad key, local server not started) stops page reading with one clear error. Either way, the confs.tech and inbox results are still saved.

**Output contract:** a JSON array of objects:

```json
{
  "name": "Silicon Slopes Summit",
  "category": "tech",
  "start_date": "2027-01-20",
  "end_date": "2027-01-21",
  "city": "Salt Lake City",
  "state": "UT",
  "is_virtual": false,
  "venue": "Salt Palace Convention Center",
  "url": "https://example.com",
  "description": "One sentence."
}
```

**Guardrails in `discovery.py`** (the model's output is untrusted):

| Check | Why |
|---|---|
| Parse JSON out of the reply text; skip what doesn't parse | Tool-using replies can't always use a strict response schema |
| Required fields, valid ISO dates, `start_date <= end_date` | Drop malformed rows |
| `end_date >= today` | Drop past events |
| `category` in `ai/tech/finance` | Keep scope tight |
| City/state present, or `is_virtual` true | Must be placeable |
| `url` is http(s) and responds | Filters out made-up events |
| County computed locally by `geo.py` | Don't trust the model for ranking inputs |

Text the model returns is stored as plain data and never run as code or followed as instructions.

---

## 2. Cowork agent

**Role:** a weekly researcher that browses the source pages and searches the web for Utah conferences, then saves a JSON array in the output contract above to `data/inbox/cowork-YYYY-MM-DD.json`. It edits no other files. The updater imports the file with the same guardrails as model output.

Setup and the ready-to-paste prompt are in [COWORK.md](COWORK.md).

---

## 3. Coding agents

Guidelines for AI assistants editing this repo:

- **Never read, print, or commit `.env`** or any API key. Use `.env.example` for new settings.
- **Run `pytest` before you finish.** Tests must pass without network access or an API key; use `tests/fixtures/`.
- **Stay compatible with Python 3.9** (no `match`, no `X | Y` type unions at runtime).
- **Keep dependencies small:** Flask, google-genai, anthropic, python-dotenv, requests. Local models are called over HTTP with `requests`, so add no Ollama/MLX packages. Ask before adding more.
- **New providers** go in `discovery.PROVIDERS` as a function `(source, today) -> rows`. They must call `record_usage()` and raise `ProviderUnavailable` when they can't run at all.
- **Schema changes** go in `conferences/schema.sql`, and existing databases need a migration step in `db.init_db()`.
- **Ranking rules** live in one place, `conferences/ranking.py`. Update ARCHITECTURE.md when they change.
- **Frontend** is plain HTML/CSS/JS with no build step. Keep it that way.
- `data/` is local state. Don't commit it.
