"""Upcoming lifecycle dates as Atom, RSS 2.0 and iCalendar documents.

Every published (non-null) milestone of every software release and every
hardware model is a candidate event: general availability, end of sale, end of
security support and end of life. `build()` keeps the events that have not
passed (`today <= date`, UTC — a date falling today is still upcoming), sorts
them by date, and writes three equivalent representations below `_site`:

* `v1/feed.atom`     RFC 4287, one `entry` per event.
* `v1/feed.rss`      RSS 2.0, one `item` per event.
* `v1/calendar.ics`  RFC 5545, one all-day `VEVENT` per event.

All three formats carry an *exact calendar day a source states*: Atom and RSS
stamp each item with an RFC 3339/RFC 822 date-time and iCalendar with a
`VALUE=DATE` day. Two kinds of upcoming event have no such day, and neither is
representable without misrepresenting the source:

* a *month-precision* event (``YYYY-MM``) — the source states a month, so a day
  would have to be invented (AGENTS.md rule 4); and
* a *derived* event — the day is arithmetic on a rule and a base date the
  vendor publishes (``milestone_provenance``; see `engine/derived.py`), so
  syndicating it would publish a computed result as a vendor-stated deadline.

Both are left out of the three documents and published instead, in full, in
`v1/feed-exclusions.json`: every excluded event with its stable identity, its
product, release, milestone and the value the source states, its own reason
code, and — for a derived event — the method, base date, rule and quote the
date was computed from. Nothing is silently dropped, no day is padded in, and
the sets are disjoint halves of one upcoming window, so a consumer that wants
every upcoming deadline reads the feed *and* that document.

Identifiers are permanent. An event is named by a `tag:` URI (RFC 4151) and
that same string is the iCalendar `UID`. The tagging entity is the project's
own authority name and the year it was assigned it; per RFC 4151 the tagging
date is never derived from catalog data and never lies in the future, so an
event dated 2099 is still `tag:eoltracker,2026:...`. The specific part holds
four `:`-separated, percent-encoded *immutable namespace* fields — kind,
product id, release or model id and milestone key:

    tag:eoltracker,2026:software:python:3.14:eol

None of those fields can change for an event that still exists: a source
correction moves the milestone's *date*, which is the event's representation,
not its identity. An earlier scheme appended the milestone date as a fifth
field, which meant a correction re-minted the identifier and left feed readers
holding an obsolete event and a duplicate reminder. `legacy_event_id()` still
reproduces that date-bearing form so a consumer can translate the identifiers
it already holds with `migrate_legacy_id()`; only the representation changes
when a date is corrected.

Encoding each field keeps the format injective, so no two events can ever mint
the same identifier, and an event keeps that identifier for its whole life
instead of being re-minted on every republication. `updated` (Atom),
`lastBuildDate`/`pubDate` (RSS) and `DTSTAMP` (iCalendar) come from the catalog
snapshot's `generated_at`.

`build()` uses the standard library only. Atom and RSS text is escaped through
`xml.sax.saxutils`; iCalendar values are escaped and the lines folded per RFC
5545 section 3.1, on UTF-8 octets, without splitting a character.
"""
import json
import re
from datetime import date, datetime, timezone
from email.utils import format_datetime
from pathlib import Path
from urllib.parse import quote, urlsplit
from xml.sax.saxutils import escape, quoteattr

from .importer import ROOT
from . import derived
from .site_config import (MILESTONES, SCHEMA_VERSION, SITE_URL, human_date, is_month,
                          published_period, site_url)

try:  # The core persistence slice owns the validator; presentation may lack it.
    from .urls import safe_http_url_or_none
except ImportError:  # pragma: no cover - exercised only without the core module
    def safe_http_url_or_none(value):
        """Fallback: keep only plain absolute http(s) URLs, no userinfo/controls."""
        if not isinstance(value, str) or any(ord(ch) < 0x20 or ch == "\x7f" for ch in value):
            return None
        parsed = urlsplit(value.strip())
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            return None
        if "@" in parsed.netloc or not parsed.hostname:
            return None
        return value

