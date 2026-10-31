"""Find conferences from free and pluggable sources, then validate the results.

1. Source pages (conferences/sources.json), read by the model chosen with
   LLM_PROVIDER:
     gemini  Gemini reads each page itself (url_context tool)
     claude  Claude reads each page itself (web_fetch tool)
     ollama  we download the page text and a local model (Ollama) extracts events
     mlx     same, with a local model served by Apple MLX (`mlx_lm.server`)
     none    skip this step
   Every model call's token input/output is recorded in USAGE.
2. confs.tech: an open, curated dataset of tech conferences on GitHub.
3. data/inbox/*.json: files written by Claude Cowork or by hand (see COWORK.md).

Everything a model returns is untrusted: it is parsed as data, checked field by
field, and its URL must respond before it reaches the database.
"""
import json
import logging
import re
import time
from datetime import date, timedelta
from html.parser import HTMLParser
from pathlib import Path
from typing import Callable, Iterable, List, Optional, Tuple

import requests

from . import config

log = logging.getLogger(__name__)

SOURCES_FILE = Path(__file__).with_name("sources.json")
CONFS_TECH_URL = ("https://raw.githubusercontent.com/tech-conferences/conference-data/"
                  "main/conferences/{year}/{topic}.json")
CONFS_TECH_TOPICS = ("data", "general", "python", "devops", "security", "opensource", "api")
AI_PATTERN = re.compile(
    r"\b(AI|A\.I\.|ML|LLMs?|GenAI|artificial intelligence|machine learning|deep learning|"
    r"data science|generative)\b", re.I)

URL_HEADER = """Read this page: {url}
It is "{name}", a listing of {focus} events."""

TEXT_HEADER = """Below is the text of {url} ("{name}", a listing of {focus} events){part}.
Links appear as "text (url)".
<page>
{text}
</page>"""

INSTRUCTIONS = """
List every conference, summit, expo, or multi-day tech week on the page that is about
AI, technology, or finance and starts between {start} and {end}. Skip single meetups,
webinars, job fairs, and anything unrelated (sports, weddings, medical, etc.).
Use only what the page says; do not add events from memory.

Reply with ONLY a JSON array (no prose). Each item:
{{"name": str, "category": "ai" | "tech" | "finance", "start_date": "YYYY-MM-DD",
  "end_date": "YYYY-MM-DD", "city": str or null, "state": two-letter US state or null,
  "is_virtual": bool, "venue": str or null,
  "url": the event's own https link if the page has one, otherwise "{url}",
  "description": one sentence}}
Pick category "ai" when AI/ML is the main topic. Return [] if there are none or you
cannot read the page."""

REQUIRED = ("name", "category", "start_date", "end_date", "url")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
ALIVE_STATUSES = {401, 403, 405, 429}  # sites that block bots but exist
USER_AGENT = "Mozilla/5.0 (Macintosh) ConferenceTracker/1.0"


class QuotaExhausted(RuntimeError):
    """The model keeps returning 429; further calls this run would fail too."""


class ProviderUnavailable(RuntimeError):
    """The provider can't be used at all (bad key, server not running, unknown name)."""


def load_sources(path: Path = SOURCES_FILE) -> List[dict]:
    return json.loads(Path(path).read_text())


def build_prompt(source: dict, today: date, page_text: Optional[str] = None,
                 part: int = 1, parts: int = 1, horizon_days: int = 365) -> str:
    """Prompt for one page. With page_text the model reads our copy instead of fetching."""
    fields = {"url": source["url"], "name": source["name"],
              "focus": source.get("focus", "upcoming")}
    if page_text is None:
        header = URL_HEADER.format(**fields)
    else:
        part_note = f", part {part} of {parts}" if parts > 1 else ""
        header = TEXT_HEADER.format(text=page_text, part=part_note, **fields)
    return header + INSTRUCTIONS.format(
        url=source["url"], start=today.isoformat(),
        end=(today + timedelta(days=horizon_days)).isoformat())


def extract_json_array(text: str) -> list:
    """Pull a JSON array out of a model reply, tolerating code fences, prose and <think>."""
    if not text:
        return []
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S)
    fenced = re.search(r"```(?:json)?\s*(\[.*?\])\s*```", text, re.S)
    candidate = fenced.group(1) if fenced else text[text.find("["): text.rfind("]") + 1]
    try:
        data = json.loads(candidate)
    except (json.JSONDecodeError, ValueError):
        log.warning("Could not parse JSON from reply: %.200s", text)
        return []
    return [d for d in data if isinstance(d, dict)] if isinstance(data, list) else []


