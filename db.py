"""SQLite persistence layer for the read-later bot.

Everything is scoped per chat_id so the bot can be used independently in
multiple chats without data leaking between them.
"""
import random
import sqlite3
import time
from datetime import datetime, timezone

DB_PATH = "readlater.db"

STATUSES = ("unread", "in_progress", "done")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS playlists (
    id INTEGER PRIMARY KEY,
    chat_id TEXT NOT NULL,
    name TEXT NOT NULL,
    comment TEXT,
    created_at TEXT NOT NULL,
    UNIQUE (chat_id, name)
);
CREATE TABLE IF NOT EXISTS items (
    id INTEGER PRIMARY KEY,
    chat_id TEXT NOT NULL,
    playlist_id INTEGER NOT NULL REFERENCES playlists(id) ON DELETE CASCADE,
    url TEXT NOT NULL,
    title TEXT,
    description TEXT,
    image_url TEXT,
    added_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'unread',
    pinned INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS comments (
    id INTEGER PRIMARY KEY,
    entity_type TEXT NOT NULL,          -- 'item' | 'playlist'
    entity_id INTEGER NOT NULL,
    text TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS rate_events (
    id INTEGER PRIMARY KEY,
    user_id TEXT NOT NULL,
    bucket TEXT NOT NULL,
    ts REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_rate_user
    ON rate_events(user_id, bucket, ts);
CREATE TABLE IF NOT EXISTS web_codes (
    id INTEGER PRIMARY KEY,
    user_id TEXT NOT NULL,
    code TEXT NOT NULL,
    expires_at REAL NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_web_code
    ON web_codes(code);
"""


def _now():
    return datetime.now(timezone.utc).isoformat()


def connect(path=DB_PATH):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    # WAL + busy timeout let the bot process and the web process share the
    # same SQLite file without "database is locked" errors. foreign_keys=ON so
    # deleting a playlist cascades to its items (fixes a latent bug where
    # orphaned items lingered).
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA busy_timeout=5000;")
    conn.execute("PRAGMA foreign_keys=ON;")
    conn.executescript(_SCHEMA)
    migrate(conn)
    conn.commit()
    return conn


def migrate(conn):
    """Add any missing columns to DBs created by older versions."""
    cols = {row["name"] for row in conn.execute("PRAGMA table_info(items)")}
    if "image_url" not in cols:
        conn.execute("ALTER TABLE items ADD COLUMN image_url TEXT")


# ---------- Playlists ----------

def create_playlist(conn, chat_id, name, comment=None):
    now = _now()
    cur = conn.execute(
        "INSERT INTO playlists (chat_id, name, comment, created_at) "
        "VALUES (?, ?, ?, ?)",
        (chat_id, name, comment, now))
    conn.commit()
    return cur.lastrowid


def list_playlists(conn, chat_id):
    rows = conn.execute(
        "SELECT * FROM playlists WHERE chat_id = ? ORDER BY created_at",
        (chat_id,)).fetchall()
    return [dict(r) for r in rows]


def get_playlist(conn, chat_id, name):
    row = conn.execute(
        "SELECT * FROM playlists WHERE chat_id = ? AND name = ?",
        (chat_id, name)).fetchone()
    return dict(row) if row else None


def get_playlist_by_id(conn, chat_id, pid):
    row = conn.execute(
        "SELECT * FROM playlists WHERE chat_id = ? AND id = ?",
        (chat_id, pid)).fetchone()
    return dict(row) if row else None


def delete_playlist(conn, chat_id, name):
    cur = conn.execute(
        "DELETE FROM playlists WHERE chat_id = ? AND name = ?",
        (chat_id, name))
    conn.commit()
    return cur.rowcount > 0


# ---------- Items ----------
# Sort rule: pinned first, then oldest-first by added_at.

def add_item(conn, chat_id, playlist_id, url, title=None, description=None,
             image_url=None):
    now = _now()
    cur = conn.execute(
        "INSERT INTO items (chat_id, playlist_id, url, title, description, "
        "image_url, added_at, status, pinned) VALUES (?, ?, ?, ?, ?, ?, ?, "
        "'unread', 0)",
        (chat_id, playlist_id, url, title, description, image_url, now))
    conn.commit()
    return cur.lastrowid


def list_items(conn, playlist_id):
    rows = conn.execute(
        "SELECT * FROM items WHERE playlist_id = ? "
        "ORDER BY pinned DESC, added_at ASC",
        (playlist_id,)).fetchall()
    return [dict(r) for r in rows]


# "done" items are archived: they no longer count toward a playlist's size and
# are hidden from the normal listing. They surface in the archive view instead.

def list_active_items(conn, playlist_id):
    """Items of a playlist that are NOT archived (status != 'done')."""
    rows = conn.execute(
        "SELECT * FROM items WHERE playlist_id = ? AND status != 'done' "
        "ORDER BY pinned DESC, added_at ASC",
        (playlist_id,)).fetchall()
    return [dict(r) for r in rows]


def count_active_items(conn, playlist_id):
    """Number of non-archived items in a playlist (shown on the UI)."""
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM items WHERE playlist_id = ? AND status != 'done'",
        (playlist_id,)).fetchone()
    return row["n"]


def list_archived_items(conn, chat_id):
    """All archived (status='done') items of a user, newest first.

    Joins the playlist so the archive view can show where each link came from.
    """
    rows = conn.execute(
        "SELECT i.*, p.name AS playlist_name FROM items i "
        "JOIN playlists p ON p.id = i.playlist_id "
        "WHERE i.chat_id = ? AND i.status = 'done' "
        "ORDER BY i.pinned DESC, i.added_at DESC",
        (chat_id,)).fetchall()
    return [dict(r) for r in rows]


def get_item(conn, chat_id, item_id):
    row = conn.execute(
        "SELECT * FROM items WHERE chat_id = ? AND id = ?",
        (chat_id, item_id)).fetchone()
    return dict(row) if row else None


def update_item_status(conn, item_id, status):
    if status not in STATUSES:
        raise ValueError(f"invalid status: {status}")
    conn.execute("UPDATE items SET status = ? WHERE id = ?",
                 (status, item_id))
    conn.commit()


def toggle_pin(conn, item_id):
    conn.execute(
        "UPDATE items SET pinned = 1 - pinned WHERE id = ?", (item_id,))
    conn.commit()


def delete_item(conn, chat_id, item_id):
    cur = conn.execute(
        "DELETE FROM items WHERE chat_id = ? AND id = ?",
        (chat_id, item_id))
    conn.commit()
    return cur.rowcount > 0


# ---------- Comments ----------

def add_comment(conn, entity_type, entity_id, text):
    cur = conn.execute(
        "INSERT INTO comments (entity_type, entity_id, text, created_at) "
        "VALUES (?, ?, ?, ?)",
        (entity_type, entity_id, text, _now()))
    conn.commit()
    return cur.lastrowid


def list_comments(conn, entity_type, entity_id):
    rows = conn.execute(
        "SELECT * FROM comments WHERE entity_type = ? AND entity_id = ? "
        "ORDER BY created_at",
        (entity_type, entity_id)).fetchall()
    return [dict(r) for r in rows]


# ---------- Web login codes ----------
# One-time 5-digit codes issued by the bot (/web command). A fresh code for a
# user invalidates their previous one; consuming a code deletes its row so it
# cannot be reused.

def create_login_code(conn, user_id, ttl_minutes=10):
    """Mint a new one-time 5-digit code for `user_id` (old codes revoked)."""
    code = str(random.randrange(100000)).zfill(5)
    conn.execute("DELETE FROM web_codes WHERE user_id = ?", (str(user_id),))
    conn.execute(
        "INSERT INTO web_codes (user_id, code, expires_at, created_at) "
        "VALUES (?, ?, ?, ?)",
        (str(user_id), code, time.time() + ttl_minutes * 60, _now()))
    conn.commit()
    return code


def consume_login_code(conn, code):
    """Validate + single-use consume a code. Returns the user_id or None."""
    row = conn.execute(
        "SELECT * FROM web_codes WHERE code = ? AND expires_at > ?",
        (code, time.time())).fetchone()
    if not row:
        return None
    conn.execute("DELETE FROM web_codes WHERE code = ?", (code,))
    conn.commit()
    return row["user_id"]