DEFAULT_DATA = ROOT / "data"
DEFAULT_OUT = ROOT / "_site"

# RFC 4151 tagging entity: an authority name plus the date it was assigned to
# us, 00:00 UTC. Fixed by definition, never minted from catalog data.
TAGGING_AUTHORITY = "eoltracker"
TAGGING_DATE = "2026"
TAG_PREFIX = f"tag:{TAGGING_AUTHORITY},{TAGGING_DATE}:"

# All three documents syndicate one logical feed — upcoming lifecycle
# milestones — so the Atom feed carries a single permanent id (RFC 4287
# section 4.2.6) while each RSS item is identified by its own tag URI.
FEED_ID = TAG_PREFIX + "upcoming-lifecycle-milestones"
FEED_TITLE = "EOL Tracker — upcoming lifecycle dates"
FEED_SUBTITLE = ("General availability, end of sale, end of security support and end of life dates "
                 "not yet reached, normalized from community catalogs and vendor lifecycle notices.")
FEED_DESCRIPTION = FEED_SUBTITLE + " One item per release or hardware model and milestone."
AUTHOR = "EOL Tracker"
PRODID = "-//EOL Tracker//upcoming lifecycle dates//EN"
CALENDAR_NAME = FEED_TITLE
GENERATOR = "EOL Tracker"

FEED_PATHS = {
    "atom": Path("v1/feed.atom"),
    "rss": Path("v1/feed.rss"),
    "ics": Path("v1/calendar.ics"),
}
EXCLUSIONS_PATH = Path("v1/feed-exclusions.json")
# The published reasons an upcoming event is not in the three documents. Each is
# a statement about the *event*, not about its validity: the milestone is real
# and upcoming, and it is listed in full next to this sentence.
MONTH_EXCLUSION_CODE = "month_precision_not_representable"
MONTH_EXCLUSION_REASON = (
    "The source states this milestone's month only (YYYY-MM), and Atom, RSS and iCalendar each "
    "carry an exact calendar day. The event is published here with the month the source states "
    "rather than padding it with a day the source never published."
)
DERIVED_EXCLUSION_CODE = "derived_not_vendor_stated"
DERIVED_EXCLUSION_REASON = (
    "This milestone is a derived date, not a vendor-stated one: its rule, inputs, and base are "
    "published in the record's milestone_provenance and engine/derived.py recomputes it from them, "
    "but the vendor states no calendar day for it. Atom, RSS and iCalendar carry a day a source "
    "states, so syndicating it would publish a calculated result as a vendor deadline. The event "
    "is listed here in full, with the rule that produced it, instead."
)
# Order is the order the reasons print and the order a consumer reads them in.
EXCLUSION_REASONS = (
    {"code": MONTH_EXCLUSION_CODE, "statement": MONTH_EXCLUSION_REASON, "precision": "month"},
    {"code": DERIVED_EXCLUSION_CODE, "statement": DERIVED_EXCLUSION_REASON, "precision": "derived"},
)
EXCLUSION_REASON_BY_CODE = {reason["code"]: reason for reason in EXCLUSION_REASONS}

# The milestone vocabulary is the published one: same keys, same labels as the
# site, so a feed never renames what a page shows.
MILESTONE_KEYS = tuple(milestone["key"] for milestone in MILESTONES)
MILESTONE_LABELS = {milestone["key"]: milestone["label"] for milestone in MILESTONES}

# RFC 5545 section 3.1: 75 octets per physical line, continuation lines start
# with one space, which leaves 74 octets of content after the first line.
LINE_OCTETS = 75
CONTENT_OCTETS = LINE_OCTETS - 1


def _clean(value):
    """One line of printable text: no control characters, single spaces."""
    return re.sub(r"\s+", " ", re.sub(r"[\x00-\x1f\x7f]", " ", str(value))).strip()


