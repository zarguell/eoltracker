"""Microsoft IIS lifecycle, from Microsoft's own lifecycle and component pages.

IIS is a Windows component, so Microsoft states two different kinds of fact
about it, and this collector reads both:

* **The IIS lifecycle table** (``internet-information-services-iis``) states
  twelve dated version rows. Those rows are published exactly as the vendor
  states them: the ``End Date`` is terminal support and fills ``eol``, while
  ``eos`` and ``eossec`` stay empty (the source states no sale or
  security-support end) and ``ga`` stays empty too — the page's ``Start Date``
  is the start of *support*, not a general-availability statement, so mapping it
  into ``ga`` would publish a release date Microsoft never states.

* **The page's component statements** (the Fixed Policy FAQ and the IIS page's
  own Note) that a component receives the same support as its parent product or
  platform. That is a rule, not a date, so it is admitted only through
  ``milestone_provenance`` with ``method: support-inheritance``, and only for a
  scope Microsoft names explicitly whose parent page states a terminal date:

  - ``Internet Information Services (IIS) 10.0 is included with Windows Server
    2022`` (the IIS 10.0 tuning page). The IIS table has no Windows Server 2022
    row at all, so the current branch is published with the parent platform's
    Extended End Date.
  - the ``Web Server (IIS)`` role on Windows Server 2025 (the ServerManager
    reference monikered ``windowsserver2025-ps``), published as
    ``Web Server (IIS) on Windows Server 2025``. Microsoft states no numeric IIS
    version for that platform, so none is invented here.
  - ``IIS 10 on Windows 10 Pro`` and ``IIS 10 on Windows 10, Enterprise and
    Education``: the table states both rows with an empty End Date, and the
    page's Note names exactly those two Windows 10 lifecycles, so the blank cell
    is completed from the matching parent page's Retirement Date.

  A scope the sources leave ambiguous stays unknown: the Semi-Annual Channel row
  states no end date and names no single parent release, so it publishes with
  ``eol`` null and no provenance at all.

Every derived row keeps the raw parent cells and the exact sentences that
license it — the scope sentence on the page naming the component/platform pair,
the rule sentence on the page stating the inheritance, and the parent page's own
``Support Dates`` row — so the derivation re-derives offline from the record
alone. A derived date is never presented as vendor-stated: ``engine/derived.py``
recomputes it, the site labels it, and the day-precision feeds and the OpenEoX
export exclude it.

Microsoft prints end instants in Pacific time as ``1/10/2029 6:59:59 AM`` — the
moment support stops — so the last full supported day is the printed day minus
one, which is the day the catalog stores (Windows Server 2022's
``10/15/2031 6:59:59 AM`` is ``2031-10-14``, matching the committed
``windows-server`` record). The raw printed cell stays in the row's cells
verbatim, beside the date it produces. Any other stated time is taken as the
printed day itself.

Out of scope by their own notices, never by table position: IIS Express,
Application Request Routing, URL Rewrite, Web Deploy, the IIS administration
modules and the Web Platform Installer (whose end of support Microsoft announces
separately) are separate products and tools, and no row of the IIS lifecycle
table states them.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path

from . import derived, net, sources
from .importer import ROOT
from .transaction import committed_product_record, publish_product_record

# The registry owns the id, the pages and the report: a record's provenance must
# name a source this checkout installs, and the report must name the pages read.
SOURCE = sources.source("import-iis")
VERIFIER = SOURCE.verifier
REPORT = SOURCE.report
RECORD_SCHEMA = "https://zarguell.github.io/eoltracker/v1/schema/product.json"
PRODUCT_ID = "iis"
PRODUCT_NAME = "Internet Information Services (IIS)"
UPSTREAM_CATEGORY = "server-app"

# The pages this collector reads, in the registry's own registration order.
IIS_URL = "https://learn.microsoft.com/en-us/lifecycle/products/internet-information-services-iis"
FIXED_POLICY_URL = "https://learn.microsoft.com/en-us/lifecycle/faq/fixed-policy"
TUNING_URL = ("https://learn.microsoft.com/en-us/windows-server/administration/"
              "performance-tuning/role/web-server/tuning-iis-10")
WINDOWS_SERVER_2022_URL = "https://learn.microsoft.com/en-us/lifecycle/products/windows-server-2022"
IIS_ROLE_2025_URL = ("https://learn.microsoft.com/en-us/powershell/module/servermanager/"
                     "install-windowsfeature?view=windowsserver2025-ps")
WINDOWS_SERVER_2025_URL = "https://learn.microsoft.com/en-us/lifecycle/products/windows-server-2025"
WINDOWS_10_HOME_PRO_URL = "https://learn.microsoft.com/en-us/lifecycle/products/windows-10-home-and-pro"
WINDOWS_10_ENTERPRISE_EDUCATION_URL = (
    "https://learn.microsoft.com/en-us/lifecycle/products/windows-10-enterprise-and-education")
PAGES = (IIS_URL, FIXED_POLICY_URL, TUNING_URL, WINDOWS_SERVER_2022_URL, IIS_ROLE_2025_URL,
         WINDOWS_SERVER_2025_URL, WINDOWS_10_HOME_PRO_URL, WINDOWS_10_ENTERPRISE_EDUCATION_URL)
# The registry decides which pages a source reads; a collector reading a page the
# registry does not publish is a drift nothing else would catch.
_UNREGISTERED = [url for url in PAGES if url not in {page.url for page in SOURCE.pages}]
if _UNREGISTERED:
    raise ValueError(f"import-iis reads pages the registry does not register: {_UNREGISTERED}")

# The two tables of the IIS lifecycle page, by the columns each declares. A
# reshaped header set refuses the parse instead of letting a column be read
# under the wrong name.
SUPPORT_TABLE = "Support Dates"
RELEASES_TABLE = "Releases"
VERSION_COLUMN = "Version"
LISTING_COLUMN = "Listing"
START_COLUMN = "Start Date"
END_COLUMN = "End Date"
RELEASES_HEADERS = (VERSION_COLUMN, START_COLUMN, END_COLUMN)
SUPPORT_HEADERS = (LISTING_COLUMN, START_COLUMN, END_COLUMN)
# The lifecycle-policy sentences a parent page states about its own listing.
FIXED_POLICY_STATEMENT = "Fixed Lifecycle Policy"
MODERN_POLICY_STATEMENT = "Modern Lifecycle Policy"

# The vendor's own sentences, each required to appear verbatim as one of the
# page's own sentences: a reworded rule is a review, never a silent change to
# what licenses a derived date. Links are reduced to their text, as the page
# renders them.
POLICY_HEADING = "How is a component supported under the Fixed Lifecycle Policy?"
FIXED_POLICY_QUOTE = (
    "A component receives the same support as its parent product or platform. When a parent product "
    "or platform is in Mainstream, or Extended Support, so is the component. When a parent product "
    "or platform reaches the end of support, so does the component.")
COMPONENT_QUOTE = (
    "Internet Information Services (IIS) is a component of the Windows operating system and follows "
    "the same lifecycle.")
SCOPE_QUOTE_2022 = "Internet Information Services (IIS) 10.0 is included with Windows Server 2022."
# Microsoft's whole statement about IIS on Windows Server 2025 names the role, not
# a version; the release built from it is named after the role for that reason.
SCOPE_QUOTE_2025 = (
    "This example shows what is installed with Web Server (IIS), including all role services, on a "
    "computer named Server1.")
# The scope sentence published for each page a derived row cites.
DECLARED_SCOPE_QUOTES = {
    TUNING_URL: SCOPE_QUOTE_2022,
    IIS_ROLE_2025_URL: SCOPE_QUOTE_2025,
    IIS_URL: COMPONENT_QUOTE,
}
# A scope whose sentence states no IIS version publishes a release named after
# the role Microsoft names; pinned here so no numeric version can appear for it.
DECLARED_SCOPE_NAMES = {IIS_ROLE_2025_URL: "Web Server (IIS) on Windows Server 2025"}
# The IIS rows the table states with an empty End Date, and the parent lifecycle
# Microsoft's own Note points at for each. The row identity is the vendor's own
# version cell: a renamed cell refuses the parse rather than quietly dropping a
# scope, and a row that starts stating its own date publishes that date instead,
# because the vendor's date always wins over a derivation.
UNDATED_ROWS = (
    {"row": "IIS 10 on Windows 10 Pro",
     "parent_page": WINDOWS_10_HOME_PRO_URL, "parent_listing": "Windows 10 Home and Pro",
     "parent_end_column": "Retirement Date"},
    {"row": "IIS 10 on Windows 10, Enterprise and Education",
     "parent_page": WINDOWS_10_ENTERPRISE_EDUCATION_URL,
     "parent_listing": "Windows 10 Enterprise and Education",
     "parent_end_column": "Retirement Date"},
)
# The current platforms the lifecycle table omits entirely, and the page stating
# which IIS scope runs on each.
OMITTED_PLATFORMS = (
    {"name": "IIS 10 on Windows Server 2022", "scope_page": TUNING_URL, "scope_quote": SCOPE_QUOTE_2022,
     "parent_page": WINDOWS_SERVER_2022_URL, "parent_listing": "Windows Server 2022",
     "parent_end_column": "Extended End Date"},
    {"name": DECLARED_SCOPE_NAMES[IIS_ROLE_2025_URL], "scope_page": IIS_ROLE_2025_URL,
     "scope_quote": SCOPE_QUOTE_2025, "parent_page": WINDOWS_SERVER_2025_URL,
     "parent_listing": "Windows Server 2025", "parent_end_column": "Extended End Date"},
)
# Every scope admitted through support inheritance, and the page stating it.
PARENT_SCOPES = tuple(
    {**spec, "scope_page": spec.get("scope_page", IIS_URL),
     "scope_quote": DECLARED_SCOPE_QUOTES[spec.get("scope_page", IIS_URL)]}
    for spec in UNDATED_ROWS + OMITTED_PLATFORMS)
# The release name each scope page declares. A page whose sentence states a
# numeric IIS version names that branch; the Windows Server 2025 page states only
# the role, so its release is named after the role and never after a version.
DECLARED_SCOPE_RELEASES = {page: names for page, names in (
    (IIS_URL, tuple(spec["row"] for spec in UNDATED_ROWS)),
    *((spec["scope_page"], (spec["name"],)) for spec in OMITTED_PLATFORMS))}

# The vendor's end instant: ``1/10/2029 6:59:59 AM``, Pacific time. The time is
# the moment support stops, so the final full day of support is the day before.
INSTANT = re.compile(r"(\d{1,2})/(\d{1,2})/(\d{4})\s+(\d{1,2}):(\d{2}):(\d{2})\s*([AaPp]\.?[Mm]\.?)")
# Every clock component is bounded so an impossible time refuses instead of
# being read as a day: the hour is a 12-hour clock, the minute and second are
# 0..59. Both the value and the width are checked, so ``99:99:99`` and a
# two-digit hour both fail rather than shifting a support boundary.
CLOCK_HOURS = range(1, 13)
CLOCK_MINUTES = range(0, 60)
CLOCK_SECONDS = range(0, 60)
MERIDIEM = {"AM": 0, "PM": 12}
# Microsoft's reviewed end instant, as ``(hour, minute, second, meridiem)`` in
# 12-hour terms: the terminal day of support begins at ``6:59:59 AM`` Pacific.
# The clock is *required*: any other stated end time is an unreviewed convention
# that would move the last full day of support to a day the vendor's own
# aggregate pages do not name, so it refuses rather than defaulting to the
# printed day.
LAST_FULL_DAY = (6, 59, 59, "AM")
# A cell that states no date. None of these is a date, and none becomes one.
NO_DATE = {"", "-", "—", "n/a", "na", "tbd", "tba", "unknown"}
# The page marks ESU-eligible rows with a trailing footnote asterisk; the marker
# belongs to the page's tip, not to the version's name.
FOOTNOTE = re.compile(r"\s*\*+\s*$")
# A sentence ends at terminal punctuation followed by whitespace and the start of
# the next one; ``IIS 10.0`` and ``Windows Server 2022. It`` are both handled.
SENTENCE_BREAK = re.compile(r"(?<=[.!?])\s+(?=[\"'(A-Z])")
SLUG = re.compile(r"[^a-z0-9]+")


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _text(value):
    """One run of page text with whitespace folded, as the pages are read."""
    return " ".join(str(value).split())


class _Document(HTMLParser):
    """One Microsoft Learn page: its canonical URL, paragraphs, sections, tables.

    Cells keep the vendor's own text — a blank cell stays blank, the footnote
    asterisk stays on the version it marks — and a table keeps the heading it was
    published under, so a row is only ever read against the table it came from.
    """

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.canonical = None
        self.paragraphs = []
        self.sections = []          # [(heading, [paragraph, ...]), ...]
        self.tables = []            # [{"heading", "rows": [[cell, ...], ...]}, ...]
        self._heading = None
        self._tag = None
        self._buffer = None
        self._table = None
        self._row = None
        self._cell = None

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag == "link" and attributes.get("rel") == "canonical" and self.canonical is None:
            self.canonical = attributes.get("href")
        elif tag in ("h1", "h2", "h3") and self._cell is None:
            self._tag, self._buffer = tag, []
        elif tag == "p" and self._cell is None:
            self._tag, self._buffer = tag, []
        elif tag == "table":
            if self._table is not None:
                raise ValueError("Nested table in a Microsoft Learn page")
            self._table = {"heading": self._heading, "rows": []}
        elif tag == "tr" and self._table is not None:
            self._row = []
        elif tag in ("td", "th") and self._row is not None:
            self._cell = []
        elif tag == "br":
            target = self._cell if self._cell is not None else self._buffer
            if target is not None:
                target.append(" ")

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self._cell is not None:
            self._row.append(_text("".join(self._cell)))
            self._cell = None
        elif tag == "tr" and self._row is not None:
            self._table["rows"].append(self._row)
            self._row = None
        elif tag == "table" and self._table is not None:
            self._table["rows"] = [row for row in self._table["rows"] if any(c.strip() for c in row)]
            self.tables.append(self._table)
            self._table = None
        elif tag in ("h1", "h2", "h3") and self._tag == tag and self._buffer is not None:
            self._heading = _text("".join(self._buffer))
            self.sections.append((self._heading, []))
            self._tag, self._buffer = None, None
        elif tag == "p" and self._tag == "p" and self._buffer is not None:
            paragraph = _text("".join(self._buffer))
            self.paragraphs.append(paragraph)
            if not self.sections:
                self.sections.append((None, []))
            self.sections[-1][1].append(paragraph)
            self._tag, self._buffer = None, None

    def handle_data(self, data):
        if self._cell is not None:
            self._cell.append(data)
        elif self._buffer is not None:
            self._buffer.append(data)


class Page:
    """One fetched page: the URL it must be, and its parsed content."""

    def __init__(self, url, html):
        self.url = url
        document = _Document()
        document.feed(html)
        document.close()
        self.document = document
        if document.canonical != url:
            raise ValueError(f"{url}: the document's canonical URL is {document.canonical!r}")

    def table(self, heading, header):
        """The one table of ``heading`` declaring ``header``, as dict rows.

        A table is identified by its heading and by declaring every required
        column: a page that renames a column, or drops one, no longer matches and
        refuses the parse instead of letting a value be read under the wrong
        name. Columns the table declares beyond the required set (the parent
        platform pages also state a ``Mainstream End Date``) are carried in the
        row's own cells but read by name, never by position.
        """
        found = []
        for table in self.document.tables:
            if table["heading"] != heading or not table["rows"]:
                continue
            declared = tuple(table["rows"][0])
            if not set(header) <= set(declared):
                continue
            if len(set(declared)) != len(declared):
                raise ValueError(f"{self.url}: {heading!r} table declares a column twice")
            # The header row is the table's declaration, not one of its data rows.
            for row in table["rows"][1:]:
                if len(row) != len(declared):
                    raise ValueError(f"{self.url}: {heading!r} row has {len(row)} cells for "
                                     f"{len(declared)} columns: {row[0]!r}")
            found.append([dict(zip(declared, row)) for row in table["rows"][1:]])
        if len(found) != 1:
            raise ValueError(f"{self.url}: expected one {heading!r} table declaring {header}, "
                             f"found {len(found)}")
        return found[0]

    def states(self, quote):
        """Require the page to state ``quote`` verbatim as one of its sentences."""
        for paragraph in self.document.paragraphs:
            if paragraph == quote or quote in _sentences(paragraph):
                return quote
        raise ValueError(f"{self.url}: the page no longer states {quote!r}")

    def policy(self, listing):
        """The lifecycle policy this page states for its own listing."""
        found = [statement for statement in (FIXED_POLICY_STATEMENT, MODERN_POLICY_STATEMENT)
                 if f"{listing} follows the {statement}." in self.document.paragraphs]
        if len(found) != 1:
            raise ValueError(f"{self.url}: {listing} states {len(found)} lifecycle-policy sentences")
        return found[0]

    def support_row(self, listing, end_column):
        """One parent platform's Support Dates row, as its page states it."""
        headers = (LISTING_COLUMN, START_COLUMN, end_column)
        rows = self.table(SUPPORT_TABLE, headers)
        found = [row for row in rows if row[LISTING_COLUMN] == listing]
        if len(found) != 1:
            raise ValueError(f"{self.url}: {len(found)} {SUPPORT_TABLE} rows for {listing!r}")
        cells = found[0]
        terminal = end_day(cells[end_column], f"{self.url}: {listing} {end_column}")
        if terminal is None:
            raise ValueError(f"{self.url}: {listing} states no {end_column}; nothing can be inherited")
        product_id, release = parent_identity(self.url, listing)
        return {
            "product_id": product_id,
            "release_id": release,
            "release_name": listing,
            "milestone": "eol",
            "date": terminal,
            "source_url": self.url,
            "start": start_day(cells[START_COLUMN], f"{self.url}: {listing} {START_COLUMN}"),
            "end_column": end_column,
            "end_cell": cells[end_column],
            "table": SUPPORT_TABLE,
            "cells": cells,
            "policy": self.policy(listing),
        }

    def component_rule(self):
        """The Fixed Policy's component rule, read from its own section."""
        for heading, paragraphs in self.document.sections:
            if heading != POLICY_HEADING:
                continue
            if not paragraphs or paragraphs[0] != FIXED_POLICY_QUOTE:
                raise ValueError(f"{self.url}: the component-support answer is no longer "
                                 f"{FIXED_POLICY_QUOTE!r}")
            return FIXED_POLICY_QUOTE
        raise ValueError(f"{self.url}: the component-support section is missing")


