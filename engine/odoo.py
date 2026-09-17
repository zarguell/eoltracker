"""Odoo release-series lifecycle, at the vendor's stated precision.

Source: the vendor's own "Standard and extended support" table on
``https://www.odoo.com/documentation/master/administration/standard_extended_support.html``
(one shared document: the 17.0/18.0/19.0 doc trees render the same table).

**The table's last column is not a terminal date, and the vendor says so.** It
is headed ``End of standard support``, and the page states standard support
covers "all major versions for three years" and "includes helpdesk support, bug
fixing, and security updates", while "Beyond those three years, extended support
is subject to a mandatory additional fee and includes helpdesk support and bug
fixes (depending on feasibility)". Odoo.sh and On-premise rows the page marks in
the legend's ``Extended support`` colour therefore continue past that date with
no published end, and a known deadline followed by an announced continuation
whose end is unpublished is exactly the case that must not collapse into
``eol`` (AGENTS.md, milestone semantics). So no row fills ``eol``.

``eossec`` stays unknown too. Whether security updates stop with standard
support is the vendor's commercial policy, not a fact this table states: the
Enterprise Subscription Agreement defines its Security Updates Service over the
"Covered Versions" (the three most recently released major versions) rather than
over this column, and the page itself publishes no security-support end. A
generic ``End of standard support`` cell does not fill ``eossec``, and an
omission in one sentence is not the vendor stating an end date.

What the source does state, and what is published:

* ``ga`` — the row's ``Release date``, at the month precision the vendor writes
  (``September 2025`` -> ``2025-09``); no day is invented (rule 4).
* The ``End of standard support`` cell is validated and retained verbatim,
  never mapped. A cell the vendor qualifies as ``(planned)``, or states as a
  bound (``Before 2024``), is not a date and is not a milestone either.

Every row the table states is accounted for: the Odoo Online (SaaS)
intermediary versions the vendor publishes one per two-to-three months, the
major series, and the grouped ``Older versions`` scope, which stays one undated
scope rather than being expanded into invented releases. A series the vendor
has not released has no row, and none is synthesized.
"""
import re
from datetime import datetime, timezone
from html import unescape
from html.parser import HTMLParser
from pathlib import Path

from . import net, sources, transaction
from .importer import ROOT

# The registry owns the id and the page: a record's provenance must name a
# source this checkout installs, and the report must name the page it read.
VERIFIER = sources.source("import-odoo").verifier
SOURCE_URL = sources.ODOO_SUPPORT
REPORT = sources.source("import-odoo").report
RECORD_SCHEMA = "https://zarguell.github.io/eoltracker/v1/schema/product.json"
PRODUCT_ID = "odoo"
PRODUCT_NAME = "Odoo"
UPSTREAM_CATEGORY = "server-app"

# The page's own section heading, and the columns its table declares. The
# vendor's first header cell is empty; every row under it names the release
# scope, which this module files under "Version" so a row states the same
# columns in the same order.
TABLE = "Standard and extended support"
HEADERS = ("Version", "Odoo Online", "Odoo.sh", "On-premise", "Release date",
           "End of standard support")
GA_COLUMN = "Release date"
SUPPORT_COLUMN = "End of standard support"
PLATFORM_COLUMNS = ("Odoo Online", "Odoo.sh", "On-premise")

# The page's own legend: the marker class a platform cell carries and the term
# the legend gives it. A marker class outside this map, or a legend that no
# longer states a term, is a reshaped page that refuses the parse rather than
# being read under the wrong colour. The class is the semantic token; the glyph
# inside the span is a rendering detail that a byte-re-encoded copy of the page
# mangles, so only the class decides which term a cell carries.
LEGEND = {"text-success": "Standard support",
          "text-warning": "Extended support (mandatory extra fee)",
          "text-danger": "Not supported"}
# The one platform value that is not a legend marker.
NOT_RELEASED = "N/A"
LEGEND_TERMS = tuple(LEGEND.values()) + ("Never released for this platform",)
# A platform cell states one of the legend's own terms, or that the product was
# never released for that platform. Nothing else appears in those columns.
PLATFORM_VALUES = frozenset(LEGEND.values()) | {NOT_RELEASED}