def validate(raw: dict, today: date) -> Tuple[Optional[dict], str]:
    """Return (clean_record, "") or (None, reason)."""
    for field in REQUIRED:
        if not raw.get(field) or not isinstance(raw[field], str):
            return None, f"missing {field}"
    category = raw["category"].strip().lower()
    if category not in config.CATEGORIES:
        return None, f"bad category {category!r}"
    start, end = raw["start_date"].strip(), raw["end_date"].strip()
    if not (DATE_RE.match(start) and DATE_RE.match(end)):
        return None, "bad date format"
    try:
        start_d, end_d = date.fromisoformat(start), date.fromisoformat(end)
    except ValueError:
        return None, "invalid date"
    if start_d > end_d:
        return None, "start after end"
    if end_d < today:
        return None, "already ended"
    url = raw["url"].strip()
    if not url.startswith(("http://", "https://")):
        return None, "bad url"
    is_virtual = bool(raw.get("is_virtual"))
    city = (raw.get("city") or "").strip() or None
    state = (raw.get("state") or "").strip().upper() or None
    if not is_virtual and not (city and state):
        return None, "no location"
    return {
        "name": raw["name"].strip(),
        "category": category,
        "start_date": start,
        "end_date": end,
        "city": city,
        "state": state,
        "is_virtual": is_virtual,
        "venue": (raw.get("venue") or "").strip() or None,
        "url": url,
        "description": (raw.get("description") or "").strip() or None,
    }, ""


def check_url(url: str, timeout: float = 8.0) -> Optional[str]:
    """Return the final URL if the page responds, else None."""
    headers = {"User-Agent": USER_AGENT}
    try:
        resp = requests.head(url, allow_redirects=True, timeout=timeout, headers=headers)
        if resp.status_code >= 400 and resp.status_code not in ALIVE_STATUSES:
            resp = requests.get(url, allow_redirects=True, timeout=timeout, headers=headers,
                                stream=True)
            resp.close()
        if resp.status_code < 400 or resp.status_code in ALIVE_STATUSES:
            return resp.url
    except requests.RequestException as exc:
        log.info("URL check failed for %s: %s", url, exc)
    return None


def clean(raw_rows: Iterable[dict], today: date,
          url_checker: Optional[Callable[[str], Optional[str]]] = check_url) -> List[dict]:
    """Validate rows, optionally verify URLs, and drop duplicates within the batch."""
    out, seen = [], set()
    for raw in raw_rows:
        rec, reason = validate(raw, today)
        if rec is None:
            log.info("Skipped %r: %s", raw.get("name"), reason)
            continue
        key = (rec["name"].lower(), rec["start_date"])
        if key in seen:
            continue
        if url_checker is not None:
            final = url_checker(rec["url"])
            if final is None:
                log.info("Skipped %r: url unreachable", rec["name"])
                continue
            rec["url"] = final
        seen.add(key)
        out.append(rec)
    return out


# --- confs.tech -----------------------------------------------------------------

def from_confs_tech(item: dict) -> Optional[dict]:
    """Map a confs.tech record to our raw format; None if it's outside the US and not online."""
    country = item.get("country")
    city, state, is_virtual = None, None, False
    if country == "U.S.A." and item.get("city"):
        city, _, state = item["city"].partition(",")
        city, state = city.strip(), state.strip() or None
    elif item.get("online"):
        is_virtual = True
    else:
        return None
    return {
        "name": item.get("name"),
        "category": "ai" if AI_PATTERN.search(item.get("name") or "") else "tech",
        "start_date": item.get("startDate"),
        "end_date": item.get("endDate") or item.get("startDate"),
        "city": city,
        "state": state,
        "is_virtual": is_virtual,
        "url": item.get("url"),
        "description": None,
    }


