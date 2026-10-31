"""Find conferences with Gemini + Google Search grounding, then validate the results.

Everything the model returns is untrusted: it is parsed as data, checked field by
field, and its URL must respond before it reaches the database.
"""
import json
import logging
import re
import time
from datetime import date, timedelta
from typing import Callable, Iterable, List, Optional, Tuple

import requests

from . import config

log = logging.getLogger(__name__)

REGIONS = {
    "core": "Salt Lake County or Utah County, Utah (e.g. Salt Lake City, Sandy, Draper, "
            "South Jordan, Lehi, Provo, Orem, American Fork)",
    "utah": "Utah outside Salt Lake and Utah County (e.g. Park City, Ogden, Logan, "
            "St. George, Layton)",
    "other": "the United States (major national events) or fully virtual/online",
}
CATEGORY_TOPICS = {
    "ai": "artificial intelligence, machine learning, generative AI, or data science",
    "tech": "software, developer, startup, cloud, cybersecurity, or general technology",
    "finance": "finance, fintech, investing, banking, accounting, or crypto/web3",
}

PROMPT = """Search the web for upcoming in-person or virtual conferences about {topic}
held in {region}, starting between {start} and {end}.

Only include real events with an official website and announced dates. Skip meetups
with no dates, webinars under half a day, and events you cannot confirm.

Reply with ONLY a JSON array (no prose). Each item:
{{"name": str, "category": "{category}", "start_date": "YYYY-MM-DD",
  "end_date": "YYYY-MM-DD", "city": str or null, "state": two-letter US state or null,
  "is_virtual": bool, "venue": str or null, "url": official https URL,
  "description": one sentence}}
Return [] if you find none."""

REQUIRED = ("name", "category", "start_date", "end_date", "url")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
ALIVE_STATUSES = {401, 403, 405, 429}  # sites that block bots but exist
USER_AGENT = "Mozilla/5.0 (Macintosh) ConferenceTracker/1.0"


def build_queries(today: date, horizon_days: int = 365) -> List[Tuple[str, str, str]]:
    """Return (category, region, prompt) for every category x region pair."""
    start, end = today.isoformat(), (today + timedelta(days=horizon_days)).isoformat()
    return [
        (cat, region, PROMPT.format(topic=topic, region=REGIONS[region], start=start,
                                    end=end, category=cat))
        for cat, topic in CATEGORY_TOPICS.items()
        for region in REGIONS
    ]


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


def ask_gemini(prompt: str) -> str:
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=config.GEMINI_API_KEY)
    resp = client.models.generate_content(
        model=config.GEMINI_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            tools=[types.Tool(google_search=types.GoogleSearch())],
            temperature=0.2,
        ),
    )
    return resp.text or ""


def discover(today: Optional[date] = None, pause_seconds: float = 6.0) -> List[dict]:
    """Run every query against Gemini and return raw (unvalidated) rows."""
    if not config.GEMINI_API_KEY or config.GEMINI_API_KEY == "your-key-here":
        raise RuntimeError("GEMINI_API_KEY is not set. Add it to .env (see README).")
    today = today or date.today()
    rows: List[dict] = []
    queries = build_queries(today)
    for i, (cat, region, prompt) in enumerate(queries):
        try:
            found = extract_json_array(ask_gemini(prompt))
            log.info("Query %s/%s returned %d rows", cat, region, len(found))
            rows.extend(found)
        except Exception as exc:  # one failed query shouldn't sink the run
            log.warning("Query %s/%s failed: %s", cat, region, exc)
        if i < len(queries) - 1:
            time.sleep(pause_seconds)  # stay under free-tier requests-per-minute
    return rows