def _sentences(text):
    """One paragraph split into the sentences it states."""
    return [sentence.strip() for sentence in SENTENCE_BREAK.split(text) if sentence.strip()]


def instant(text, where):
    """One printed ``M/D/YYYY H:MM:SS AM`` cell, as its calendar day and clock.

    Every component is bounded: the date must be a real calendar day, the hour
    a 12-hour clock value, and the minute and second 0..59. A cell like
    ``1/10/2029 99:99:99 AM`` states no instant Microsoft could print, so it
    refuses here rather than being read as the printed day.
    """
    match = INSTANT.fullmatch(text.strip())
    if match is None:
        raise ValueError(f"{where}: unrecognized Microsoft lifecycle cell {text!r}")
    month, day, year, hour, minute, second, meridiem = match.groups()
    try:
        stated_day = date(int(year), int(month), int(day))
    except ValueError as error:
        raise ValueError(f"{where}: {text!r} is not a real calendar day") from error
    # ``A.M.`` and ``AM`` are the same clock marker; the stored clock is folded.
    clock = (int(hour), int(minute), int(second), meridiem.replace(".", "").upper())
    if clock[0] not in CLOCK_HOURS or clock[1] not in CLOCK_MINUTES or clock[2] not in CLOCK_SECONDS:
        raise ValueError(f"{where}: {text!r} states an impossible support clock "
                         f"{clock[0]:02d}:{clock[1]:02d}:{clock[2]:02d} {clock[3]}")
    return stated_day, clock


