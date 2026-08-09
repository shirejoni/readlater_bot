"""Fetch a link's title, description and image for saving as a read-later item.

Preference order:
  title:       og:title  ->  <title>
  description: og:description -> <meta name=description>
  image_url:   og:image  ->  twitter:image

Never raises on a broken/unreachable link: callers always get a usable
(title=url, description=None, image_url=None) fallback.
"""
import re
from urllib.parse import urljoin

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


def _meta_tags(soup, *selectors):
    tags = []
    for selector in selectors:
        tags.extend(soup.find_all("meta", attrs=selector))
    return tags


def _image_url(soup, base_url):
    """Extract the post image URL from Open Graph / Twitter metadata.

    Prefers the largest og:image (by og:image:width) when several are
    declared; otherwise the first og:image, then twitter:image.
    """
    og_images = [m for m in _meta_tags(
        soup, {"property": "og:image"}, {"name": "og:image"})
        if m.get("content") and not m["content"].startswith("data:")]
    if og_images:
        widths = {}
        for m in _meta_tags(
                soup, {"property": "og:image:width"}, {"name": "og:image:width"}):
            if m.get("content"):
                sizes = re.findall(r"\d+", m["content"])
                widths[m["content"].strip()] = int(sizes[0]) if sizes else 0
        best = None, 0
        for m in og_images:
            w = widths.get(m["content"].strip(), 0)
            if best[0] is None or w > best[1]:
                best = m["content"].strip(), w
        return urljoin(base_url, best[0])

    tw = _meta_content(soup, {"property": "twitter:image"},
                             {"name": "twitter:image"})
    return urljoin(base_url, tw) if tw else None


def fetch_metadata(url):
    """Return (title, description, image_url). Falls back gracefully on any error."""
    try:
        resp = requests.get(url, timeout=TIMEOUT, headers={"User-Agent": UA},
                            proxies=_proxies())
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
    except requests.RequestException:
        return url, None, None
    except Exception:
        return url, None, None

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

    image_url = _image_url(soup, resp.url or url)

    return title, description, image_url