def _specific(value):
    """The RFC 4151 specific part for one catalog identifier.

    Unreserved characters stay as they are, so a version reads as `3.14`;
    anything else (spaces, parentheses, quotes) is percent-encoded, which keeps
    the result valid in a `tag:` URI and an iCalendar `TEXT` value without
    further escaping.
    """
    return quote(str(value), safe="")


def _event_id(kind, product_id, release_id, milestone):
    """The permanent identity of one event, from immutable namespace fields only.

    Product id, release or model id and milestone key, colon separated and
    percent encoded:
      tag:eoltracker,2026:software:python:3.14:eol
    The kind namespaces software against hardware, which is required: the same
    product/release/milestone can exist in both catalogs. The milestone's date
    is deliberately absent — a source correction moves the date, and an
    identity that moved with it would re-mint the event and duplicate it in
    every reader that already held the old one.
    """
    return TAG_PREFIX + ":".join(_specific(part) for part in (kind, product_id, release_id, milestone) if part)


def legacy_event_id(kind, product_id, release_id, milestone, value):
    """Reproduce the pre-2026-09 identity, which appended the mutable date.

    Provided so a consumer can recognise the identifiers it already holds; this
    module never mints one. The legacy specific part was hyphen joined and
    carried no namespace, which is why `migrate_legacy_id` needs the event's
    own fields to translate it.
    """
    specific = "-".join(_specific(part) for part in (product_id, release_id, milestone, value) if part)
    return TAG_PREFIX + specific


def migrate_legacy_id(kind, product_id, release_id, milestone, value):
    """The permanent identity for the event a legacy date-bearing id named.

    The legacy specific part was `<product>-<release>-<milestone>-<date>`, all
    hyphen joined and with no namespace. That form is ambiguous — a product id
    containing a hyphen is indistinguishable from a product/release boundary —
    so the translation is not a pure string rewrite: it takes the event's own
    namespace fields, which the consumer already holds from the entry, and maps
    the *date-bearing* id it cached onto the permanent identity.

    `value` must be that legacy id (or already the permanent one); anything else
    raises `ValueError` rather than silently inventing a different event's
    identity. The date in `value` is discarded: the milestone's date is the
    representation, and the point of the migration is that correcting it must
    not re-mint the event.
    """
    permanent = _event_id(kind, product_id, release_id, milestone)
    if not isinstance(value, str) or not value.startswith(TAG_PREFIX):
        raise ValueError(f"Not an event identifier: {value!r}")
    specific = value[len(TAG_PREFIX):]
    if specific == permanent[len(TAG_PREFIX):]:
        return permanent
    legacy_prefix = "-".join(_specific(part) for part in (product_id, release_id, milestone) if part)
    if re.fullmatch(re.escape(legacy_prefix) + r"-(?:\d{4}-\d{2}|\d{4}-\d{2}-\d{2})", specific):
        return permanent
    raise ValueError(
        f"{value!r} is not the identifier of {kind}/{product_id}/{release_id}/{milestone} "
        f"in either the legacy date-bearing or the permanent form")