def start_day(text, where):
    """A support-start cell: the printed day itself, at the stored day precision."""
    return instant(text, where)[0].isoformat()


def end_day(text, where):
    """A support-end cell: the last full day of support, or None when unstated.

    Microsoft prints the instant support stops, in Pacific time. ``6:59:59 AM``
    on the printed day means the final full day of support is the calendar day
    before it — the day the catalog stores and the day the vendor's own aggregate
    pages name. That clock is the only end convention this source has reviewed:
    any other stated end time would move the last supported day, so it refuses
    rather than being read as the printed day.
    """
    value = text.strip()
    if value.lower() in NO_DATE:
        return None
    stated_day, clock = instant(value, where)
    if clock != LAST_FULL_DAY:
        raise ValueError(f"{where}: unreviewed end-of-support clock "
                         f"{clock[0]:02d}:{clock[1]:02d}:{clock[2]:02d} {clock[3]} in {text!r}; "
                         f"Microsoft's support boundary is stated as 06:59:59 AM")
    return (stated_day - timedelta(days=1)).isoformat()


def release_id(name):
    """The stable identity of one row: the vendor's own version text, slugged."""
    text = FOOTNOTE.sub("", name).replace(" on ", " ").replace(",", "")
    return SLUG.sub("-", text.lower()).strip("-")


