# Architecture

## Overview

```
 launchd (Mon 08:00, catches up after sleep)
        │
        ▼
 conferences.updater ──► db.prune()            delete events whose end_date < today
        │
        ├──► discovery.fetch_confs_tech()       open dataset (GitHub), US + online events
        ├──► discovery.discover()               1 Gemini call per page in sources.json (url_context tool)
        │        ├─ parse JSON from reply text
        │        ├─ validate (name, dates, category, location)
        │        └─ check URL is reachable
        │        (429 → wait 60 s, retry once, then keep what we have)
        │
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
| `conferences/sources.json` | Calendar pages Gemini reads each week (editable) |
| `conferences/discovery.py` | confs.tech import, Gemini page reading, parsing, validation, URL check |
| `conferences/updater.py` | CLI entry point used by launchd |
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
| source | TEXT | `gemini`, `confs.tech`, `fixture`, or `manual` |
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

## Scheduling

`launchd` was picked over `cron` because it runs a missed `StartCalendarInterval` job once the Mac wakes. `scripts/install_schedule.sh` fills the template with absolute paths (repo and venv Python), installs it to `~/Library/LaunchAgents/com.conferences.weekly.plist`, and loads it with `launchctl bootstrap`.

## Deleting past events

`db.prune()` deletes rows where `end_date < date('now', 'localtime')`. It runs at the start of every update and every time the app starts, so a missed weekly run never leaves stale events showing.
