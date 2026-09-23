"""Microsoft Entra Connect lifecycle, from Microsoft's own lifecycle and release pages.

Three pages are authoritative, and each answers a different question:

* the **Microsoft Lifecycle** product page
  (``/en-us/lifecycle/products/azure-active-directory-ad-connect``) publishes the
  Lifecycle *Releases* table — the ``Version 1.x`` / ``Version 2.x`` family
  scopes with their start and end cells — plus the prose notice retiring all
  1.x versions;
* the **version release history** page names every current and supported build
  and carries the support table: ``Version``, ``End of support date``, ``Release
  date``;
* the **archive** page holds every build older than 1.5.42.0 with its own
  ``Status`` line.

**One row is one release, at the precision its own line states.** A support
table row states a day; an archive ``Released: May 2017`` states a month and
stays ``2017-05``; ``Status: Released to select customers`` states no date at
all, so the build is published with an unknown GA rather than an invented one.
A build the vendor says "won't be released" is not a release: it is excluded
with the vendor's own sentence as the reason, and the row is still accounted
for.

**A conflict is published, not resolved.** The Lifecycle page's prose retires
"all 1.x versions" on August 31, 2022 while its own *Releases* row ends
``Version 1.x`` at the instant ``9/1/2022 6:59:59 AM`` Pacific, and one build's
own section on the history page says it "was retired on August 31, 2022" too.
Three statements are not one resolved claim, so no normalized ``eol`` is
published for the family or its builds while every statement is stored verbatim
and the disagreement is reported. The same applies to the Lifecycle family start
(``Version 2.x`` on 9/30/2021) sitting after the release history's first 2.x
build (2.0.3.0 on 7/20/2021): both scopes are published as their own row and
neither overwrites the other.

**Nothing here is derived.** Every published date is a date the vendor's own row
states (``labels`` records the two column labels that were mapped); the 12-month
retirement rule and the September 30, 2026 synchronization cut-off are
published as the vendor's rules, never converted into a date on their own.
A release that does carry ``milestone_provenance`` — a derived date admitted by
``engine.derived`` — is preserved through a refresh and re-derived offline by
``validate_record``, so this collector cannot publish a derived date it cannot
recompute.

Only Microsoft Entra Connect is in scope. **Microsoft Entra Connect Health is a
different product** with its own role-specific agents and no per-agent support
dates, so no Health version is published here and no Health release id is ever
an alias for one of these builds.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path

from . import derived, net, sources, transaction
from .importer import ROOT

# The registry owns the id and the pages: a record's provenance must name a
# source this checkout installs, and the report must name the pages it read.
SOURCE = sources.source("import-entra-connect")
VERIFIER = SOURCE.verifier
REPORT = SOURCE.report
RECORD_SCHEMA = "https://zarguell.github.io/eoltracker/v1/schema/product.json"
PRODUCT_ID = "microsoft-entra-connect"
PRODUCT_NAME = "Microsoft Entra Connect"
UPSTREAM_CATEGORY = "server-app"
PAGES = SOURCE.pages
if len(PAGES) != 3:
    raise ValueError("Microsoft Entra Connect registers exactly three source pages")
LIFECYCLE_URL, HISTORY_URL, ARCHIVE_URL = (page.url for page in PAGES)

# The channel each row was read from: the heading that introduces the table, or
# the page's own heading for a page whose inventory is headings rather than a
# table. The value is stored on every release and is what validation dispatches
# on offline, so a stored row is always re-derived by the mapping that read it.
LIFECYCLE_TABLE = "Releases"
SUPPORT_TABLE = "Retiring Microsoft Entra Connect 2.x versions"
HISTORY_TABLE = "Microsoft Entra Connect: Version release history"
ARCHIVE_TABLE = "Microsoft Entra Connect: Version release history archive"
# Which page each channel's rows were read from; a report quotes the page a row
# came from, and validation needs the reverse direction to re-read it.
PAGE_OF = {LIFECYCLE_TABLE: LIFECYCLE_URL, SUPPORT_TABLE: HISTORY_URL,
           HISTORY_TABLE: HISTORY_URL, ARCHIVE_TABLE: ARCHIVE_URL}
# The columns each source channel declares, in the order the vendor states them.
LISTING_HEADERS = ("Listing", "Start Date", "Retirement Date")
LIFECYCLE_HEADERS = ("Version", "Start Date", "End Date")
SUPPORT_HEADERS = ("Version", "End of support date", "Release date")
# A section's own retirement sentence: the vendor's prose evidence for a build,
# retained as its own cell because it is one of the conflicting 1.x statements.
RETIREMENT_CELL = "Retirement notice"

# A build number, and a Lifecycle family scope. Only these two shapes are
# releases: anything else on these pages is prose.
BUILD = re.compile(r"\d+(?:\.\d+){2,}")
FAMILY = re.compile(r"Version (\d+)\.x")
# A Pacific timestamp the Lifecycle page prints beside a family scope.
STAMP = re.compile(r"(\d{1,2})/(\d{1,2})/(\d{4}) (\d{1,2}):(\d{2}):(\d{2}) (AM|PM)")
# The status line forms the release-history pages publish, widest first: a
# day-precision date, then a month. Anything else is a reshaped line.
DATE_FORMS = (
    (re.compile(r"\d{1,2}/\d{1,2}/\d{4}"), "day"),
    (re.compile(r"\d{1,2} [A-Za-z]+\.? \d{4}"), "day"),
    (re.compile(r"[A-Za-z]+\.? \d{1,2}(?:st|nd|rd|th)?,? \d{4}"), "day"),
    (re.compile(r"[A-Za-z]+\.? \d{4}"), "month"),
)
# The one status line the vendor publishes without any date.
NO_DATE_STATUS = ("Released to select customers",)
# The Lifecycle listing's retirement cell states an open status, not a date, so
# the product row contributes no deadline of its own.
IN_SUPPORT = ("In Support",)
MONTHS = {name: index for index, names in enumerate(
    (("january", "jan"), ("february", "feb"), ("march", "mar"), ("april", "apr"),
     ("may",), ("june", "jun"), ("july", "jul"), ("august", "aug"),
     ("september", "sep", "sept"), ("october", "oct"), ("november", "nov"),
     ("december", "dec")), start=1) for name in names}
WITHDRAWN = "won't be released"


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


class _Content(HTMLParser):
    """The page's main content as ordered blocks: headings, paragraphs, tables.

    Only the ``<main>`` region is read, so the navigation, feedback and the
    machine-readable JSON the site embeds around it can never be mistaken for a
    source row. Text is collected through a frame stack rather than one flat
    buffer, because the vendor nests markup inside table cells
    (``<td><p>…</p></td>``): the inner text belongs to the cell it sits in, so a
    paragraph inside a cell can never escape as a release-status block, and a
    nested list or table inside a cell cannot become a section body.
    """

    # Elements that separate their own text from a sibling's, so a cell holding
    # a nested list never joins two words into one.
    BLOCK = ("h1", "h2", "h3", "h4", "p")
    BREAK = ("li", "p", "div", "br", "tr", "td", "th", "ul", "ol", "h1", "h2",
             "h3", "h4", "table")

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.blocks = []
        self._main = 0
        self._skip = 0
        self._frames = []
        self._table = None
        self._row = None

    def _open(self, kind, level=None):
        self._frames.append({"kind": kind, "level": level, "text": []})

    def _close(self, kind):
        """Close the innermost frame, which must be of *kind*."""
        if not self._frames or self._frames[-1]["kind"] != kind:
            return
        frame = self._frames.pop()
        text = " ".join("".join(frame["text"]).split())
        if kind == "cell":
            self._row.append(text)
        elif text:
            self.blocks.append({"kind": kind, "level": frame["level"], "text": text})

    def _inner(self):
        """True when the current frame is nested inside a table cell."""
        return any(frame["kind"] == "cell" for frame in self._frames)

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self._skip += 1
        elif self._skip:
            return
        elif tag == "main":
            self._main += 1
        elif not self._main:
            return
        elif tag == "table":
            if self._table is not None:
                raise ValueError("Nested table in Microsoft lifecycle page")
            self._table = {"rows": []}
        elif self._table is not None and tag == "tr":
            self._row = []
        elif self._table is not None and tag in ("th", "td"):
            self._open("cell")
        elif tag in self.BLOCK and not self._inner():
            self._open("heading" if tag[0] == "h" else "p", int(tag[1]) if tag[0] == "h" else None)
        elif tag in self.BREAK and self._frames:
            # A nested list or paragraph inside a cell separates its own text
            # from a sibling's, so a cell never joins two words into one.
            self._frames[-1]["text"].append(" ")

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self._skip = max(0, self._skip - 1)
        elif self._skip:
            return
        elif tag == "main":
            self._main = max(0, self._main - 1)
        elif not self._main:
            return
        elif tag in ("th", "td"):
            self._close("cell")
        elif tag == "tr" and self._row is not None:
            if any(self._row):
                self._table["rows"].append(self._row)
            self._row = None
        elif tag == "table" and self._table is not None:
            rows = self._table["rows"]
            if rows:
                self.blocks.append({"kind": "table", "header": rows[0], "rows": rows[1:]})
            self._table = None
        elif tag in self.BLOCK:
            self._close("heading" if tag[0] == "h" else "p")

    def handle_data(self, data):
        # Text belongs to the innermost open frame: a paragraph inside a cell
        # appends to that cell, so its text never escapes as a block.
        if self._main and not self._skip and self._frames:
            self._frames[-1]["text"].append(data)


def content(html, where):
    """The page's blocks, with its own single title checked before anything is read."""
    parser = _Content()
    parser.feed(html)
    parser.close()
    blocks = parser.blocks
    titles = [block["text"] for block in blocks
              if block["kind"] == "heading" and block["level"] == 1]
    if len(titles) != 1:
        raise ValueError(f"{where}: page states {len(titles)} top-level headings, expected one")
    return blocks


