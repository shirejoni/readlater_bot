# Bale "Read Later" Bot

A personal **read-later organizer** for [Bale](https://docs.bale.ai/) (a
Telegram-compatible messenger). Paste a link and the bot scrapes its title +
description, saves it to a playlist, and lets you pin / mark-read / comment /
remove it.

## Setup

1. Create a bot in Bale via **[@botfather](https://ble.ir/botfather)** and copy
   the token (looks like `123456789:abcd...`).
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Copy `.env.example` to `.env` and fill in your values (the real `.env` is
   gitignored):
   ```bash
   cp .env.example .env
   ```
   ```bash
   BALE_TOKEN=<your-token>
   ADMIN_USER_ID=            # optional: admin user id, exempt from all limits
   ```
4. Run it:
   ```bash
   python3 bot.py
   ```

- Data is stored in a local `readlater.db` (SQLite) file next to the bot.

## Backup

Every `backup.interval_hours` (default `24`) the bot zips its SQLite DB and sends
it to `backup.chat_id`. If `chat_id` is empty it defaults to `ADMIN_USER_ID`.
Set `backup.enabled: false` in `config.yaml` to disable.

```
backup:
  enabled: true
  interval_hours: 24
  chat_id: ""
```

## Fetching links through a proxy

When the bot scrapes a link's title/description it routes the request through an
HTTP proxy read from `config.yaml` (`proxy:`), default `http://127.0.0.1:2080`.
Set `proxy: ""` in `config.yaml` to disable proxying.

## Multi-user

Anyone who messages the bot gets their **own** playlists and items — nothing is
shared between users. Data is scoped per user id (not per chat), so two users in
the same group chat still keep separate libraries.

## Rate limits

Each user has per-user rate limits, defined in `config.yaml` (committed, edit to
adjust the defaults):

| Bucket | What it covers | Default |
|---|---|---|
| `playlist_create` | creating playlists (`/new`, auto "default") | 20 / day |
| `item_create` | adding saved links | 100 / day |
| `commands` | any bot command | 300 / hour |

`per` units: `minute`, `hour`, `day`, `week`. Limits are recorded in the DB, so a
daily window survives a restart. The **admin** (`ADMIN_USER_ID` in `.env`) is
exempt from all limits.

## Commands

| Command | Action |
|---|---|
| */start*, */help* | Show help |
| Send any link (or */add <url>*) | Pick which playlist to save it into (or create a new one). Multiple links can be queued at once. |
| */new <name>* | Create (and open) a playlist |
| */playlists* | List all playlists (tap one to open) |
| */open <name>* | Make a playlist active and list its links |
| */list* | List links in the active playlist |
| */delpl <name>* | Delete a playlist |
| */plc <name> <text>* | Comment on a playlist |
| */pc <item_id> <text>* | Comment on an item |
| */comments* | Comment help |
| */web* | Get a one-time 5-digit login code for the web dashboard |

## Sorting & status

- Default order is **oldest-first** by date added.
- **Pinned** (📌) links sort to the top.
- Each link has a three-state status: ⬜ Unread → 🔁 In Progress → ✅ Done.
- Buttons on each card: Pin/Unpin, set status, Comment, Remove, Open the link.

## Web dashboard

A Flask web UI (`webapp.py`) that mirrors every bot feature with a modern RTL
dark interface. It shares the bot's SQLite DB and rate limits, so a single
daily cap applies across both bot and web.

**Login (per-user link, no passwords)**

1. Message the bot with `/web` — it replies with a **one-time 5-digit code**
   (valid 10 minutes).
2. Open the web app (default `http://127.0.0.1:8000`) and enter the code.
3. You're signed in with an HttpOnly JWT session cookie, scoped to **your**
   Bale user id — every user sees only their own playlists/links.

Codes are single-use and per-user; the JWT signing secret comes from `WEB_SECRET`
in `.env`, or is auto-generated into `web_secret.key` on first run.

**Run it**

```bash
uv pip install -r requirements.txt
./run_web.sh                # -> http://127.0.0.1:8000
./run_web.sh --port 9000
```

Set `web.base_url` in `config.yaml` to the public address the bot should tell
users to open (it appends `/login`). If you serve over HTTPS, also set
`web.secure_cookie: true`. A systemd unit example lives in
`readlater-web.service` (run alongside `readlater-bot`).

What you can do in the UI: save one or many links at once (scraped
server-side), pick or create the target playlist, pin, set read status
(⬜/🔁/✅), comment on items and playlists, delete, create and delete
playlists.

## Files

- `bot.py` — polling loop, command & button routing, rate-limit enforcement
- `bale.py` — thin Bale HTTP API client
- `db.py` — SQLite schema + queries (incl. `rate_events` and `web_codes`)
- `scraper.py` — link title/description extraction
- `config.py` — loads `.env` (secrets) + `config.yaml` (limits, web)
- `limits.py` — SQLite-backed sliding-window rate limiter
- `webapp.py` — Flask dashboard: code login, JWT cookie, JSON API, dashboard
- `templates/`, `static/` — dashboard UI (RTL Persian dark theme)
- `run.sh` / `run_web.sh` — process launchers; `*.service` — systemd units
