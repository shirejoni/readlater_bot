"""Fetch a link's title and description for saving as a read-later item.

Preference order:
  title:       og:title  ->  <title>
  description: og:description -> <meta name=description>

Never raises on a broken/unreachable link: callers always get a usable
(title=url, description=None) fallback.
"""
import re

import requests
from bs4 import BeautifulSoup

import config

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36")
TIMEOUT = 15


def _proxies():
    """Build the requests proxies dict from config.PROXY (None if disabled)."""
    if not config.PROXY:
        return None
    return {"http": config.PROXY, "https": config.PROXY}


def _meta_content(soup, *selectors):
    for selector in selectors:
        tag = soup.find("meta", attrs=selector)
        if tag and tag.get("content"):
            return tag["content"].strip()
    return None


def fetch_metadata(url):
    """Return (title, description). Falls back gracefully on any error."""
    try:
        resp = requests.get(url, timeout=TIMEOUT, headers={"User-Agent": UA},
                            proxies=_proxies())
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
    except requests.RequestException:
        return url, None
    except Exception:
        return url, None

    title = _meta_content(soup, {"property": "og:title"},
                                 {"name": "og:title"})
    if not title:
        t = soup.find("title")
        title = t.get_text(strip=True) if t else None
    if not title:
        title = url

    description = _meta_content(soup, {"property": "og:description"},
                                        {"name": "og:description"},
                                        {"name": "description"})
    if description:
        description = re.sub(r"\s+", " ", description).strip()[:400]

    return title, description
