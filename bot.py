"""ربات «بعداً بخوانم» برای پیام‌رسان بله — نقطه ورود اصلی.

از getUpdates بله با long polling استفاده می‌کند، دستورها و دکمه‌های کلیکی را
مسیردهی می‌کند و همه‌چیز را در SQLite ذخیره می‌کند (ببینید db.py).

اجرا:
    python3 bot.py   (token را در فایل .env بگذارید: BALE_TOKEN=...)
هر کاربر داده‌ی جدا و محدودیت نرخ خودش را دارد (config.yaml). مدیر
(ADMIN_USER_ID در فایل .env) از همه محدودیت‌ها معاف است.
"""
import re
import time

import bale
import backup
import config
import db
import limits

URL_RE = re.compile(r"https?://[^\s]+")

# حالت حافظه هر کاربر (دائمی نیست): پلی‌لیست فعال و چیزی که منتظر آن هستیم (مثلاً متن نظر).
ACTIVE = {}        # user_id -> playlist_id
PENDING = {}       # user_id -> (kind, item_id)  مثل ('comment', 5) یا ('newpl', url)
PENDING_LINKS = {} # user_id -> {token: url}  لینک‌های منتظر انتخاب پلی‌لیست (چندتایی)
_TOKEN_SEQ = 0     # شمارنده برای ساخت token های لینک‌های منتظر

HELP = (
    "*ربات «بعداً بخوانم»* 📚\n\n"
    "*ذخیره لینک* — هر پیامی که URL داشته باشد بفرستید (یا */add <url>*) تا "
    "عنوان و توضیح آن را استخراج کنم؛ بعد پلی‌لیست مقصد را از فهرست انتخاب "
    "می‌کنید (یا پلی‌لیست جدید می‌سازید).\n\n"
    "*پلی‌لیست‌ها*\n"
    "/new <نام> — ساخت پلی‌لیست\n"
    "/playlists — فهرست پلی‌لیست‌ها\n"
    "/open <نام> — فعال کردن و نمایش لینک‌های یک پلی‌لیست\n"
    "/list — نمایش لینک‌های پلی‌لیست فعال\n"
    "/delpl <نام> — حذف پلی‌لیست\n\n"
    "*نظرها*\n"
    "/plc <نام> <متن> — نظر روی پلی‌لیست\n"
    "/pc <شناسه> <متن> — نظر روی یک لینک\n\n"
    "*ورود به سایت*\n"
    "/web — دریافت کد ورود ۵ رقمی وب‌اپلیکیشن\n\n"
    "هر لینک دکمه دارد: پین، وضعیت (خوانده شد / در حال خواندن / خوانده نشده)، "
    "نظر، حذف و باز کردن.\n"
    "مرتب‌سازی: قدیمی‌تر اول؛ لینک‌های پین‌شده بالاترند."
)


def md(text):
    """escape کردن چند کاراکتر خاص markdown پیش از قرار گرفتن در متن."""
    return text.replace("\\", "").replace("*", "\\*").replace("_", "\\_") \
               .replace("[", "\\[").replace("]", "\\]")


# ---------- رندر ----------

def status_label(status):
    return {"unread": "⬜ خوانده نشده", "in_progress": "🔁 در حال خواندن",
            "done": "✅ خوانده شد"}.get(status, status)


def item_markup(item):
    """دکمه‌های هر لینک — حداکثر دو ستون در هر ردیف."""
    pin = "📌 برداشتن پین" if item["pinned"] else "📌 پین"
    return {
        "inline_keyboard": [
            [{"text": pin, "callback_data": f"pin:{item['id']}"},
             {"text": "✅ خوانده شد",
              "callback_data": f"st:{item['id']}:done"}],
            [{"text": "🔁 در حال خواندن",
              "callback_data": f"st:{item['id']}:in_progress"},
             {"text": "⬜ خوانده نشده",
              "callback_data": f"st:{item['id']}:unread"}],
            [{"text": "💬 نظر", "callback_data": f"comment:{item['id']}"},
             {"text": "🗑 حذف", "callback_data": f"remove:{item['id']}"}],
            [{"text": "🔗 باز کردن", "url": item["url"]}],
        ]
    }


def item_text(item, index=None):
    idx = f"[{index}] " if index else ""
    lines = [f"*{md(item['title'] or item['url'])}*"]
    if item["description"]:
        lines.append(md(item["description"]))
    lines.append(md(item["url"]))
    lines.append(f"#{item['id']} · {status_label(item['status'])}"
                 f"{' · 📌 پین‌شده' if item['pinned'] else ''}"
                 f" · اضافه: {item['added_at'][:10]} · {idx.strip()}")
    return "\n".join(lines)


