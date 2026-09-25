"""Shared HTTP layer: one requests implementation, one politeness policy per host.

Every upstream fetch in this repository goes through here — the endoflife.date
API, the eosl.date family pages, Opengear's lifecycle tables and configurator,
and the one-off source pages a researched contribution cites. Consolidating
them keeps the things that must never drift apart in one place:

* **Identification.** One User-Agent string naming this project and where it
  lives. An anonymous crawler is not a polite one.
* **Egress policy.** Only public HTTPS destinations are fetched, redirects are
  followed one hop at a time with every hop re-checked, and a hop/byte/deadline
  budget bounds the whole exchange. A *cited* URL is untrusted input: an
  operator checking a contribution, or a compromised upstream, must not be able
  to point this repository at a loopback admin socket or a cloud metadata
  endpoint. Deterministic collectors fetch fixed, registry-declared hosts, so
  they opt out of the per-hop checks with ``trusted=True`` and keep them
  everywhere else.
* **Bounded transfers.** Responses are streamed and materialized under a
  decompressed-byte ceiling, so an oversized or adversarial body fails cleanly
  instead of exhausting memory; the per-attempt duration and the total request
  budget are both capped.
* **Transient retry.** A GET is idempotent: a connection reset, a timeout or a
  5xx is retried after a pause, then the last failure is raised unchanged so the
  caller can report it. Non-transient failures (4xx, a refusal, a parse error)
  are not retried — retrying a 404, or an address the policy just refused, only
  wastes the upstream's time.

Politeness varies by host because the hosts differ. endoflife.date serves a
documented JSON API and tolerates a small pool of parallel fetches with no
pause; eosl.date and opengear.com are small server-rendered sites that publish
no rate limit, so they are crawled by two workers with a pause before each
request and a longer retry delay. :func:`profile` is the single source of those
numbers, so a caller never restates them; the byte, redirect, duration and
budget ceilings live there too, and a host that is not registered gets the
documented :data:`DEFAULT` policy rather than an unbounded one.
"""
from __future__ import annotations

import ipaddress
import socket
import time
from dataclasses import dataclass, replace
from urllib.parse import urljoin, urlsplit

import requests

try:  # pragma: no cover - the URL rule is a sibling module in every real run
    from .urls import redact_url as _redact_url
    from .urls import safe_http_url as _safe_http_url

    URL_POLICY = True
except ImportError:  # pragma: no cover - keeps this module a usable leaf
    URL_POLICY = False

    def _redact_url(value):
        return "<url>"

    def _safe_http_url(value, field="url", allow_fragment=True):
        parsed = urlsplit(value)
        if parsed.scheme.lower() not in ("http", "https") or not parsed.netloc:
            raise ValueError(f"{field} must be an absolute http(s) URL")
        if parsed.username is not None or parsed.password is not None:
            raise ValueError(f"{field} must not carry credentials")
        return value


USER_AGENT = "eoltracker/1.0 (+https://github.com/zarguell/eoltracker)"

# --- Bounds -----------------------------------------------------------------
# Every number below is a ceiling on one exchange, not a target: it exists so a
# stalled, oversized or redirect-looping upstream fails cleanly instead of
# consuming a runner. Registered hosts may tighten them; nothing may remove one.
MAX_RESPONSE_BYTES = 32 * 1024 * 1024
MAX_REDIRECTS = 5
MAX_REQUEST_SECONDS = 300.0
MAX_REQUESTS = 12
CHUNK_BYTES = 64 * 1024


@dataclass(frozen=True)
class Profile:
    """How one host is fetched: bounds, retries and crawl pace.

    ``timeout`` is the requests connect/read pair; ``deadline`` caps the whole
    exchange in wall-clock seconds, retries included. ``max_bytes`` bounds one
    response's *decompressed* size, and ``max_redirects``/``max_requests`` bound
    the redirect hops and every request one ``get`` makes, so neither a redirect
    chain nor a retry can multiply the budget. ``trusted`` is reserved for a
    registry-declared host whose URLs are built in code rather than read from
    upstream: it skips the per-request address check, never the scheme,
    redirect, byte, deadline or budget rules.
    """

    timeout: tuple[float, float]
    attempts: int = 2
    retry_delay: float = 5.0
    pause: float = 0.0
    workers: int = 1
    max_bytes: int = MAX_RESPONSE_BYTES
    max_redirects: int = MAX_REDIRECTS
    deadline: float = MAX_REQUEST_SECONDS
    max_requests: int = MAX_REQUESTS
    trusted: bool = False


