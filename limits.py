"""SQLite-backed sliding-window rate limiter.

Usage events are persisted in a `rate_events` table so daily/hourly caps survive
a bot restart. The admin (checked by the caller) is exempt and never reaches this
module.
"""
import time

RATE_SCHEMA = """
CREATE TABLE IF NOT EXISTS rate_events (
    id INTEGER PRIMARY KEY,
    user_id TEXT NOT NULL,
    bucket TEXT NOT NULL,
    ts REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_rate_user ON rate_events(user_id, bucket, ts);
"""

_SECONDS = {
    "minute": 60,
    "hour": 3600,
    "day": 86400,
    "week": 604800,
}


def check(conn, user_id, bucket, max_allowed, per="day"):
    """Record one usage of `bucket` for `user_id` if under the cap.

    Returns (ok, reason): ok is True when the action is allowed and recorded;
    otherwise reason is a user-facing string. max_allowed of None/0 means
    unlimited.
    """
    user_id = str(user_id)
    max_allowed = int(max_allowed)
    if max_allowed <= 0:
        return True, None

    window = _SECONDS.get(per, 86400)
    now = time.time()

    # Drop events older than the window (keeps the table bounded per user/bucket).
    conn.execute(
        "DELETE FROM rate_events WHERE user_id = ? AND bucket = ? AND ts < ?",
        (user_id, bucket, now - window))

    count = conn.execute(
        "SELECT COUNT(*) FROM rate_events WHERE user_id = ? AND bucket = ?",
        (user_id, bucket)).fetchone()[0]

    if count >= max_allowed:
        return False, (max_allowed, per)

    conn.execute(
        "INSERT INTO rate_events (user_id, bucket, ts) VALUES (?, ?, ?)",
        (user_id, bucket, now))
    conn.commit()
    return True, None


def reset(conn, user_id=None, bucket=None):
    """Clear rate events (used by tests/admin tooling)."""
    sql = "DELETE FROM rate_events"
    args = []
    if user_id is not None or bucket is not None:
        conds, args = [], []
        if user_id is not None:
            conds.append("user_id = ?")
            args.append(str(user_id))
        if bucket is not None:
            conds.append("bucket = ?")
            args.append(bucket)
        sql += " WHERE " + " AND ".join(conds)
    conn.execute(sql, args)
    conn.commit()
