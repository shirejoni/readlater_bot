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
    print("Warning: BALE_TOKEN is not set. The bot needs it in .env; "
          "the web dashboard (webapp.py) works without it.")


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
DEFAULT_BACKUP = {"enabled": True, "interval_hours": 24, "chat_id": ""}
DEFAULT_WEB = {"base_url": "http://127.0.0.1:8000", "secure_cookie": False, "url_prefix": ""}

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


def load_backup():
    """Return the backup settings dict from config.yaml (falls back to default)."""
    b = dict(DEFAULT_BACKUP)
    for key, val in (_raw_config().get("backup") or {}).items():
        if val is not None:
            b[key] = val
    return b


LIMITS = load_limits()
PROXY = load_proxy()
BACKUP = load_backup()


def backup_chat_id():
    """Target chat for backups: config.chat_id, else ADMIN_USER_ID."""
    if BACKUP.get("chat_id"):
        return str(BACKUP["chat_id"])
    return str(ADMIN_USER_ID) if ADMIN_USER_ID else None


def load_web():
    """Web dashboard settings (base_url used by the bot's /web command)."""
    w = dict(DEFAULT_WEB)
    for key, val in (_raw_config().get("web") or {}).items():
        if val is not None:
            w[key] = val
    return w


WEB = load_web()


def web_base_url():
    """Public base URL of the web dashboard, e.g. http://127.0.0.1:8000."""
    return str(WEB.get("base_url") or DEFAULT_WEB["base_url"]).rstrip("/")


def web_secure_cookie():
    """Whether the session cookie should carry the Secure flag (HTTPS only)."""
    return bool(WEB.get("secure_cookie"))


def web_url_prefix():
    """URL prefix under which the dashboard is served, e.g. "/readlater".

    Empty string (default) means the dashboard serves at the root. A non-empty
    value (with leading slash, no trailing slash) is used both by the WSGI
    prefix-stripping middleware in webapp.py and by nginx. The bot's /web
    command appends this prefix to its login link.
    """
    p = str(WEB.get("url_prefix") or "").strip()
    if p and not p.startswith("/"):
        p = "/" + p
    return p.rstrip("/")


_WEB_SECRET = None


def web_secret():
    """JWT signing secret: WEB_SECRET env var, else a generated + persisted key.

    The generated key lives in web_secret.key next to the DB so long-lived
    session cookies survive restarts without further setup.
    """
    global _WEB_SECRET
    if _WEB_SECRET is None:
        secret = os.environ.get("WEB_SECRET") or ""
        if not secret:
            key_path = BASE_DIR / "web_secret.key"
            if key_path.exists():
                secret = key_path.read_text(encoding="utf-8").strip()
            else:
                import secrets
                secret = secrets.token_urlsafe(32)
                key_path.write_text(secret, encoding="utf-8")
        _WEB_SECRET = secret
    return _WEB_SECRET