def heading(blocks):
    """The page's own h1, the one title `content` already checked."""
    return next(block["text"] for block in blocks
                if block["kind"] == "heading" and block["level"] == 1)


def tables(blocks):
    """Every table in the page with the heading that introduces it."""
    found, current = [], None
    for block in blocks:
        if block["kind"] == "heading":
            current = block["text"]
        elif block["kind"] == "table":
            found.append((current, block))
    return found


def only_table(blocks, where, name, headers):
    """The one table introduced by *name* with exactly *headers*."""
    found = [table for title, table in tables(blocks) if title == name]
    if len(found) != 1:
        raise ValueError(f"{where}: expected one table under {name!r}, found {len(found)}")
    table = found[0]
    if tuple(table["header"]) != headers:
        raise ValueError(f"{where}: {name!r} columns changed: {table['header']}")
    if not table["rows"]:
        raise ValueError(f"{where}: {name!r} table is empty")
    for row in table["rows"]:
        if len(row) != len(headers):
            raise ValueError(f"{where}: {name!r} row width changed: {row}")
    return table


def sections(blocks):
    """The page's heading sections: ``[(heading, level, [blocks until the next peer])]``.

    A section runs from its heading to the next heading at the same or a
    shallower level, so a section's own subsections (``Release status``,
    ``Bug fixes``) stay inside it and the status line the vendor prints under a
    subsection is still found from the build heading it belongs to.
    """
    found = []
    for index, block in enumerate(blocks):
        if block["kind"] != "heading":
            continue
        body = []
        for following in blocks[index + 1:]:
            if following["kind"] == "heading" and following["level"] <= block["level"]:
                break
            body.append(following)
        found.append((block["text"], block["level"], body))
    return found