# One row scope, exactly as the vendor writes it. A row that names something
# else is a reshaped table, not a release this module should guess at.
SCOPE = re.compile(r"(?:Odoo SaaS \d+\.\d+|Odoo \d+\.\d+|Older versions)")
MONTHS = {name.lower(): number for number, name in enumerate(
    ("January", "February", "March", "April", "May", "June", "July", "August",
     "September", "October", "November", "December"), 1)}
MONTH_YEAR = re.compile(r"([A-Za-z]+) (\d{4})")
# The vendor's own qualifiers: a date it marks planned may still move, and a
# bound is not a day. Neither is a milestone.
PLANNED = re.compile(r"[A-Za-z]+ \d{4} \(planned\)")
BOUND = re.compile(r"Before \d{4}")
# Cells that state no date at all.
NO_DATE = frozenset({"", "-", "–", "—", "n/a", "na", "tbd", "tba", "unknown"})


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


class _Tables(HTMLParser):
    """Read table cells including nested markup; reject span/layout drift."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tables = []
        self.table = None
        self.row = None
        self.cell = None
        self.marker = None

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            if self.table is not None:
                raise ValueError("Nested Odoo support table")
            self.table = []
        elif self.table is not None:
            if tag == "tr":
                self.row = []
            elif tag in ("th", "td"):
                if self.row is None or any(dict(attrs).get(key, "1") != "1"
                                           for key in ("rowspan", "colspan")):
                    raise ValueError("Unexpected Odoo support cell layout")
                self.cell = ""
                self.marker = None
            elif tag == "span" and self.cell is not None and self.marker is None:
                classes = (dict(attrs).get("class") or "").split()
                self.marker = next((name for name in classes if name in LEGEND), None)
            elif tag == "br" and self.cell is not None:
                self.cell += " "

    def handle_data(self, text):
        if self.cell is not None:
            self.cell += text

    def handle_endtag(self, tag):
        if self.table is None:
            return
        if tag in ("td", "th") and self.cell is not None:
            self.row.append({"text": " ".join(self.cell.split()), "marker": self.marker})
            self.cell = None
        elif tag == "tr" and self.row is not None:
            self.table.append(self.row)
            self.row = None
        elif tag == "table":
            self.tables.append(self.table)
            self.table = None


def cell_value(cell):
    """One cell as the page publishes it: a legend marker becomes its own term."""
    if cell["marker"] is None:
        return cell["text"]
    if not cell["text"]:
        raise ValueError("Odoo platform marker cell carries no glyph")
    return LEGEND[cell["marker"]]


def month_value(text, where):
    """One stated calendar month as ``YYYY-MM``; a qualified or bounded cell is none.

    Only the vendor's exact month-and-year form is a date. ``September 2028
    (planned)`` is a plan the vendor may move, ``Before 2024`` is a bound, and
    an empty cell states nothing: all three return None and stay in the row's
    cells. Anything else is a reshaped table and fails the parse rather than
    being read as a date it does not state.
    """
    value = " ".join(text.split())
    if value in NO_DATE or BOUND.fullmatch(value) or PLANNED.fullmatch(value):
        return None
    match = MONTH_YEAR.fullmatch(value)
    if match is None or match[1].lower() not in MONTHS:
        raise ValueError(f"{where}: unrecognized Odoo lifecycle date {text!r}")
    return f"{match[2]}-{MONTHS[match[1].lower()]:02d}"


def support_end(text, where):
    """The ``End of standard support`` cell, validated and deliberately unmapped.

    Standard support ending is not terminal support ending (see the module
    docstring), and the vendor states no end date for extended support, so this
    column is retained verbatim and never fills a milestone. Validating its
    shape still refuses a reshaped table.
    """
    month_value(text, where)
    return None


def release_id(name):
    """The stable identity of one row scope: the vendor's own name, URL-safe.

    ``Odoo 19.0`` -> ``odoo-19.0``; ``Odoo SaaS 19.4`` -> ``odoo-saas-19.4``;
    the grouped ``Older versions`` keeps its whole scope.
    """
    return re.sub(r"[^a-z0-9.]+", "-", name.lower()).strip("-")


def release_for(cells):
    """One published release row, derived from the vendor's own cells."""
    if set(cells) != set(HEADERS):
        raise ValueError("Odoo support columns changed")
    name = cells[HEADERS[0]]
    if not SCOPE.fullmatch(name):
        raise ValueError(f"Unexpected Odoo release scope: {name!r}")
    for column in PLATFORM_COLUMNS:
        if cells[column] not in PLATFORM_VALUES:
            raise ValueError(f"Unrecognized Odoo platform cell: {cells[column]!r}")
    # Validate the column that is never a milestone, so a reshaped cell is a
    # parse failure here rather than an unnoticed row.
    support_end(cells[SUPPORT_COLUMN], f"{name} {SUPPORT_COLUMN}")
    return {
        "id": release_id(name), "name": name,
        "milestones": {"ga": month_value(cells[GA_COLUMN], f"{name} {GA_COLUMN}"),
                       "eos": None, "eossec": None, "eol": None},
        "upstream": {"name": name, "cells": cells, "table": TABLE},
    }


