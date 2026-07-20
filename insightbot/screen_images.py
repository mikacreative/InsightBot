"""Server-side news image fetching and caching for the TV screen.

Selected brief items may carry an ``image_url`` from their RSS entry; items
without one fall back to an ``og:image`` lookup on the article page. All
images are downloaded server-side — WeChat's image CDN (mmbiz.qpic.cn)
rejects hotlinking without an mp.weixin.qq.com referer — into
``<screen_output_dir>/img/news/`` and referenced relatively, which also
keeps the kiosk page working when the TV loses network. Cache files no
longer referenced by the latest run are removed on each refresh.

Every function here is best-effort: any network or parsing failure degrades
to "no image" instead of raising, so the task run is never affected.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import struct
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests

logger = logging.getLogger(__name__)

DOWNLOAD_TIMEOUT_S = 8
PAGE_FETCH_TIMEOUT_S = 6
MAX_IMAGE_BYTES = 8 * 1024 * 1024
MIN_IMAGE_BYTES = 8 * 1024  # skip tracking pixels and tiny icons
MIN_IMAGE_WIDTH = 400
MIN_IMAGE_HEIGHT = 240
MAX_WORKERS = 4
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)

_OG_IMAGE_RE = re.compile(
    r"""<meta[^>]+(?:property|name)=["']og:image["'][^>]+content=["']([^"']+)["']""",
    re.IGNORECASE,
)
_OG_IMAGE_RE_ALT = re.compile(
    r"""<meta[^>]+content=["']([^"']+)["'][^>]+(?:property|name)=["']og:image["']""",
    re.IGNORECASE,
)


def _image_dimensions(data: bytes) -> tuple[int, int] | None:
    """Parse (width, height) from PNG/JPEG/GIF headers, stdlib only."""
    if len(data) >= 24 and data[:8] == b"\x89PNG\r\n\x1a\n":
        width, height = struct.unpack(">II", data[16:24])
        return int(width), int(height)
    if len(data) >= 10 and data[:6] in (b"GIF87a", b"GIF89a"):
        width, height = struct.unpack("<HH", data[6:10])
        return int(width), int(height)
    if len(data) >= 4 and data[:2] == b"\xff\xd8":
        idx = 2
        while idx + 9 < len(data):
            if data[idx] != 0xFF:
                idx += 1
                continue
            marker = data[idx + 1]
            if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                height, width = struct.unpack(">HH", data[idx + 5 : idx + 9])
                return int(width), int(height)
            if marker in (0xD8, 0xD9) or 0xD0 <= marker <= 0xD7:
                idx += 2
                continue
            seg_len = struct.unpack(">H", data[idx + 2 : idx + 4])[0]
            if seg_len < 2:
                return None
            idx += 2 + seg_len
    return None


def _suffix_for(content_type: str, url: str) -> str:
    mapping = {"image/jpeg": ".jpg", "image/jpg": ".jpg", "image/png": ".png", "image/gif": ".gif", "image/webp": ".webp"}
    if content_type in mapping:
        return mapping[content_type]
    match = re.search(r"\.(jpe?g|png|gif|webp)(?:[?#]|$)", url, re.IGNORECASE)
    return "." + match.group(1).lower().replace("jpeg", "jpg") if match else ".jpg"


def _referer_for(url: str) -> str:
    # WeChat image CDN serves images only to requests with an mp referer.
    if "qpic.cn" in url:
        return "https://mp.weixin.qq.com/"
    return ""


def fetch_og_image_url(page_url: str) -> str:
    """Best-effort og:image lookup on an article page; "" on any failure."""
    try:
        resp = requests.get(page_url, headers={"User-Agent": USER_AGENT}, timeout=PAGE_FETCH_TIMEOUT_S)
    except Exception as exc:
        logger.info("screen_images: og:image fetch failed for %s: %s", page_url, exc)
        return ""
    if resp.status_code != 200:
        return ""
    text = resp.text[:200_000]  # og tags live in <head>
    match = _OG_IMAGE_RE.search(text) or _OG_IMAGE_RE_ALT.search(text)
    if not match:
        return ""
    url = match.group(1).strip()
    return url if url.startswith(("http://", "https://")) else ""


def fetch_og_image_urls(page_urls: list[str]) -> dict[str, str]:
    """Parallel og:image lookup for a batch of pages; {page_url: image_url}."""
    unique = [u for u in dict.fromkeys(page_urls) if u]
    if not unique:
        return {}
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        results = list(pool.map(fetch_og_image_url, unique))
    return {url: img for url, img in zip(unique, results) if img}


def download_image(url: str, cache_dir: Path) -> str | None:
    """Download one image into cache_dir; return the file name or None.

    Rejects non-image content, oversized/tiny payloads and (when dimensions
    are parseable) icon-sized images.
    """
    headers = {"User-Agent": USER_AGENT}
    referer = _referer_for(url)
    if referer:
        headers["Referer"] = referer
    try:
        with requests.get(url, headers=headers, timeout=DOWNLOAD_TIMEOUT_S, stream=True) as resp:
            if resp.status_code != 200:
                logger.info("screen_images: HTTP %s for %s", resp.status_code, url)
                return None
            content_type = str(resp.headers.get("Content-Type", "")).split(";")[0].strip().lower()
            chunks: list[bytes] = []
            size = 0
            for chunk in resp.iter_content(chunk_size=65536):
                chunks.append(chunk)
                size += len(chunk)
                if size > MAX_IMAGE_BYTES:
                    logger.info("screen_images: image too large, aborted: %s", url)
                    return None
            data = b"".join(chunks)
    except Exception as exc:
        logger.info("screen_images: download failed for %s: %s", url, exc)
        return None
    if content_type and not content_type.startswith("image/"):
        logger.info("screen_images: non-image content-type %s for %s", content_type, url)
        return None
    if len(data) < MIN_IMAGE_BYTES:
        logger.info("screen_images: payload too small (%d bytes): %s", len(data), url)
        return None
    dims = _image_dimensions(data)
    if dims is not None and (dims[0] < MIN_IMAGE_WIDTH or dims[1] < MIN_IMAGE_HEIGHT):
        logger.info("screen_images: image too small %sx%s: %s", dims[0], dims[1], url)
        return None
    name = hashlib.sha1(url.encode("utf-8")).hexdigest()[:16] + _suffix_for(content_type, url)
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
        path = cache_dir / name
        if not path.exists() or path.stat().st_size != len(data):
            path.write_bytes(data)
            os.chmod(path, 0o644)  # served by nginx as a different user
    except OSError as exc:
        logger.warning("screen_images: failed to write cache file for %s: %s", url, exc)
        return None
    return name


def cache_news_images(image_urls: list[str], cache_dir: Path) -> dict[str, str]:
    """Download image urls in parallel; return {url: file_name}.

    Files left over from previous runs and no longer referenced are removed
    so the cache stays bounded by the current brief (<= max items per run).
    """
    unique = [u for u in dict.fromkeys(image_urls) if u]
    cached: dict[str, str] = {}
    if unique:
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
            names = list(pool.map(lambda u: download_image(u, cache_dir), unique))
        cached = {url: name for url, name in zip(unique, names) if name}
    keep = set(cached.values())
    try:
        if cache_dir.exists():
            for old in cache_dir.iterdir():
                if old.is_file() and old.name not in keep:
                    old.unlink(missing_ok=True)
    except OSError as exc:
        logger.info("screen_images: cache cleanup failed: %s", exc)
    return cached