def release_row(cells):
    """One IIS lifecycle row, exactly as the vendor's own cells state it."""
    version = cells[VERSION_COLUMN]
    where = f"IIS {version!r}"
    return {
        "id": release_id(version),
        "name": FOOTNOTE.sub("", version),
        # The page's Start Date is the start of *support*: mapping it into `ga`
        # would publish a release date this source never states.
        "milestones": {"ga": None, "eos": None, "eossec": None,
                       "eol": end_day(cells[END_COLUMN], f"{where} {END_COLUMN}")},
        "upstream": {"name": version, "cells": cells, "table": RELEASES_TABLE},
    }


def parse_page(page):
    """The IIS lifecycle page's own rows -> ``(releases, excluded)``.

    Both of the page's tables are read, so every row it states is accounted for:
    the version rows are published, and the product-level Support Dates row —
    whose End Date cell says ``See Note`` instead of naming a date — is reported
    with its reason rather than being read as a release.
    """
    releases_table = page.table(RELEASES_TABLE, RELEASES_HEADERS)
    support_table = page.table(SUPPORT_TABLE, SUPPORT_HEADERS)
    excluded, releases, seen = [], [], set()
    for cells in support_table:
        excluded.append({
            "page": page.url, "table": SUPPORT_TABLE,
            "row": " | ".join(cells[column] for column in SUPPORT_HEADERS),
            "reason": ("the page's Support Dates row is the product-level listing, not a version "
                       "row: its End Date cell states 'See Note', a pointer to the Windows platform "
                       "lifecycles rather than a date, so no release or date is published from it")})
    for cells in releases_table:
        release = release_row(cells)
        if release["id"] in seen:
            raise ValueError(f"{page.url}: IIS row {release['id']!r} is stated twice")
        seen.add(release["id"])
        releases.append(release)
    if not releases:
        raise ValueError(f"{page.url}: the {RELEASES_TABLE} table produced no rows")
    return releases, excluded


