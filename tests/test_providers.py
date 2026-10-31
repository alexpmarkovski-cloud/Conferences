import csv
import json
from datetime import date
from types import SimpleNamespace

import pytest

from conferences import config, discovery, updater

TODAY = date(2026, 10, 31)
SOURCE = {"name": "Test page", "url": "https://test.example", "focus": "tech"}
ROW = {"name": "Local AI Summit", "category": "ai", "start_date": "2027-02-01",
       "end_date": "2027-02-02", "city": "Provo", "state": "UT", "url": "https://a.example"}


@pytest.fixture(autouse=True)
def clear_usage():
    discovery.USAGE.clear()
    yield
    discovery.USAGE.clear()


def test_html_to_text_keeps_links_and_drops_scripts():
    html = ('<html><head><title>x</title></head><body><script>var a=1;</script>'
            '<h2>Events</h2><p><a href="https://ev.example/ai">Utah AI Day</a> Feb 3, 2027</p>'
            '<a href="/relative">skip me</a></body></html>')
    text = discovery.html_to_text(html)
    assert "Utah AI Day (https://ev.example/ai)" in text
    assert "var a" not in text and "(/relative)" not in text


def test_chunk_text_overlaps_and_covers_everything():
    text = "".join(str(i % 10) for i in range(25000))
    chunks = discovery.chunk_text(text, 10000, overlap=400)
    assert len(chunks) == 3
    assert chunks[0][-400:] == chunks[1][:400]
    assert chunks[-1].endswith(text[-100:])
    assert discovery.chunk_text("short", 10000) == ["short"]


def test_extract_json_ignores_think_blocks():
    reply = '<think>maybe [1, 2]?</think>\n[{"name": "A"}]'
    assert discovery.extract_json_array(reply) == [{"name": "A"}]


def test_text_prompt_embeds_page_and_part():
    prompt = discovery.build_prompt(SOURCE, TODAY, page_text="EVENT LIST", part=2, parts=3)
    assert "EVENT LIST" in prompt and "part 2 of 3" in prompt and "https://test.example" in prompt


@pytest.mark.parametrize("provider", ["ollama", "mlx"])
def test_local_providers_chunk_and_record_tokens(monkeypatch, provider):
    monkeypatch.setattr(config, "LOCAL_CHUNK_CHARS", 1000)
    monkeypatch.setattr(discovery, "fetch_page_text", lambda url: "x" * 1500)
    chat = lambda prompt: (json.dumps([ROW]), 800, 120, 4.0)
    monkeypatch.setattr(discovery, f"{provider}_chat", chat)
    monkeypatch.setitem(discovery.PROVIDERS, provider,
                        lambda s, t: discovery._ask_local(s, t, chat, provider, "m"))

    rows = discovery.discover(TODAY, sources=[SOURCE], provider=provider)
    assert len(rows) == 2  # two chunks, one row each (deduped later by clean())
    assert [u["chunk"] for u in discovery.USAGE] == [1, 2]
    totals = discovery.usage_totals()
    assert totals == {"calls": 2, "input_tokens": 1600, "output_tokens": 240,
                      "seconds": 8.0, "output_tok_per_s": 30.0}


def test_mlx_chat_parses_openai_style_usage(monkeypatch):
    payload = {"choices": [{"message": {"content": "[]"}}],
               "usage": {"prompt_tokens": 900, "completion_tokens": 50}}
    monkeypatch.setattr(discovery.requests, "post",
                        lambda *a, **k: SimpleNamespace(json=lambda: payload,
                                                        raise_for_status=lambda: None))
    reply, tin, tout, secs = discovery.mlx_chat("hi")
    assert (reply, tin, tout) == ("[]", 900, 50) and secs >= 0


def test_ollama_chat_reports_server_timing(monkeypatch):
    payload = {"message": {"content": "[]"}, "prompt_eval_count": 700, "eval_count": 30,
               "total_duration": 2_500_000_000}
    monkeypatch.setattr(discovery.requests, "post",
                        lambda *a, **k: SimpleNamespace(status_code=200, json=lambda: payload,
                                                        raise_for_status=lambda: None))
    assert discovery.ollama_chat("hi") == ("[]", 700, 30, 2.5)


def test_unavailable_local_server_stops_discovery(monkeypatch):
    def refuse(*a, **k):
        raise discovery.requests.ConnectionError("refused")
    monkeypatch.setattr(discovery, "fetch_page_text", lambda url: "page")
    monkeypatch.setattr(discovery.requests, "post", refuse)
    with pytest.raises(discovery.ProviderUnavailable, match="mlx_lm.server"):
        discovery.discover(TODAY, sources=[SOURCE, SOURCE], provider="mlx")


def test_unknown_and_none_providers():
    assert discovery.discover(TODAY, sources=[SOURCE], provider="none") == []
    with pytest.raises(discovery.ProviderUnavailable):
        discovery.discover(TODAY, sources=[SOURCE], provider="gpt")


def test_write_usage_appends_csv(tmp_path):
    path = tmp_path / "usage.csv"
    entry = {"provider": "mlx", "model": "m", "source": "s", "chunk": 1, "input_tokens": 10,
             "output_tokens": 5, "seconds": 1.0, "output_tok_per_s": 5.0}
    updater.write_usage([entry], path)
    updater.write_usage([entry], path)
    rows = list(csv.DictReader(path.open()))
    assert len(rows) == 2 and rows[0]["provider"] == "mlx" and rows[1]["output_tokens"] == "5"


def test_inbox_import_saves_rows_and_archives_file(monkeypatch, tmp_path):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "cowork-2026-10-31.json").write_text(json.dumps([ROW]))
    monkeypatch.setattr(config, "INBOX_DIR", inbox)
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.db")
    monkeypatch.setattr(updater.db.config, "DB_PATH", tmp_path / "test.db")

    summary = updater.run(inbox_only=True, check_urls=False)
    assert summary["added"] == 1 and summary["total"] == 1
    assert not list(inbox.glob("*.json"))
    assert (inbox / "processed" / "cowork-2026-10-31.json").exists()
