import json
from datetime import date
from pathlib import Path

from conferences import discovery

TODAY = date(2026, 10, 31)
FIXTURE = Path(__file__).parent / "fixtures" / "sample_gemini_response.json"


def test_extract_json_from_fenced_reply():
    text = 'Here you go:\n```json\n[{"name": "A"}]\n```\nThanks'
    assert discovery.extract_json_array(text) == [{"name": "A"}]


def test_extract_json_handles_garbage():
    assert discovery.extract_json_array("no events found") == []
    assert discovery.extract_json_array("[not json") == []
    assert discovery.extract_json_array("") == []


def test_clean_fixture_drops_bad_rows():
    rows = json.loads(FIXTURE.read_text())
    cleaned = discovery.clean(rows, TODAY, url_checker=None)
    names = {r["name"] for r in cleaned}
    assert len(cleaned) == 6
    assert "Sample Past Conference" not in names
    assert "Sample Bad Category" not in names
    assert "Sample No Location" not in names


def test_clean_drops_unreachable_urls():
    rows = json.loads(FIXTURE.read_text())[:2]
    cleaned = discovery.clean(rows, TODAY, url_checker=lambda url: None if "dev-days" in url else url)
    assert [r["name"] for r in cleaned] == ["Sample Wasatch AI Summit"]


def test_validate_rejects_reversed_dates():
    rec, reason = discovery.validate(
        {"name": "X", "category": "ai", "start_date": "2027-02-02", "end_date": "2027-02-01",
         "url": "https://x.com", "is_virtual": True}, TODAY)
    assert rec is None and reason == "start after end"


def test_sources_file_is_valid():
    sources = discovery.load_sources()
    assert sources and all(s["url"].startswith("https://") and s["name"] for s in sources)
    prompt = discovery.build_prompt(sources[0], TODAY)
    assert sources[0]["url"] in prompt and "2027-10-31" in prompt


def test_from_confs_tech_maps_us_online_and_skips_foreign():
    us = discovery.from_confs_tech({"name": "AI DevCon NYC", "url": "https://x.dev",
                                    "startDate": "2027-01-05", "city": "Brooklyn, NY",
                                    "country": "U.S.A.", "online": True})
    assert us["city"] == "Brooklyn" and us["state"] == "NY"
    assert us["category"] == "ai" and not us["is_virtual"] and us["end_date"] == "2027-01-05"

    online = discovery.from_confs_tech({"name": "DevOps Days Online", "url": "https://y.dev",
                                        "startDate": "2027-02-01", "endDate": "2027-02-02",
                                        "online": True})
    assert online["is_virtual"] and online["category"] == "tech"

    assert discovery.from_confs_tech({"name": "PyCon DE", "country": "Germany",
                                      "city": "Berlin", "online": False}) is None


class FakeQuotaError(Exception):
    code = 429


def test_discover_keeps_rows_and_stops_when_quota_runs_out(monkeypatch):
    calls = []

    def fake_ask(prompt):
        calls.append(prompt)
        if len(calls) == 1:
            return '[{"name": "A"}]'
        raise FakeQuotaError("RESOURCE_EXHAUSTED")

    monkeypatch.setattr(discovery.config, "GEMINI_API_KEY", "test")
    monkeypatch.setattr(discovery, "ask_gemini", fake_ask)
    monkeypatch.setattr(discovery.time, "sleep", lambda s: None)
    sources = [{"name": n, "url": f"https://{n}.com"} for n in ("a", "b", "c")]
    rows = discovery.discover(TODAY, sources=sources)
    assert rows == [{"name": "A"}]
    assert len(calls) == 3  # first source, then second source + one retry; third never called


def test_discover_raises_when_quota_exhausted_from_start(monkeypatch):
    def always_429(prompt):
        raise FakeQuotaError("RESOURCE_EXHAUSTED")

    monkeypatch.setattr(discovery.config, "GEMINI_API_KEY", "test")
    monkeypatch.setattr(discovery, "ask_gemini", always_429)
    monkeypatch.setattr(discovery.time, "sleep", lambda s: None)
    try:
        discovery.discover(TODAY, sources=[{"name": "a", "url": "https://a.com"}])
    except discovery.QuotaExhausted:
        return
    raise AssertionError("expected QuotaExhausted")