def render_item(chat_id, item, index=None):
    """Send an item: with its image (photo + caption + buttons) if available."""
    text = item_text(item, index)
    if item.get("image_url"):
        bale.send_photo(chat_id, item["image_url"], caption=text,
                        reply_markup=item_markup(item))
    else:
        bale.send_message(chat_id, text, reply_markup=item_markup(item))


def render_edit(chat_id, message_id, item):
    """Re-render an already-sent item after a callback (handles photo msgs)."""
    text = item_text(item)
    if item.get("image_url"):
        bale.edit_message_caption(chat_id, message_id, text,
                                  reply_markup=item_markup(item))
    else:
        bale.edit_message_text(chat_id, message_id, text,
                               reply_markup=item_markup(item))


def playlist_listing(conn, user_id):
    pls = db.list_playlists(conn, user_id)
    if not pls:
        return "هنوز پلی‌لیستی ندارید. با */new <نام>* بسازید.", None
    rows = []
    for pl in pls:
        n = len(db.list_items(conn, pl["id"]))
        active = " 👈" if ACTIVE.get(user_id) == pl["id"] else ""
        rows.append([{"text": f"{pl['name']} ({n}){active}",
                      "callback_data": f"openpl:{pl['id']}"}])
    return "*پلی‌لیست‌های شما:*", {"inline_keyboard": rows}


def list_playlist_items(conn, chat_id, pl):
    items = db.list_items(conn, pl["id"])
    header = f"*{md(pl['name'])}* — {len(items)} پیوند"
    if pl.get("comment"):
        header += f"\n📝 {md(pl['comment'])}"
    bale.send_message(chat_id, header)
    if not items:
        bale.send_message(chat_id, "خالی است. برای افزودن یک لینک بفرستید.")
        return
    for i, item in enumerate(items, 1):
        render_item(chat_id, item, i)


# ---------- مدیریت پیام و رویدادها ----------

def handle_message(conn, msg):
    chat_id = msg["chat"]["id"]            # جایی که پاسخ می‌دهیم
    text = msg.get("text") or ""
    from_id = (msg.get("from") or {}).get("id")
    user_id = str(from_id) if from_id is not None else str(chat_id)

    # گرفتن متن نظرِ منتظر، اولویت بالاتر از همه دارد.
    if user_id in PENDING:
        kind, item_id = PENDING.pop(user_id)
        body = text.strip()
        if not body:
            bale.send_message(chat_id, "نظر خالی نادیده گرفته شد.")
            return
        if kind == "newpl":
            if not _limited(conn, chat_id, user_id, "playlist_create"):
                return
            try:
                pid = db.create_playlist(conn, user_id, body)
            except Exception:
                bale.send_message(chat_id, "پلی‌لیستی با این نام وجود دارد.")
                return
            ACTIVE[user_id] = pid
            pl = db.get_playlist_by_id(conn, user_id, pid)
            bale.send_message(chat_id, f"پلی‌لیست */{md(body)}* ساخته شد.")
            save_to_playlist(conn, chat_id, user_id, item_id, pl)
            return
        if kind == "comment":
            db.add_comment(conn, "item", item_id, body)
        elif kind == "plc":
            db.add_comment(conn, "playlist", item_id, body)
        pid = ACTIVE.get(user_id)
        if pid and kind == "comment":
            pl = db.get_playlist_by_id(conn, user_id, pid)
            list_playlist_items(conn, chat_id, pl)
        else:
            bale.send_message(chat_id, "نظر ذخیره شد ✅")
        return

    # دستورها.
    if text.startswith("/"):
        handle_command(conn, chat_id, user_id, text)
        return

    # در غیر این صورت هر پیام حاوی URL ذخیره می‌شود.
    urls = URL_RE.findall(text)
    if not urls:
        bale.send_message(chat_id, "یک لینک (*https://...*) بفرستید تا ذخیره کنم، "
                                   "یا /help برای راهنما.")
        return
    offer_save(conn, chat_id, user_id, urls)


def _limited(conn, chat_id, user_id, bucket):
    """اعمال محدودیت نرخ برای یک کاربر. True اگر انجام کار مجاز است."""
    if config.is_admin(user_id):
        return True
    spec = config.LIMITS.get(bucket)
    if not spec:
        return True
    ok, reason = limits.check(conn, user_id, bucket,
                              spec.get("max", 0), spec.get("per", "day"))
    if ok:
        return True
    n, unit = reason
    bale.send_message(
        chat_id,
        f"به حد مجاز رسیدید: حداکثر {n} بار در هر {unit} برای این کار. "
        "کمی بعد دوباره تلاش کنید.")
    return False


