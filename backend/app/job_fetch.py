"""Small, bounded public-only HTTP reader. No proxies, cookies, or auth forwarding."""
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from dataclasses import dataclass
import http.client
import ipaddress
import re
import socket
import ssl
import threading
import time
from urllib.parse import urljoin, urlsplit, urlunsplit

MAX_BYTES = 2 * 1024 * 1024
MAX_REDIRECTS = 3
TOTAL_SECONDS = 15
_dns_pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="job-dns")
_dns_slots = threading.BoundedSemaphore(4)


class ImportFailure(ValueError):
    """Safe, user-facing failure without remote bodies or URL query secrets."""


def public_ip(address: str) -> bool:
    ip = ipaddress.ip_address(address)
    if isinstance(ip, ipaddress.IPv6Address):
        # Translation/tunneling ranges can encode otherwise-private IPv4 targets.
        if ip.sixtofour or ip.teredo or ip in ipaddress.ip_network("64:ff9b::/96") or ip in ipaddress.ip_network("64:ff9b:1::/48"):
            return False
        if ip.ipv4_mapped:
            ip = ip.ipv4_mapped
    return ip.is_global and not (ip.is_multicast or ip.is_reserved or ip.is_unspecified)


def parse_destination(url: str):
    try:
        if len(url) > 2048 or re.search(r"[\s\\\x00-\x1f\x7f]", url):
            raise ValueError()
        parts = urlsplit(url)
        if parts.scheme not in ("http", "https") or not parts.hostname:
            raise ValueError()
        if parts.username is not None or parts.password is not None:
            raise ValueError()
        port = parts.port or (443 if parts.scheme == "https" else 80)
        if port != (443 if parts.scheme == "https" else 80):
            raise ValueError()
        host = parts.hostname.encode("idna").decode("ascii").lower().rstrip(".")
        try:
            ip = ipaddress.ip_address(host)
        except ValueError:
            if not re.fullmatch(r"[a-z0-9.-]+", host) or "." not in host or host.endswith((".localhost", ".local", ".internal")):
                raise ValueError()
        else:
            if not public_ip(str(ip)):
                raise ValueError()
        authority = f"[{host}]" if ":" in host else host
        normalized = urlunsplit((parts.scheme, authority, parts.path or "/", parts.query, ""))
        return normalized, host, port
    except (ValueError, UnicodeError):
        raise ImportFailure("Use a public HTTP(S) job URL on the standard port, without credentials.") from None


def remaining(deadline: float) -> float:
    seconds = deadline - time.monotonic()
    if seconds <= 0:
        raise ImportFailure("The job site took too long to respond. You can enter the details manually.")
    return min(seconds, 5.0)


def resolve_public(host: str, port: int, deadline: float) -> str:
    if not _dns_slots.acquire(timeout=remaining(deadline)):
        raise ImportFailure("Destination validation is busy. Please try again.")
    try:
        future = _dns_pool.submit(socket.getaddrinfo, host, port, type=socket.SOCK_STREAM)
    except Exception:
        _dns_slots.release()
        raise ImportFailure("The destination could not be validated.") from None
    future.add_done_callback(lambda _: _dns_slots.release())
    try:
        addresses = future.result(timeout=remaining(deadline))
        ips = {entry[4][0] for entry in addresses}
        if not ips or any(not public_ip(ip) for ip in ips):
            raise ImportFailure("This destination is not a safe public address.")
        return sorted(ips)[0]
    except (OSError, ValueError, FutureTimeout):
        raise ImportFailure("The destination could not be validated.") from None


class PinnedConnection(http.client.HTTPConnection):
    """Resolve once outside this class; connect only to that IP. TLS verifies host."""
    def __init__(self, host, port, ip, secure, deadline):
        super().__init__(host, port, timeout=remaining(deadline))
        self.ip, self.secure, self.deadline = ip, secure, deadline

    def connect(self):
        # Numeric IP passed to connect: no second hostname resolution.
        family = socket.AF_INET6 if ":" in self.ip else socket.AF_INET
        self.sock = socket.socket(family, socket.SOCK_STREAM)
        try:
            self.sock.settimeout(remaining(self.deadline))
            self.sock.connect((self.ip, self.port))
            if self.secure:
                self.sock.settimeout(remaining(self.deadline))
                self.sock = ssl.create_default_context().wrap_socket(self.sock, server_hostname=self.host)
        except BaseException:
            self.close()
            raise


@dataclass
class Page:
    url: str
    body: str
    content_type: str


class PublicFetcher:
    def __init__(self):
        self.deadline = time.monotonic() + TOTAL_SECONDS
        self.redirects = 0

    def get(self, url: str) -> Page:
        try:
            while True:
                url, host, port = parse_destination(url)
                ip = resolve_public(host, port, self.deadline)
                parts = urlsplit(url)
                connection = PinnedConnection(host, port, ip, parts.scheme == "https", self.deadline)
                timer = None
                try:
                    connection.connect()
                    active_socket = connection.sock
                    def abort():
                        try:
                            active_socket.shutdown(socket.SHUT_RDWR)
                        except OSError:
                            pass
                    timer = threading.Timer(max(0, self.deadline - time.monotonic()), abort)
                    timer.daemon = True
                    timer.start()
                    path = (parts.path or "/") + ("?" + parts.query if parts.query else "")
                    connection.request("GET", path, headers={"User-Agent": "ApplyTrack/0.1 (job preview)", "Accept": "text/html, application/json", "Accept-Encoding": "identity"})
                    active_socket.settimeout(remaining(self.deadline))
                    response = connection.getresponse()
                    if response.status in (301, 302, 303, 307, 308):
                        self.redirects += 1
                        location = response.getheader("Location")
                        if not location or self.redirects > MAX_REDIRECTS:
                            raise ImportFailure("The job site redirected too many times.")
                        url = urljoin(url, location)
                        continue
                    if response.status != 200:
                        raise ImportFailure(f"The job site returned HTTP {response.status}. It may restrict access or the posting may have closed.")
                    if response.getheader("Content-Encoding", "identity").lower() != "identity":
                        raise ImportFailure("The job site returned an unsupported compressed response.")
                    content_type = response.getheader("Content-Type", "").split(";")[0].lower().strip()
                    if content_type not in ("text/html", "application/xhtml+xml", "application/json", "application/ld+json"):
                        raise ImportFailure("The URL did not return a supported job page.")
                    size = response.getheader("Content-Length")
                    if size is not None and (not size.isdigit() or int(size) > MAX_BYTES):
                        raise ImportFailure("The job page exceeds the 2 MiB limit.")
                    data = bytearray()
                    while True:
                        active_socket.settimeout(remaining(self.deadline))
                        chunk = response.read1(min(65536, MAX_BYTES + 1 - len(data)))
                        if not chunk:
                            break
                        data.extend(chunk)
                        if len(data) > MAX_BYTES:
                            raise ImportFailure("The job page exceeds the 2 MiB limit.")
                    if size is not None and len(data) != int(size):
                        raise ImportFailure("The job site returned an incomplete page. Please try again or enter details manually.")
                    remaining(self.deadline)
                    return Page(url, data.decode("utf-8", errors="replace"), content_type)
                finally:
                    if timer is not None:
                        timer.cancel()
                    connection.close()
        except (OSError, http.client.HTTPException, UnicodeError, ValueError) as exc:
            if isinstance(exc, ImportFailure):
                raise
            raise ImportFailure("Could not read the public job page. You can enter the details manually.") from None
