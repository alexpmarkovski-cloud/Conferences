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


def test_build_queries_covers_every_pair():
    queries = discovery.build_queries(TODAY)
    assert len(queries) == 9
    assert {(c, r) for c, r, _ in queries} == {
        (c, r) for c in ("ai", "tech", "finance") for r in ("core", "utah", "other")}