def fetch_confs_tech(today: date) -> List[dict]:
    rows: List[dict] = []
    for year in (today.year, today.year + 1):
        for topic in CONFS_TECH_TOPICS:
            try:
                resp = requests.get(CONFS_TECH_URL.format(year=year, topic=topic), timeout=15)
                if resp.status_code == 404:
                    continue
                resp.raise_for_status()
                rows.extend(r for r in map(from_confs_tech, resp.json()) if r)
            except (requests.RequestException, ValueError) as exc:
                log.warning("confs.tech %s/%s failed: %s", year, topic, exc)
    log.info("confs.tech returned %d US/online rows", len(rows))
    return rows


# --- Inbox (Cowork or manual) ------------------------------------------------------

def read_inbox(inbox: Path = None) -> List[Tuple[Path, list]]:
    """Return (file, rows) for every JSON file waiting in the inbox."""
    inbox = Path(inbox or config.INBOX_DIR)
    out = []
    for path in sorted(inbox.glob("*.json")):
        try:
            data = json.loads(path.read_text())
        except (OSError, ValueError) as exc:
            log.warning("Inbox file %s unreadable: %s", path.name, exc)
            continue
        rows = data if isinstance(data, list) else []
        out.append((path, [r for r in rows if isinstance(r, dict)]))
    return out


def archive_inbox_file(path: Path) -> None:
    done = path.parent / "processed"
    done.mkdir(exist_ok=True)
    path.rename(done / path.name)


# --- Page text for local models ------------------------------------------------------

class _TextExtractor(HTMLParser):
    SKIP = {"script", "style", "noscript", "svg", "head", "template"}

    def __init__(self):
        super().__init__()
        self.parts: List[str] = []
        self._skip = 0
        self._href: Optional[str] = None

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self._skip += 1
        elif tag == "a":
            self._href = dict(attrs).get("href")
        elif tag in ("br", "p", "div", "li", "tr", "h1", "h2", "h3", "h4", "article", "section"):
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in self.SKIP and self._skip:
            self._skip -= 1
        elif tag == "a" and self._href:
            if self._href.startswith("http"):
                self.parts.append(f" ({self._href})")
            self._href = None

    def handle_data(self, data):
        if not self._skip and data.strip():
            self.parts.append(data.strip() + " ")


def html_to_text(html: str) -> str:
    parser = _TextExtractor()
    parser.feed(html)
    text = "".join(parser.parts)
    return re.sub(r"\n\s*\n+", "\n", re.sub(r"[ \t]+", " ", text)).strip()


def chunk_text(text: str, size: int, overlap: int = 400) -> List[str]:
    if len(text) <= size:
        return [text]
    step = max(size - overlap, 1)
    return [text[i:i + size] for i in range(0, len(text) - overlap, step)]


def fetch_page_text(url: str, timeout: float = 20.0) -> str:
    resp = requests.get(url, timeout=timeout, headers={"User-Agent": USER_AGENT})
    resp.raise_for_status()
    return html_to_text(resp.text)


# --- Token usage ------------------------------------------------------------------------

USAGE: List[dict] = []  # one entry per model call this run; reset by discover()


def record_usage(provider: str, model: str, source: str, input_tokens: int,
                 output_tokens: int, seconds: float, chunk: int = 1) -> None:
    entry = {
        "provider": provider, "model": model, "source": source, "chunk": chunk,
        "input_tokens": int(input_tokens or 0), "output_tokens": int(output_tokens or 0),
        "seconds": round(seconds, 2),
        "output_tok_per_s": round(output_tokens / seconds, 1) if seconds and output_tokens else 0.0,
    }
    USAGE.append(entry)
    log.info("  tokens %s: in=%d out=%d %.1fs (%.1f tok/s)", source, entry["input_tokens"],
             entry["output_tokens"], seconds, entry["output_tok_per_s"])


def usage_totals(entries: Iterable[dict] = None) -> dict:
    entries = list(USAGE if entries is None else entries)
    seconds = sum(e["seconds"] for e in entries)
    out = sum(e["output_tokens"] for e in entries)
    return {
        "calls": len(entries),
        "input_tokens": sum(e["input_tokens"] for e in entries),
        "output_tokens": out,
        "seconds": round(seconds, 1),
        "output_tok_per_s": round(out / seconds, 1) if seconds else 0.0,
    }


# --- Providers --------------------------------------------------------------------------
# Each takes (source, today) and returns raw rows.

