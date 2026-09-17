"""Upcoming lifecycle dates as Atom, RSS 2.0 and iCalendar documents.

Every published (non-null) milestone of every software release and every
hardware model is a candidate event: general availability, end of sale, end of
security support and end of life. `build()` keeps the events that have not
passed (`today <= date`, UTC — a date falling today is still upcoming), sorts
them by date, and writes three equivalent representations below `_site`:

* `v1/feed.atom`     RFC 4287, one `entry` per event.
* `v1/feed.rss`      RSS 2.0, one `item` per event.
* `v1/calendar.ics`  RFC 5545, one all-day `VEVENT` per event.

Identifiers are permanent. An event is named by a `tag:` URI (RFC 4151) and
that same string is the iCalendar `UID`. The tagging entity is the project's
own authority name and the year it was assigned it; per RFC 4151 the tagging
date is never derived from catalog data and never lies in the future, so an
event dated 2099 is still `tag:eoltracker,2026:...`. The specific part holds
five `:`-separated, percent-encoded fields — kind, product id, release or model
id, milestone key and the full milestone date:

    tag:eoltracker,2026:software:python:3.14:eol:2030-10-31

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
from urllib.parse import quote
from xml.sax.saxutils import escape, quoteattr

from .importer import ROOT
from .site import MILESTONES, SITE_URL, human_date, site_url

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


def _event(product_id, product_name, release_id, release_name, milestone, value, url):
    """One upcoming milestone as a stable id plus the text every format prints."""
    name = _clean(product_name)
    release = _clean(release_name) if release_name else None
    label = MILESTONE_LABELS[milestone]
    title = " ".join(part for part in (name, None if release == name else release, label) if part)
    # Product id, release or model id, milestone key and the full milestone
    # date, hyphen joined:
    #   tag:eoltracker,2026:python-3.14-eol-2030-10-31
    specific = "-".join(_specific(part) for part in (product_id, release_id, milestone, value) if part)
    return {
        "id": TAG_PREFIX + specific,
        "date": value,
        "milestone": milestone,
        "label": label,
        "title": title,
        "url": url,
        "summary": f"{title} on {human_date(value)} ({value}). Full lifecycle: {url}",
    }


def software_events(products):
    """Every published milestone of every release of every product, unsorted."""
    events = []
    for record in products or ():
        url = site_url(f"products/{record['id']}/")
        for release in record["releases"]:
            milestones = release["milestones"]
            for milestone in MILESTONE_KEYS:
                value = milestones.get(milestone)
                if not value:
                    continue
                events.append(_event(
                    record["id"], record["name"], release["id"],
                    release.get("name") or release["id"], milestone, value, url,
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
            events.append(_event(record["id"], record["name"], model, model, milestone, value, url))
    return events


def upcoming_events(products, hardware=None, today=None):
    """Milestone dates that have not passed yet, from today (UTC), soonest first.

    Raises `ValueError` if two events would mint one identifier: duplicate
    Atom `id`s, RSS `guid`s and iCalendar `UID`s would make the calendar merge
    two different deadlines into one event.
    """
    today = today or datetime.now(timezone.utc).date()
    cutoff = today.isoformat()
    events = [event for event in software_events(products) + hardware_events(hardware)
              if event["date"] >= cutoff]
    seen = {}
    for event in events:
        if event["id"] in seen:
            raise ValueError(
                f"Duplicate event identifier {event['id']!r} for {seen[event['id']]!r} and {event['title']!r}")
        seen[event["id"]] = event["title"]
    events.sort(key=lambda event: (event["date"], event["title"], event["id"]))
    return events


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


def _ics_date(value):
    return date.fromisoformat(value).strftime("%Y%m%d")


def _rfc822(value):
    return format_datetime(datetime.fromisoformat(value).replace(tzinfo=timezone.utc), usegmt=True)


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

    The channel's `pubDate` and `lastBuildDate` are the snapshot time, while
    each item's `pubDate` is the milestone date itself: readers sort and render
    a date feed by when the event happens, not by when the catalog was rebuilt.
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
            f"      <pubDate>{_rfc822(event['date'])}</pubDate>",
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
    current UTC time is used. Returns the event count, the update timestamp as
    Atom prints it, and the written paths.
    """
    out = Path(out_dir) if out_dir is not None else DEFAULT_OUT
    updated = generated_at(manifest)
    events = upcoming_events(products, hardware)
    documents = {
        "atom": atom_feed(events, updated),
        "rss": rss_feed(events, updated),
        "ics": calendar_feed(events, updated),
    }
    written = []
    for name, document in documents.items():
        path = out / FEED_PATHS[name]
        _write(path, document)
        written.append(str(path))
    return {"events": len(events), "updated": _atom_stamp(updated), "files": written}