def paragraphs(blocks):
    return [block["text"] for block in blocks if block["kind"] == "p"]


def statement(blocks, needle, where):
    """The one paragraph on the page that carries *needle*, verbatim.

    The vendor's own sentences are quoted in the published report, so a page
    that no longer states one of them is a source change to review rather than
    a sentence to keep printing from memory.
    """
    found = [text for text in paragraphs(blocks) if needle in text]
    if len(found) != 1:
        raise ValueError(f"{where}: expected one statement containing {needle!r}, "
                         f"found {len(found)}")
    return found[0]


def _month(name, where):
    number = MONTHS.get(name.lower().rstrip("."))
    if number is None:
        raise ValueError(f"{where}: unrecognized month name {name!r}")
    return number


def _day(year, month, day, where):
    try:
        return date(int(year), int(month), int(day)).isoformat()
    except ValueError as error:
        raise ValueError(f"{where}: not a real calendar day: {year}-{month}-{day}") from error


def date_cell(text, where):
    """One lifecycle date cell at the width it states: a day, a month, or none.

    A blank cell states no date; a cell written any other way is a reshaped
    table and fails the parse rather than being read as a date it does not
    state. No day is ever padded onto a month.
    """
    value = text.strip()
    if not value:
        return None
    match = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{4})", value)
    if match:
        return _day(match.group(3), match.group(1), match.group(2), where)
    match = re.fullmatch(r"(\d{1,2}) ([A-Za-z]+)\.? (\d{4})", value)
    if match:
        return _day(match.group(3), _month(match.group(2), where), match.group(1), where)
    match = re.fullmatch(r"([A-Za-z]+)\.? (\d{1,2})(?:st|nd|rd|th)?,? (\d{4})", value)
    if match:
        return _day(match.group(3), _month(match.group(1), where), match.group(2), where)
    match = re.fullmatch(r"([A-Za-z]+)\.? (\d{4})", value)
    if match:
        return f"{match.group(2)}-{_month(match.group(1), where):02d}"
    raise ValueError(f"{where}: unrecognized lifecycle date cell {text!r}")


def _strip_label(body):
    """Drop a leading release-status label only when a status statement follows it.

    The vendor writes the line with a label (``Release status``, ``Status``,
    ``Released``), with or without a colon, or as a bare ``<date>: <what
    happened>`` paragraph. ``Released to select customers`` begins with a label
    word too, so the label is dropped only when what remains is a date, the
    vendor's one undated status, or its withdrawal notice.
    """
    match = re.match(r"^(?:Release status|Status|Released)\b\s*:?\s*", body)
    if match is None:
        return body
    rest = body[match.end():].strip()
    if rest in NO_DATE_STATUS or rest.startswith(WITHDRAWN) or _date_prefix(rest) is not None:
        return rest
    return body


def _date_prefix(body):
    """The leading date form *body* states, or ``None`` when it states none."""
    for pattern, _ in DATE_FORMS:
        match = pattern.match(body)
        if match is not None:
            return match
    return None


def status_cell(text, where):
    """The date a release-status line states, and whether the build was withdrawn.

    Returns ``(value, withdrawn)``: ``value`` is the stated day or month at the
    width the line gives, or ``None`` for the one line the vendor publishes
    without a date. A line that says the build won't be released is reported as
    withdrawn — the row is an exclusion, never a release with an invented GA.
    """
    body = _strip_label(text.strip())
    if body.startswith(WITHDRAWN):
        return None, True
    if body in NO_DATE_STATUS:
        return None, False
    match = _date_prefix(body)
    if match is None:
        raise ValueError(f"{where}: release status line states no date: {text!r}")
    rest = body[match.end():].strip()
    if rest and rest[0] not in ":,.":
        raise ValueError(f"{where}: unparsed text after the release date: {text!r}")
    return date_cell(match.group(0), where), False


def instant(text, where):
    """A Pacific timestamp cell -> ``(hour, minute, second, ISO day)``."""
    match = STAMP.fullmatch(text.strip())
    if match is None:
        raise ValueError(f"{where}: unrecognized Microsoft lifecycle timestamp {text!r}")
    hour = int(match.group(4)) % 12
    if match.group(7) == "PM":
        hour += 12
    day = _day(match.group(3), match.group(1), match.group(2), where)
    return hour, int(match.group(5)), int(match.group(6)), day


def start_day(text, where):
    """A lifecycle *start* instant -> the calendar day it names.

    The Lifecycle page prints start instants as ``<day> 8:00:00 AM`` Pacific,
    the beginning of the business day it names, so the stated day is that day.
    Any other instant is a source change to review, not a value to round.
    """
    hour, minute, second, day = instant(text, where)
    if (hour, minute, second) != (8, 0, 0):
        raise ValueError(f"{where}: unrecognized lifecycle start instant {text!r}")
    return day


