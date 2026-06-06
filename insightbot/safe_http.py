"""Safe HTTP helpers for user-configured fetch targets."""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urljoin, urlparse

import requests


class UnsafeURL(ValueError):
    """Raised when a configured URL points to a disallowed network target."""


def _resolve_host(hostname: str) -> list[ipaddress._BaseAddress]:
    try:
        infos = socket.getaddrinfo(hostname, None)
    except socket.gaierror as exc:
        raise UnsafeURL(f"Cannot resolve host: {hostname}") from exc

    addresses: list[ipaddress._BaseAddress] = []
    for info in infos:
        raw_ip = info[4][0]
        try:
            addresses.append(ipaddress.ip_address(raw_ip))
        except ValueError:
            continue
    return addresses


def _is_disallowed_ip(address: ipaddress._BaseAddress) -> bool:
    return any(
        (
            address.is_private,
            address.is_loopback,
            address.is_link_local,
            address.is_multicast,
            address.is_reserved,
            address.is_unspecified,
        )
    )


def validate_public_http_url(url: str) -> str:
    candidate = str(url or "").strip()
    parsed = urlparse(candidate)
    if parsed.scheme not in {"http", "https"}:
        raise UnsafeURL("Only http/https URLs are allowed.")
    if not parsed.hostname:
        raise UnsafeURL("URL host is required.")

    for address in _resolve_host(parsed.hostname):
        if _is_disallowed_ip(address):
            raise UnsafeURL(f"URL resolves to a disallowed address: {address}")
    return candidate


def safe_get(
    url: str,
    *,
    timeout: int | float = 10,
    headers: dict | None = None,
    max_redirects: int = 3,
    max_bytes: int = 5_000_000,
) -> requests.Response:
    """GET a public URL while blocking private-network targets and redirects."""
    current_url = validate_public_http_url(url)
    response = None
    for _ in range(max_redirects + 1):
        response = requests.get(
            current_url,
            timeout=timeout,
            headers=headers,
            allow_redirects=False,
        )
        if response.is_redirect or response.is_permanent_redirect:
            location = response.headers.get("Location", "")
            if not location:
                break
            current_url = validate_public_http_url(urljoin(current_url, location))
            continue

        content_length = response.headers.get("Content-Length")
        if content_length and int(content_length) > max_bytes:
            raise UnsafeURL(f"Response is too large: {content_length} bytes")
        if len(response.content or b"") > max_bytes:
            raise UnsafeURL(f"Response is too large: {len(response.content)} bytes")
        return response

    raise UnsafeURL("Too many redirects.") if response is not None else UnsafeURL("No response.")
