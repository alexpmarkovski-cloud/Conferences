# Conference Tracker

A local web app that tracks upcoming **AI, tech, and finance** conferences, with priority given to events in **Utah**, especially **Salt Lake County** and **Utah County**.

Every week a scheduled job finds new conferences from two free sources:

- **Calendar pages** listed in [`conferences/sources.json`](conferences/sources.json) (Silicon Slopes, Visit Salt Lake, Utah Tech Week, dev.events, Money20/20, and more). Google's Gemini API reads each page with its free `url_context` tool and pulls out the events.
- **[confs.tech](https://confs.tech)**, an open dataset of tech conferences.

The results are stored in a local SQLite database, and conferences that have already ended are deleted automatically. You browse everything in a simple HTML page served on your own machine.

To track more sources, add a `{"name", "url", "focus"}` entry to `sources.json`.

## What it does

- **Ranks by place first:** Salt Lake & Utah County → elsewhere in Utah → rest of the US & virtual.
- **Then by topic:** AI → tech → finance, then by soonest start date.
- **Updates weekly** through macOS `launchd`. A run that was missed while the Mac was asleep happens when it wakes.
- **Prunes past events** on every update and every time the app starts.
- **Lets you hide** conferences you don't care about.

## Requirements

- macOS (the scheduler uses `launchd`; the app itself runs anywhere Python does)
- Python 3.9+
- A free Gemini API key from [Google AI Studio](https://aistudio.google.com/apikey)

## Setup

```bash
git clone https://github.com/<you>/Conferences.git
cd Conferences
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Open `.env` in an editor and paste your key after `GEMINI_API_KEY=`.

### Keeping your API key safe

- `.env` is listed in `.gitignore` and must never be committed. Only `.env.example` (a placeholder) goes in the repo.
- Create the key in a Google project **without billing**. If it ever leaked, it could only use up free quota and couldn't run up charges.
- Optionally restrict the key to the *Generative Language API* in Google Cloud Console.
- If a key leaks, delete it in AI Studio and create a new one.
- Free-tier limits and data-use terms change, so check the current ones on Google's [Gemini API pricing page](https://ai.google.dev/gemini-api/docs/pricing). You can see your own limits at https://ai.dev/rate-limit. A weekly run uses one request per source page (14 by default). Google Search grounding isn't free, so the app doesn't use it.
- If a run logs `quota exhausted`, set `GEMINI_MODEL` in `.env` to another model that has free quota.

## Usage

```bash
# Find new conferences now (prune → search → save)
python -m conferences.updater

# Try it offline with sample data, no API key needed
python -m conferences.updater --fixture tests/fixtures/sample_gemini_response.json

# Start the web app → http://localhost:5050
python -m conferences.app
```

### Weekly schedule

```bash
./scripts/install_schedule.sh     # runs every Monday at 08:00
./scripts/uninstall_schedule.sh   # removes it
```

Logs are written to `data/logs/`. To run the scheduled job once right away:

```bash
launchctl kickstart gui/$(id -u)/com.conferences.weekly
```

## Tests

```bash
pytest
```

## Docs

- [ARCHITECTURE.md](ARCHITECTURE.md): components, data flow, schema, ranking
- [AGENTS.md](AGENTS.md): the Gemini discovery agent, and rules for AI coding agents working on this repo