def handle_command(conn, chat_id, user_id, text):
    cmd, _, rest = text.partition(" ")
    cmd = cmd.lower()
    rest = rest.strip()

    # هر دستوری به‌صورت جداگانه محدود می‌شود (مدیر معاف است).
    if not _limited(conn, chat_id, user_id, "commands"):
        return

    if cmd == "/start":
        bale.send_message(chat_id, HELP)
    elif cmd == "/help":
        bale.send_message(chat_id, HELP)
    elif cmd == "/new":
        if not rest:
            bale.send_message(chat_id, "کاربرد: */new <نام>*")
            return
        if not _limited(conn, chat_id, user_id, "playlist_create"):
            return
        try:
            db.create_playlist(conn, user_id, rest)
        except Exception:
            bale.send_message(chat_id, "پلی‌لیستی با این نام وجود دارد.")
            return
        ACTIVE[user_id] = db.get_playlist(conn, user_id, rest)["id"]
        bale.send_message(chat_id, f"پلی‌لیست */{md(rest)}* ساخته و باز شد.")
    elif cmd == "/playlists":
        header, markup = playlist_listing(conn, user_id)
        bale.send_message(chat_id, header, reply_markup=markup)
    elif cmd == "/open":
        open_playlist(conn, chat_id, user_id, rest)
    elif cmd == "/list":
        pl = current_playlist(conn, chat_id, user_id)
        if pl:
            list_playlist_items(conn, chat_id, pl)
    elif cmd in ("/add", "/save"):
        if not rest:
            bale.send_message(chat_id, "کاربرد: */add <url>*")
            return
        urls = URL_RE.findall(rest)
        if not urls:
            bale.send_message(chat_id, "در این پیام لینکی پیدا نکردم.")
            return
        offer_save(conn, chat_id, user_id, urls)
    elif cmd == "/delpl":
        if not rest:
            bale.send_message(chat_id, "کاربرد: */delpl <نام>*")
            return
        ok = db.delete_playlist(conn, user_id, rest)
        if ok and ACTIVE.get(user_id) is not None:
            ACTIVE.pop(user_id, None)
        bale.send_message(chat_id, "حذف شد ✅" if ok else "پلی‌لیست پیدا نشد.")
    elif cmd == "/plc":
        name, _, body = rest.partition(" ")
        if not name or not body:
            bale.send_message(chat_id, "کاربرد: */plc <نام> <متن>*")
            return
        pl = db.get_playlist(conn, user_id, name)
        if not pl:
            bale.send_message(chat_id, "پلی‌لیست پیدا نشد.")
            return
        db.add_comment(conn, "playlist", pl["id"], body)
        bale.send_message(chat_id, "نظر ذخیره شد ✅")
    elif cmd == "/pc":
        iid, _, body = rest.partition(" ")
        if not iid or not body:
            bale.send_message(chat_id, "کاربرد: */pc <شناسه> <متن>*")
            return
        if not db.get_item(conn, user_id, int(iid)):
            bale.send_message(chat_id, "لینک پیدا نشد.")
            return
        db.add_comment(conn, "item", int(iid), body)
        bale.send_message(chat_id, "نظر ذخیره شد ✅")
    elif cmd == "/comments":
        show_comments_help(chat_id)
    elif cmd == "/web":
        code = db.create_login_code(conn, user_id)
        url = config.web_base_url() + config.web_url_prefix() + "/login"
        bale.send_message(
            chat_id,
            f"کد ورود شما: *`{code}`*\n\n"
            f"در این صفحه وارد کنید: {url}\n"
            "کد تا ۱۰ دقیقه معتبر است و فقط یک بار مصرف میشود.")
    else:
        bale.send_message(chat_id, "دستور ناشناخته است. /help را ببینید.")


def current_playlist(conn, chat_id, user_id):
    pid = ACTIVE.get(user_id)
    if pid is None:
        bale.send_message(chat_id, "پلی‌لیست فعالی ندارید. از */open <نام>* یا "
                                   "*/new <نام>* استفاده کنید.")
        return None
    pl = db.get_playlist_by_id(conn, user_id, pid)
    if not pl:
        ACTIVE.pop(user_id, None)
        bale.send_message(chat_id, "پلی‌لیست فعال دیگر وجود ندارد.")
        return None
    return pl