def ask_gemini(source: dict, today: date) -> list:
    if not config.GEMINI_API_KEY or config.GEMINI_API_KEY == "your-key-here":
        raise ProviderUnavailable("GEMINI_API_KEY is not set. Add it to .env (see README).")
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=config.GEMINI_API_KEY)
    started = time.monotonic()
    resp = client.models.generate_content(
        model=config.GEMINI_MODEL,
        contents=build_prompt(source, today),
        config=types.GenerateContentConfig(
            tools=[types.Tool(url_context=types.UrlContext())],
            temperature=0.2,
        ),
    )
    meta = resp.usage_metadata
    if meta is not None:
        record_usage("gemini", config.GEMINI_MODEL, source["name"],
                     (meta.prompt_token_count or 0) + (meta.tool_use_prompt_token_count or 0),
                     (meta.candidates_token_count or 0) + (meta.thoughts_token_count or 0),
                     time.monotonic() - started)
    return extract_json_array(resp.text or "")


def ask_claude(source: dict, today: date, max_continuations: int = 3) -> list:
    import anthropic

    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY or None)
    messages = [{"role": "user", "content": build_prompt(source, today)}]
    tools = [{"type": "web_fetch_20260209", "name": "web_fetch", "max_uses": 5}]
    started, tokens_in, tokens_out = time.monotonic(), 0, 0
    try:
        for _ in range(max_continuations + 1):
            resp = client.beta.messages.create(
                model=config.CLAUDE_MODEL,
                max_tokens=16000,
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",  # retry on another model if a safety filter declines
                output_config={"effort": "medium"},
                tools=tools,
                messages=messages,
            )
            tokens_in += resp.usage.input_tokens
            tokens_out += resp.usage.output_tokens
            if resp.stop_reason != "pause_turn":
                break
            # Server-side fetch loop paused; send the turn back and it resumes.
            messages = messages[:1] + [{"role": "assistant", "content": resp.content}]
    except (anthropic.AuthenticationError, anthropic.PermissionDeniedError) as exc:
        raise ProviderUnavailable(f"Claude rejected the API key: {exc}") from exc
    except anthropic.NotFoundError as exc:
        raise ProviderUnavailable(f"Claude model {config.CLAUDE_MODEL!r} not found") from exc
    record_usage("claude", config.CLAUDE_MODEL, source["name"], tokens_in, tokens_out,
                 time.monotonic() - started)
    if resp.stop_reason == "refusal":
        log.warning("%s: Claude declined the request", source["name"])
        return []
    return extract_json_array("".join(b.text for b in resp.content if b.type == "text"))


def ollama_chat(prompt: str) -> Tuple[str, int, int, float]:
    """Return (reply, input_tokens, output_tokens, seconds) from a local Ollama server."""
    started = time.monotonic()
    try:
        resp = requests.post(f"{config.OLLAMA_URL}/api/chat", timeout=900, json={
            "model": config.OLLAMA_MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
            "options": {"temperature": 0.1, "num_ctx": config.LOCAL_CONTEXT_TOKENS,
                        "num_predict": config.LOCAL_MAX_OUTPUT_TOKENS},
        })
    except requests.ConnectionError as exc:
        raise ProviderUnavailable(
            f"Ollama isn't running at {config.OLLAMA_URL} (start it with `ollama serve`)") from exc
    if resp.status_code == 404:
        raise ProviderUnavailable(
            f"Ollama model {config.OLLAMA_MODEL!r} not found; run `ollama pull {config.OLLAMA_MODEL}`")
    resp.raise_for_status()
    data = resp.json()
    # Ollama reports its own timing in nanoseconds; fall back to wall clock.
    seconds = data.get("total_duration", 0) / 1e9 or time.monotonic() - started
    return (data.get("message", {}).get("content", ""), data.get("prompt_eval_count", 0),
            data.get("eval_count", 0), seconds)


def mlx_chat(prompt: str) -> Tuple[str, int, int, float]:
    """Return (reply, input_tokens, output_tokens, seconds) from `mlx_lm.server`."""
    started = time.monotonic()
    try:
        resp = requests.post(f"{config.MLX_URL}/v1/chat/completions", timeout=900, json={
            "model": config.MLX_MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.1,
            "max_tokens": config.LOCAL_MAX_OUTPUT_TOKENS,
        })
    except requests.ConnectionError as exc:
        raise ProviderUnavailable(
            f"MLX server isn't running at {config.MLX_URL} "
            f"(start it with `mlx_lm.server --model {config.MLX_MODEL}`)") from exc
    resp.raise_for_status()
    data = resp.json()
    usage = data.get("usage") or {}
    reply = (data.get("choices") or [{}])[0].get("message", {}).get("content", "")
    return (reply, usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0),
            time.monotonic() - started)


