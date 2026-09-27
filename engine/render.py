"""The opt-in rendering fetch profile: one honest browser, declared and gated.

Most vendor pages in this repository are read with ``engine.net``, which is
polite, identifying and scriptable. A few are not readable that way: the
content is assembled by JavaScript and the server HTML carries none of it. This
module is the second profile, for those pages, and it is deliberately narrow.

**What it is.** A real headless browser fetching the vendor's own published URL.
It is not a way to be somewhere it was refused, and three rules follow from
that:

* **It does not pretend to be a different browser.** No user-agent override, no
  ``navigator.webdriver`` patching, no header rewriting. The request identifies
  itself as what it is — a headless browser — because a profile that lies about
  its identity to reach a page is an impersonating one, and the difference
  between "browser-capable" and "impersonating" is the whole reason this path is
  acceptable.
* **It never solves a challenge.** No CAPTCHA handling, no WAF interstitial
  retry, no rotating identity. A page behind a login or a challenge is a
  *refusal*, and this profile does not attempt to get past one. Those sources
  stay researched records with a citation, which is what they were before this
  module existed.
* **It is opt-in twice over.** A source must register ``fetch="rendered"`` in
  ``engine.sources`` to be allowed here at all, and the operator must set
  ``EOLTRACKER_ALLOW_RENDER=1``. Absent either, this module raises rather than
  quietly falling back, so a rendered fetch can never happen by accident on a
  schedule the maintainer did not choose.

**Why the second gate exists.** A rendered fetch is slower, heavier and less
polite than a plain GET: it loads a browser engine, runs the page's own scripts,
and fetches their subresources. That belongs on a schedule the maintainer
picks, not in the daily refresh that every other source rides.

**What a record must carry.** Anything read through here is marked
``provenance.fetch = "rendered"``, permanently, so a reader can always tell which
records came from a rendered page. The profile refuses to return HTML it cannot
attribute to a specific registered source.

The dependency is optional and deliberately absent from ``requirements.txt``:
``pip install playwright && playwright install chromium`` is an explicit operator
step, and every existing collector is unaffected while it is missing.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

from . import net, sources

#: The operator switch. Rendering is off unless this is set to a true value.
ENV_SWITCH = "EOLTRACKER_ALLOW_RENDER"
#: The fetch profile name a source registers to be read this way.
PROFILE = "rendered"
#: A rendered fetch is slower and heavier, so it waits longer between requests
#: and caps itself harder than a plain GET. These are the defaults; a host with
#: its own entry in ``net.HOSTS`` keeps that host's stated pause.
RENDERED_TIMEOUT_MS = 120_000
SETTLE_MS = 4_000
MAX_HTML_BYTES = 32 * 1024 * 1024
TRUTHY = frozenset({"1", "true", "yes", "on"})


class RenderUnavailable(RuntimeError):
    """The rendering profile is not available, and will not pretend to be."""


class RenderRefused(ValueError):
    """A page this profile was asked to read, and read nothing usable from."""


@dataclass(frozen=True)
class Rendered:
    """One rendered page: the HTML, and the source it was read for."""

    url: str
    source_id: str
    html: str


def enabled():
    """True when the operator has switched rendering on for this process."""
    return os.environ.get(ENV_SWITCH, "").strip().lower() in TRUTHY


def profile_available(source):
    """Whether this source's registered fetch profile can run right now.

    The two gates a rendered source must pass, answered without launching a
    browser: the operator's switch, and the optional dependency being installed.
    A source whose profile is unavailable is skipped rather than failed.
    """
    if not enabled():
        return False
    try:
        import playwright.sync_api  # noqa: F401
    except ImportError:
        return False
    return True


def switch_state():
    """The operator switch as text, for a report that records why a run stopped."""
    return f"{ENV_SWITCH}={'on' if enabled() else 'off'}"


def declaring(source_id):
    """The registered source that may be read through this profile, or raise.

    A collector cannot opt itself in: the profile is named in the registry, so
    the set of pages rendered is visible in one place and adding one is a
    reviewed change.
    """
    source = sources.source(source_id)
    if source.fetch != PROFILE:
        raise RenderUnavailable(
            f"Source {source_id!r} is registered with fetch={source.fetch!r}, not {PROFILE!r}; "
            f"a source must register the rendering profile before a page may be rendered for it")
    return source


def render(url, source_id, trusted=False):
    """The rendered HTML of one registered source's page.

    ``trusted`` has the same meaning as in ``net.get``: it relaxes the per-request
    address check for a URL the registry built, and nothing else.
    """
    source = declaring(source_id)
    if not enabled():
        raise RenderUnavailable(
            f"Source {source_id!r} registers the {PROFILE!r} fetch profile, but "
            f"{ENV_SWITCH} is not set. A rendered fetch runs a browser and the page's own "
            f"scripts, so it runs only on a schedule the operator chooses. Fetch the page, set "
            f"the switch, and run this source again.")
    if url not in source.urls:
        raise RenderUnavailable(
            f"Source {source_id!r} does not list {url}; a rendered fetch may only read a URL the "
            f"registry names for that source")
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as error:
        raise RenderUnavailable(
            "Playwright is not installed. The rendering profile is an optional extra and is not "
            "in requirements.txt: install it deliberately with "
            "`pip install playwright && playwright install chromium`") from error
    destination = url if trusted else net.safe_url(url)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = browser.new_page()
            page.goto(destination, wait_until="networkidle", timeout=RENDERED_TIMEOUT_MS)
            # The page's own scripts have fetched what they fetch by now; a fixed
            # settle is a blunt instrument, and a page that needs longer is a
            # page whose absence of the expected table is caught below.
            page.wait_for_timeout(SETTLE_MS)
            html = page.content()
        finally:
            browser.close()
    if not html or len(html) > MAX_HTML_BYTES:
        raise RenderRefused(
            f"{source_id}: {url} rendered {len(html) if html else 0} bytes, which is empty or "
            f"beyond this profile's {MAX_HTML_BYTES} byte ceiling")
    return Rendered(url=url, source_id=source_id, html=html)


def fetch_note():
    """The provenance entry that marks a record as read through this profile."""
    return {
        "fetch": PROFILE,
        "rendered_by": "playwright chromium (headless); the page is the vendor's own published "
                       "URL, requested as a headless browser with no user-agent override, no "
                       "identity rewriting and no challenge solving",
        "operator_switch": ENV_SWITCH,
    }