def last_support_day(text, where):
    """A lifecycle *end* instant -> the last full calendar day of support.

    The vendor prints end instants as ``<day> 6:59:59 AM`` Pacific, the moment
    that day begins in Redmond, so the support the instant closes covers the day
    before it. The repository's convention for such a cell is that last full
    calendar day (the same normalizing the same Microsoft dates carry
    elsewhere); the raw cell is retained verbatim beside it.
    """
    hour, minute, second, day = instant(text, where)
    if (hour, minute, second) != (6, 59, 59):
        raise ValueError(f"{where}: unrecognized lifecycle end instant {text!r}")
    return (date.fromisoformat(day) - timedelta(days=1)).isoformat()


def retired_on(text, where):
    """The day a section's own retirement sentence states.

    The sentence is prose, so the day is extracted to be checked and reported —
    it is evidence that the 1.x question is genuinely contested, never a source
    for an ``eol`` milestone.
    """
    match = re.search(r"was retired on ([A-Z][a-z]+ \d{1,2}, \d{4})", text)
    if match is None:
        raise ValueError(f"{where}: retirement sentence states no date: {text!r}")
    return date_cell(match.group(1), where + " retirement notice")


def version_id(text, where):
    """One release identity, exactly as the vendor writes the version."""
    value = text.strip()
    family = FAMILY.fullmatch(value)
    if family is not None:
        return f"{family.group(1)}.x"
    if BUILD.fullmatch(value):
        return value
    raise ValueError(f"{where}: unrecognized Microsoft Entra Connect version {text!r}")


def supports_cell(text, where):
    """A support-table end-of-support cell -> the day it states, or none.

    The cell states its day first and the vendor's own rationale for it in
    parentheses; the rationale is retained verbatim in the raw cell and is never
    read as the date.
    """
    value = text.strip()
    if not value:
        return None
    stated = re.sub(r"\s*\(.*\)\s*$", "", value)
    if not stated:
        raise ValueError(f"{where}: end-of-support cell carries no date: {text!r}")
    return date_cell(stated, where)


def parse_lifecycle(html, where="Microsoft Lifecycle page"):
    """The Lifecycle page -> its listing row, its family releases, its 1.x notice.

    The family rows are built through `_release` here, so a reshaped start
    instant fails at the page that states it rather than later in the run.
    """
    blocks = content(html, where)
    title = heading(blocks)
    if title != "Azure Active Directory (AD) Connect":
        raise ValueError(f"{where}: page is not the Entra Connect lifecycle page: {title!r}")
    listing = only_table(blocks, where, "Support Dates", LISTING_HEADERS)
    if len(listing["rows"]) != 1:
        raise ValueError(f"{where}: the Support Dates table states {len(listing['rows'])} "
                         "product rows, expected one")
    product = dict(zip(LISTING_HEADERS, listing["rows"][0]))
    if product["Retirement Date"] not in IN_SUPPORT:
        raise ValueError(f"{where}: the product row no longer states an open status: "
                         f"{product['Retirement Date']!r}")
    table = only_table(blocks, where, LIFECYCLE_TABLE, LIFECYCLE_HEADERS)
    prose = statement(blocks, "will be retired because they include SQL Server 2012", where)
    if "On August 31, 2022, all 1.x versions" not in prose:
        raise ValueError(f"{where}: the 1.x retirement notice changed: {prose!r}")
    releases = [_release(dict(zip(LIFECYCLE_HEADERS, cells)), LIFECYCLE_TABLE)
                for cells in table["rows"]]
    return {"heading": title, "listing": product, "releases": releases, "prose": prose}


def parse_support(html, where="Microsoft Entra Connect version history"):
    """The support table's builds, the retirement rule beside them, the cut-off.

    Each row is built through `_release`, so the table's own columns and dates
    are checked here rather than trusted until a later stage.
    """
    blocks = content(html, where)
    title = heading(blocks)
    if title != HISTORY_TABLE:
        raise ValueError(f"{where}: page is not the current Entra Connect history: {title!r}")
    table = only_table(blocks, where, SUPPORT_TABLE, SUPPORT_HEADERS)
    releases = [_release(dict(zip(SUPPORT_HEADERS, cells)), SUPPORT_TABLE)
                for cells in table["rows"]]
    return {"heading": title, "releases": releases,
            "policy": statement(blocks, "retire 12 months from the date that a newer version",
                                where),
            "cutoff": statement(blocks, "will stop working on", where)}


def parse_sections(html, where, expected_title, key):
    """One release-history page's per-build releases, in page order.

    A section is a build-number heading and the one status line that follows it.
    Both pages' rows are built through `_release`, so the page's own line is
    checked here. The archive page marks a build the vendor never released, so
    that row is returned as an exclusion with the vendor's own sentence: a build
    that was never released is not a release, and its GA would be an invention.

    A section that also states a retirement in prose keeps that sentence as its
    own cell. It is evidence, not a milestone: it is one of the statements about
    the 1.x end date that the Lifecycle page states differently, so it is
    published beside the row rather than turned into an ``eol``.
    """
    blocks = content(html, where)
    title = heading(blocks)
    if title != expected_title:
        raise ValueError(f"{where}: page is not {expected_title!r}: {title!r}")
    released, excluded = [], []
    for section, level, body in sections(blocks):
        if level != 2 or not BUILD.fullmatch(section.strip()):
            continue
        lines = []
        for text in paragraphs(body):
            if _is_status(text) and text not in lines:
                lines.append(text)
        if len(lines) != 1:
            raise ValueError(f"{where}: section {section!r} states {len(lines)} different release "
                             f"status lines: {lines}")
        line = lines[0]
        if status_cell(line, f"{where}: {section}")[1]:
            excluded.append({
                "page": PAGE_OF[expected_title], "row": section, "cell": line,
                "reason": "the source states this build won't be released, so it is not a release "
                          "of the product; its changes shipped in a later build",
            })
            continue
        cells = {"Version": section, key: line}
        notice = [text for text in paragraphs(body) if "was retired on" in text]
        if len(notice) > 1:
            raise ValueError(f"{where}: section {section!r} states {len(notice)} retirement "
                             f"sentences")
        if notice:
            cells[RETIREMENT_CELL] = notice[0]
        released.append(_release(cells, expected_title))
    if not released:
        raise ValueError(f"{where}: page states no build sections")
    return {"heading": title, "releases": released, "excluded": excluded}