def _event(kind, product_id, product_name, release_id, release_name, milestone, value, url, derived=None):
    """One upcoming milestone as a stable id plus the text every format prints.

    `kind` is the namespace half of the event's identity — `software` or
    `hardware` — and is carried on the event because the exclusion document
    names each excluded event by the same fields its identifier encodes.

    `derived` is the milestone's own derivation disclosure when the record
    states a rule instead of a day (see `engine/derived.py`): a derived event is
    never syndicated, so this is what the exclusion document publishes about it
    instead of the three documents publishing the date.
    """
    name = _clean(product_name)
    release = _clean(release_name) if release_name else None
    label = MILESTONE_LABELS[milestone]
    title = " ".join(part for part in (name, None if release == name else release, label) if part)
    # A month-precision value is stated as the month it is ("July 2028") rather
    # than dressed as a day; the parenthesized ISO value keeps the stored width
    # legible either way.
    human = human_date(value)
    stated = f"{human} (month precision)" if is_month(value) else f"{human} ({value})"
    # Only a source page that is a plain absolute http(s) URL reaches a
    # syndicated link or an iCalendar URL value; an unsafe scheme is dropped
    # rather than republished as something a feed client might interpret.
    safe_url = safe_http_url_or_none(url) or SITE_URL
    return {
        "id": _event_id(kind, product_id, release_id, milestone),
        "date": value,
        "month": is_month(value),
        "derived": derived or None,
        "milestone": milestone,
        "label": label,
        "kind": kind,
        "product_id": product_id,
        "product": name,
        "release_id": release_id,
        "release": release or name,
        "title": title,
        "url": safe_url,
        "summary": f"{title} on {stated}. Full lifecycle: {safe_url}",
    }


def _derived_view(provenance, milestone):
    """The derivation disclosure one release carries for one milestone, or None.

    The rule fields are copied verbatim — the identity of the rule is part of
    what the exclusion publishes — so a consumer can recompute the date or
    check it against the record without a second fetch.
    """
    entry = (provenance or {}).get(milestone)
    if not entry:
        return None
    return {
        "method": entry["method"],
        "base_date": entry["base_date"],
        "base_label": entry["base_label"],
        "source_url": entry["source_url"],
        "quote": entry["quote"],
        "duration": entry.get("duration"),
        "trigger": entry.get("trigger"),
        "parent": entry.get("parent"),
    }


def software_events(products):
    """Every published milestone of every release of every product, unsorted.

    A release's `milestone_provenance` is read here rather than in the
    formatters: an event carries whether its date is derived, so the split into
    syndicated and excluded events happens once and every format agrees.
    """
    events = []
    for record in products or ():
        url = site_url(f"products/{record['id']}/")
        for release in record["releases"]:
            milestones = release["milestones"]
            provenance = release.get(derived.DERIVED_KEY)
            for milestone in MILESTONE_KEYS:
                value = milestones.get(milestone)
                if not value:
                    continue
                events.append(_event(
                    "software", record["id"], record["name"], release["id"],
                    release.get("name") or release["id"], milestone, value, url,
                    _derived_view(provenance, milestone),
                ))
    return events


def hardware_events(hardware):
    """Every published milestone of every hardware model, unsorted.

    Hardware has no page of its own on the site, so an event links to the
    vendor source the record was verified against, falling back to the site.
    """
    events = []
    for record in hardware or ():
        sources = (record.get("provenance") or {}).get("source_urls") or ()
        url = sources[0] if sources else SITE_URL
        model = record.get("model_number")
        for milestone in MILESTONE_KEYS:
            value = record["milestones"].get(milestone)
            if not value:
                continue
            events.append(_event("hardware", record["id"], record["name"], model, model, milestone, value, url))
    return events


def upcoming_events(products, hardware=None, today=None):
    """Milestone dates that have not passed yet, from today (UTC), soonest first.

    Raises `ValueError` if two events would mint one identifier: duplicate
    Atom `id`s, RSS `guid`s and iCalendar `UID`s would make the calendar merge
    two different deadlines into one event. The uniqueness check covers the
    month-precision events too — they share the identifier space even though
    only the exclusion document publishes them.

    A month-precision event is upcoming for the whole month it covers, so it
    drops out of the window only once that month has passed.
    """
    today = today or datetime.now(timezone.utc).date()
    events = [event for event in software_events(products) + hardware_events(hardware)
              if published_period(event["date"]) >= today]
    seen = {}
    for event in events:
        if event["id"] in seen:
            raise ValueError(
                f"Duplicate event identifier {event['id']!r} for {seen[event['id']]!r} and {event['title']!r}")
        seen[event["id"]] = event["title"]
    events.sort(key=lambda event: (event["date"], event["title"], event["id"]))
    return events