def open_playlist(conn, chat_id, user_id, name):
    if not name:
        bale.send_message(chat_id, "کاربرد: */open <نام>*")
        return
    pl = db.get_playlist(conn, user_id, name)
    if not pl:
        bale.send_message(chat_id, "پلی‌لیست پیدا نشد. */playlists* را ببینید.")
        return
    ACTIVE[user_id] = pl["id"]
    list_playlist_items(conn, chat_id, pl)


def _new_token():
    global _TOKEN_SEQ
    _TOKEN_SEQ += 1
    return str(_TOKEN_SEQ)


def _pick_keyboard(conn, user_id, pls, token):
    """کیبورد انتخاب پلی‌لیست برای یک لینک؛ ژم داده‌ها token لینک + شناسه پلی‌لیست است."""
    rows = []
    for pl in pls:
        n = len(db.list_items(conn, pl["id"]))
        rows.append([{"text": f"{pl['name']} ({n})",
                      "callback_data": f"pickpl:{token}:{pl['id']}"}])
    rows.append([{"text": "➕ پلی‌لیست جدید", "callback_data": f"newpl:{token}"},
                 {"text": "❌ انصراف", "callback_data": f"cancel:{token}"}])
    return {"inline_keyboard": rows}


def offer_save(conn, chat_id, user_id, urls):
    """برای هر لینک، پیامی جدا با فهرست پلی‌لیست‌ها می‌فرستد.

    چند لینک می‌توانند هم‌زمان در انتظار باشند و هرکدام جداگانه به پلی‌لیست
    دلخواهش برود. token هر لینک داخل callback_data می‌رود تا همان لینک را
    پیدا کنیم (URLها برای callback_data زیادی بلندند).
    اگر پلی‌لیستی وجود نداشته باشد مستقیم در «پیش‌فرض» ذخیره می‌کند.
    """
    pls = db.list_playlists(conn, user_id)
    pend = PENDING_LINKS.setdefault(user_id, {})
    for url in urls:
        if not pls:
            save_to_playlist(conn, chat_id, user_id, url, None)
            continue
        token = _new_token()
        pend[token] = url
        short = url if len(url) <= 60 else url[:60] + "…"
        bale.send_message(chat_id, "کدام پلی‌لیست؟\n" + short,
                          reply_markup=_pick_keyboard(conn, user_id, pls, token))
    if not pend:
        PENDING_LINKS.pop(user_id, None)


def save_to_playlist(conn, chat_id, user_id, url, pl):
    """افزودن لینک به پلی‌لیست: محدودیت نرخ، دریافت اطلاعات، ذخیره و نمایش.

    اگر pl None باشد (مثلاً هیچ پلی‌لیستی نداریم) در پلی‌لیست فعال یا در
    «پیش‌فرض» ذخیره می‌کند (رفتار قبلی).
    """
    if pl is None:
        pl = current_playlist(conn, chat_id, user_id)
        if pl is None:  # پلی‌لیست فعال نبود -> پلی‌لیست «پیش‌فرض» بساز
            if not _limited(conn, chat_id, user_id, "playlist_create"):
                bale.send_message(chat_id, "برای ذخیره یک پلی‌لیست محلی باز کنید "
                                           "(حد مجاز ساختن پلی‌لیست رسیده است).")
                return
            pid = db.create_playlist(conn, user_id, "default")
            ACTIVE[user_id] = pid
            pl = db.get_playlist_by_id(conn, user_id, pid)

    # محدودیت افزودن لینک (مدیر معاف است).
    if not _limited(conn, chat_id, user_id, "item_create"):
        return

    bale.send_message(chat_id, "در حال دریافت اطلاعات…")
    title, description, image_url = scraper_fetch(url)
    item_id = db.add_item(conn, user_id, pl["id"], url,
                          title=title, description=description,
                          image_url=image_url)
    item = db.get_item(conn, user_id, item_id)
    bale.send_message(chat_id, f"در *{md(pl['name'])}* ذخیره شد ✅")
    render_item(chat_id, item)


def scraper_fetch(url):
    from scraper import fetch_metadata  # import محلی تا شروع سریع باشد
    return fetch_metadata(url)


def show_comments_help(chat_id):
    bale.send_message(
        chat_id,
        "نظرها:\n/pc <شناسه> <متن> — نظر روی یک لینک\n"
        "/plc <پلی‌لیست> <متن> — نظر روی پلی‌لیست\n"
        "یا از دکمه 💬 روی هر لینک استفاده کنید.")


