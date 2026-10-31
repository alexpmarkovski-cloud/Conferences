"""Find conferences from two free sources, then validate the results.

1. Source pages (conferences/sources.json): Gemini reads each page with the
   url_context tool and extracts events as JSON.
2. confs.tech: an open, curated dataset of tech conferences on GitHub.

Everything Gemini returns is untrusted: it is parsed as data, checked field by
field, and its URL must respond before it reaches the database.
"""
import json
import logging
import re
import time
from datetime import date, timedelta
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

PROMPT = """Read this page: {url}
It is "{name}", a listing of {focus} events.

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
    """Gemini keeps returning 429; further calls this run would fail too."""


def load_sources(path: Path = SOURCES_FILE) -> List[dict]:
    return json.loads(Path(path).read_text())


def build_prompt(source: dict, today: date, horizon_days: int = 365) -> str:
    return PROMPT.format(url=source["url"], name=source["name"],
                         focus=source.get("focus", "upcoming"),
                         start=today.isoformat(),
                         end=(today + timedelta(days=horizon_days)).isoformat())


def extract_json_array(text: str) -> list:
    """Pull a JSON array out of a model reply, tolerating code fences and prose."""
    if not text:
        return []
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


# --- Gemini over source pages ------------------------------------------------------

def ask_gemini(prompt: str) -> str:
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=config.GEMINI_API_KEY)
    resp = client.models.generate_content(
        model=config.GEMINI_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            tools=[types.Tool(url_context=types.UrlContext())],
            temperature=0.2,
        ),
    )
    return resp.text or ""


def _is_quota_error(exc: Exception) -> bool:
    return getattr(exc, "code", None) == 429 or "RESOURCE_EXHAUSTED" in str(exc)


def _is_overloaded(exc: Exception) -> bool:
    return getattr(exc, "code", None) == 503 or "UNAVAILABLE" in str(exc)


def ask_with_retry(prompt: str, retry_wait: float = 60.0) -> str:
    """Call Gemini; on a 429 or 503 wait and retry once. Repeated 429s end the run."""
    try:
        return ask_gemini(prompt)
    except Exception as exc:
        if not (_is_quota_error(exc) or _is_overloaded(exc)):
            raise
        log.info("Gemini busy (%s); waiting %.0fs and retrying once",
                 getattr(exc, "code", "?"), retry_wait)
        time.sleep(retry_wait)
        try:
            return ask_gemini(prompt)
        except Exception as exc2:
            if _is_quota_error(exc2):
                raise QuotaExhausted(
                    f"Gemini quota exhausted for model {config.GEMINI_MODEL}. "
                    "Check https://ai.dev/rate-limit, or set GEMINI_MODEL in .env "
                    "to a model with free-tier quota.") from exc2
            raise


def discover(today: Optional[date] = None, pause_seconds: float = 5.0,
             sources: Optional[List[dict]] = None) -> List[dict]:
    """Have Gemini read every source page and return raw (unvalidated) rows."""
    if not config.GEMINI_API_KEY or config.GEMINI_API_KEY == "your-key-here":
        raise RuntimeError("GEMINI_API_KEY is not set. Add it to .env (see README).")
    today = today or date.today()
    sources = sources if sources is not None else load_sources()
    rows: List[dict] = []
    for i, source in enumerate(sources):
        try:
            found = extract_json_array(ask_with_retry(build_prompt(source, today)))
            log.info("%s: %d rows", source["name"], len(found))
            rows.extend(found)
        except QuotaExhausted:
            log.error("Stopping after %d/%d sources: quota exhausted", i, len(sources))
            if not rows:
                raise
            break
        except Exception as exc:  # one bad source shouldn't sink the run
            log.warning("%s failed: %.200s", source["name"], exc)
        if i < len(sources) - 1:
            time.sleep(pause_seconds)  # stay under free-tier requests-per-minute
    return rows