def representable(events):
    """Split upcoming events into ``(day_events, excluded_events)``, order preserved.

    The three syndication formats carry an exact calendar day a source states;
    only those events can be written to them. Two kinds of upcoming event have
    no such day:

    * a month-precision event (``month``) — the source states a month, so there
      is no day to carry; and
    * a derived event (``derived``) — the day is arithmetic on a published rule
      and base, so carrying it would syndicate a computed date as a vendor
      deadline.

    Neither is dropped: they are what the exclusion document publishes, each
    tagged with its own code, so the two lists are disjoint and together cover
    every upcoming event. ``excluded`` keeps the upcoming order of ``events``.
    """
    days = [event for event in events if not event["month"] and not event["derived"]]
    excluded = [event for event in events if event["month"] or event["derived"]]
    return days, excluded


def _exclusion(event):
    """One excluded upcoming event, with the code and reason that apply to it.

    A derived event can also be month precision in principle; the derived code
    wins, because "the vendor states a rule rather than a day" is the stronger
    statement about why syndicating it would misrepresent the source. Each
    excluded event carries exactly one code.
    """
    code = DERIVED_EXCLUSION_CODE if event["derived"] else MONTH_EXCLUSION_CODE
    reason = EXCLUSION_REASON_BY_CODE[code]
    entry = {
        "id": event["id"],
        "kind": event["kind"],
        "product": event["product_id"],
        "product_name": event["product"],
        "release": event["release_id"],
        "release_name": event["release"],
        "milestone": event["milestone"],
        "milestone_label": event["label"],
        "date": event["date"],
        "human": human_date(event["date"]),
        "url": event["url"],
        "code": code,
        "reason": reason["statement"],
    }
    if event["month"]:
        entry["month"] = event["date"]
    if event["derived"]:
        entry["derived"] = event["derived"]
    return entry


def exclusions_document(excluded, day_count, updated):
    """The machine-readable account of the upcoming events no feed can carry.

    Written next to the three documents so a consumer reading `v1/feed.atom`
    can discover, without guessing, which upcoming deadlines it does not
    contain: the counts, every reason code with its statement, and every
    excluded event with its stable identity, product, release, milestone and the
    value the source states — plus, for a derived event, the rule, base and
    quote its date was computed from. Nothing is dropped silently and no day is
    invented for either exclusion.

    ``counts`` keeps its three preserved keys and the accounting invariant they
    state (``upcoming_events`` = ``feeds`` + ``excluded``); ``by_code`` adds the
    per-reason tally, which sums to ``excluded`` and names each code once.
    """
    entries = [_exclusion(event) for event in excluded]
    counts = {
        "upcoming_events": day_count + len(entries),
        "feeds": day_count,
        "excluded": len(entries),
    }
    by_code = {reason["code"]: sum(1 for entry in entries if entry["code"] == reason["code"])
               for reason in EXCLUSION_REASONS}
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": _atom_stamp(updated),
        "feeds": [str(path) for path in FEED_PATHS.values()],
        "reasons": EXCLUSION_REASONS,
        "counts": {**counts, "by_code": by_code},
        "excluded": entries,
    }


def generated_at(manifest=None):
    """The catalog snapshot time as UTC, never invented when a manifest exists.

    `manifest` is the catalog manifest mapping; when it is omitted
    `data/manifest.json` is read. Without either, the current UTC time is used.
    """
    if manifest is None:
        path = DEFAULT_DATA / "manifest.json"
        manifest = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    value = (manifest or {}).get("generated_at")
    if not value:
        return datetime.now(timezone.utc).replace(microsecond=0)
    moment = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return moment.astimezone(timezone.utc).replace(microsecond=0)


def _atom_stamp(moment):
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def _ics_stamp(moment):
    return moment.strftime("%Y%m%dT%H%M%SZ")


