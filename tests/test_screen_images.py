"""
test_screen_images.py — insightbot.screen_images 新闻图片抓取/缓存测试

测试范围：
  - _image_dimensions: PNG/JPEG/GIF 头部尺寸解析
  - fetch_og_image_url: og:image 两种属性顺序、非 200、异常
  - download_image: 正常下载、非图片类型、过小文件、过小尺寸、防盗链 Referer
  - cache_news_images: 并行缓存 + 过期文件清理
  - editorial_pipeline._extract_entry_image: RSS 图源提取顺序
"""

import struct
import sys
from unittest.mock import MagicMock

sys.modules.setdefault("feedparser", MagicMock())
sys.modules.setdefault("requests", MagicMock())

import insightbot.screen_images as si  # noqa: E402
from insightbot.editorial_pipeline import _extract_entry_image  # noqa: E402


def _png(width: int, height: int, pad: int = 9000) -> bytes:
    header = b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR" + struct.pack(">II", width, height)
    return header + b"\x00" * pad


def _jpeg(width: int, height: int, pad: int = 9000) -> bytes:
    header = b"\xff\xd8\xff\xc0" + struct.pack(">H", 17) + b"\x08" + struct.pack(">HH", height, width)
    return header + b"\x00" * pad


def _gif(width: int, height: int, pad: int = 9000) -> bytes:
    return b"GIF89a" + struct.pack("<HH", width, height) + b"\x00" * pad


class _FakeResp:
    def __init__(self, *, status=200, data=b"", content_type="image/jpeg", text=""):
        self.status_code = status
        self._data = data
        self.headers = {"Content-Type": content_type}
        self.text = text

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def iter_content(self, chunk_size=65536):
        yield self._data


class TestImageDimensions:
    def test_png(self):
        assert si._image_dimensions(_png(800, 600)) == (800, 600)

    def test_jpeg(self):
        assert si._image_dimensions(_jpeg(1024, 768)) == (1024, 768)

    def test_gif(self):
        assert si._image_dimensions(_gif(320, 200)) == (320, 200)

    def test_unknown_returns_none(self):
        assert si._image_dimensions(b"RIFF....WEBPVP8 ") is None
        assert si._image_dimensions(b"") is None


class TestFetchOgImageUrl:
    def test_parses_both_meta_orders(self, monkeypatch):
        html_a = '<html><head><meta property="og:image" content="https://cdn.x.com/a.jpg"></head></html>'
        html_b = '<html><head><meta content="https://cdn.x.com/b.jpg" property="og:image"></head></html>'
        monkeypatch.setattr(si.requests, "get", lambda *a, **k: _FakeResp(text=html_a))
        assert si.fetch_og_image_url("https://x.com/a") == "https://cdn.x.com/a.jpg"
        monkeypatch.setattr(si.requests, "get", lambda *a, **k: _FakeResp(text=html_b))
        assert si.fetch_og_image_url("https://x.com/b") == "https://cdn.x.com/b.jpg"

    def test_non_200_and_exception_return_empty(self, monkeypatch):
        monkeypatch.setattr(si.requests, "get", lambda *a, **k: _FakeResp(status=404))
        assert si.fetch_og_image_url("https://x.com/a") == ""

        def _boom(*a, **k):
            raise RuntimeError("network down")

        monkeypatch.setattr(si.requests, "get", _boom)
        assert si.fetch_og_image_url("https://x.com/a") == ""

    def test_no_og_tag_returns_empty(self, monkeypatch):
        monkeypatch.setattr(si.requests, "get", lambda *a, **k: _FakeResp(text="<html></html>"))
        assert si.fetch_og_image_url("https://x.com/a") == ""


