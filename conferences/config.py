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

INBOX_DIR = DATA_DIR / "inbox"  # JSON files dropped here (e.g. by Cowork) get imported

# Which model reads the source pages: gemini | claude | ollama | mlx | none
LLM_PROVIDER = os.environ.get("LLM_PROVIDER", "gemini").strip().lower()

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.8-flash")

# Empty is fine: the Anthropic SDK also finds credentials from `ant auth login`.
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL = os.environ.get("CLAUDE_MODEL", "claude-sonnet-5-5")

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434").rstrip("/")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "gemma3:12b")

# Apple MLX via `mlx_lm.server` (OpenAI-compatible API, Apple Silicon only).
MLX_URL = os.environ.get("MLX_URL", "http://localhost:8080").rstrip("/")
MLX_MODEL = os.environ.get("MLX_MODEL", "mlx-community/gemma-3-12b-it-4bit")

# Max tokens a local model may write per chunk.
LOCAL_MAX_OUTPUT_TOKENS = int(os.environ.get("LOCAL_MAX_OUTPUT_TOKENS", "4096"))
USAGE_LOG = LOG_DIR / "token_usage.csv"
# Local models read page text in chunks; smaller models do better with smaller chunks.
LOCAL_CHUNK_CHARS = int(os.environ.get("LOCAL_CHUNK_CHARS", "12000"))
LOCAL_CONTEXT_TOKENS = int(os.environ.get("LOCAL_CONTEXT_TOKENS", "16384"))

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
