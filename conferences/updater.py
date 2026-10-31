"""Weekly job: prune past events, discover new ones, save them.

    python -m conferences.updater                  # real run with Gemini
    python -m conferences.updater --fixture FILE   # offline run from a JSON file
    python -m conferences.updater --dry-run        # discover + validate, don't save
"""
import argparse
import json
import logging
import sys
import warnings
from datetime import date
from pathlib import Path

# Python 3.9 + LibreSSL triggers harmless deprecation noise from urllib3 and google-auth.
warnings.filterwarnings("ignore", message=".*OpenSSL.*")
warnings.filterwarnings("ignore", category=FutureWarning, module=r"google\..*")

from . import config, db, discovery  # noqa: E402

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
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("google_genai").setLevel(logging.ERROR)


def run(fixture: Path = None, dry_run: bool = False, check_urls: bool = True) -> dict:
    today = date.today()
    conn = db.connect()
    db.init_db(conn)
    pruned = 0 if dry_run else db.prune(conn, today)

    checker = discovery.check_url if check_urls else None
    # (source, rows, url_checker). confs.tech is curated, so its URLs aren't re-checked.
    batches = []
    if fixture:
        batches.append(("fixture", json.loads(Path(fixture).read_text()), checker))
    else:
        batches.append(("confs.tech", discovery.fetch_confs_tech(today), None))
        try:
            batches.append(("gemini", discovery.discover(today), checker))
        except discovery.QuotaExhausted as exc:
            log.error("%s", exc)

    found = valid = added = 0
    for source, raw, url_checker in batches:
        records = discovery.clean(raw, today, url_checker=url_checker)
        found += len(raw)
        valid += len(records)
        if not dry_run:
            added += db.upsert_many(conn, records, source=source)
    total = conn.execute("SELECT COUNT(*) FROM conferences").fetchone()[0]
    conn.close()

    summary = {"pruned": pruned, "found": found, "valid": valid,
               "added": added, "updated": 0 if dry_run else valid - added, "total": total,
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