def _declares_support_columns(rows):
    """Whether a raw table's first row is the vendor's support-table header."""
    if not rows:
        return False
    try:
        header = [cell_value(cell) for cell in rows[0]]
    except ValueError:
        # A foreign table's first row is not this source's header; only the
        # support table's own shape decides, so an unrelated table is skipped.
        return False
    return len(header) == len(HEADERS) and header[0] == "" and tuple(header[1:]) == HEADERS[1:]


def parse_releases(html):
    """Every row of the vendor's support table, in the order the page states."""
    folded = " ".join(unescape(re.sub(r"<[^>]+>", " ", html)).split())
    for term in LEGEND_TERMS:
        if term not in folded:
            raise ValueError(f"Odoo support legend no longer states {term!r}")
    parser = _Tables()
    parser.feed(html)
    parser.close()
    # The table is identified by the columns it declares, not by being the only
    # table left on the page: a second table elsewhere is not this source's
    # scope, and two tables claiming these columns are an ambiguity to refuse.
    tables = [table for table in parser.tables if _declares_support_columns(table)]
    if len(tables) != 1:
        raise ValueError("Missing or duplicate Odoo support table")
    rows = [[cell_value(cell) for cell in row] for row in tables[0]]
    header, *data = rows
    if tuple(header[1:]) != HEADERS[1:]:
        raise ValueError("Odoo support headers changed")
    if not data:
        raise ValueError("Odoo support table is empty")
    releases, seen = [], set()
    for row in data:
        if len(row) != len(HEADERS):
            raise ValueError("Odoo support row width changed")
        release = release_for(dict(zip(HEADERS, row)))
        if release["id"] in seen:
            raise ValueError("Duplicate Odoo release scope")
        seen.add(release["id"])
        releases.append(release)
    return releases


def validate_record(record):
    """Rebuild every stored release from its own published cells, offline."""
    if (record["id"] != PRODUCT_ID or record["provenance"]["verifier"] != VERIFIER
            or record["provenance"]["source_url"] != SOURCE_URL or not record["releases"]):
        raise ValueError("Invalid Odoo source identity")
    seen = set()
    for release in record["releases"]:
        upstream = release["upstream"]
        expected = release_for(upstream.get("cells", {}))
        if (release["id"] in seen or upstream.get("table") != TABLE
                or upstream.get("in_source") not in (None, False)
                or any(release[key] != expected[key] for key in ("id", "name", "milestones"))
                or upstream["name"] != expected["upstream"]["name"]):
            raise ValueError("Odoo release contradicts its stored source cells")
        seen.add(release["id"])


def qualified_rows(releases):
    """The rows whose standard-support cell is the vendor's own plan, not a date."""
    return [{"id": release["id"], "cell": release["upstream"]["cells"][SUPPORT_COLUMN],
             "reason": "the vendor marks this end of standard support as planned; a planned "
                       "date is retained as the vendor's cell and never published as a milestone"}
            for release in releases
            if PLANNED.fullmatch(release["upstream"]["cells"][SUPPORT_COLUMN])]


def unstated_support_rows(releases):
    """The rows whose standard-support cell states no date: blank, or a bound."""
    return [{"id": release["id"],
             "cells": {column: release["upstream"]["cells"][column]
                       for column in (GA_COLUMN, SUPPORT_COLUMN)},
             "reason": "the vendor's own cell is blank or a bound ('Before 2024') rather than a "
                       "date; the wording is kept and no date is invented for the row"}
            for release in releases
            if BOUND.fullmatch(release["upstream"]["cells"][SUPPORT_COLUMN])
            or release["upstream"]["cells"][SUPPORT_COLUMN] in NO_DATE]