def _ask_local(source: dict, today: date, chat: Callable, provider: str, model: str) -> list:
    """Download the page ourselves, then have a local model read it chunk by chunk."""
    text = fetch_page_text(source["url"])
    if not text:
        return []
    chunks = chunk_text(text, config.LOCAL_CHUNK_CHARS)
    rows: list = []
    for i, chunk in enumerate(chunks, 1):
        prompt = build_prompt(source, today, page_text=chunk, part=i, parts=len(chunks))
        reply, tokens_in, tokens_out, seconds = chat(prompt)
        record_usage(provider, model, source["name"], tokens_in, tokens_out, seconds, chunk=i)
        rows.extend(extract_json_array(reply))
    return rows


def ask_ollama(source: dict, today: date) -> list:
    return _ask_local(source, today, ollama_chat, "ollama", config.OLLAMA_MODEL)


def ask_mlx(source: dict, today: date) -> list:
    return _ask_local(source, today, mlx_chat, "mlx", config.MLX_MODEL)


PROVIDERS = {"gemini": ask_gemini, "claude": ask_claude, "ollama": ask_ollama, "mlx": ask_mlx}
LOCAL_PROVIDERS = {"ollama", "mlx"}


def _status(exc: Exception):
    return getattr(exc, "code", None) or getattr(exc, "status_code", None)


def _is_quota_error(exc: Exception) -> bool:
    return _status(exc) == 429 or "RESOURCE_EXHAUSTED" in str(exc)


def _is_overloaded(exc: Exception) -> bool:
    return _status(exc) in (503, 529) or "UNAVAILABLE" in str(exc) or "overloaded" in str(exc)


def ask_with_retry(call: Callable[[], list], retry_wait: float = 60.0) -> list:
    """Run one provider call; on a 429/503/529 wait and retry once. Repeated 429s end the run."""
    try:
        return call()
    except Exception as exc:
        if not (_is_quota_error(exc) or _is_overloaded(exc)):
            raise
        log.info("Model busy (%s); waiting %.0fs and retrying once", _status(exc), retry_wait)
        time.sleep(retry_wait)
        try:
            return call()
        except Exception as exc2:
            if _is_quota_error(exc2):
                raise QuotaExhausted(
                    f"{config.LLM_PROVIDER} quota exhausted. Check your provider's rate limits, "
                    "or pick another model or LLM_PROVIDER in .env.") from exc2
            raise


def discover(today: Optional[date] = None, pause_seconds: float = 5.0,
             sources: Optional[List[dict]] = None, provider: Optional[str] = None) -> List[dict]:
    """Have the configured model read every source page and return raw (unvalidated) rows."""
    provider = provider or config.LLM_PROVIDER
    if provider == "none":
        log.info("LLM_PROVIDER=none: skipping source pages")
        return []
    if provider not in PROVIDERS:
        raise ProviderUnavailable(
            f"Unknown LLM_PROVIDER {provider!r}; use one of {', '.join(PROVIDERS)} or none")
    ask = PROVIDERS[provider]
    USAGE.clear()
    today = today or date.today()
    sources = sources if sources is not None else load_sources()
    log.info("Reading %d source pages with %s", len(sources), provider)
    rows: List[dict] = []
    for i, source in enumerate(sources):
        try:
            found = ask_with_retry(lambda: ask(source, today))
            log.info("%s: %d rows", source["name"], len(found))
            rows.extend(found)
        except QuotaExhausted:
            log.error("Stopping after %d/%d sources: quota exhausted", i, len(sources))
            if not rows:
                raise
            break
        except ProviderUnavailable:
            raise
        except Exception as exc:  # one bad source shouldn't sink the run
            log.warning("%s failed: %.200s", source["name"], exc)
        if i < len(sources) - 1 and provider not in LOCAL_PROVIDERS:
            time.sleep(pause_seconds)  # stay under hosted requests-per-minute limits
    return rows
