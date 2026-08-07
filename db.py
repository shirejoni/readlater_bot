"""SQLite persistence layer for the read-later bot.

Everything is scoped per chat_id so the bot can be used independently in
multiple chats without data leaking between them.
"""
import sqlite3
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
"""


def _now():
    return datetime.now(timezone.utc).isoformat()


def connect(path=DB_PATH):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    conn.commit()
    return conn


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

def add_item(conn, chat_id, playlist_id, url, title=None, description=None):
    now = _now()
    cur = conn.execute(
        "INSERT INTO items (chat_id, playlist_id, url, title, description, "
        "added_at, status, pinned) VALUES (?, ?, ?, ?, ?, ?, 'unread', 0)",
        (chat_id, playlist_id, url, title, description, now))
    conn.commit()
    return cur.lastrowid


def list_items(conn, playlist_id):
    rows = conn.execute(
        "SELECT * FROM items WHERE playlist_id = ? "
        "ORDER BY pinned DESC, added_at ASC",
        (playlist_id,)).fetchall()
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