def _is_status(text):
    """True for a paragraph that is a release-status line rather than prose.

    The vendor writes the line either with a leading ``Release status``/``Status``
    label or as a bare ``<date>: <what happened>`` paragraph, so both forms are
    recognized. Nothing else is a status line, so an unlabelled date in prose can
    never be read as one.
    """
    if re.match(r"^(?:Release status|Status|Released)\b", text):
        return True
    return any(re.match(f"({pattern.pattern})\\s*:", text) for pattern, _ in DATE_FORMS)


def _release(cells, table):
    """One published release, re-derived from the vendor's own row cells.

    One function per source channel, dispatched on the stored table name, so a
    committed release is always rebuilt by the mapping that read it and a cell
    edited by hand can never survive validation.
    """
    where = f"{table}: {cells.get('Version')!r}"
    version = cells.get("Version")
    release_id = version_id(version, where)
    if table == SUPPORT_TABLE:
        if set(cells) != set(SUPPORT_HEADERS):
            raise ValueError(f"{where}: columns changed {sorted(cells)}")
        milestones = {"ga": date_cell(cells["Release date"], where + " release date"),
                      "eos": None, "eossec": None,
                      "eol": supports_cell(cells["End of support date"], where + " end of support")}
    elif table in (HISTORY_TABLE, ARCHIVE_TABLE):
        key = "Release status" if table == HISTORY_TABLE else "Status"
        if set(cells) - {RETIREMENT_CELL} != {"Version", key}:
            raise ValueError(f"{where}: columns changed {sorted(cells)}")
        ga, withdrawn = status_cell(cells[key], where + " status")
        if withdrawn:
            raise ValueError(f"{where}: a withdrawn build is not published")
        # A historical row states when the build shipped and nothing about when
        # it stops being supported, so eol stays unknown rather than guessed. A
        # retirement sentence is the vendor's prose evidence and stays a cell.
        if RETIREMENT_CELL in cells:
            retired_on(cells[RETIREMENT_CELL], where)
        milestones = {"ga": ga, "eos": None, "eossec": None, "eol": None}
    elif table == LIFECYCLE_TABLE:
        if set(cells) != {"Version", "Start Date", "End Date"}:
            raise ValueError(f"{where}: columns changed {sorted(cells)}")
        # Microsoft defines this Start Date as the day support starts, not the
        # build's release date. Validate and retain it, but do not relabel it
        # general availability. A stated End Date is checked below and retained
        # verbatim; the 1.x family conflict keeps its normalized milestone null.
        start_day(cells["Start Date"], where + " start date")
        if cells["End Date"]:
            instant(cells["End Date"], where + " end date")
        milestones = {"ga": None, "eos": None, "eossec": None, "eol": None}
    else:
        raise ValueError(f"{where}: unknown source channel")
    return {
        "id": release_id,
        "name": f"{PRODUCT_NAME} {version}",
        "milestones": milestones,
        "upstream": {"name": version, "cells": cells, "table": table},
    }


