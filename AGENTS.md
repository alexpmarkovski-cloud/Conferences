# Agents

This project involves two kinds of agents:

1. **The discovery agent:** the Gemini model the weekly job calls to find conferences.
2. **Coding agents:** AI assistants (Claude Code, Codex, Gemini CLI, etc.) that work on this repo.

---

## 1. Discovery agent (Gemini)

**Role:** a research assistant that searches the web and reports upcoming conferences as structured data. It suggests candidates. It never writes to the database directly; `discovery.py` validates everything first.

**Model:** `gemini-2.5-flash` with the `google_search` grounding tool (set in `conferences/config.py`).

**Queries:** one call per topic × region pair, about 10 per run. For example:

- AI / tech / finance conferences in Salt Lake County and Utah County (Salt Lake City, Sandy, Draper, Lehi, Provo, Orem…)
- AI / tech / finance conferences elsewhere in Utah (Park City, Ogden, St. George…)
- Major US AI / tech / finance conferences, in person or virtual

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
| Parse JSON out of the reply text; skip what doesn't parse | Grounded replies can't always use a strict response schema |
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
