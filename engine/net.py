"""Shared HTTP layer: one requests implementation, one politeness policy per host.

Every upstream fetch in this repository goes through here — the endoflife.date
API, the eosl.date family pages, Opengear's lifecycle tables and configurator,
and the one-off source pages a researched contribution cites. Consolidating
them keeps the three things that must never drift apart in one place:

* **Identification.** One User-Agent string naming this project and where it
  lives. An anonymous crawler is not a polite one.
* **Bounded requests.** A connect/read timeout pair on every call, so a stalled
  upstream cannot hang a scheduled refresh.
* **Transient retry.** A GET is idempotent: a connection reset, a timeout or a
  5xx is retried after a pause, then the last failure is raised unchanged so the
  caller can report it. Non-transient failures (4xx, a parse error) are not
  retried — retrying a 404 only wastes the upstream's time.

Politeness varies by host because the hosts differ. endoflife.date serves a
documented JSON API and tolerates a small pool of parallel fetches with no
pause; eosl.date and opengear.com are small server-rendered sites that publish
no rate limit, so they are crawled by two workers with a pause before each
request and a longer retry delay. :func:`profile` is the single source of those
numbers, so a caller never restates them.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from urllib.parse import urlparse

import requests

USER_AGENT = "eoltracker/1.0 (+https://github.com/zarguell/eoltracker)"


@dataclass(frozen=True)
class Profile:
    """How one host is fetched: bounds, retries and crawl pace."""

    timeout: tuple[float, float]
    attempts: int = 2
    retry_delay: float = 5.0
    pause: float = 0.0
    workers: int = 1


# Per-host policy, keyed by the exact hostname the URL resolves to.
HOSTS = {
    # A JSON API that serves the whole catalog: eight parallel detail fetches,
    # no artificial pause, and no retry — a full crawl is cheap to repeat, and
    # retrying every one of 450 fetches against a failing API helps nobody.
    "endoflife.date": Profile(timeout=(15, 90), attempts=1, workers=8),
    # Server-rendered sites crawled as HTML: two workers, half a second between
    # requests and one retry after a pause.
    "eosl.date": Profile(timeout=(15, 60), pause=0.5, workers=2),
    "opengear.com": Profile(timeout=(15, 60), pause=0.5, workers=2),
}
# Any other host — a researched contribution's cited page, for instance — is
# read serially with the generous catalog timeout and one retry.
DEFAULT = Profile(timeout=(15, 90))
# Server-side statuses that say "try again": a rate limit or an outage, as
# opposed to a 4xx, which says the request itself is wrong.
TRANSIENT_STATUS = frozenset({429})


def profile(url):
    """The politeness policy for ``url``'s host."""
    return HOSTS.get(urlparse(url).hostname or "", DEFAULT)


def workers(url):
    """The parallel fetch pool size this host tolerates."""
    return profile(url).workers


def transient(error):
    """Whether a failure is worth retrying: the request may succeed unchanged.

    A dropped connection, a timeout, a rate limit or a 5xx is transient. A 4xx
    is not: the request is wrong, and retrying it wastes the upstream's time
    while hiding the real problem from the caller.
    """
    if isinstance(error, (requests.ConnectionError, requests.Timeout)):
        return True
    response = getattr(error, "response", None)
    if isinstance(error, requests.HTTPError) and response is not None:
        return response.status_code in TRANSIENT_STATUS or response.status_code >= 500
    return False


def get(url):
    """GET ``url`` under its host policy, retrying a transient failure.

    Returns the response with its status checked. A transient failure is
    retried up to the host's attempt count after its retry delay; the last
    failure is then raised unchanged, and a non-transient failure (a 4xx, a
    parse-level error) is raised at once. Requests exceptions propagate as
    themselves, so a caller can distinguish a network failure from a parse
    error (``engine.contribute`` reports the former as unverifiable evidence
    rather than as a bad contribution).
    """
    policy = profile(url)
    for attempt in range(policy.attempts):
        try:
            response = requests.get(url, timeout=policy.timeout,
                                    headers={"User-Agent": USER_AGENT})
            response.raise_for_status()
            return response
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