def _day_only(value, where):
    """Refuse a month-precision value at a day-precision formatter.

    The three syndication formats carry days; a caller that hands one a month
    has already lost the information a day would need, so this fails loudly
    rather than padding `-01` or raising a bare `ValueError` from `fromisoformat`.
    """
    if is_month(value):
        raise ValueError(f"{where}: {value!r} is month precision; it has no calendar day to format")
    return value


def _ics_date(value):
    return date.fromisoformat(_day_only(value, "iCalendar DTSTART")).strftime("%Y%m%d")


def _rfc822(value):
    day = _day_only(value, "RSS pubDate")
    return format_datetime(datetime.fromisoformat(day).replace(tzinfo=timezone.utc), usegmt=True)


def _ics_text(value):
    """A TEXT value: one line, with backslash, semicolon and comma escaped."""
    return _clean(value).translate({ord("\\"): "\\\\", ord(";"): "\\;", ord(","): "\\,"})


def _fold(line):
    """RFC 5545 line folding: 75 UTF-8 octets, continuation lines start with a space."""
    data = line.encode("utf-8")
    if len(data) <= LINE_OCTETS:
        return line
    chunks = []
    limit = LINE_OCTETS
    while data:
        cut = min(limit, len(data))
        while 0 < cut < len(data) and (data[cut] & 0xC0) == 0x80:
            cut -= 1
        chunks.append(data[:cut])
        data = data[cut:]
        limit = CONTENT_OCTETS
    return b"\r\n ".join(chunks).decode("utf-8")


def atom_feed(events, updated):
    """RFC 4287 document: one entry per event, newest update from the manifest."""
    stamp = _atom_stamp(updated)
    lines = [
        '<?xml version="1.0" encoding="utf-8"?>',
        '<feed xmlns="http://www.w3.org/2005/Atom" xml:lang="en">',
        f"  <id>{escape(FEED_ID)}</id>",
        f"  <title>{escape(FEED_TITLE)}</title>",
        f"  <subtitle>{escape(FEED_SUBTITLE)}</subtitle>",
        f"  <updated>{stamp}</updated>",
        f'  <link rel="self" type="application/atom+xml" href={quoteattr(site_url("v1/feed.atom"))}/>',
        f'  <link rel="alternate" type="text/html" href={quoteattr(SITE_URL)}/>',
        f"  <author><name>{escape(AUTHOR)}</name></author>",
        f'  <generator uri={quoteattr(SITE_URL)}>{escape(GENERATOR)}</generator>',
    ]
    for event in events:
        lines.extend([
            "  <entry>",
            f"    <id>{escape(event['id'])}</id>",
            f"    <title>{escape(event['title'])}</title>",
            f"    <updated>{stamp}</updated>",
            f'    <link rel="alternate" type="text/html" href={quoteattr(event["url"])}/>',
            f'    <category term={quoteattr(event["milestone"])} label={quoteattr(event["label"])}/>',
            f'    <summary type="text">{escape(event["summary"])}</summary>',
            "  </entry>",
        ])
    lines.append("</feed>")
    return "\n".join(lines) + "\n"


