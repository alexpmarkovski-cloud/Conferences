# Agents

This project involves two kinds of agents:

1. **The discovery agent:** the Gemini model the weekly job calls to find conferences.
2. **Coding agents:** AI assistants (Claude Code, Codex, Gemini CLI, etc.) that work on this repo.

---

## 1. Discovery agent (Gemini)

**Role:** a reader that pulls upcoming conferences out of known calendar pages and returns them as structured data. It only reports what the page says, not events from memory. It never writes to the database directly; `discovery.py` validates everything first.

**Model:** `gemini-3.8-flash` with the `url_context` tool (set in `conferences/config.py`, override with `GEMINI_MODEL` in `.env`). Google Search grounding isn't part of the free tier, but `url_context` is.

**Sources:** one call per page in [`conferences/sources.json`](conferences/sources.json), 14 by default. Edit that file to add or remove pages. They include:

- Utah: Silicon Slopes, Utah Technology Council, Utah Tech Week, Visit Salt Lake convention calendar, dev.events Utah, Utah Business, CFA Society Utah
- National: dev.events US AI and fintech, Techmeme events, Money20/20, Finovate, CFA Institute

Separately, `fetch_confs_tech()` pulls US and online events from the open [confs.tech dataset](https://github.com/tech-conferences/conference-data). That needs no model, and events whose names mention AI/ML are tagged `ai`.

**Quota handling:** on a 429 the job waits 60 s and retries once. If it fails again, it skips the remaining pages and keeps what it already has, including the confs.tech results.

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

## 2. Coding agents

Guidelines for AI assistants editing this repo:

- **Never read, print, or commit `.env`** or any API key. Use `.env.example` for new settings.
- **Run `pytest` before you finish.** Tests must pass without network access or an API key; use `tests/fixtures/`.
- **Stay compatible with Python 3.9** (no `match`, no `X | Y` type unions at runtime).
- **Keep dependencies small:** Flask, google-genai, python-dotenv, requests. Ask before adding more.
- **Schema changes** go in `conferences/schema.sql`, and existing databases need a migration step in `db.init_db()`.
- **Ranking rules** live in one place, `conferences/ranking.py`. Update ARCHITECTURE.md when they change.
- **Frontend** is plain HTML/CSS/JS with no build step. Keep it that way.
- `data/` is local state. Don't commit it.
