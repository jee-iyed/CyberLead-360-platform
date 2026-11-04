"""SSRF-hardened, polite HTTP retrieval of public web pages.

Safeguards
----------
* http/https only, no credentials in URLs, standard ports only.
* Every hostname is resolved and EVERY resolved address must be public
  (private, loopback, link-local incl. 169.254.169.254 metadata, multicast,
  reserved, unspecified and CGNAT ranges are blocked).
* Redirects are followed manually and each hop is re-validated.
* robots.txt is honoured; a clear User-Agent is sent.
* Per-host rate limit, connect/read timeouts, streamed size cap, HTML only.
* Retrieved content is returned as inert text — scripts are never executed.

Known limitation: DNS could change between validation and connection (DNS
rebinding). Production deployments should additionally enforce egress rules
at the network layer (proxy / firewall). See docs/SECURITY.md.
"""

from __future__ import annotations

import ipaddress
import socket
import time
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser

import httpx

from cyberlead360.domain.exceptions import RetrievalBlockedError

Resolver = Callable[[str], list[str]]
_CGNAT = ipaddress.ip_network("100.64.0.0/10")
_ALLOWED_PORTS = {None, 80, 443}
MAX_REDIRECTS = 3


def default_resolver(host: str) -> list[str]:
    try:
        infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise RetrievalBlockedError(f"Host '{host}' could not be resolved.") from exc
    return sorted({str(info[4][0]) for info in infos})


def is_public_ip(address: str) -> bool:
    ip = ipaddress.ip_address(address)
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    if isinstance(ip, ipaddress.IPv4Address) and ip in _CGNAT:
        return False
    return (
        not (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_unspecified
        )
        and ip.is_global
    )


@dataclass(frozen=True)
class FetchResult:
    url: str
    final_url: str
    status_code: int
    content_type: str
    text: str
    truncated: bool


class SafeFetcher:
    def __init__(
        self,
        user_agent: str,
        timeout_seconds: float = 10.0,
        max_bytes: int = 1_000_000,
        min_interval_seconds: float = 2.0,
        resolver: Resolver = default_resolver,
        transport: httpx.BaseTransport | None = None,
        respect_robots: bool = True,
    ) -> None:
        self.user_agent = user_agent
        self.max_bytes = max_bytes
        self.min_interval = min_interval_seconds
        self.resolver = resolver
        self.respect_robots = respect_robots
        self._last_hit: dict[str, float] = {}
        self._client = httpx.Client(
            timeout=httpx.Timeout(timeout_seconds, connect=min(timeout_seconds, 5.0)),
            follow_redirects=False,
            headers={"User-Agent": user_agent, "Accept": "text/html,application/xhtml+xml"},
            transport=transport,
        )

    # ------------------------------------------------------------------ validation
    def validate_url(self, url: str) -> str:
        parts = urlsplit(url)
        if parts.scheme not in {"http", "https"}:
            raise RetrievalBlockedError("Only http and https URLs are allowed.")
        if parts.username or parts.password:
            raise RetrievalBlockedError("URLs with embedded credentials are not allowed.")
        if parts.port not in _ALLOWED_PORTS:
            raise RetrievalBlockedError("Only standard web ports (80/443) are allowed.")
        host = (parts.hostname or "").lower()
        if not host or host == "localhost" or host.endswith((".localhost", ".local", ".internal")):
            raise RetrievalBlockedError("Local or internal host names are not allowed.")
        try:
            ipaddress.ip_address(host)
            literal = True
        except ValueError:
            literal = False
        addresses = [host] if literal else self.resolver(host)
        if not addresses:
            raise RetrievalBlockedError(f"Host '{host}' has no address.")
        bad = [a for a in addresses if not is_public_ip(a)]
        if bad:
            raise RetrievalBlockedError(
                f"Host '{host}' resolves to a non-public address; retrieval refused."
            )
        return host

    def _throttle(self, host: str) -> None:
        last = self._last_hit.get(host)
        if last is not None:
            wait = self.min_interval - (time.monotonic() - last)
            if wait > 0:
                time.sleep(wait)
        self._last_hit[host] = time.monotonic()

    def _robots_allows(self, url: str) -> bool:
        parts = urlsplit(url)
        robots_url = f"{parts.scheme}://{parts.netloc}/robots.txt"
        try:
            text = self._get_raw(robots_url, max_bytes=200_000, html_only=False).text
        except RetrievalBlockedError:
            return True  # no robots.txt (or unreachable) → no explicit restriction
        parser = RobotFileParser()
        parser.parse(text.splitlines())
        return parser.can_fetch(self.user_agent, url)

    # ------------------------------------------------------------------ fetching
    def _get_raw(self, url: str, *, max_bytes: int, html_only: bool) -> FetchResult:
        current = url
        for _ in range(MAX_REDIRECTS + 1):
            host = self.validate_url(current)
            self._throttle(host)
            try:
                with self._client.stream("GET", current) as response:
                    if response.is_redirect:
                        location = response.headers.get("location")
                        if not location:
                            raise RetrievalBlockedError("Redirect without location.")
                        current = urljoin(current, location)
                        continue  # re-validated at the top of the loop
                    if response.status_code >= 400:
                        raise RetrievalBlockedError(f"HTTP {response.status_code} for {current}")
                    ctype = response.headers.get("content-type", "").split(";")[0].strip()
                    if html_only and ctype not in {"text/html", "application/xhtml+xml"}:
                        raise RetrievalBlockedError(f"Unsupported content type '{ctype}'.")
                    chunks: list[bytes] = []
                    size, truncated = 0, False
                    for chunk in response.iter_bytes():
                        size += len(chunk)
                        if size > max_bytes:
                            chunks.append(chunk[: max_bytes - (size - len(chunk))])
                            truncated = True
                            break
                        chunks.append(chunk)
                    body = b"".join(chunks)
                    encoding = response.encoding or "utf-8"
                    return FetchResult(
                        url=url,
                        final_url=current,
                        status_code=response.status_code,
                        content_type=ctype,
                        text=body.decode(encoding, errors="replace"),
                        truncated=truncated,
                    )
            except httpx.TimeoutException as exc:
                raise RetrievalBlockedError("The request timed out.") from exc
            except httpx.HTTPError as exc:
                raise RetrievalBlockedError(f"Network error: {type(exc).__name__}") from exc
        raise RetrievalBlockedError("Too many redirects.")

    def fetch_html(self, url: str) -> FetchResult:
        self.validate_url(url)
        if self.respect_robots and not self._robots_allows(url):
            raise RetrievalBlockedError("robots.txt disallows retrieving this page.")
        return self._get_raw(url, max_bytes=self.max_bytes, html_only=True)

    def close(self) -> None:
        self._client.close()
