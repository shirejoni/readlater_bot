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
3. Run it:
   ```bash
   BALE_TOKEN=<your-token> python3 bot.py
   ```
   - Optional: set `BALE_OWNER_ID=<numeric id>` to only let a single user use it.
   - Data is stored in a local `readlater.db` (SQLite) file next to the bot.

## Commands

| Command | Action |
|---|---|
| */start*, */help* | Show help |
| Send any link (or */add <url>*) | Scrape + save into the active playlist |
| */new <name>* | Create (and open) a playlist |
| */playlists* | List all playlists (tap one to open) |
| */open <name>* | Make a playlist active and list its links |
| */list* | List links in the active playlist |
| */delpl <name>* | Delete a playlist |
| */plc <name> <text>* | Comment on a playlist |
| */pc <item_id> <text>* | Comment on an item |
| */comments* | Comment help |

## Sorting & status

- Default order is **oldest-first** by date added.
- **Pinned** (📌) links sort to the top.
- Each link has a three-state status: ⬜ Unread → 🔁 In Progress → ✅ Done.
- Buttons on each card: Pin/Unpin, set status, Comment, Remove, Open the link.

## Files

- `bot.py` — polling loop, command & button routing
- `bale.py` — thin Bale HTTP API client
- `db.py` — SQLite schema + queries
- `scraper.py` — link title/description extraction