# Per-host policy, keyed by the exact hostname the URL resolves to.
HOSTS = {
    # A JSON API that serves the whole catalog: eight parallel detail fetches,
    # no artificial pause, and no retry — a full crawl is cheap to repeat, and
    # retrying every one of 450 fetches against a failing API helps nobody.
    "endoflife.date": Profile(timeout=(15, 90), attempts=1, workers=8, trusted=True),
    # Server-rendered sites crawled as HTML: two workers, half a second between
    # requests and one retry after a pause.
    "eosl.date": Profile(timeout=(15, 60), pause=0.5, workers=2, trusted=True),
    "opengear.com": Profile(timeout=(15, 60), pause=0.5, workers=2, trusted=True),
}
# Any other host — a researched contribution's cited page, for instance — is
# read serially with the generous catalog timeout and one retry, and every one
# of its destinations is checked.
DEFAULT = Profile(timeout=(15, 90))
# Server-side statuses that say "try again": a rate limit or an outage, as
# opposed to a 4xx, which says the request itself is wrong.
TRANSIENT_STATUS = frozenset({429})
REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})


class UnsafeDestination(ValueError):
    """A destination this layer refuses to contact.

    Deliberately *not* a :class:`requests.RequestException`: a refusal is a
    policy statement about the URL, not a transport failure, so retrying it is
    pointless, ``transient()`` says so, and a caller that already treats a bad
    contribution as a ``ValueError`` (``engine.contribute``) reports it as one.
    """


class ResponseTooLarge(ValueError):
    """A response body exceeded its decompressed-byte ceiling."""


class RequestBudgetExceeded(ValueError):
    """One ``get`` spent its redirect-hop or request budget."""


def profile(url):
    """The politeness policy for ``url``'s host."""
    try:
        return HOSTS.get(urlsplit(url).hostname or "", DEFAULT)
    except ValueError:
        return DEFAULT


def workers(url):
    """The parallel fetch pool size this host tolerates."""
    return profile(url).workers


def transient(error):
    """Whether a failure is worth retrying: the request may succeed unchanged.

    A dropped connection, a timeout, a rate limit or a 5xx is transient. A 4xx
    is not: the request is wrong, and retrying it wastes the upstream's time
    while hiding the real problem from the caller. A refusal
    (:class:`UnsafeDestination`) or an exceeded budget is not transient either —
    the same URL fails the same way every time.
    """
    if isinstance(error, (UnsafeDestination, ResponseTooLarge, RequestBudgetExceeded)):
        return False
    if isinstance(error, (requests.ConnectionError, requests.Timeout)):
        return True
    response = getattr(error, "response", None)
    if isinstance(error, requests.HTTPError) and response is not None:
        return response.status_code in TRANSIENT_STATUS or response.status_code >= 500
    return False


def _is_public(address):
    """True only for an address a public web fetch may reach.

    ``is_global`` is the admission test, so loopback, private, link-local,
    carrier-grade NAT, unspecified, multicast, reserved and the RFC 5737/3849
    documentation ranges are all refused. An IPv4-mapped IPv6 address is judged
    as the IPv4 address it actually reaches, and an IPv6 6to4 address is judged
    by its embedded IPv4 address, so neither spelling can smuggle a private
    destination past the check.
    """
    mapped = getattr(address, "ipv4_mapped", None)
    if mapped is not None:
        return mapped.is_global
    if address.version == 6:
        # 2002::/16 carries its IPv4 destination in bits 16-47.
        packed = address.packed
        if packed[:2] == b"\x20\x02":
            return ipaddress.ip_address(packed[2:6]).is_global
    return address.is_global


def _destination(url, trusted):
    """Refuse ``url`` unless it is a public HTTPS destination.

    The string rule (:func:`engine.urls.safe_http_url`) owns everything about
    the URL itself — scheme, authority, credentials, control characters — and
    this adds the two things only a network layer can decide: HTTPS-only, and
    that the host does not resolve to a private address. A *name* is resolved
    here so a citation cannot point at a name whose records are internal, and an
    address literal is judged directly.
    """
    try:
        _safe_http_url(url, "destination", allow_fragment=True)
    except ValueError as error:
        raise UnsafeDestination(str(error)) from None
    parsed = urlsplit(url)
    if parsed.scheme.lower() != "https":
        raise UnsafeDestination(
            f"destination must use HTTPS: {_redact_url(url)!r}")
    if trusted:
        return url
    hostname = parsed.hostname.rstrip(".").lower()
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        try:
            resolved = socket.getaddrinfo(hostname, parsed.port or None, type=socket.SOCK_STREAM)
        except socket.gaierror as error:
            # The resolver failed, not the address. Reported as the transport's
            # own connection failure so a transient DNS blip is retried exactly
            # as requests would have retried it.
            raise requests.ConnectionError(f"cannot resolve {hostname!r}: {error}") from error
        for entry in resolved:
            try:
                address = ipaddress.ip_address(entry[4][0])
            except ValueError:
                raise UnsafeDestination(
                    f"destination {hostname!r} resolved to an unusable address") from None
            if not _is_public(address):
                raise UnsafeDestination(
                    f"destination {hostname!r} resolves to the non-public address {address}")
    else:
        if not _is_public(address):
            raise UnsafeDestination(
                f"destination {hostname!r} is the non-public address {address}")
    return url