class TestDownloadImage:
    def test_ok_writes_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr(si.requests, "get", lambda *a, **k: _FakeResp(data=_png(800, 600), content_type="image/png"))
        name = si.download_image("https://cdn.x.com/a.png", tmp_path)
        assert name is not None and name.endswith(".png")
        assert (tmp_path / name).exists()

    def test_rejects_non_image_content_type(self, tmp_path, monkeypatch):
        monkeypatch.setattr(si.requests, "get", lambda *a, **k: _FakeResp(data=_png(800, 600), content_type="text/html"))
        assert si.download_image("https://cdn.x.com/a", tmp_path) is None

    def test_rejects_tiny_payload(self, tmp_path, monkeypatch):
        monkeypatch.setattr(si.requests, "get", lambda *a, **k: _FakeResp(data=_png(800, 600, pad=100), content_type="image/png"))
        assert si.download_image("https://cdn.x.com/a.png", tmp_path) is None

    def test_rejects_icon_sized_image(self, tmp_path, monkeypatch):
        monkeypatch.setattr(si.requests, "get", lambda *a, **k: _FakeResp(data=_png(64, 64), content_type="image/png"))
        assert si.download_image("https://cdn.x.com/icon.png", tmp_path) is None

    def test_wechat_referer_header(self, tmp_path, monkeypatch):
        captured = {}

        def _get(url, headers=None, **k):
            captured.update(headers or {})
            return _FakeResp(data=_png(800, 600), content_type="image/jpeg")

        monkeypatch.setattr(si.requests, "get", _get)
        assert si.download_image("https://mmbiz.qpic.cn/mmbiz_jpg/abc/640", tmp_path) is not None
        assert captured.get("Referer") == "https://mp.weixin.qq.com/"

    def test_network_failure_returns_none(self, tmp_path, monkeypatch):
        def _boom(*a, **k):
            raise RuntimeError("timeout")

        monkeypatch.setattr(si.requests, "get", _boom)
        assert si.download_image("https://cdn.x.com/a.jpg", tmp_path) is None


class TestCacheNewsImages:
    def test_caches_and_cleans_stale_files(self, tmp_path, monkeypatch):
        (tmp_path / "stale.jpg").write_bytes(b"old")
        monkeypatch.setattr(si, "download_image", lambda url, cache_dir: "h-" + url.rsplit("/", 1)[-1])
        cached = si.cache_news_images(["https://cdn.x.com/a.jpg", "https://cdn.x.com/b.jpg"], tmp_path)
        assert cached == {"https://cdn.x.com/a.jpg": "h-a.jpg", "https://cdn.x.com/b.jpg": "h-b.jpg"}
        assert not (tmp_path / "stale.jpg").exists()

    def test_empty_input_still_cleans(self, tmp_path):
        (tmp_path / "stale.jpg").write_bytes(b"old")
        assert si.cache_news_images([], tmp_path) == {}
        assert not (tmp_path / "stale.jpg").exists()


class TestExtractEntryImage:
    def test_media_content_first(self):
        entry = MagicMock()
        entry.media_content = [{"url": "https://cdn.x.com/media.jpg", "medium": "image"}]
        entry.media_thumbnail = [{"url": "https://cdn.x.com/thumb.jpg"}]
        entry.enclosures = []
        entry.summary = '<p>text <img src="https://cdn.x.com/inline.jpg"></p>'
        assert _extract_entry_image(entry) == "https://cdn.x.com/media.jpg"

    def test_enclosure_fallback(self):
        entry = MagicMock()
        entry.media_content = []
        entry.media_thumbnail = []
        entry.enclosures = [{"type": "image/jpeg", "href": "https://cdn.x.com/enc.jpg"}]
        entry.summary = ""
        assert _extract_entry_image(entry) == "https://cdn.x.com/enc.jpg"

    def test_summary_img_fallback(self):
        entry = MagicMock()
        entry.media_content = []
        entry.media_thumbnail = []
        entry.enclosures = []
        entry.summary = '<p><img src="https://cdn.x.com/inline.jpg"></p>'
        assert _extract_entry_image(entry) == "https://cdn.x.com/inline.jpg"

    def test_no_image_returns_empty(self):
        entry = MagicMock()
        entry.media_content = []
        entry.media_thumbnail = []
        entry.enclosures = []
        entry.summary = "纯文本摘要"
        assert _extract_entry_image(entry) == ""