def handle_callback(cb):
    chat_id = cb["message"]["chat"]["id"]
    message_id = cb["message"]["message_id"]
    from_id = (cb.get("from") or {}).get("id")
    user_id = str(from_id) if from_id is not None else str(chat_id)
    data = cb["data"]
    parts = data.split(":")

    if len(parts) < 2:
        return
    action = parts[0]

    if action == "openpl":
        pid = int(parts[1])
        ACTIVE[user_id] = pid
        pl = db.get_playlist_by_id(conn, user_id, pid)
        if pl:
            list_playlist_items(conn, chat_id, pl)
        bale.answer_callback_query(cb["id"])
        return

    if action in ("pickpl", "newpl", "cancel"):
        pend = PENDING_LINKS.get(user_id, {})
        if len(parts) < 2 or parts[1] not in pend:
            bale.answer_callback_query(cb["id"], "این لینک دیگر در انتظار نیست.")
            return
        url = pend.pop(parts[1])
        if not pend:
            PENDING_LINKS.pop(user_id, None)
        if action == "pickpl":
            if len(parts) < 3:
                return
            pl = db.get_playlist_by_id(conn, user_id, int(parts[2]))
            if not pl:
                bale.answer_callback_query(cb["id"], "پلی‌لیست پیدا نشد.")
                return
            bale.answer_callback_query(cb["id"], "ذخیره می‌شود…")
            bale.edit_message_text(chat_id, message_id, "در حال ذخیره…")
            save_to_playlist(conn, chat_id, user_id, url, pl)
            return
        if action == "newpl":
            PENDING[user_id] = ("newpl", url)
            empty = {"inline_keyboard": []}
            bale.edit_message_reply_markup(chat_id, message_id, empty)
            bale.send_message(chat_id, "نام پلی‌لیست جدید را بنویسید:")
            bale.answer_callback_query(cb["id"])
            return
        # cancel — فقط همین لینک لغو می‌شود.
        empty = {"inline_keyboard": []}
        bale.edit_message_reply_markup(chat_id, message_id, empty)
        bale.send_message(chat_id, "ذخیره این لینک لغو شد ❌")
        bale.answer_callback_query(cb["id"], "لغو شد.")
        return

    try:
        item_id = int(parts[1])
    except ValueError:
        bale.answer_callback_query(cb["id"], "لینک نامعتبر.")
        return

    item = db.get_item(conn, user_id, item_id)
    if not item:
        bale.answer_callback_query(cb["id"], "لینک دیگر وجود ندارد.")
        return

    if action == "pin":
        db.toggle_pin(conn, item_id)
    elif action == "st" and len(parts) == 3:
        db.update_item_status(conn, item_id, parts[2])
    elif action == "remove":
        db.delete_item(conn, user_id, item_id)
        empty = {"inline_keyboard": []}
        if item.get("image_url"):
            bale.edit_message_caption(chat_id, message_id, "*حذف شد* 🗑",
                                      reply_markup=empty)
        else:
            bale.edit_message_text(chat_id, message_id, "*حذف شد* 🗑",
                                   reply_markup=empty)
        bale.answer_callback_query(cb["id"], "حذف شد.")
        return
    elif action == "comment":
        PENDING[user_id] = ("comment", item_id)
        bale.send_message(chat_id,
                          f"متن نظر برای #{item_id} (عنوان: "
                          f"*{md(item['title'] or item['url'])}*) را بفرستید:")
        bale.answer_callback_query(cb["id"], "نظرتان را بنویسید.")
        return

    # بازنشانی کارت با وضعیت جدید.
    item = db.get_item(conn, user_id, item_id)
    render_edit(chat_id, message_id, item)
    bale.answer_callback_query(cb["id"])


def handle_update(upd):
    if "callback_query" in upd:
        handle_callback(upd["callback_query"])
    elif "message" in upd:
        msg = upd["message"]
        if msg.get("text") is None:
            return
        handle_message(conn, msg)


def main():
    global conn
    conn = db.connect()
    backup.start_backup_scheduler()
    print("ربات آنلاین:", bale.get_me().get("username", "?"))
    offset = None
    while True:
        try:
            updates = bale.get_updates(offset=offset) or []
        except Exception as e:
            print(f"خطای دریافت: {e}")
            time.sleep(3)
            continue
        for upd in updates:
            offset = upd["update_id"] + 1
            try:
                handle_update(upd)
            except Exception as e:
                print(f"خطای پردازش: {e}")


if __name__ == "__main__":
    main()
