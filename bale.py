"""Thin Bale Bot API client.

Bale (https://docs.bale.ai/) exposes a Telegram-compatible HTTP API at
    https://tapi.bale.ai/bot<TOKEN>/METHOD_NAME

Method names are case-insensitive, responses are JSON with an `ok` boolean.
We use long polling via getUpdates (no webhook / public server needed).
"""
import os
import time

import requests

BASE = "https://tapi.bale.ai/bot{token}/{method}"


class BaleError(Exception):
    """Raised when the Bale API returns ok=false."""


def get_token():
    token = os.environ.get("BALE_TOKEN")
    if not token:
        raise SystemExit("BALE_TOKEN environment variable is not set.")
    return token


def call(method, token=None, **params):
    """POST a JSON request to a Bale API method and return its `result`."""
    token = token or get_token()
    url = BASE.format(token=token, method=method)
    resp = requests.post(url, json=params, timeout=30)
    data = resp.json()
    if not data.get("ok"):
        raise BaleError(
            f"{method} failed: {data.get('error_code')} {data.get('description')}"
        )
    return data.get("result")


def get_me(token=None):
    return call("getMe", token=token)


def get_updates(offset=None, timeout=50, token=None):
    params = {"timeout": timeout}
    if offset is not None:
        params["offset"] = offset
    return call("getUpdates", token=token, **params)


def send_message(chat_id, text, reply_markup=None, parse_mode="Markdown",
                 token=None):
    params = {"chat_id": chat_id, "text": text, "parse_mode": parse_mode}
    if reply_markup is not None:
        params["reply_markup"] = reply_markup
    return call("sendMessage", token=token, **params)


def edit_message_text(chat_id, message_id, text, reply_markup=None,
                      parse_mode="Markdown", token=None):
    params = {"chat_id": chat_id, "message_id": message_id, "text": text,
              "parse_mode": parse_mode}
    if reply_markup is not None:
        params["reply_markup"] = reply_markup
    try:
        return call("editMessageText", token=token, **params)
    except BaleError:
        # Message content unchanged is fine; ignore.
        return None


def edit_message_reply_markup(chat_id, message_id, reply_markup, token=None):
    params = {"chat_id": chat_id, "message_id": message_id,
              "reply_markup": reply_markup}
    try:
        return call("editMessageReplyMarkup", token=token, **params)
    except BaleError:
        return None


def answer_callback_query(callback_query_id, text=None, token=None):
    params = {"callback_query_id": callback_query_id}
    if text:
        params["text"] = text
    return call("answerCallbackQuery", token=token, **params)
