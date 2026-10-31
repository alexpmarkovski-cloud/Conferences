# Conference Tracker

A local web app that tracks upcoming **AI, tech, and finance** conferences, with priority given to events in **Utah**, especially **Salt Lake County** and **Utah County**.

Every week a scheduled job finds new conferences from three sources:

- **Calendar pages** listed in [`conferences/sources.json`](conferences/sources.json) (Silicon Slopes, Visit Salt Lake, Utah Tech Week, dev.events, Money20/20, and more). A model of your choice reads each page and pulls out the events: **Gemini** (free tier, the default), **Claude**, or a **local model** through Ollama or Apple MLX.
- **[confs.tech](https://confs.tech)**, an open dataset of tech conferences. It needs no key.
- **Claude Cowork** (optional): Cowork does the research and drops a file in `data/inbox/`. See [COWORK.md](COWORK.md).

The results are stored in a local SQLite database, and conferences that have already ended are deleted automatically. You browse everything in a simple HTML page served on your own machine.

To track more sources, add a `{"name", "url", "focus"}` entry to `sources.json`.

## What it does

- **Ranks by place first:** Salt Lake & Utah County → elsewhere in Utah → rest of the US & virtual.
- **Then by topic:** AI → tech → finance, then by soonest start date.
- **Updates weekly** through macOS `launchd`. A run that was missed while the Mac was asleep happens when it wakes.
- **Prunes past events** on every update and every time the app starts.
- **Lets you hide** conferences you don't care about.
- **Reports token usage** for every model call, with throughput for local models.

## Requirements

- macOS (the scheduler uses `launchd`; the app itself runs anywhere Python does)
- Python 3.9+
- One of: a free [Gemini API key](https://aistudio.google.com/apikey), a [Claude API key](https://platform.claude.com/settings/keys), a local model ([Ollama](https://ollama.com) or Apple MLX), or Claude Cowork

## Setup

```bash
git clone https://github.com/<you>/Conferences.git
cd Conferences
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Open `.env` in an editor, set `LLM_PROVIDER`, and fill in that provider's settings.

## Choosing a provider

Set `LLM_PROVIDER` in `.env`, or override it for one run with `--provider`.

| `LLM_PROVIDER` | How pages are read | Cost | Settings |
|---|---|---|---|
| `gemini` (default) | Gemini fetches each page (`url_context` tool) | Free tier | `GEMINI_API_KEY`, `GEMINI_MODEL` (default `gemini-3.8-flash`) |
| `claude` | Claude fetches each page (`web_fetch` tool) | Paid per token | `ANTHROPIC_API_KEY`, `CLAUDE_MODEL` (default `claude-sonnet-5-5`) |
| `ollama` | The app downloads each page; a local model reads the text | Free, runs on your Mac | `OLLAMA_MODEL` (default `gemma3:12b`), `OLLAMA_URL` |
| `mlx` | Same, served by Apple MLX (Apple Silicon only) | Free, runs on your Mac | `MLX_MODEL` (default `mlx-community/gemma-3-12b-it-4bit`), `MLX_URL` |
| `none` | Skip page reading; use confs.tech + Cowork inbox only | Free | (none) |

### Gemini

Get a free key at [Google AI Studio](https://aistudio.google.com/apikey) and set `GEMINI_API_KEY`. Free-tier limits change; see your own at https://ai.dev/rate-limit. A run makes one request per source page (14 by default). Google Search grounding isn't free, so the app reads pages with `url_context` instead. If a run logs `quota exhausted`, wait for the daily reset or set `GEMINI_MODEL` to another model.

### Claude

Set `LLM_PROVIDER=claude` and `ANTHROPIC_API_KEY`, or leave the key empty if you've signed in with `ant auth login`. The default model is Claude Sonnet 5.5, which costs $2 / $10 per million input/output tokens. A weekly run is 14 calls, and fetched pages count as input tokens, so check `data/logs/token_usage.csv` after your first run to see your real cost. Requests opt into Anthropic's server-side fallback: if a safety filter declines a page, the request is retried on another model.

### Local models (Ollama or Apple MLX)

Local models can't browse the web, so the app downloads each page itself, turns the HTML into plain text (keeping links), and sends it to the model in chunks of `LOCAL_CHUNK_CHARS` characters (default 12,000, about 3–4k tokens).

**Ollama** is the easiest setup:

```bash
brew install ollama
ollama serve                  # leave running
ollama pull gemma3:12b
```

**Apple MLX** is built for Apple Silicon and is usually faster on the same Mac. Install it in its own environment, since `mlx-lm` needs a newer Python than this project's 3.9:

```bash
python3.12 -m venv ~/.mlx && ~/.mlx/bin/pip install mlx-lm
~/.mlx/bin/mlx_lm.server --model mlx-community/gemma-3-12b-it-4bit   # leave running (port 8080)
```

Then set `LLM_PROVIDER=ollama` or `LLM_PROVIDER=mlx` in `.env`.

#### Which local models can do this?

The job is extracting events from a few thousand tokens of messy web text into strict JSON with correct dates. That needs reliable instruction-following and JSON output more than raw knowledge. Every row is still validated (dates, fields, live URL), so a weak model mostly **misses** events rather than adding bad ones.

| Size | Examples | Verdict | Mac memory (4-bit) |
|---|---|---|---|
| **1–4B** | Llama 3.2 3B, Qwen3 4B, Gemma 3 4B, Phi-4-mini | **Not recommended.** Frequent broken JSON, wrong years, skipped events on long pages. If you try one, set `LOCAL_CHUNK_CHARS=4000` and expect gaps. | 3–4 GB |
| **7–9B** | Qwen3 8B, Llama 3.1 8B | **Usable minimum.** Handles simple listing pages; struggles with crowded calendars. Try `LOCAL_CHUNK_CHARS=8000`. | 6–8 GB |
| **12–14B** | Gemma 3 12B (default), Qwen3 14B, Phi-4 14B, Mistral Nemo 12B | **Recommended starting point.** Good JSON and dates on most pages; fits a 16 GB Mac. | 9–12 GB |
| **24–32B** | Mistral Small 24B, Gemma 3 27B, Qwen3 32B | **Close to hosted-model quality.** Needs a 32 GB+ Mac. | 16–22 GB |
| **70B+** | Llama 3.3 70B, Qwen2.5 72B | **Best local results**, but slow. Needs 64 GB+. | 40–48 GB |

These are model families, not a ranking. Newer releases in the same size class should do as well or better. For MLX, look up the exact names at [huggingface.co/mlx-community](https://huggingface.co/mlx-community) (e.g. `mlx-community/Qwen3-14B-4bit`). Reasoning models (Qwen3, etc.) are fine; their `<think>` text is removed before parsing.

Tuning knobs (`.env`): `LOCAL_CHUNK_CHARS` (smaller is easier for small models but means more calls), `LOCAL_CONTEXT_TOKENS` (Ollama's context window, default 16384), and `LOCAL_MAX_OUTPUT_TOKENS` (default 4096).

## Token usage

Every model call records how many tokens went in and out. A run logs one line per call and a total at the end:

```
INFO conferences.discovery:   tokens Visit Salt Lake convention calendar: in=3912 out=486 21.4s (22.7 tok/s)
INFO conferences.updater: Tokens (mlx): 31 calls, 104220 in / 9873 out, 702.5s model time, 14.1 output tok/s → per-call detail in data/logs/token_usage.csv
```

Each call is also appended to `data/logs/token_usage.csv`:

| Column | Meaning |
|---|---|
| `timestamp` | When the run finished |
| `provider`, `model` | Which model was used |
| `source`, `chunk` | Which page, and which chunk of it (local models split long pages) |
| `input_tokens` | Prompt tokens: instructions + page text. For Gemini/Claude this includes the fetched page. |
| `output_tokens` | Tokens the model wrote (for Gemini/Claude, including thinking) |
| `seconds` | Time for the call (Ollama reports its own timing; others use wall-clock time) |
| `output_tok_per_s` | Generation speed. Useful for comparing local models and Ollama vs MLX on your Mac. |

Open the CSV in Numbers or Excel to compare models, or to estimate Claude costs (input tokens × input price + output tokens × output price).

## Keeping your API keys safe

- `.env` is listed in `.gitignore` and must never be committed. Only `.env.example` (placeholders) goes in the repo.
- Create the Gemini key in a Google project **without billing**. If it ever leaked, it could only use up free quota and couldn't run up charges.
- For Claude, set a monthly spend limit in the Claude Console.
- If a key leaks, delete it in the provider's console and create a new one.

## Usage

```bash
# Find new conferences now (inbox → confs.tech → source pages → save)
python -m conferences.updater

# Use a different provider for one run
python -m conferences.updater --provider ollama

# Import only Cowork's files in data/inbox/
python -m conferences.updater --inbox-only

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

With a local provider, keep Ollama or the MLX server running (or start it at login) so the Monday job can reach it. If it can't, the run logs a clear error and still saves the confs.tech and inbox events.

## Tests

```bash
pytest
```

The tests use no network or API keys.

## Docs

- [ARCHITECTURE.md](ARCHITECTURE.md): components, data flow, providers, schema, ranking
- [AGENTS.md](AGENTS.md): the discovery agent and its guardrails, plus rules for AI coding agents working on this repo
- [COWORK.md](COWORK.md): running discovery with Claude Cowork, with a ready-to-paste prompt