def rss_feed(events, updated):
    """RSS 2.0 document: one item per event.

    RSS 2.0 defines `pubDate` as *when the item was published*, not when the
    event it describes occurs, so every date here is the snapshot time the
    manifest states. The lifecycle date is not a publication date and never
    becomes one: a future deadline would be a publication timestamp in the
    future, which readers misorder or reject outright. The event's own date
    stays in the representation instead — it is the `title`/`description`
    text, the Atom `<category>`, and the iCalendar `DTSTART`. Because the item
    is a snapshot of a live feed rather than an archival post, `pubDate` is
    omitted: an unchanged event republished in a new snapshot has no single
    publication instant, and `lastBuildDate` (with the feed-level `pubDate`)
    already states when this document was produced.
    """
    stamp = format_datetime(updated, usegmt=True)
    lines = [
        '<?xml version="1.0" encoding="utf-8"?>',
        '<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">',
        "  <channel>",
        f"    <title>{escape(FEED_TITLE)}</title>",
        f"    <link>{escape(SITE_URL)}</link>",
        f"    <description>{escape(FEED_DESCRIPTION)}</description>",
        "    <language>en</language>",
        f"    <lastBuildDate>{stamp}</lastBuildDate>",
        f"    <pubDate>{stamp}</pubDate>",
        f'    <atom:link rel="self" type="application/rss+xml" href={quoteattr(site_url("v1/feed.rss"))}/>',
        f"    <generator>{escape(GENERATOR)}</generator>",
    ]
    for event in events:
        lines.extend([
            "    <item>",
            f"      <title>{escape(event['title'])}</title>",
            f"      <link>{escape(event['url'])}</link>",
            f'      <guid isPermaLink="false">{escape(event["id"])}</guid>',
            f"      <category>{escape(event['label'])}</category>",
            f"      <description>{escape(event['summary'])}</description>",
            "    </item>",
        ])
    lines.extend(["  </channel>", "</rss>"])
    return "\n".join(lines) + "\n"


def calendar_feed(events, updated):
    """RFC 5545 document, CRLF terminated: one all-day VEVENT per event."""
    stamp = _ics_stamp(updated)
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        f"PRODID:{PRODID}",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-CALNAME:{_ics_text(CALENDAR_NAME)}",
        f"X-WR-CALDESC:{_ics_text(FEED_DESCRIPTION)}",
        "X-WR-TIMEZONE:UTC",
    ]
    for event in events:
        lines.extend([
            "BEGIN:VEVENT",
            f"UID:{event['id']}",
            f"DTSTAMP:{stamp}",
            f"DTSTART;VALUE=DATE:{_ics_date(event['date'])}",
            f"SUMMARY:{_ics_text(event['title'])}",
            f"DESCRIPTION:{_ics_text(event['summary'])}",
            f"URL:{event['url']}",
            f"CATEGORIES:{_ics_text(event['label'])}",
            "TRANSP:TRANSPARENT",
            "END:VEVENT",
        ])
    lines.append("END:VCALENDAR")
    return "".join(_fold(line) + "\r\n" for line in lines)


def _write(path, content):
    """Write UTF-8 without newline translation: the iCalendar CRLF are content."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        handle.write(content)


def build(products, hardware=None, out_dir=None, manifest=None):
    """Write the Atom, RSS and iCalendar documents below `_site` (or `out_dir`).

    `products` is the software catalog (`validate_data()`) and `hardware` the
    hardware records (`validate_hardware()`); both may be empty. `manifest` is
    the catalog manifest supplying `generated_at` for every feed timestamp;
    when omitted it is read from `data/manifest.json`, and failing that the
    current UTC time is used.

    Only events whose date a source states as a calendar day reach the three
    documents; month-precision events — and derived events, whose day is
    arithmetic on a published rule — are written to `v1/feed-exclusions.json`
    instead, so the return value's counts are split rather than a single total.
    Returns the day-event count as `events`, the excluded-event count as
    `excluded`, the update timestamp as Atom prints it, and every written path.
    """
    out = Path(out_dir) if out_dir is not None else DEFAULT_OUT
    updated = generated_at(manifest)
    days, excluded = representable(upcoming_events(products, hardware))
    documents = {
        "atom": atom_feed(days, updated),
        "rss": rss_feed(days, updated),
        "ics": calendar_feed(days, updated),
    }
    written = []
    for name, document in documents.items():
        path = out / FEED_PATHS[name]
        _write(path, document)
        written.append(str(path))
    exclusions = out / EXCLUSIONS_PATH
    _write(exclusions, json.dumps(exclusions_document(excluded, len(days), updated),
                                  ensure_ascii=False, indent=2) + "\n")
    written.append(str(exclusions))
    return {"events": len(days), "excluded": len(excluded), "updated": _atom_stamp(updated), "files": written}
