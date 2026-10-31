"""SQLite access: init, upsert with dedupe, prune past events, ranked queries."""
import re
import sqlite3
from datetime import date, datetime
from pathlib import Path
from typing import Iterable, List, Mapping, Optional, Union

from . import config, geo, ranking

SCHEMA = Path(__file__).with_name("schema.sql")


def connect(path: Optional[Union[str, Path]] = None) -> sqlite3.Connection:
    path = Path(path or config.DB_PATH)
    if str(path) != ":memory:":
        path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA.read_text())
    conn.commit()


def dedupe_key(name: str, start_date: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", " ", name.lower())
    # Drop years so "Summit 2026" and "Summit" with the same start year match.
    normalized = re.sub(r"\b(19|20)\d{2}\b", " ", normalized)
    return f"{' '.join(normalized.split())}|{start_date[:4]}"


def upsert(conn: sqlite3.Connection, conf: Mapping, source: str = "gemini") -> bool:
    """Insert or refresh a conference. Returns True if it was new."""
    now = datetime.now().isoformat(timespec="seconds")
    county, _ = geo.classify(conf.get("city"), conf.get("state"), bool(conf.get("is_virtual")))
    key = dedupe_key(conf["name"], conf["start_date"])
    existed = conn.execute("SELECT 1 FROM conferences WHERE dedupe_key = ?", (key,)).fetchone()
    conn.execute(
        """
        INSERT INTO conferences (name, category, start_date, end_date, city, state, county,
                                 is_virtual, venue, url, description, source, dedupe_key,
                                 first_seen, last_seen)
        VALUES (:name, :category, :start_date, :end_date, :city, :state, :county,
                :is_virtual, :venue, :url, :description, :source, :dedupe_key, :now, :now)
        ON CONFLICT(dedupe_key) DO UPDATE SET
            name = excluded.name, category = excluded.category,
            start_date = excluded.start_date, end_date = excluded.end_date,
            city = excluded.city, state = excluded.state, county = excluded.county,
            is_virtual = excluded.is_virtual, venue = excluded.venue, url = excluded.url,
            description = excluded.description, last_seen = excluded.last_seen
        """,
        {
            "name": conf["name"],
            "category": conf["category"],
            "start_date": conf["start_date"],
            "end_date": conf["end_date"],
            "city": conf.get("city"),
            "state": conf.get("state"),
            "county": county,
            "is_virtual": int(bool(conf.get("is_virtual"))),
            "venue": conf.get("venue"),
            "url": conf.get("url"),
            "description": conf.get("description"),
            "source": source,
            "dedupe_key": key,
            "now": now,
        },
    )
    conn.commit()
    return existed is None


def upsert_many(conn: sqlite3.Connection, confs: Iterable[Mapping], source: str = "gemini") -> int:
    return sum(upsert(conn, c, source) for c in confs)


def prune(conn: sqlite3.Connection, today: Optional[date] = None) -> int:
    """Delete conferences that have already ended. Returns rows deleted."""
    today_iso = (today or date.today()).isoformat()
    cur = conn.execute("DELETE FROM conferences WHERE end_date < ?", (today_iso,))
    conn.commit()
    return cur.rowcount


def hide(conn: sqlite3.Connection, conf_id: int) -> bool:
    cur = conn.execute("UPDATE conferences SET hidden = 1 WHERE id = ?", (conf_id,))
    conn.commit()
    return cur.rowcount > 0


def list_ranked(conn: sqlite3.Connection, category: Optional[str] = None,
                region: Optional[str] = None, include_hidden: bool = False) -> List[dict]:
    sql = "SELECT * FROM conferences WHERE 1 = 1"
    params: list = []
    if not include_hidden:
        sql += " AND hidden = 0"
    if category in config.CATEGORIES:
        sql += " AND category = ?"
        params.append(category)
    rows = [dict(r) for r in conn.execute(sql, params)]
    for r in rows:
        r["tier"] = ranking.tier(r)
        r["tier_label"] = config.TIER_LABELS[r["tier"]]
    if region in config.REGION_TIERS:
        rows = [r for r in rows if r["tier"] == config.REGION_TIERS[region]]
    return sorted(rows, key=ranking.sort_key)
