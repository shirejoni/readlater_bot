"""Central config loader: .env (secrets) + config.yaml (rate limit defaults).

- .env is gitignored and holds secrets: BALE_TOKEN, ADMIN_USER_ID.
- config.yaml is committed and holds per-user rate limit defaults.
"""
import os
from pathlib import Path

from dotenv import load_dotenv
import yaml

BASE_DIR = Path(__file__).resolve().parent

# Load secrets from .env (gitignored) if present.
load_dotenv(BASE_DIR / ".env")

BALE_TOKEN = os.environ.get("BALE_TOKEN")
ADMIN_USER_ID = os.environ.get("ADMIN_USER_ID")
if not BALE_TOKEN:
    raise SystemExit("BALE_TOKEN is not set. Put it in the .env file.")


def is_admin(user_id):
    """True if user_id is the configured admin (exempt from rate limits)."""
    return bool(ADMIN_USER_ID) and str(user_id) == str(ADMIN_USER_ID)


# Defaults used when config.yaml is missing or a section is absent.
DEFAULT_LIMITS = {
    "playlist_create": {"max": 20, "per": "day"},
    "item_create": {"max": 100, "per": "day"},
    "commands": {"max": 300, "per": "hour"},
}
DEFAULT_PROXY = "http://127.0.0.1:2080"

_RAW = None  # parsed config.yaml dict (parsed once, cached)


def _raw_config():
    """Parse config.yaml once; return {} if missing/malformed."""
    global _RAW
    if _RAW is None:
        _RAW = {}
        cfg = BASE_DIR / "config.yaml"
        if cfg.exists():
            try:
                _RAW = yaml.safe_load(cfg.read_text(encoding="utf-8")) or {}
            except yaml.YAMLError:
                _RAW = {}
    return _RAW


def load_limits():
    """Return the rate-limit dict from config.yaml (falls back to defaults)."""
    limits = {k: dict(v) for k, v in DEFAULT_LIMITS.items()}
    for key, val in (_raw_config().get("limits") or {}).items():
        if isinstance(val, dict):
            limits[key] = val
    return limits


def load_proxy():
    """Return the HTTP proxy string from config.yaml (falls back to default)."""
    val = _raw_config().get("proxy")
    if val:
        return str(val)
    return DEFAULT_PROXY


LIMITS = load_limits()
PROXY = load_proxy()
