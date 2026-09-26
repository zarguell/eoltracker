"""ownCloud Server core release-line lifecycle (#135).

Source: the **owncloud/core** project wiki's "Maintenance and Release Schedule",
``https://github.com/owncloud/core/wiki/Maintenance-and-Release-Schedule``.

ownCloud Server's own support page designates that page as the place to follow
for Server releases, so the source is the vendor's own project statement rather
than a third-party catalog. The attribution is the one issue #126 settled: the
record names **ownCloud** as the vendor and never Kiteworks, because ownCloud
publishes this under its own project identity.

The schedule is one table, one row per major release line:

===========================  ==========  ===================  ================
version                      release     end of life          current version
===========================  ==========  ===================  ================
``10``                       2017-04-27  ``2027-01``          10.16.4 (...)
``9.1``                      2016-07-21  ``2018-02``          9.1.8 (...)
``11``                       2026-07-30  ``maintained, EOL TBA``  11.0.0 (...)
===========================  ==========  ===================  ================

Three things in that shape decide the mapping, and all three are the vendor's
own columns rather than this module's reading of them.

**The line is the release, and its ``release date`` is that line's GA.** The
``current version`` column states a *patch* release and its own date — for line
10, ``10.16.4 (2026-07-29)``, which is a different fact from the line's
2017-04-27 release. Publishing the patch's date as the line's ``ga`` would
replace a stated date with a different stated date, so both are kept: the line
publishes its own ``ga``, and the patch and its date stay in the vendor's cells.

**``end of life`` is a month, and stays a month.** Fourteen of the fifteen rows
state ``YYYY-MM``. The schedule publishes no day, so no day is invented
(AGENTS.md rule 4) and those events are not syndicated into the exact-day Atom,
RSS and iCalendar feeds; ``v1/feed-exclusions.json`` enumerates them instead.

**``maintained, EOL TBA`` is the vendor's own trigger, not an unknown date.**
Line 11 states it verbatim, and it means the line is supported with no announced
end: ``eol`` is null, the cell is kept, and the schedule must still state that
trigger or the run refuses.

The two absence tokens are the page's own vocabulary, not missing data. A line
that is long retired states ``-`` for its current version and ``End of Life``
for its next one; both state that no such version exists, and neither is a date
or an error.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

from . import net, sources, tables, transaction
from .importer import ROOT

SOURCE = sources.source("import-owncloud")
VERIFIER = SOURCE.verifier
REPORT = SOURCE.report
SOURCE_URL = SOURCE.url
SUPPORT_URL = "https://owncloud.com/support/"
RECORD_SCHEMA = "https://zarguell.github.io/eoltracker/v1/schema/product.json"
PRODUCT_ID = "owncloud-server"
VENDOR = "ownCloud"
UPSTREAM_CATEGORY = "os"
ATTRIBUTION = ("ownCloud Server release lines published from the owncloud/core project's own "
               "Maintenance and Release Schedule, the page owncloud.com/support/ designates for "
               "Server releases; the vendor is ownCloud, not Kiteworks (issue #126). Each line's "
               "release date is its GA and its end of life is a month the schedule states without "
               "a day, so it is published at month precision and never widened.")

# The page's own title, required verbatim before a row is read: a wiki page that
# is renamed or replaced must refuse rather than be read as this schedule.
PAGE_TITLE = "Maintenance and Release Schedule"
TABLE_HEADING = ("version", "release date", "end of life", "current version", "next version")
# The vendor's own cell for a supported line with no announced end, and the two
# tokens the page uses to say a version does not exist.
TBA_CELL = "maintained, EOL TBA"
NO_VERSION = ("-", "end of life", "")
# The line's own release date is a day; its end of life is a month. Both widths
# are separate values and neither is padded into the other.
DAY = re.compile(r"(?P<year>\d{4})-(?P<month>\d{2})-(?P<day>\d{2})\Z")
MONTH = re.compile(r"(?P<year>\d{4})-(?P<month>\d{2})\Z")
# ``10.16.4 (2026-07-29)`` — the current patch and its own release date.
PATCH = re.compile(r"(?P<patch>\d+(?:\.\d+)*)\s*\((?P<date>[^()]*)\)")


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _fold(text):
    return tables.fold(text)


def _day(text, where):
    """A stated day, or ``None`` when the vendor states none."""
    value = _fold(text)
    if value.lower() in ("n/a", "na", "-"):
        return None
    match = DAY.fullmatch(value)
    if not match:
        raise ValueError(f"{where}: {value!r} is not an ISO day this schedule states")
    year, month, day = (int(match.group("year")), int(match.group("month")),
                        int(match.group("day")))
    try:
        datetime(year, month, day)
    except ValueError:
        raise ValueError(f"{where}: {value!r} is not a real calendar day") from None
    return value


def _month(text, where):
    """A stated month, or ``None`` when the vendor states none.

    The schedule publishes ``2027-01`` and no day, so the month is stored as a
    month. A day-shaped value in this column would mean the column changed, and
    refuses rather than being narrowed to a month.
    """
    value = _fold(text)
    if value.lower() in ("n/a", "na", "-"):
        return None
    if DAY.fullmatch(value):
        raise ValueError(f"{where}: {value!r} is a day in a column the schedule states in months")
    match = MONTH.fullmatch(value)
    if not match:
        if _fold(text).lower() == TBA_CELL.lower():
            return None
        raise ValueError(f"{where}: {value!r} is not a month this schedule states")
    year, month = int(match.group("year")), int(match.group("month"))
    if not 1 <= month <= 12:
        raise ValueError(f"{where}: {value!r} is not a real calendar month")
    return value


def require_page(html, where):
    """Refuse unless this is the schedule page the vendor designates."""
    if PAGE_TITLE not in html:
        raise ValueError(f"{where}: the page no longer carries the {PAGE_TITLE!r} title, so it is "
                         f"not the schedule this collector reads")


def parse(html, where="ownCloud Server Maintenance and Release Schedule"):
    """The schedule as ``(releases, accounting)``.

    Every stated row is one release line. A row whose line the page states
    without a release date refuses: the line's identity is the line, and a line
    with no stated date is a page this collector cannot interpret rather than a
    release to publish with borrowed dates.
    """
    require_page(html, where)
    doc = tables.parse_document(html)
    # ``th_header`` returns the folded leaf labels and how many header rows state
    # them, so a table whose columns changed simply is not this table.
    blocks = [block for block in doc.blocks if tables.th_header(block)[0] == TABLE_HEADING]
    if len(blocks) != 1:
        raise ValueError(f"{where}: the page states {len(blocks)} release tables, expected the one "
                         f"it publishes")
    block = blocks[0]
    headers, start = tables.header_rows(block, where)
    if len(headers) != 1:
        raise ValueError(f"{where}: the release table states {len(headers)} header rows")
    body, controls = tables.spanned_rows(block, TABLE_HEADING, start)
    if controls:
        raise ValueError(f"{where}: the release table states unrecognized control row(s) {controls}")
    rows = tables.data_rows(body, where, PAGE_TITLE, TABLE_HEADING)
    if not rows:
        raise ValueError(f"{where}: the schedule states no release line")

    releases, triggers = [], []
    for index, cells in enumerate(rows, 1):
        at = f"{where} row {index}"
        line = _fold(cells["version"])
        if not line:
            raise ValueError(f"{at}: row states no release line")
        if not re.fullmatch(r"\d+(?:\.\d+)*", line):
            raise ValueError(f"{at}: {line!r} is not a release line this schedule states")
        raw_ga = _fold(cells["release date"])
        ga = _day(raw_ga, f"{at} release date")
        if ga is None:
            raise ValueError(f"{at}: {line} states no release date")
        raw_eol = _fold(cells["end of life"])
        eol = _month(cells["end of life"], f"{at} end of life")
        if eol is None and raw_eol.lower() != TBA_CELL.lower():
            raise ValueError(f"{at}: {line} states no end of life and does not state the "
                             f"vendor's {TBA_CELL!r} either")
        if eol is None:
            triggers.append({"line": line, "cell": raw_eol,
                             "reason": "the schedule states the line is maintained with no announced "
                                       "end of life; it is a vendor trigger, not an unknown date, "
                                       "so eol is null and the cell is kept verbatim"})
        upstream = {"name": line, "cells": {"version": line, "release date": raw_ga, "end of life": raw_eol,
                              "current version": _fold(cells["current version"]),
                              "next version": _fold(cells["next version"])},
                    "table": PAGE_TITLE}
        if eol is None:
            upstream["eol_note"] = (
                f"the schedule's own {TBA_CELL!r}: this line is maintained and has no announced "
                f"end of life, so no milestone is published for it")
        else:
            upstream["eol_note"] = (
                "a month the schedule states without a day, so it is published at month precision, "
                "is not syndicated into the exact-day feeds, and is listed in "
                "v1/feed-exclusions.json instead")
        patch, patch_date = _patch(cells["current version"], at, line)
        if patch:
            upstream["current version release"] = patch_date
        next_version = _fold(cells["next version"])
        if next_version.lower() not in NO_VERSION:
            upstream["next version release"] = _next_date(cells["next version"], at, line)
        releases.append({"id": line, "name": line,
                         "milestones": {"ga": ga, "eos": None, "eossec": None, "eol": eol},
                         "upstream": upstream})
    seen = [release["id"] for release in releases]
    if len(set(seen)) != len(seen):
        raise ValueError(f"{where}: the schedule states a release line more than once: "
                         f"{sorted({line for line in seen if seen.count(line) > 1})}")
    return releases, {"rows": len(rows), "lines": len(releases), "triggers": triggers}


def _patch(cell, at, line):
    """The current patch release and its own date, or ``(None, None)``.

    The schedule writes ``10.16.4 (2026-07-29)`` for a line that has one and
    ``-`` for a line that does not. This is a per-patch fact, not the line's
    GA, so it is kept as the vendor's own cell and never becomes a milestone.
    """
    value = _fold(cell)
    if value.lower() in NO_VERSION:
        return None, None
    match = PATCH.fullmatch(value)
    if not match:
        raise ValueError(f"{at}: the current version {value!r} is not a patch and date this "
                         f"schedule states")
    if not value.startswith(line):
        raise ValueError(f"{at}: the current version {value!r} is not a release of line {line}")
    return match.group("patch"), _day(match.group("date"), f"{at} current version date")


def _next_date(cell, at, line):
    """The next release's stated date, or ``None`` when the vendor says TBA."""
    value = _fold(cell)
    match = PATCH.fullmatch(value)
    if not match:
        raise ValueError(f"{at}: the next version {value!r} is not a patch and date this schedule "
                         f"states")
    if not value.startswith(line):
        raise ValueError(f"{at}: the next version {value!r} is not a release of line {line}")
    stated = _fold(match.group("date"))
    if stated.lower() in ("tba", "n/a", "-"):
        return None
    return _day(stated, f"{at} next version date")


