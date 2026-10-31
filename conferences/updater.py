"""Weekly job: prune past events, discover new ones, save them.

    python -m conferences.updater                  # real run with Gemini
    python -m conferences.updater --fixture FILE   # offline run from a JSON file
    python -m conferences.updater --dry-run        # discover + validate, don't save
"""
import argparse
import json
import logging
import sys
from datetime import date
from pathlib import Path

from . import config, db, discovery

log = logging.getLogger("conferences.updater")


def setup_logging() -> None:
    config.LOG_DIR.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    for handler in (logging.FileHandler(config.LOG_DIR / "updater.log"),
                    logging.StreamHandler(sys.stdout)):
        handler.setFormatter(fmt)
        root.addHandler(handler)
    for noisy in ("httpx", "google_genai", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def run(fixture: Path = None, dry_run: bool = False, check_urls: bool = True) -> dict:
    today = date.today()
    conn = db.connect()
    db.init_db(conn)
    pruned = 0 if dry_run else db.prune(conn, today)

    if fixture:
        raw = json.loads(Path(fixture).read_text())
        source = "fixture"
    else:
        raw = discovery.discover(today)
        source = "gemini"

    checker = discovery.check_url if check_urls else None
    records = discovery.clean(raw, today, url_checker=checker)
    added = 0 if dry_run else db.upsert_many(conn, records, source=source)
    total = conn.execute("SELECT COUNT(*) FROM conferences").fetchone()[0]
    conn.close()

    summary = {"pruned": pruned, "found": len(raw), "valid": len(records),
               "added": added, "updated": len(records) - added, "total": total,
               "dry_run": dry_run}
    log.info("Summary: %s", summary)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--fixture", type=Path, help="load rows from a JSON file instead of Gemini")
    parser.add_argument("--dry-run", action="store_true", help="don't write to the database")
    parser.add_argument("--no-url-check", action="store_true", help="skip checking that URLs respond")
    args = parser.parse_args()

    setup_logging()
    try:
        # Fixture URLs are placeholders, so skip the network check for them.
        run(args.fixture, args.dry_run, check_urls=not (args.no_url_check or args.fixture))
    except Exception as exc:
        log.error("Update failed: %s", exc)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