def conflicts(lifecycle, releases):
    """The source disagreements this record publishes instead of resolving.

    The Lifecycle page contradicts itself about the 1.x scope, and its 2.x family
    start day sits after the first 2.x build the release history states. Both are
    facts about the source, so both are reported with the statements that
    disagree rather than resolved by preferring one page's wording.
    """
    scopes = {release["id"]: release for release in lifecycle["releases"]}
    one, two = scopes.get("1.x"), scopes.get("2.x")
    if one is None or two is None:
        raise ValueError("The Lifecycle page no longer states both family scopes")
    notice = re.search(r"On ([A-Z][a-z]+ \d{1,2}, \d{4}),", lifecycle["prose"])
    if notice is None:
        raise ValueError("The 1.x retirement notice no longer states a date")
    builds = [release for release in releases
              if release["upstream"]["table"] != LIFECYCLE_TABLE
              and release["milestones"]["ga"] and release["id"].startswith("2.")]
    if not builds:
        raise ValueError("No dated Microsoft Entra Connect 2.x build was parsed")
    earliest = min(builds, key=lambda release: release["milestones"]["ga"])
    if not earliest["id"].startswith("2.0."):
        raise ValueError(f"The earliest dated 2.x build is no longer a 2.0 build: {earliest['id']}")
    family_start = start_day(two["upstream"]["cells"]["Start Date"], "Version 2.x Start Date")
    if not earliest["milestones"]["ga"] < family_start:
        raise ValueError("The 2.x family support start and the first 2.x build no longer disagree")
    contested = [release for release in releases
                 if RETIREMENT_CELL in release["upstream"]["cells"]]
    if len(contested) != 1:
        raise ValueError(f"Expected one build to carry a retirement sentence, found {len(contested)}")
    notice_one = contested[0]
    cells = notice_one["upstream"]["cells"]
    structured = one["upstream"]["cells"]
    return [
        {
            "scope": "Version 1.x eol",
            "published": None,
            "reason": ("The pages state the 1.x end date in prose and in a Pacific timestamp. "
                       "The prose names August 31 while the timestamp falls at 6:59:59 AM on "
                       "September 1; those are different printed dates even though the repository's "
                       "last-full-day boundary reads both as August 31. Every statement is stored "
                       "verbatim and the family milestone remains null until the vendor resolves "
                       "the wording."),
            "statements": [
                {"kind": "prose", "page": LIFECYCLE_URL, "quote": lifecycle["prose"],
                 "stated": date_cell(notice.group(1), "1.x retirement notice")},
                {"kind": "structured", "page": LIFECYCLE_URL, "table": LIFECYCLE_TABLE,
                 "cell": "End Date", "value": structured["End Date"],
                 "last_full_day": last_support_day(structured["End Date"],
                                                   "Version 1.x End Date")},
                {"kind": "release prose", "release": notice_one["id"], "page": HISTORY_URL,
                 "cell": RETIREMENT_CELL, "quote": cells[RETIREMENT_CELL],
                 "stated": retired_on(cells[RETIREMENT_CELL],
                                      f"{notice_one['id']} retirement notice")},
            ],
        },
        {
            "scope": f"Version 2.x family start vs {earliest['id']}",
            "published": "both, as their own records",
            "reason": ("The Lifecycle Releases row dates 2.x family support from a later day than "
                       "the release history dates the first 2.x build; a family support scope and "
                       "a build are different claims, so neither overwrites the other and both are "
                       "published."),
            "statements": [
                {"kind": "family", "release": "2.x", "page": LIFECYCLE_URL,
                 "cell": "Start Date", "value": two["upstream"]["cells"]["Start Date"],
                 "stated": family_start},
                {"kind": "release", "release": earliest["id"],
                 "page": PAGE_OF[earliest["upstream"]["table"]],
                 "cell": "Release date", "stated": earliest["milestones"]["ga"],
                 "value": (earliest["upstream"]["cells"].get("Release date")
                           or earliest["upstream"]["cells"]["Release status"])},
            ],
        },
    ]


def build(snapshot):
    """Every source row -> ``(releases, duplicate views)``; no row is dropped.

    The support table and the page's own sections describe the same 17 supported
    builds, so the table's row is the release (it states the end of support date)
    and the section's line is a duplicate view that must agree on the release
    date. The Lifecycle page's product listing row repeats the 1.x family start
    the same way. Both are counted as duplicate views, not as extra releases.
    """
    lifecycle = snapshot["lifecycle"]
    support, history, archive = snapshot["support"], snapshot["history"], snapshot["archive"]
    sections = {release["id"]: release for release in history["releases"]}
    if len(sections) != len(history["releases"]):
        raise ValueError("The release history states a build twice")
    releases, duplicates = [], []
    for release in support["releases"]:
        section = sections.get(release["id"])
        if section is None:
            raise ValueError(f"Support row {release['id']} has no section on the history page")
        if section["milestones"]["ga"] != release["milestones"]["ga"]:
            raise ValueError(f"The support table and the release history disagree on {release['id']}")
        duplicates.append({
            "row": release["id"], "page": HISTORY_URL,
            "reason": "the page's own section repeats the support-table row; the table's row is "
                      "published because it is the one that states an end of support date",
        })
    # The support table leads: it is the one listing that states an end of
    # support date, so its rows are the releases whose history sections are a
    # duplicate view of the same build.
    support_ids = {release["id"] for release in support["releases"]}
    for group, table in ((support["releases"], SUPPORT_TABLE),
                         (history["releases"], HISTORY_TABLE),
                         (archive["releases"], ARCHIVE_TABLE),
                         (lifecycle["releases"], LIFECYCLE_TABLE)):
        for release in group:
            if table == HISTORY_TABLE and release["id"] in support_ids:
                continue
            if any(existing["id"] == release["id"] for existing in releases):
                raise ValueError(f"Duplicate Microsoft Entra Connect release {release['id']}")
            releases.append(release)
    listing = lifecycle["listing"]
    one = next(release for release in lifecycle["releases"] if release["id"] == "1.x")
    if listing["Start Date"] != one["upstream"]["cells"]["Start Date"]:
        raise ValueError("The product listing row no longer repeats the 1.x family start date")
    duplicates.append({
        "row": listing["Listing"], "page": LIFECYCLE_URL,
        "reason": "the product listing row repeats the Version 1.x start date already published; "
                  "its retirement cell is the open status 'In Support', not a date",
    })
    duplicates.sort(key=lambda entry: (entry["page"], entry["row"]))
    return releases, duplicates


def snapshot(lifecycle_html, history_html, archive_html):
    """The three pages as one consistent source snapshot."""
    lifecycle = parse_lifecycle(lifecycle_html)
    support = parse_support(history_html)
    history = parse_sections(history_html, HISTORY_URL, HISTORY_TABLE, "Release status")
    archive = parse_sections(archive_html, ARCHIVE_URL, ARCHIVE_TABLE, "Status")
    combined = {"lifecycle": lifecycle, "support": support, "history": history,
                "archive": archive, "excluded": list(archive["excluded"])}
    releases, duplicates = build(combined)
    combined["releases"], combined["duplicates"] = releases, duplicates
    combined["conflicts"] = conflicts(lifecycle, releases)
    return combined