# The identity published for each parent a row inherits from. Where the parent
# platform is a record of this catalog, its own product and release ids are
# used, so the inherited date points at the record a reader can open. A parent
# Microsoft states only as a lifecycle page (the Windows 10 lifecycles, which
# have no product-level catalog record) is named by that page's own slug — a
# verifiable identity rather than a record this catalog does not hold.
PARENT_IDENTITIES = {
    WINDOWS_SERVER_2022_URL: ("windows-server", "2022"),
    WINDOWS_SERVER_2025_URL: ("windows-server", "2025"),
}


def parent_identity(page, listing):
    """The parent's published product/release identity."""
    if page in PARENT_IDENTITIES:
        return PARENT_IDENTITIES[page]
    slug = SLUG.sub("-", page.rsplit("/", 1)[-1].split("?", 1)[0].lower()).strip("-")
    return slug, release_id(listing)


def parent_metadata(parent):
    """The raw parent row a derived release was read from, kept beside it.

    The parent's own ``Support Dates`` cells are stored verbatim, so the
    inherited date re-derives from the record alone and a reader can see the
    exact cell — including the printed instant — it came from.
    """
    return {"page": parent["source_url"], "listing": parent["release_name"],
            "end_column": parent["end_column"], "end_cell": parent["end_cell"],
            "cells": parent["cells"], "milestone": parent["milestone"], "policy": parent["policy"]}


def parent_evidence(parent):
    """The parent row's own cells and dates, published with the report."""
    return parent_metadata(parent) | {"date": parent["date"], "start": parent["start"]}


def scope_evidence(spec):
    """The published evidence that Microsoft names this IIS/platform scope."""
    return {"page": spec["scope_page"], "label": sources.source_label(spec["scope_page"]),
            "quote": spec["scope_quote"]}


def provenance(parent, rule):
    """One ``support-inheritance`` entry: the rule, the base, and the parent row."""
    return {
        "kind": derived.KIND,
        "method": "support-inheritance",
        "source_url": rule["page"],
        "quote": rule["quote"],
        "base_date": parent["date"],
        "base_label": f"{parent['release_name']} {parent['end_column']}",
        "parent": {"product_id": parent["product_id"], "release_id": parent["release_id"],
                   "release_name": parent["release_name"], "milestone": parent["milestone"],
                   "date": parent["date"], "source_url": parent["source_url"]},
    }


def rule_for(parent, policy_quote):
    """The vendor sentence that licenses inheriting from this parent.

    A parent on the Fixed Lifecycle Policy is covered by the Fixed Policy's own
    component rule. A parent on the Modern Lifecycle Policy is not, so the rule
    stored is the IIS page's statement that IIS is a Windows component and
    follows the same lifecycle — the same sentence that made Microsoft's undated
    Windows 10 rows inherit in the first place.
    """
    if parent["policy"] == FIXED_POLICY_STATEMENT:
        return {"page": FIXED_POLICY_URL, "quote": policy_quote}
    return {"page": IIS_URL, "quote": COMPONENT_QUOTE}


