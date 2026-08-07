"""Periodic DB backup: zip the SQLite database and send it to a chat.

The scheduler thread lives in bot.py; this module just builds the zip and
delivers it via the Bale API.
"""
import io
import time
import zipfile
from datetime import datetime

import bale
import config
import db


def _zip_bytes(db_path=db.DB_PATH):
    """Return (filename, bytes) of a timestamped zip containing the DB file."""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    name = f"readlater_backup_{ts}.zip"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.write(db_path, arcname="readlater.db")
    return name, buf.getvalue()


def send_backup(chat_id, db_path=db.DB_PATH):
    """Zip the DB and send it to chat_id. Raises on API failure."""
    name, data = _zip_bytes(db_path)
    return bale.send_document(chat_id, data, filename=name,
                              caption=f"بکاپ پایگاه‌داده — {datetime.now().strftime('%Y-%m-%d %H:%M')}")


def start_backup_scheduler():
    """Start a daemon thread that sends a DB backup every interval_hours."""
    bcfg = config.BACKUP
    if not bcfg.get("enabled"):
        print("Backups disabled (backup.enabled: false).")
        return
    chat_id = config.backup_chat_id()
    if not chat_id:
        print("Backup enabled but no target chat (set ADMIN_USER_ID or "
              "backup.chat_id in config.yaml). Skipping.")
        return
    interval = int(bcfg.get("interval_hours") or 24) * 3600

    def loop():
        while True:
            time.sleep(interval)
            try:
                send_backup(chat_id)
                print(f"DB backup sent to {chat_id}.")
            except Exception as e:
                print(f"DB backup failed: {e}")

    import threading
    threading.Thread(target=loop, daemon=True).start()
    print(f"Backup scheduler started: every {interval // 3600}h to {chat_id}.")
