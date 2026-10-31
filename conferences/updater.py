"""Weekly job: prune past events, discover new ones, save them.

    python -m conferences.updater                  # confs.tech + inbox + LLM_PROVIDER pages
    python -m conferences.updater --inbox-only     # just import data/inbox/*.json (e.g. from Cowork)
    python -m conferences.updater --provider mlx   # override LLM_PROVIDER for this run
    python -m conferences.updater --fixture FILE   # offline run from a JSON file
    python -m conferences.updater --dry-run        # discover + validate, don't save
"""
import argparse
import csv
import json
import logging
import sys
import warnings
from datetime import date, datetime
from pathlib import Path

# Python 3.9 + LibreSSL triggers harmless deprecation noise from urllib3 and google-auth.
warnings.filterwarnings("ignore", message=".*OpenSSL.*")
warnings.filterwarnings("ignore", category=FutureWarning, module=r"google\..*")

from . import config, db, discovery  # noqa: E402

log = logging.getLogger("conferences.updater")

USAGE_FIELDS = ("timestamp", "provider", "model", "source", "chunk", "input_tokens",
                "output_tokens", "seconds", "output_tok_per_s")


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


def write_usage(entries: list, path: Path = None) -> None:
    """Append this run's per-call token usage to the CSV log."""
    if not entries:
        return
    path = Path(path or config.USAGE_LOG)
    path.parent.mkdir(parents=True, exist_ok=True)
    new_file = not path.exists()
    stamp = datetime.now().isoformat(timespec="seconds")
    with path.open("a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=USAGE_FIELDS)
        if new_file:
            writer.writeheader()
        for e in entries:
            writer.writerow({"timestamp": stamp, **e})


def run(fixture: Path = None, dry_run: bool = False, check_urls: bool = True,
        inbox_only: bool = False, provider: str = None) -> dict:
    today = date.today()
    provider = provider or config.LLM_PROVIDER
    checker = discovery.check_url if check_urls else None
    # (source, rows, url_checker). confs.tech is curated, so its URLs aren't re-checked.
    batches = []
    inbox_files = []
    if fixture:
        batches.append(("fixture", json.loads(Path(fixture).read_text()), checker))
    else:
        for path, rows in discovery.read_inbox():
            log.info("Inbox %s: %d rows", path.name, len(rows))
            batches.append(("cowork" if path.name.startswith("cowork") else "inbox", rows, checker))
            inbox_files.append(path)
        if not inbox_only:
            batches.append(("confs.tech", discovery.fetch_confs_tech(today), None))
            try:
                batches.append((provider, discovery.discover(today, provider=provider), checker))
            except (discovery.QuotaExhausted, discovery.ProviderUnavailable) as exc:
                log.error("%s", exc)

    cleaned = [(source, discovery.clean(raw, today, url_checker=url_checker), len(raw))
               for source, raw, url_checker in batches]

    # Discovery can take a long time, so open the database only once it's done.
    conn = db.connect()
    db.init_db(conn)
    pruned = 0 if dry_run else db.prune(conn, today)
    found = valid = added = 0
    for source, records, n_raw in cleaned:
        found += n_raw
        valid += len(records)
        if not dry_run:
            added += db.upsert_many(conn, records, source=source)
    total = conn.execute("SELECT COUNT(*) FROM conferences").fetchone()[0]
    conn.close()

    if not dry_run:
        for path in inbox_files:
            discovery.archive_inbox_file(path)

    usage = list(discovery.USAGE) if not (fixture or inbox_only) else []
    write_usage(usage)
    summary = {"pruned": pruned, "found": found, "valid": valid,
               "added": added, "updated": 0 if dry_run else valid - added, "total": total,
               "dry_run": dry_run}
    log.info("Summary: %s", summary)
    if usage:
        totals = discovery.usage_totals(usage)
        summary["tokens"] = totals
        log.info("Tokens (%s): %d calls, %d in / %d out, %.1fs model time, %.1f output tok/s "
                 "→ per-call detail in %s", provider, totals["calls"], totals["input_tokens"],
                 totals["output_tokens"], totals["seconds"], totals["output_tok_per_s"],
                 config.USAGE_LOG)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--fixture", type=Path, help="load rows from a JSON file instead")
    parser.add_argument("--inbox-only", action="store_true",
                        help="only import data/inbox/*.json; skip confs.tech and the model")
    parser.add_argument("--provider", choices=sorted(discovery.PROVIDERS) + ["none"],
                        help="override LLM_PROVIDER for this run")
    parser.add_argument("--dry-run", action="store_true", help="don't write to the database")
    parser.add_argument("--no-url-check", action="store_true", help="skip checking that URLs respond")
    args = parser.parse_args()

    setup_logging()
    try:
        # Fixture URLs are placeholders, so skip the network check for them.
        run(args.fixture, args.dry_run, check_urls=not (args.no_url_check or args.fixture),
            inbox_only=args.inbox_only, provider=args.provider)
    except Exception as exc:
        log.error("Update failed: %s", exc)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
