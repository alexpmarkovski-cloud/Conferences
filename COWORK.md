# Running discovery with Claude Cowork

[Claude Cowork](https://claude.com) (in the Claude desktop app) can do the research step for you. It browses the source pages, searches the web for Utah conferences, and writes what it finds to a JSON file in this repo. The app imports that file on its next run.

This needs **no API key**. It runs on your Claude plan.

## How it fits in

```
Cowork (weekly)  ──writes──►  data/inbox/cowork-YYYY-MM-DD.json
                                        │
launchd (Mon 08:00) or you  ──runs──►  python -m conferences.updater
                                        │  validates every row, checks each URL,
                                        ▼  moves the file to data/inbox/processed/
                                 data/conferences.db
```

The updater treats Cowork's file exactly like model output: rows with missing fields, past dates or dead links are dropped.

## Setup

1. Clone the repo and do the normal setup in the [README](README.md) (venv + `pip install`).
2. If Cowork will be your only discovery method, set this in `.env` so the weekly job doesn't call another model:
   ```
   LLM_PROVIDER=none
   ```
   (confs.tech is still imported; it needs no key.)
3. In the Claude desktop app, open **Cowork** and give it access to this project folder.
4. Paste the prompt below. To run it weekly, use Cowork's scheduled tasks and set it for **Sunday evening**, so Monday's 08:00 job imports the results.

## Prompt

Replace `<PROJECT_FOLDER>` with the path to your clone (e.g. `~/Coding/Conferences`).

```text
You're doing the weekly research step for my conference tracker in <PROJECT_FOLDER>.

1. Read <PROJECT_FOLDER>/AGENTS.md (the "Output contract" section) and
   <PROJECT_FOLDER>/conferences/sources.json.
2. Visit every page in sources.json. Also search the web for AI, tech, and finance
   conferences in Utah over the next 12 months, focusing on Salt Lake County
   (Salt Lake City, Sandy, Draper, South Jordan…) and Utah County (Lehi, Provo, Orem,
   American Fork…), then elsewhere in Utah, then major US and virtual events.
3. Include only conferences, summits, expos, or multi-day tech weeks with announced
   dates and an official website. Skip meetups, webinars, and anything you can't confirm
   on a real page. Don't add events from memory.
4. Save a JSON array that follows the output contract exactly to
   <PROJECT_FOLDER>/data/inbox/cowork-<today's date as YYYY-MM-DD>.json
   (create the inbox folder if needed). Use "ai", "tech", or "finance" for category,
   two-letter state codes, and is_virtual: true for online-only events.
5. Don't edit any other file in the project. Reply with how many events you saved,
   and list the Utah ones.
```

## Importing right away

To import the file without waiting for Monday:

```bash
.venv/bin/python -m conferences.updater --inbox-only
```

This only imports the inbox, so it doesn't call confs.tech or any model. Then refresh http://localhost:5050.

## Notes

- Files that start with `cowork` are saved with source `cowork`, so you can tell them apart in the database.
- Imported files are moved to `data/inbox/processed/`, never deleted, so you can check what Cowork found.
- You can combine Cowork with another provider: leave `LLM_PROVIDER=gemini` and the weekly run imports Cowork's file **and** reads the source pages. Duplicates are merged.
