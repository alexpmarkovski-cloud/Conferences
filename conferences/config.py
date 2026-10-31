"""Paths, ranking weights, and environment settings."""
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

DATA_DIR = ROOT / "data"
LOG_DIR = DATA_DIR / "logs"
DB_PATH = Path(os.environ.get("CONFERENCES_DB", DATA_DIR / "conferences.db"))
if not DB_PATH.is_absolute():
    DB_PATH = ROOT / DB_PATH

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.8-flash")

APP_HOST = "127.0.0.1"
APP_PORT = 5050

CATEGORIES = ("ai", "tech", "finance")
CATEGORY_WEIGHT = {"ai": 3, "tech": 2, "finance": 1}

# Location tiers: higher ranks first.
TIER_CORE = 3      # Salt Lake County or Utah County
TIER_UTAH = 2      # elsewhere in Utah
TIER_OTHER = 1     # rest of US, international, or virtual
TIER_LABELS = {
    TIER_CORE: "Salt Lake & Utah County",
    TIER_UTAH: "Elsewhere in Utah",
    TIER_OTHER: "US & Virtual",
}
REGION_TIERS = {"core": TIER_CORE, "utah": TIER_UTAH, "other": TIER_OTHER}