def safe_url(url):
    """The URL when a *reader* may follow it, else ``None``.

    The presentation form of the destination rule: it never raises, so a
    renderer or feed can drop a link that would become a live private-address
    request instead of failing the whole build over one bad upstream value.
    Nothing here is fetched, and no name is resolved — a stored link is judged
    on its own text.
    """
    try:
        _safe_http_url(url, "url", allow_fragment=True)
    except (ValueError, TypeError):
        return None
    try:
        if urlsplit(url).scheme.lower() != "https":
            return None
    except ValueError:
        return None
    return url


def _materialize(response, limit):
    """Read a streamed response body fully, under ``limit`` decompressed bytes.

    ``requests`` applies content decoding — so a gzipped body is measured after
    decompression, which is the size that actually lands in memory — and
    ``iter_content`` never raises ``ContentTooMuchError`` on its own, so the
    accumulation here is what enforces the ceiling. A double that is not a real
    :class:`requests.Response` (a test double, or a caller's prepared response)
    is returned untouched: it has no stream to bound.
    """
    if not isinstance(response, requests.Response):
        return response
    chunks = []
    total = 0
    try:
        for chunk in response.iter_content(chunk_size=CHUNK_BYTES):
            if not chunk:
                continue
            total += len(chunk)
            if total > limit:
                raise ResponseTooLarge(
                    f"response exceeded the {limit}-byte decompressed limit for {response.url}")
            chunks.append(chunk)
        response._content = b"".join(chunks)
        response._content_consumed = True
    finally:
        # The body is fully in memory (or refused): release the socket either way.
        if getattr(response, "raw", None) is not None:
            response.close()
    return response


def _fetch(url, policy, spent):
    """Follow one URL to its final response, checking every hop.

    Redirects are followed manually — never by ``requests`` — so each hop's
    destination is validated before the next request exists, and the hop count,
    the request count and the wall-clock deadline all bind across the chain
    rather than per request.
    """
    current = url
    hops = 0
    while True:
        if spent["requests"] >= policy.max_requests:
            raise RequestBudgetExceeded(
                f"request budget of {policy.max_requests} exhausted for {_redact_url(url)!r}")
        if time.monotonic() > spent["deadline"]:
            raise requests.Timeout(
                f"request deadline of {policy.deadline}s exhausted for {_redact_url(url)!r}")

        current = _destination(current, policy.trusted)
        spent["requests"] += 1
        response = requests.get(current, timeout=policy.timeout,
                                headers={"User-Agent": USER_AGENT},
                                allow_redirects=False, stream=True)
        try:
            status = getattr(response, "status_code", None)
            if status in REDIRECT_STATUSES:
                if hops >= policy.max_redirects:
                    raise RequestBudgetExceeded(
                        f"more than {policy.max_redirects} redirects for {_redact_url(url)!r}")
                hops += 1
                location = response.headers.get("Location")
                response.close()
                if not location:
                    raise UnsafeDestination(
                        f"redirect from {_redact_url(current)!r} has no Location header")
                current = urljoin(current, location)
                continue
            response.raise_for_status()
            return _materialize(response, min(policy.max_bytes, MAX_RESPONSE_BYTES))
        except BaseException:
            response.close()
            raise


def get(url, trusted=False):
    """GET ``url`` under its host policy, retrying a transient failure.

    Destinations, and every redirect hop, are checked before the request they
    belong to; the body is bounded in decompressed bytes; the attempts, redirect
    hops, requests and wall clock are all capped. ``trusted=True`` is for a
    deterministic collector whose URLs are built from the registry rather than
    read from upstream, and it relaxes one thing only: the per-request address
    check. The scheme, redirect, byte, deadline and budget rules still bind.

    A transient failure is retried up to the host's attempt count after its
    retry delay; the last failure is then raised unchanged, and a non-transient
    failure (a 4xx, a refusal, a parse-level error) is raised at once. Requests
    exceptions and the two policy errors above propagate as themselves, so a
    caller can distinguish a network failure from a refusal or a parse error.
    """
    policy = profile(url)
    if trusted:
        policy = replace(policy, trusted=True)
    # One budget for the whole call, retries included: an attempt does not reset
    # the request, redirect or wall-clock allowance it already spent.
    spent = {"requests": 0, "deadline": time.monotonic() + policy.deadline}
    for attempt in range(policy.attempts):
        try:
            return _fetch(url, policy, spent)
        except requests.RequestException as error:
            if not transient(error) or attempt + 1 >= policy.attempts:
                raise
            time.sleep(policy.retry_delay)


def get_text(url, encoding=None):
    """GET ``url`` as text; HTML sources declare UTF-8 explicitly."""
    response = get(url)
    if encoding is not None:
        response.encoding = encoding
    return response.text


def get_json(url):
    """GET ``url`` and decode its JSON body."""
    return get(url).json()