def combine(releases, committed):
    """This fetch's lines plus any committed line the schedule no longer states.

    A major line that disappears from the page is retained with its dates and
    marked ``in_source: false`` rather than deleted, so a line the vendor
    quietly removed stays visible with a reason instead of vanishing from the
    catalog and from the feed identities it already has.
    """
    if committed is None:
        return releases, []
    stated = {release["id"] for release in releases}
    kept = [{**release, "upstream": {**release["upstream"], "in_source": False}}
            for release in committed["releases"] if release["id"] not in stated]
    if not kept:
        return releases, []
    return releases + kept, [{"id": release["id"], "name": release["name"],
                              "reason": "the ownCloud Server schedule no longer states this release "
                                        "line; the committed line and its dates are retained"}
                             for release in kept]


def record_for(releases, checked):
    """The published ownCloud Server record."""
    return {
        "$schema": RECORD_SCHEMA,
        "id": PRODUCT_ID,
        "name": "ownCloud Server",
        "category": "software",
        "upstream_category": UPSTREAM_CATEGORY,
        "identifiers": [],
        "labels": {"ga": "release date", "eol": "end of life",
                   "precision": "end of life is a month the schedule states without a day"},
        "links": {"html": SOURCE_URL, "support": SUPPORT_URL,
                  "vendor designation": SUPPORT_URL},
        "releases": releases,
        "provenance": {"source_url": SOURCE_URL, "verifier": VERIFIER,
                       "last_checked": checked, "upstream_modified": None},
    }


