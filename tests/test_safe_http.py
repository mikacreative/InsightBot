from unittest.mock import MagicMock, patch

import pytest

from insightbot.safe_http import UnsafeURL, safe_get, validate_public_http_url


def _addrinfo(ip: str):
    return [(None, None, None, None, (ip, 0))]


class TestSafeHttp:
    def test_rejects_loopback_url(self):
        with patch("insightbot.safe_http.socket.getaddrinfo", return_value=_addrinfo("127.0.0.1")):
            with pytest.raises(UnsafeURL):
                validate_public_http_url("http://localhost:8501")

    def test_rejects_metadata_ip(self):
        with patch("insightbot.safe_http.socket.getaddrinfo", return_value=_addrinfo("169.254.169.254")):
            with pytest.raises(UnsafeURL):
                validate_public_http_url("http://169.254.169.254/latest/meta-data")

    def test_allows_public_http_url(self):
        with patch("insightbot.safe_http.socket.getaddrinfo", return_value=_addrinfo("93.184.216.34")):
            assert validate_public_http_url("https://example.com/feed.xml") == "https://example.com/feed.xml"

    def test_rejects_redirect_to_private_address(self):
        first = MagicMock()
        first.is_redirect = True
        first.is_permanent_redirect = False
        first.headers = {"Location": "http://127.0.0.1/private"}

        with patch(
            "insightbot.safe_http.socket.getaddrinfo",
            side_effect=[_addrinfo("93.184.216.34"), _addrinfo("127.0.0.1")],
        ), patch("insightbot.safe_http.requests.get", return_value=first):
            with pytest.raises(UnsafeURL):
                safe_get("https://example.com/feed.xml")
