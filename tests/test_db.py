from datetime import date

import pytest

from conferences import db


@pytest.fixture
def conn():
    c = db.connect(":memory:")
    db.init_db(c)
    yield c
    c.close()


def conf(**overrides):
    base = {"name": "Utah AI Summit", "category": "ai", "start_date": "2027-03-01",
            "end_date": "2027-03-02", "city": "Lehi", "state": "UT", "is_virtual": False,
            "url": "https://example.com"}
    base.update(overrides)
    return base


def test_upsert_dedupes_and_keeps_hidden(conn):
    assert db.upsert(conn, conf()) is True
    conf_id = conn.execute("SELECT id FROM conferences").fetchone()[0]
    db.hide(conn, conf_id)
    assert db.upsert(conn, conf(name="Utah AI Summit 2027", venue="Hall A")) is False
    rows = conn.execute("SELECT venue, hidden, county FROM conferences").fetchall()
    assert len(rows) == 1
    assert rows[0]["venue"] == "Hall A"
    assert rows[0]["hidden"] == 1
    assert rows[0]["county"] == "Utah"


def test_prune_removes_only_ended(conn):
    db.upsert(conn, conf(name="Past", start_date="2026-10-01", end_date="2026-10-30"))
    db.upsert(conn, conf(name="Ends today", start_date="2026-10-30", end_date="2026-10-31"))
    db.upsert(conn, conf(name="Future"))
    assert db.prune(conn, today=date(2026, 10, 31)) == 1
    names = {r["name"] for r in conn.execute("SELECT name FROM conferences")}
    assert names == {"Ends today", "Future"}


def test_list_ranked_filters(conn):
    db.upsert(conn, conf())
    db.upsert(conn, conf(name="NYC Fintech", category="finance", city="New York", state="NY"))
    assert [r["name"] for r in db.list_ranked(conn)] == ["Utah AI Summit", "NYC Fintech"]
    assert [r["name"] for r in db.list_ranked(conn, category="finance")] == ["NYC Fintech"]
    assert [r["name"] for r in db.list_ranked(conn, region="core")] == ["Utah AI Summit"]
