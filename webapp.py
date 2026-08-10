#!/usr/bin/env python3
"""Web dashboard for the Bale "Read Later" bot.

Authenticates via a one-time 5-digit code issued by the bot's /web command. A
successful login issues a JWT stored in an HttpOnly cookie (so browser JS can
never read it), and every request is scoped to the Bale user id inside that
JWT. The dashboard shares the bot's SQLite DB and rate limits, so a combined
daily cap applies across bot and web.

Run:
    .venv/bin/python webapp.py              # -> http://127.0.0.1:8000
    .venv/bin/python webapp.py --port 9000
"""
import argparse
import re
import time
from functools import wraps

import jwt
from flask import Flask, g, jsonify, redirect, render_template, request, url_for

import config
import db
import limits
from scraper import fetch_metadata

app = Flask(__name__)

COOKIE = "readlater_session"
SESSION_TTL = 30 * 86400          # 30-day sliding session
SESSION_REFRESH_AFTER = SESSION_TTL // 2
CODE_TTL_MINUTES = 10

# Prefix under which this app is served (e.g. "/readlater"). Empty = root.
PREFIX = config.web_url_prefix()


class PrefixMiddleware:
    """Strip the URL prefix and set SCRIPT_NAME so Flask's url_for generates
    correct absolute URLs when the app is served behind a path prefix."""

    def __init__(self, wsgi_app, prefix):
        self.wsgi_app = wsgi_app
        self.prefix = prefix

    def __call__(self, environ, start_response):
        if self.prefix:
            path = environ.get("PATH_INFO", "")
            if path == self.prefix:
                path = self.prefix + "/"
            if path.startswith(self.prefix + "/"):
                environ["SCRIPT_NAME"] = environ.get("SCRIPT_NAME", "") + self.prefix
                environ["PATH_INFO"] = path[len(self.prefix):]
        return self.wsgi_app(environ, start_response)


app.wsgi_app = PrefixMiddleware(app.wsgi_app, PREFIX)
app.jinja_env.globals["PREFIX"] = PREFIX

# Brute-force guard for the 5-digit code: 10 tries per IP in a 15-min window.
MAX_ATTEMPTS = 10
ATTEMPT_WINDOW = 15 * 60
_ATTEMPTS = {}                    # ip -> [timestamps]

URL_RE = re.compile(r"https?://[^\s]+")

STATUS_LABELS = {
    "unread": "⬜ خوانده نشده",
    "in_progress": "🔁 در حال خواندن",
    "done": "✅ خوانده شد",
}


def get_conn():
    if "conn" not in g:
        g.conn = db.connect()
    return g.conn


@app.teardown_appcontext
def _close_conn(exc):
    conn = g.pop("conn", None)
    if conn is not None:
        conn.close()


# ---------- JWT auth ----------

def _make_jwt(user_id):
    now = int(time.time())
    return jwt.encode(
        {"sub": user_id, "iat": now, "exp": now + SESSION_TTL},
        config.web_secret(), algorithm="HS256")


def _parse_jwt(token):
    try:
        return jwt.decode(token, config.web_secret(), algorithms=["HS256"])
    except jwt.InvalidTokenError:
        return None


def _set_session_cookie(resp, user_id):
    resp.set_cookie(COOKIE, _make_jwt(user_id), max_age=SESSION_TTL,
                    httponly=True, samesite="Lax",
                    secure=config.web_secure_cookie(), path="/")


@app.before_request
def _load_user():
    g.user_id = None
    g.refresh_session = False
    token = request.cookies.get(COOKIE)
    if not token:
        return
    payload = _parse_jwt(token)
    if not payload:
        return
    g.user_id = payload["sub"]
    # Sliding expiry: re-issue a fresh cookie when over halfway through the
    # session so active users never get logged out.
    now = int(time.time())
    if now - int(payload.get("iat", now)) > SESSION_REFRESH_AFTER:
        g.refresh_session = True


@app.after_request
def _maybe_refresh(resp):
    if g.get("refresh_session") and g.get("user_id"):
        _set_session_cookie(resp, g.user_id)
    return resp