def complete(direct, pages):
    """The published row set: the page's rows plus the scopes Microsoft names.

    Two shapes of derived row come out of here, and the shared pipeline labels
    both as derived:

    * a row the IIS table states with an empty End Date, completed from the
      matching parent page's terminal date (``kind: undated-row``);
    * a row for a current platform the IIS table omits, published from the
      parent platform's own Support Dates row (``kind: omitted-platform``).

    A row that starts stating its own End Date is published as stated: the
    vendor's date always wins, and no derivation is attached beside it.
    """
    policy_quote = pages[FIXED_POLICY_URL].component_rule()
    pages[IIS_URL].states(COMPONENT_QUOTE)
    by_row = {release["upstream"]["name"]: release for release in direct}
    releases, changes, parents = list(direct), [], {}
    for spec in PARENT_SCOPES:
        key = (spec["parent_page"], spec["parent_listing"], spec["parent_end_column"])
        if key not in parents:
            parents[key] = pages[spec["parent_page"]].support_row(*key[1:])
        parent = parents[key]
        pages[spec["scope_page"]].states(spec["scope_quote"])
        rule = rule_for(parent, policy_quote)
        if "row" in spec:
            release = by_row.get(spec["row"])
            if release is None:
                raise ValueError(f"{IIS_URL}: the lifecycle table no longer states {spec['row']!r}; "
                                 f"its declared scope needs review")
            if release["milestones"]["eol"] is not None:
                changes.append({"id": release["id"], "name": release["name"], "kind": "undated-row",
                                "state": "stated-by-source", "date": release["milestones"]["eol"],
                                "note": "the IIS table now states this row's own End Date; the "
                                        "vendor's date is published and nothing is derived"})
                continue
            release["milestones"]["eol"] = parent["date"]
            release["upstream"] = {**release["upstream"], "scope": scope_evidence(spec),
                                   "parent": parent_metadata(parent)}
            release[derived.DERIVED_KEY] = {"eol": provenance(parent, rule)}
            changes.append({"id": release["id"], "name": release["name"], "kind": "undated-row",
                            "state": "inherited", "date": parent["date"],
                            "parent": parent_evidence(parent), "scope": scope_evidence(spec),
                            "rule": rule})
            continue
        existing = by_row.get(spec["name"])
        if existing is not None:
            # Microsoft states this platform's row itself now. The vendor's own
            # End Date wins when it states one; a stated row that is still blank
            # is completed in place, exactly like the undated rows above.
            if existing["milestones"]["eol"] is not None:
                changes.append({"id": existing["id"], "name": existing["name"],
                                "kind": "omitted-platform", "state": "stated-by-source",
                                "date": existing["milestones"]["eol"],
                                "note": "the IIS lifecycle table now states this platform's own End "
                                        "Date; the vendor's date is published and nothing is derived"})
                continue
            existing["milestones"]["eol"] = parent["date"]
            existing["upstream"] = {**existing["upstream"], "scope": scope_evidence(spec),
                                    "parent": parent_metadata(parent)}
            existing[derived.DERIVED_KEY] = {"eol": provenance(parent, rule)}
            changes.append({"id": existing["id"], "name": existing["name"],
                            "kind": "omitted-platform", "state": "inherited",
                            "date": parent["date"], "parent": parent_evidence(parent),
                            "scope": scope_evidence(spec), "rule": rule})
            continue
        if any(candidate["id"] == release_id(spec["name"]) for candidate in releases):
            raise ValueError(f"{IIS_URL}: {spec['name']!r} is published twice")
        releases.append({
            "id": release_id(spec["name"]),
            "name": spec["name"],
            # The parent's Start Date is the platform's support start, not an IIS
            # release date: it stays a raw cell and no `ga` is published from it.
            "milestones": {"ga": None, "eos": None, "eossec": None, "eol": parent["date"]},
            "upstream": {"name": spec["name"], "cells": parent["cells"], "table": parent["table"],
                         "parent": parent_metadata(parent), "scope": scope_evidence(spec)},
            derived.DERIVED_KEY: {"eol": provenance(parent, rule)},
        })
        changes.append({"id": release_id(spec["name"]), "name": spec["name"],
                        "kind": "omitted-platform", "state": "inherited", "date": parent["date"],
                        "parent": parent_evidence(parent), "scope": scope_evidence(spec),
                        "rule": rule})
    return _ordered(releases), changes, parents


def start_of(release):
    """A release's stored support start, read from its own cells."""
    return start_day(release["upstream"]["cells"][START_COLUMN],
                     f"{release['id']} {START_COLUMN}")


def _ordered(releases):
    """Newest platform first, as the vendor's own pages list their platforms."""
    return sorted(releases, key=lambda release: (start_of(release),
                                                 release["milestones"]["eol"] or "", release["id"]),
                  reverse=True)