def retained(release):
    """A committed release the pages no longer state, marked as such.

    The row is republished from its own stored cells, so retention can never
    introduce a date the vendor did not publish; the marker says only that the
    current pages lack the row.
    """
    return {**release, "upstream": {**release["upstream"], "in_source": False}}


def _with_committed_provenance(fresh, committed):
    """Carry a committed derived date forward onto the row that still states it.

    A derived date is maintained beside the record by whoever admitted it, not by
    this fetch: while the vendor's own cells are byte-identical nothing the
    derivation rests on moved, so dropping the provenance would silently delete a
    published date and its disclosure. Two cases are refused rather than
    resolved: cells that changed under a derived key (the derivation's basis is
    no longer the one it was admitted against), and a vendor row that now states
    a date for a derived key with a different value (two answers, neither of
    which this fetch may pick). `validate_record` re-derives every carried entry,
    so a stale or tampered rule is refused rather than republished.
    """
    if committed is None:
        return fresh
    known = {release["id"]: release for release in committed["releases"]}
    merged = []
    for release in fresh:
        old = known.get(release["id"])
        provenance = (old or {}).get(derived.DERIVED_KEY)
        if not provenance:
            merged.append(release)
            continue
        if old["upstream"].get("cells") != release["upstream"].get("cells"):
            raise ValueError(f"release {release['id']} carries a derived "
                             f"{derived.DERIVED_KEY} but its stored source cells changed; "
                             "the derivation's basis is no longer the one it was admitted against")
        milestones = dict(release["milestones"])
        for key, entry in provenance.items():
            stated = release["milestones"][key]
            if stated is not None and stated != old["milestones"][key]:
                raise ValueError(f"release {release['id']} states {key} {stated} while its "
                                 f"committed record derives {old['milestones'][key]} from "
                                 f"{entry['method']}; the two must agree before this publishes")
            milestones[key] = stated if stated is not None else old["milestones"][key]
        merged.append({**release, "milestones": milestones, derived.DERIVED_KEY: provenance})
    return merged


def combine_releases(fresh, committed):
    """This fetch's rows plus the committed rows the pages no longer state."""
    if committed is None:
        return _sorted(fresh), []
    ids = {release["id"] for release in fresh}
    kept = [retained(release) for release in committed["releases"] if release["id"] not in ids]
    return (_sorted(_with_committed_provenance(fresh, committed) + kept),
            [{"id": release["id"], "name": release["name"],
              "reason": "the three Microsoft pages no longer state this build; the committed "
                        "row and its dates are retained"} for release in kept])


def _order(release):
    """Ascending sort key: dated before undated, then chronological, then version.

    The build numbers are compared as integers, so ``2.6.91.0`` sorts after
    ``2.6.84.0`` instead of before it alphabetically; a family scope
    (``Version 2.x``) keeps its own number and sorts before the builds of the
    same major. Callers publish with ``_sorted`` (newest first); an undated
    build carries no date, so it lands last in either direction.
    """
    ga = release["milestones"]["ga"]
    numbers = tuple(int(part) for part in re.findall(
        r"\d+", release["upstream"]["cells"]["Version"]))
    return ga is not None, ga or "", numbers


def _sorted(releases):
    """Releases newest first, with an unknown release date last."""
    return sorted(releases, key=_order, reverse=True)


def validate_record(record):
    """Rebuild every stored release from its own published cells, offline.

    A release's cells are the whole evidence: identity, name and milestones are
    re-derived from them, so a file whose dates no longer follow the row it
    stores is never published. A release carrying ``milestone_provenance`` is
    re-derived through ``engine.derived`` as well, so a derived date this
    collector cannot recompute from its own base and rule is refused here
    instead of being republished.
    """
    if (record["id"] != PRODUCT_ID or record["provenance"]["verifier"] != VERIFIER
            or record["provenance"]["source_url"] != LIFECYCLE_URL or not record["releases"]):
        raise ValueError("Invalid Microsoft Entra Connect source identity")
    ids = {release["id"] for release in record["releases"]}
    seen = set()
    for release in record["releases"]:
        upstream = release["upstream"]
        cells = upstream.get("cells")
        if not isinstance(cells, dict) or not cells:
            raise ValueError(f"{record['id']}: release {release['id']} carries no source cells")
        where = f"{record['id']}: release {release['id']}"
        expected = _release(cells, upstream.get("table"))
        if (release["id"] in seen or release["id"] != expected["id"]
                or release["name"] != expected["name"] or upstream.get("name") != expected["upstream"]["name"]
                or upstream.get("in_source") not in (None, False)):
            raise ValueError(f"{where} contradicts its stored cells")
        seen.add(release["id"])
        provenance = release.get(derived.DERIVED_KEY)
        if provenance:
            derived.validate_milestone_provenance(release["milestones"], provenance, where, ids)
        for key in ("ga", "eos", "eossec", "eol"):
            if provenance and key in provenance:
                continue
            if release["milestones"][key] != expected["milestones"][key]:
                raise ValueError(f"{where} milestones contradict its stored cells")


def record_for(releases, checked):
    """The published ``microsoft-entra-connect`` record for one complete snapshot."""
    return {
        "$schema": RECORD_SCHEMA,
        "id": PRODUCT_ID,
        "name": PRODUCT_NAME,
        "category": "software",
        "upstream_category": UPSTREAM_CATEGORY,
        # Microsoft publishes no CPE or other identifier for Entra Connect, and
        # an invented one would be a claim its pages never make.
        "identifiers": [],
        "labels": {"ga": "Release date", "eol": "End of support date"},
        "links": {"html": LIFECYCLE_URL, "release history": HISTORY_URL,
                  "release history archive": ARCHIVE_URL},
        "releases": _sorted(releases),
        "provenance": {"source_url": LIFECYCLE_URL, "verifier": VERIFIER,
                       "last_checked": checked, "upstream_modified": None},
    }