def require_page(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if g.user_id is None:
            return redirect(url_for("login"))
        return fn(*args, **kwargs)
    return wrapper


def require_api(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if g.user_id is None:
            return jsonify({"ok": False, "error": "not authenticated"}), 401
        return fn(*args, **kwargs)
    return wrapper


# ---------- Rate limits (shared with the bot) ----------

def limit_error(conn, bucket):
    """Return a Persian error string if this user is over the limit, else None."""
    if config.is_admin(g.user_id):
        return None
    spec = config.LIMITS.get(bucket)
    if not spec:
        return None
    ok, reason = limits.check(conn, g.user_id, bucket,
                              spec.get("max", 0), spec.get("per", "day"))
    if ok:
        return None
    n, unit = reason
    return f"به حد مجاز رسیدید: حداکثر {n} بار در هر {unit} برای این کار."


# ---------- Auth routes ----------

@app.route("/login", methods=["GET", "POST"])
def login():
    if g.user_id is not None:
        return redirect(url_for("dashboard"))
    error = None
    if request.method == "POST":
        ip = request.remote_addr or "?"
        code = (request.form.get("code") or "").strip()
        if not _attempt_allowed(ip):
            error = "تعداد تلاش‌های ناموفق زیاد شد. کمی بعد دوباره تلاش کنید."
        elif len(code) != 5 or not code.isdigit():
            error = "کد باید ۵ رقم باشد."
        else:
            uid = db.consume_login_code(get_conn(), code)
            if not uid:
                error = "کد اشتباه است، منقضی شده یا قبلاً مصرف شده است."
            else:
                _ATTEMPTS.pop(ip, None)
                resp = redirect(url_for("dashboard"))
                _set_session_cookie(resp, uid)
                return resp
    return render_template("login.html", error=error)


@app.route("/logout", methods=["POST"])
def logout():
    resp = redirect(url_for("login"))
    resp.delete_cookie(COOKIE, path="/")
    return resp


def _attempt_allowed(ip):
    now = time.time()
    hits = [t for t in _ATTEMPTS.get(ip, []) if now - t < ATTEMPT_WINDOW]
    _ATTEMPTS[ip] = hits
    if len(hits) >= MAX_ATTEMPTS:
        return False
    hits.append(now)
    return True


# ---------- Dashboard ----------

@app.route("/")
@require_page
def dashboard():
    conn = get_conn()
    uid = g.user_id
    playlists = db.list_playlists(conn, uid)

    pid = request.args.get("pl", type=int)
    if pid not in [p["id"] for p in playlists]:
        pid = playlists[0]["id"] if playlists else None

    active = next((p for p in playlists if p["id"] == pid), None)

    counts = {p["id"]: len(db.list_items(conn, p["id"])) for p in playlists}
    items, comments, ccounts = [], {}, {}
    if active:
        items = db.list_items(conn, active["id"])
        comments = {it["id"]: db.list_comments(conn, "item", it["id"])
                    for it in items}
        ccounts = {it["id"]: len(comments[it["id"]]) for it in items}

    return render_template(
        "dashboard.html",
        playlists=playlists, active=active, active_pid=pid,
        items=items, counts=counts, comments=comments, ccounts=ccounts,
        status_labels=STATUS_LABELS,
        limit_playlist=config.LIMITS.get("playlist_create"),
        limit_item=config.LIMITS.get("item_create"))


# ---------- Playlist API ----------

@app.route("/api/playlists", methods=["POST"])
@require_api
def api_create_playlist():
    name = (request.get_json(silent=True) or {}).get("name") or ""
    name = name.strip()
    if not name:
        return jsonify({"ok": False, "error": "نام پلی‌لیست را وارد کنید."}), 400
    err = limit_error(get_conn(), "playlist_create")
    if err:
        return jsonify({"ok": False, "error": err}), 429
    try:
        db.create_playlist(get_conn(), g.user_id, name)
    except Exception:
        return jsonify({"ok": False, "error": "پلی‌لیستی با این نام وجود دارد."}), 400
    return jsonify({"ok": True})


@app.route("/api/playlists/<int:pid>/delete", methods=["POST"])
@require_api
def api_delete_playlist(pid):
    pl = db.get_playlist_by_id(get_conn(), g.user_id, pid)
    if not pl:
        return jsonify({"ok": False, "error": "پلی‌لیست پیدا نشد."}), 404
    db.delete_playlist(get_conn(), g.user_id, pl["name"])
    return jsonify({"ok": True})


@app.route("/api/playlists/<int:pid>/comment", methods=["POST"])
@require_api
def api_playlist_comment(pid):
    text = (request.get_json(silent=True) or {}).get("text") or ""
    text = text.strip()
    if not text:
        return jsonify({"ok": False, "error": "متن نظر خالی است."}), 400
    if not db.get_playlist_by_id(get_conn(), g.user_id, pid):
        return jsonify({"ok": False, "error": "پلی‌لیست پیدا نشد."}), 404
    db.add_comment(get_conn(), "playlist", pid, text)
    return jsonify({"ok": True})


# ---------- Item API ----------

@app.route("/api/items", methods=["POST"])
@require_api
def api_add_items():
    conn = get_conn()
    uid = g.user_id
    body = request.get_json(silent=True) or {}
    raw = body.get("urls") or ""
    pid = body.get("playlist_id")

    urls = list(dict.fromkeys(URL_RE.findall(raw)))
    if not urls:
        return jsonify({"ok": False, "error": "لینکی پیدا نشد."}), 400

    if pid is not None:
        pl = db.get_playlist_by_id(conn, uid, pid)
        if not pl:
            return jsonify({"ok": False, "error": "پلی‌لیست پیدا نشد."}), 404
    else:
        if db.list_playlists(conn, uid):
            return jsonify({"ok": False, "error": "پلی‌لیست مقصد را انتخاب کنید."}), 400
        err = limit_error(conn, "playlist_create")
        if err:
            return jsonify({"ok": False, "error": err}), 429
        try:
            new_pid = db.create_playlist(conn, uid, "default")
        except Exception:
            return jsonify({"ok": False, "error": "ساخت پلی‌لیست «default» ناموفق بود."}), 400
        pl = db.get_playlist_by_id(conn, uid, new_pid)

    added, warn = 0, None
    for url in urls:
        err = limit_error(conn, "item_create")
        if err:
            warn = err
            break
        title, description, image_url = fetch_metadata(url)
        db.add_item(conn, uid, pl["id"], url, title=title,
                    description=description, image_url=image_url)
        added += 1

    out = {"ok": True, "added": added}
    if warn:
        out["warn"] = warn
    return jsonify(out)


@app.route("/api/items/<int:iid>/status", methods=["POST"])
@require_api
def api_item_status(iid):
    status = (request.get_json(silent=True) or {}).get("status")
    if status not in db.STATUSES:
        return jsonify({"ok": False, "error": "وضعیت نامعتبر است."}), 400
    if not db.get_item(get_conn(), g.user_id, iid):
        return jsonify({"ok": False, "error": "لینک پیدا نشد."}), 404
    db.update_item_status(get_conn(), iid, status)
    return jsonify({"ok": True, "status": status})


@app.route("/api/items/<int:iid>/pin", methods=["POST"])
@require_api
def api_item_pin(iid):
    item = db.get_item(get_conn(), g.user_id, iid)
    if not item:
        return jsonify({"ok": False, "error": "لینک پیدا نشد."}), 404
    db.toggle_pin(get_conn(), iid)
    return jsonify({"ok": True, "pinned": not item["pinned"]})


@app.route("/api/items/<int:iid>/comment", methods=["POST"])
@require_api
def api_item_comment(iid):
    text = (request.get_json(silent=True) or {}).get("text") or ""
    text = text.strip()
    if not text:
        return jsonify({"ok": False, "error": "متن نظر خالی است."}), 400
    if not db.get_item(get_conn(), g.user_id, iid):
        return jsonify({"ok": False, "error": "لینک پیدا نشد."}), 404
    db.add_comment(get_conn(), "item", iid, text)
    return jsonify({"ok": True})


@app.route("/api/items/<int:iid>/delete", methods=["POST"])
@require_api
def api_item_delete(iid):
    if not db.delete_item(get_conn(), g.user_id, iid):
        return jsonify({"ok": False, "error": "لینک پیدا نشد."}), 404
    return jsonify({"ok": True})


# ---------- Run ----------

def main():
    p = argparse.ArgumentParser(description="Bale read-later web dashboard")
    p.add_argument("--host", default="127.0.0.1", help="Bind host (default 127.0.0.1).")
    p.add_argument("--port", type=int, default=8000, help="Bind port (default 8000).")
    p.add_argument("--debug", action="store_true", help="Enable Flask debug mode.")
    args = p.parse_args()
    print(f"Read-later dashboard -> http://{args.host}:{args.port}")
    print("Users log in with the 5-digit code the bot sends via /web.")
    app.run(host=args.host, port=args.port, debug=args.debug)


if __name__ == "__main__":
    main()