def validate_record(record):
    """Rebuild every line from its own stored cells, offline."""
    if record["id"] != PRODUCT_ID:
        raise ValueError(f"{record['id']} is not the ownCloud Server record")
    if record["provenance"]["verifier"] != VERIFIER:
        raise ValueError(f"{PRODUCT_ID} does not carry this source's verifier")
    if record["provenance"]["source_url"] != SOURCE_URL:
        raise ValueError(f"{PRODUCT_ID} does not name the schedule it came from")
    seen = set()
    for release in record["releases"]:
        where = f"{PRODUCT_ID}/{release['id']}"
        cells = release["upstream"].get("cells")
        if not isinstance(cells, dict) or tuple(cells) != (
                "version", "release date", "end of life", "current version", "next version"):
            raise ValueError(f"{where} does not carry the schedule's own columns")
        if release["upstream"].get("table") != PAGE_TITLE:
            raise ValueError(f"{where} does not name the schedule it came from")
        if _fold(cells["version"]) != release["id"]:
            raise ValueError(f"{where} does not match its own version cell")
        if release["milestones"]["ga"] != _day(cells["release date"], f"{where} release date"):
            raise ValueError(f"{where} claims a ga its own cell does not state")
        expected_eol = _month(cells["end of life"], f"{where} end of life")
        if expected_eol is None and _fold(cells["end of life"]).lower() != TBA_CELL.lower():
            raise ValueError(f"{where} states neither a month nor the vendor's trigger")
        if release["milestones"]["eol"] != expected_eol:
            raise ValueError(f"{where} claims an eol its own cell does not state")
        if release["milestones"]["eos"] is not None or release["milestones"]["eossec"] is not None:
            raise ValueError(f"{where} claims an eos or eossec this source never states")
        # A month must stay a month: the schedule publishes no day here, so a
        # day-shaped milestone would be a date the vendor never wrote.
        if expected_eol is not None and DAY.fullmatch(expected_eol):
            raise ValueError(f"{where} widened a month-precision end of life into a day")
        if expected_eol is None and "eol_note" not in release["upstream"]:
            raise ValueError(f"{where} publishes no eol without the vendor's own trigger note")
        if release["id"] in seen:
            raise ValueError(f"{PRODUCT_ID} states release line {release['id']} twice")
        seen.add(release["id"])