def report_for(data, releases, kept, checked):
    """The per-row accounting this source publishes beside its record.

    ``rows.seen`` counts every source row this fetch read, and the counted
    families reconcile with it exactly: each row is either published as a
    release (or retained from the committed snapshot), excluded with a reason,
    or a duplicate view of a row already published. The check below fails the
    refresh if that stops being true, so the report can never claim coverage the
    parsed pages do not show.
    """
    excluded, duplicates = data["excluded"], data["duplicates"]
    counts = {
        "lifecycle_scopes": len(data["lifecycle"]["releases"]),
        "lifecycle_listing": 1,
        "support_table": len(data["support"]["releases"]),
        "release_history": len(data["history"]["releases"]),
        "archive": len(data["archive"]["releases"]),
    }
    seen = sum(counts.values()) + len(excluded)
    fresh = len(releases) - len(kept)
    if seen != fresh + len(excluded) + len(duplicates):
        raise ValueError(f"Entra Connect row accounting does not reconcile: {seen} source rows, "
                         f"{fresh} fresh releases, {len(excluded)} excluded, "
                         f"{len(duplicates)} duplicate views")
    ga_unknown = sum(1 for release in releases if release["milestones"]["ga"] is None)
    eol_known = sum(1 for release in releases if release["milestones"]["eol"] is not None)
    return {
        "source_url": LIFECYCLE_URL,
        "verifier": VERIFIER,
        "checked_at": checked,
        "page_urls": {"lifecycle": LIFECYCLE_URL, "history": HISTORY_URL, "archive": ARCHIVE_URL},
        "record_scope": ("Microsoft Entra Connect: one software record with one release per "
                         "published build (the supported table, the current release history and the "
                         "archive) plus the Lifecycle 1.x and 2.x family scopes, each at the "
                         "precision its own row states"),
        "rows": {"seen": seen, "published": len(releases), "fresh": fresh,
                 "retained": len(kept), "excluded": len(excluded),
                 "duplicate_views": len(duplicates), **counts},
        "milestones": {"ga_stated": len(releases) - ga_unknown, "ga_unknown": ga_unknown,
                       "eol_stated": eol_known, "eol_unknown": len(releases) - eol_known},
        "excluded": excluded,
        "retained": [{"id": entry["id"], "name": entry["name"]} for entry in kept],
        "duplicates": duplicates,
        "conflicts": data["conflicts"],
        "rules": {
            "retirement": {"page": HISTORY_URL, "quote": data["support"]["policy"],
                           "note": "The vendor's stated rule for when a 2.x build retires. The "
                                   "support table states each build's date outright, so the rule "
                                   "is published as the rule and no date is derived from it."},
            "synchronization_cutoff": {
                "page": HISTORY_URL, "quote": data["support"]["cutoff"],
                "note": "A service-compatibility threshold below version 2.5.79.0, not an end of "
                        "life; the support table separately dates 2.5.79.0's own end of support."},
        },
        "total_records": 1,
        "limitations": [
            "Every published milestone is stated by the vendor's own row: no date here is "
            "derived, and the 12-month retirement rule is published as a rule, never as a date.",
            "A build whose section states only when it shipped carries no eol: Microsoft publishes "
            "no per-build end of support date for it. The archive note retiring one 1.x build "
            "('was retired on August 31, 2022') is the same 1.x question the family conflict "
            "leaves open, so it stays in the stored cell rather than becoming a milestone.",
            "Month-only archive statuses keep month precision ('Released: May 2017' is 2017-05); "
            "no day is inferred. 'Status: Released to select customers' states no date at all, so "
            "that build is published with an unknown GA.",
            "Microsoft Entra Connect Health is a separate product with role-specific agents and "
            "no per-agent support dates; no Health version is published here and no Health build "
            "is an alias for one of these releases.",
            "The 2.x family's support start and the first 2.x build's release are different "
            "vendor claims, so both are retained rather than one overwriting the other; the "
            "family support start is not relabeled general availability.",
        ],
    }


def committed_record(root):
    """The committed record, refusing one this source cannot own."""
    return transaction.committed_product_record(root, PRODUCT_ID, VERIFIER,
                                                validate_record, PRODUCT_NAME)


def import_entra_connect(directory=None):
    """Fetch the three pages and publish the ``microsoft-entra-connect`` record.

    Complete-or-nothing: the committed ownership check runs before any fetch, the
    three pages are parsed into one snapshot, and the staged catalog is validated
    before anything is written, so a parse failure, a source disagreement or a
    tampered committed record leaves every committed file untouched.
    """
    root = Path(directory) if directory is not None else ROOT / "data"
    committed = committed_record(root)
    checked = _now()
    data = snapshot(net.get_text(LIFECYCLE_URL), net.get_text(HISTORY_URL),
                    net.get_text(ARCHIVE_URL))
    releases, kept = combine_releases(data["releases"], committed)
    record = record_for(releases, checked)
    validate_record(record)
    report = report_for(data, releases, kept, checked)
    transaction.publish_product_record(record, report, root, REPORT)
    rows = report["rows"]
    return (f"imported {len(releases)} Microsoft Entra Connect releases "
            f"({rows['support_table']} supported from the table, {rows['archive'] - rows['excluded']} "
            f"archived); excluded {rows['excluded']} withdrawn build, "
            f"retained {rows['retained']} (data/{REPORT})")