def report_for(releases, kept, checked):
    """The per-row accounting this source publishes beside its record.

    ``rows`` counts every source row in disjoint buckets, so a row cannot be
    neither published nor accounted for: the release-date columns partition the
    rows by whether the vendor states a date, and the standard-support columns
    by what the vendor's cell states instead of a published date. The two
    partitions must each sum to the rows seen, or this report would describe a
    table other than the one just read.
    """
    planned = qualified_rows(releases)
    unstated = unstated_support_rows(releases)
    cells = [release["upstream"]["cells"][SUPPORT_COLUMN] for release in releases]
    stated_ga = sum(release["milestones"]["ga"] is not None for release in releases)
    rows = {
        "seen": len(releases), "published": len(releases) + len(kept),
        "retained": len(kept), "excluded": 0,
        # Every row has a release-date cell; these two say what it states.
        "release_date_stated": stated_ga, "release_date_unstated": len(releases) - stated_ga,
        # Every row has a standard-support cell; these three say what it states.
        "support_end_stated": len(releases) - len(planned) - len(unstated),
        "support_end_planned": len(planned), "support_end_unstated": len(unstated),
    }
    if (rows["release_date_stated"] + rows["release_date_unstated"] != rows["seen"]
            or rows["support_end_stated"] + rows["support_end_planned"]
            + rows["support_end_unstated"] != rows["seen"]):
        raise ValueError(f"Odoo row accounting does not reconcile: {cells!r}")
    return {
        "source_url": SOURCE_URL, "verifier": VERIFIER, "checked_at": checked,
        "record_scope": "Odoo release series and Odoo Online (SaaS) intermediary versions; "
                        "'Older versions' remains one grouped scope",
        "rows": rows,
        "total_records": 1, "excluded": [], "planned": planned, "unstated": unstated,
        "retained": [{"id": release["id"], "reason": "Absent from the current table; stored "
                                                     "evidence retained"} for release in kept],
        "limitations": [
            "The table's last column is 'End of standard support' only; the page states "
            "extended support continues beyond it against a mandatory fee and publishes no end "
            "for it, so eol stays unknown for every row.",
            "Whether security updates end with standard support is the vendor's commercial "
            "policy, not a statement of this table; eossec stays unknown rather than inferred.",
            "A cell the vendor marks '(planned)' is a plan it may move; it is retained as the "
            "vendor's own cell and never becomes a milestone.",
            "A cell stated as a bound ('Before 2024') is not a date; the row keeps the vendor's "
            "wording and no date is invented.",
            "Release dates carry the month the vendor states; no day is inferred.",
            "Odoo Online (SaaS) intermediary versions are released every two to three months and "
            "the vendor states they are not eligible for extended support.",
            "A release series the vendor has not published a row for is absent; no row and no "
            "date is synthesized for it.",
            "The platform columns record the vendor's own legend terms for each row; they are "
            "support statuses, not dates.",
        ],
    }


def committed_record(root):
    """The committed ``odoo`` record, refusing one this source cannot own."""
    return transaction.committed_product_record(root, PRODUCT_ID, VERIFIER,
                                                validate_record, "Odoo")


def import_odoo(directory=None):
    """Fetch the support table and publish the ``odoo`` record and its report."""
    root = Path(directory) if directory is not None else ROOT / "data"
    old = committed_record(root)
    fresh = parse_releases(net.get_text(SOURCE_URL))
    ids = {release["id"] for release in fresh}
    kept = [{**release, "upstream": {**release["upstream"], "in_source": False}}
            for release in (old["releases"] if old else []) if release["id"] not in ids]
    checked = _now()
    record = {
        "$schema": RECORD_SCHEMA,
        "id": PRODUCT_ID, "name": PRODUCT_NAME, "category": "software",
        "upstream_category": UPSTREAM_CATEGORY,
        "identifiers": [{"type": "purl", "id": "pkg:github/odoo/odoo"}],
        "labels": {"ga": GA_COLUMN},
        "links": {"html": SOURCE_URL}, "releases": fresh + kept,
        "provenance": {"source_url": SOURCE_URL, "verifier": VERIFIER,
                       "last_checked": checked, "upstream_modified": None},
    }
    report = report_for(fresh, kept, checked)
    transaction.publish_product_record(record, report, root, REPORT)
    rows = report["rows"]
    return (f"imported {rows['seen']} Odoo release scopes; retained {rows['retained']} "
            f"(data/{REPORT})")