def validate_record(record):
    """Rebuild every stored row from its own published cells, offline.

    A direct row's date must be exactly what its cells state; a row that inherits
    must carry the shared contract's entry and re-derive to the parent date its
    own stored parent row states; and no row may claim a release, sale or
    security-support date the source does not publish. The published order is
    re-derived too, so a reordered catalog fails here rather than on a page.
    """
    if record["provenance"]["verifier"] != VERIFIER:
        raise ValueError("Invalid IIS source identity")
    if record["id"] != PRODUCT_ID or record["provenance"]["source_url"] != IIS_URL:
        raise ValueError("Invalid IIS product identity")
    seen = set()
    for release in record["releases"]:
        upstream = release["upstream"]
        cells = upstream.get("cells")
        where = f"{record['id']}: release {release['id']}"
        if not isinstance(cells, dict) or not cells:
            raise ValueError(f"{where}: no stored source cells")
        if release["id"] in seen:
            raise ValueError(f"Duplicate IIS row: {where}")
        seen.add(release["id"])
        if release["id"] != release_id(upstream["name"]):
            raise ValueError(f"{where} does not name its own version cell")
        if release["name"] != FOOTNOTE.sub("", upstream["name"]):
            raise ValueError(f"{where} does not name the version it stores")
        if upstream.get("in_source") not in (None, False):
            raise ValueError(f"{where} carries an invalid retention marker")
        if any(release["milestones"][key] for key in ("ga", "eos", "eossec")):
            raise ValueError(f"{where} claims a release, sale or security-support date the IIS "
                             f"source does not publish")
        provenance = release.get(derived.DERIVED_KEY)
        if upstream["table"] == RELEASES_TABLE:
            expected = end_day(cells.get(END_COLUMN, ""), f"{where} {END_COLUMN}")
            if provenance is None:
                if release["milestones"]["eol"] != expected:
                    raise ValueError(f"{where} eol contradicts its stored cells")
                continue
            if expected is not None:
                raise ValueError(f"{where} derives an end the vendor's own cell already states")
        elif upstream["table"] == SUPPORT_TABLE:
            if provenance is None:
                raise ValueError(f"{where} claims a platform the IIS table does not state, without "
                                 f"the inheritance that licenses it")
        else:
            raise ValueError(f"{where} does not name the vendor table it came from")
        if upstream["table"] == SUPPORT_TABLE and (
                not isinstance(upstream.get("parent"), dict)
                or not {LISTING_COLUMN, START_COLUMN,
                        upstream["parent"].get("end_column")} <= set(cells)):
            raise ValueError(f"{where} does not carry its parent's declared columns")
        derived.validate_milestone_provenance(release["milestones"], provenance, where)
        entry = provenance["eol"]
        if entry["method"] != "support-inheritance" or entry["kind"] != derived.KIND:
            raise ValueError(f"{where} is not a support-inheritance entry")
        metadata = upstream.get("parent")
        if not isinstance(metadata, dict) or set(metadata) != {
                "page", "listing", "end_column", "end_cell", "cells", "milestone", "policy"}:
            raise ValueError(f"{where} does not carry the parent row it was derived from")
        if not isinstance(metadata["cells"], dict):
            raise ValueError(f"{where} does not store its parent row's cells")
        stated_parent = end_day(metadata["cells"].get(metadata["end_column"], ""),
                                f"{where} {metadata['end_column']}")
        if stated_parent is None or stated_parent != entry["parent"]["date"]:
            raise ValueError(f"{where} does not derive from the parent date its own cells state")
        if metadata["end_cell"] != metadata["cells"].get(metadata["end_column"]):
            raise ValueError(f"{where} stores a parent cell that contradicts its parent row")
        if metadata["listing"] != entry["parent"]["release_name"]:
            raise ValueError(f"{where} inherits from a parent it does not store")
        if entry["parent"]["source_url"] != metadata["page"]:
            raise ValueError(f"{where} inherits from a parent page it does not store")
        if entry["source_url"] not in {FIXED_POLICY_URL, IIS_URL}:
            raise ValueError(f"{where} cites an inheritance rule no Microsoft page states")
        if entry["quote"] != (FIXED_POLICY_QUOTE if entry["source_url"] == FIXED_POLICY_URL
                              else COMPONENT_QUOTE):
            raise ValueError(f"{where} stores an inheritance rule its page does not state")
        expected_rule = (FIXED_POLICY_URL if metadata["policy"] == FIXED_POLICY_STATEMENT else IIS_URL)
        if entry["source_url"] != expected_rule:
            raise ValueError(f"{where} cites a rule that does not cover its parent's "
                             f"{metadata['policy']!r}")
        evidence = upstream.get("scope")
        if not isinstance(evidence, dict) or set(evidence) != {"page", "label", "quote"}:
            raise ValueError(f"{where} does not carry the scope evidence for its derivation")
        if evidence["page"] not in DECLARED_SCOPE_QUOTES:
            raise ValueError(f"{where} cites a page that states no IIS scope")
        if evidence["quote"] != DECLARED_SCOPE_QUOTES[evidence["page"]]:
            raise ValueError(f"{where} stores a scope sentence its page does not state")
        if "IIS" not in evidence["quote"]:
            raise ValueError(f"{where} cites a scope sentence that names no IIS scope")
        if evidence["page"] not in DECLARED_SCOPE_RELEASES:
            raise ValueError(f"{where} cites a page that states no IIS scope")
        if release["name"] not in DECLARED_SCOPE_RELEASES[evidence["page"]]:
            raise ValueError(f"{where} names a release the scope sentence does not state")
    if record["releases"] != _ordered(record["releases"]):
        raise ValueError("IIS rows are not in platform order")


def record_for(releases, checked):
    """The published ``iis`` record for one complete lifecycle snapshot."""
    return {
        "$schema": RECORD_SCHEMA,
        "id": PRODUCT_ID,
        "name": PRODUCT_NAME,
        "category": "software",
        "upstream_category": UPSTREAM_CATEGORY,
        # Microsoft publishes no CPE for IIS, and an invented one would be a
        # claim the source does not make.
        "identifiers": [],
        # The column the direct rows' end date was read from; a derived row names
        # its own parent page and column in its stored parent metadata.
        "labels": {"eol": END_COLUMN},
        "links": {"html": IIS_URL, "releasePolicy": FIXED_POLICY_URL},
        "releases": releases,
        "provenance": {"source_url": IIS_URL, "verifier": VERIFIER,
                       "last_checked": checked, "upstream_modified": None},
    }


def committed_record(root):
    """The committed ``iis`` record, refusing one this source cannot own."""
    return committed_product_record(root, PRODUCT_ID, VERIFIER, validate_record, "Microsoft IIS")


def combine(fresh, committed):
    """The direct rows to publish when the current page no longer states some.

    A direct row missing from the current table is retained from its own stored
    cells, so a retired row's dates do not vanish from the catalog. A derived row
    is never retained: it is republished only while the pages that license it
    still state it.
    """
    if committed is None:
        return fresh, []
    ids = {release["id"] for release in fresh}
    kept = [release for release in committed["releases"]
            if release["id"] not in ids and release["upstream"].get("table") == RELEASES_TABLE
            and derived.DERIVED_KEY not in release]
    return fresh + [{**release, "upstream": {**release["upstream"], "in_source": False}}
                    for release in kept], kept