def import_owncloud(directory=None):
    """Fetch the schedule and publish the ownCloud Server record."""
    root = Path(directory) if directory is not None else ROOT / "data"
    committed = transaction.committed_product_record(
        root, PRODUCT_ID, VERIFIER, validate_record, "ownCloud Server")
    checked = _now()
    releases, accounting = parse(net.get_text(SOURCE_URL))
    rows, kept = combine(releases, committed)
    record = record_for(rows, checked)
    validate_record(record)
    report = {
        "source_url": SOURCE_URL, "support_url": SUPPORT_URL, "verifier": VERIFIER,
        "checked_at": checked,
        "record_scope": ("ownCloud Server major release lines: one software record with one "
                         "release per line the schedule states, at the precision each column "
                         "states"),
        "rows": {"seen": accounting["rows"], "published": accounting["lines"],
                 "retained": len(kept), "triggers": len(accounting["triggers"])},
        "triggers": accounting["triggers"],
        "total_records": 1,
        "limitations": [
            "A release line's own release date is its ga. The current-version column states a "
            "patch release and that patch's own date, which is a different fact, so it is kept as "
            "the vendor's cell and never becomes the line's ga.",
            "End of life is a month the schedule states without a day, so it is published at month "
            "precision and never widened into a day. Those events are not syndicated into the "
            "exact-day Atom, RSS and iCalendar feeds; v1/feed-exclusions.json enumerates them "
            "instead.",
            "The schedule states 'maintained, EOL TBA' for a line that is supported with no "
            "announced end. That is the vendor's own trigger rather than an unknown date, so eol is "
            "null, the cell is kept verbatim, and the run refuses if the schedule stops stating it.",
            "A line that is long retired states '-' for its current version and 'End of Life' for "
            "its next one. Both are the page's own vocabulary for a version that does not exist, "
            "not missing data, and neither is read as a date.",
            "The source is the owncloud/core project wiki, which owncloud.com/support/ designates "
            "for Server releases. It is the vendor's own project statement, and the record names "
            "ownCloud as the vendor rather than Kiteworks (issue #126). A wiki page is editable by "
            "the project, so the page's own title is required verbatim and a renamed or replaced "
            "page refuses rather than being read as this schedule.",
            "The schedule states no publication cadence and no page-level version; the refresh "
            "records when it last checked and what it found.",
        ],
    }
    transaction.publish_product_record(record, report, root, REPORT)
    return (f"imported {accounting['lines']} ownCloud Server release lines from {accounting['rows']}"
            f" rows ({len(accounting['triggers'])} with no announced end, {len(kept)} retained; "
            f"month-precision end of life) (data/{REPORT})")