def report_for(releases, excluded, changes, parents, checked):
    """The per-row accounting this source publishes beside its record.

    ``rows.seen`` is every data row of the freshly read IIS page;
    ``rows.direct + rows.excluded`` is that same page, ``rows.published`` is the
    record's row count, and ``direct + derived + retained`` reproduces it, so no
    source row is unaccounted for and no published row appears from nowhere.
    """
    retained = [release for release in releases if release["upstream"].get("in_source") is False]
    retained_ids = {release["id"] for release in retained}
    fetched = [release for release in releases if release["id"] not in retained_ids]
    direct = [release for release in fetched if release["upstream"]["table"] == RELEASES_TABLE]
    added = [release for release in fetched if release["upstream"]["table"] == SUPPORT_TABLE]
    inherited = [release for release in fetched if derived.DERIVED_KEY in release]
    if len(releases) != len(direct) + len(added) + len(retained):
        raise ValueError("IIS published rows do not account for their own derivation")
    return {
        "source_url": IIS_URL, "verifier": VERIFIER, "checked_at": checked,
        "record_scope": ("Microsoft IIS lifecycle rows: one software record with one release per "
                         "IIS/platform scope, from the IIS lifecycle table as stated plus the "
                         "current scopes Microsoft names elsewhere, whose dates are inherited from "
                         "the parent platform and labeled derived"),
        "pages": [{"url": url, "label": sources.source_label(url)} for url in PAGES],
        "rows": {
            "seen": len(direct) + len(excluded),
            "published": len(releases),
            "direct": len(direct),
            "derived": len(added),
            "inherited": len(inherited),
            "retained": len(retained),
            "excluded": len(excluded),
        },
        "milestones": {
            "eol_stated": sum(1 for release in direct if derived.DERIVED_KEY not in release
                              and release["milestones"]["eol"] is not None),
            "eol_inherited": len(inherited),
            "eol_unknown": sum(1 for release in releases if release["milestones"]["eol"] is None),
            "ga_published": sum(1 for release in releases if release["milestones"]["ga"] is not None),
        },
        "excluded": excluded,
        "derived": changes,
        "parents": [parent_evidence(parent) for parent in parents.values()],
        "retained": [{"id": release["id"], "name": release["name"],
                      "reason": ("the current IIS lifecycle table no longer states this row; the "
                                 "committed row and its dates are retained")}
                     for release in retained],
        "total_records": 1,
        "limitations": [
            "The IIS lifecycle table omits the current Windows Server 2022 and Windows Server 2025 "
            "platforms; those releases are published from Microsoft's explicit statements about IIS "
            "on each platform, with the parent platform's terminal date inherited and labeled "
            "derived, never as a vendor-stated IIS deadline.",
            "Microsoft publishes no numeric IIS version for Windows Server 2025, so that release is "
            "named after the role Microsoft states, 'Web Server (IIS) on Windows Server 2025', and "
            "no IIS version is asserted for the platform. The platform itself is identified by the "
            "moniker of the reference the scope sentence was read from "
            "('?view=windowsserver2025-ps'), which the fetch requires to be the document's own "
            "canonical URL.",
            "The two Windows 10 rows state no End Date; their dates are inherited from the exact "
            "Windows 10 lifecycles Microsoft's own Note links, and the blank cell is kept verbatim "
            "in the row's stored cells.",
            "'IIS 10 on Windows Server (Semi-Annual Channel)' states no end date in the source and "
            "names no single parent release, so its eol stays unknown; no date is inferred from the "
            "channel's newer releases.",
            "The page's Start Date column is the start of support, never a general-availability "
            "statement, so every row publishes with ga absent while the raw cell stays visible.",
            "The footnote tip about Extended Security Updates ('up to an additional three years') is "
            "a program description, not a date, and is never added to any milestone.",
            "Microsoft prints end instants in Pacific time; a printed 6:59:59 AM instant is read as "
            "support through the previous full calendar day, which is the day stored, and the raw "
            "cell is retained verbatim beside it.",
            "IIS Express, Application Request Routing, URL Rewrite, Web Deploy, the IIS "
            "administration modules and the Web Platform Installer are separate products and tools "
            "with their own lifecycle, and no row of the IIS lifecycle table states them.",
            "A derived date is published in the catalog and on the product page only: the shared "
            "pipeline excludes derived dates from the day-precision feeds and the OpenEoX export, "
            "with the reason stated there.",
        ],
    }


def publish_record(record, report, root):
    """Stage the record beside the committed catalog, validate, then replace it."""
    return publish_product_record(record, report, root, REPORT)


def import_iis(directory=None):
    """Fetch the Microsoft pages and publish the ``iis`` record and report.

    Complete-or-nothing: the fetched snapshot is staged beside the committed
    catalog and validated there before anything is written, so a reshaped table,
    a reworded rule or an inconsistent catalog leaves every committed file
    untouched. Ownership is checked before the first request.
    """
    root = Path(directory) if directory is not None else ROOT / "data"
    committed = committed_record(root)
    checked = _now()
    pages = {url: Page(url, net.get_text(url)) for url in PAGES}
    direct, excluded = parse_page(pages[IIS_URL])
    fresh, changes, parents = complete(direct, pages)
    releases, kept = combine(fresh, committed)
    report = report_for(_ordered(releases), excluded, changes, parents, checked)
    publish_record(record_for(_ordered(releases), checked), report, root)
    rows = report["rows"]
    return (f"imported {rows['published']} Microsoft IIS releases ({rows['direct']} direct rows, "
            f"{rows['derived']} derived from omitted platforms, {rows['inherited']} inherited); "
            f"excluded {rows['excluded']} rows, retained {rows['retained']} (data/{REPORT})")
