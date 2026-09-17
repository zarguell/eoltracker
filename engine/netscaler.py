"""NetScaler ADC firmware lifecycle, from Citrix's own product matrices.

Sources (both public, unauthenticated, server-rendered, robots-permitted):

* ``https://www.citrix.com/support/product-lifecycle/product-matrix.html`` —
  the current product matrix. Its "NetScaler ADC (formerly Citrix ADC)" tab
  carries the supported firmware lines with the dates the vendor announced.
* ``https://www.citrix.com/support/product-lifecycle/legacy-product-matrix.html``
  — the legacy matrix, whose "NetScaler ADC" tab carries the retired firmware
  lines (13.0 down to 5.x). The current matrix covers, by its own design, only
  products "that have not yet reached the end of their lifecycle", so complete
  firmware coverage reads both pages.

**EOM is not an end of life, and the vendor says so.** The vendor's lifecycle
milestones page defines End of Maintenance as the date "a specific product
release will have no further code-level maintenance" and states "After the EOM
date, Software Support Programs and Hardware Support Programs continue as
before", while End of Life is when "technical support and product downloads
will no longer be available". So EOM stays a stored cell and never fills
``eol`` or ``eossec``; ``eol`` is filled only from the matrix's EOL column,
``eos`` only from EOS, and ``eossec`` stays null because neither page
publishes a security-support-only column. The firmware release cycle
(CTX241500, a 7-year 3+3+1 model) is a policy, never a date source.

Only the two dates a firmware row states become milestones, at the day
precision the vendor writes (``08-Aug-30``): ``ga`` from the ``GA: <date>``
text inside the Version/Model cell — the only GA statement the tables make,
absent for lines that state none (13.1 FIPS, 12.1 NDcPP) — and ``eol`` from
EOL. ``N/A``/``NA``/empty cells state no date and become none. The vendor's
asterisk on 13.1's EOL ties to an SDX-14K-FIPS footnote, not to a "tentative"
marker, so it is kept verbatim in the cell and never read as a precision
qualifier.

One product (``netscaler-adc``), one release per firmware line (``14.1``,
``13.1-fips``), never per patch. Firmware and appliances are different
families the vendor itself separates into different product cells: the
MPX/SDX platform rows are appliance groups with per-group part lists, reported
here as excluded rows with their own dates and left to a hardware scope
(AGENTS.md rule 7). Every data row the two tables state is accounted:
published, or excluded with the reason it states no firmware lifecycle.
"""
import re
from datetime import date, datetime, timezone
from html.parser import HTMLParser
from pathlib import Path

from . import net, sources, transaction
from .importer import ROOT

# The registry owns the ids and the pages: a record's provenance must name a
# source this checkout installs, and the report must name the pages it read.
VERIFIER = sources.source("import-netscaler").verifier
SOURCE_URL = sources.NETSCALER_SOURCE
LEGACY_URL = sources.NETSCALER_LEGACY
REPORT = sources.source("import-netscaler").report
RECORD_SCHEMA = "https://zarguell.github.io/eoltracker/v1/schema/product.json"
PRODUCT_ID = "netscaler-adc"
PRODUCT_NAME = "NetScaler ADC"
UPSTREAM_CATEGORY = "server-app"

# The tab whose table states firmware lifecycle dates, exactly as each page
# labels it. A renamed tab is a reshaped page that refuses the parse.
CURRENT_TAB = "NetScaler ADC (formerly Citrix ADC)"
LEGACY_TAB = "NetScaler ADC"
# The columns both tables declare (the legacy page writes them with a trailing
# footnote asterisk: "NSC*", "EOL*"; the marker is the page's footnote, not
# part of the column's name, and folding below treats the two as one column).
HEADERS = ("Product/Component Name", "Version / Model", "Language", "NSC",
           "EOS", "EOM", "EOL")
# Cells that state no date. The current table uses N/A and NA interchangeably;
# the Editions and license rows use genuinely empty cells. None is a date.
NO_DATE = {"", "-", "—", "n/a", "na", "tbd", "tba", "unknown"}
# ``GA: 08-Aug-23`` inside the Version/Model cell: the only GA statement the
# tables make, and only for the lines that state one.
GA_TEXT = re.compile(r"GA:\s*(\d{1,2}-[A-Za-z]+-\d{2,4})")
# ``08-Aug-30`` and the full-month spelling the legacy table also uses
# (``01-April-23``). Two-digit years are 20xx: the matrices publish nothing
# older, and an invented century would be a claim the source does not make.
DATE = re.compile(r"(\d{1,2})-([A-Za-z]+)-(\d{2,4})\*?")
MONTHS = {name: number for number, name in enumerate(
    ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct",
     "nov", "dec"), start=1)}
MONTHS.update({"january": 1, "february": 2, "march": 3, "april": 4, "june": 6,
               "july": 7, "august": 8, "september": 9, "october": 10,
               "november": 11, "december": 12})


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _normalized(text):
    """Fold a header or value for comparison: case and punctuation removed."""
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def date_value(text, where):
    """Parse an explicitly stated calendar day, optionally carrying a footnote."""
    text = re.sub(r"\s+", " ", text or "").strip()
    if text.lower() in NO_DATE:
        return None
    match = DATE.fullmatch(text)
    if match is None:
        raise ValueError(f"{where}: unrecognized day-precision date {text!r}")
    day, month, year = int(match.group(1)), match.group(2).lower(), int(match.group(3))
    if month not in MONTHS:
        raise ValueError(f"{where}: unrecognized month in {text!r}")
    return date(2000 + year if year < 100 else year, MONTHS[month], day).isoformat()


def line_id(version):
    """The stable identity of one firmware line: its version text, slugged.

    ``14.1 (GA: 08-Aug-23)`` -> ``14.1``; ``13.1 FIPS`` -> ``13.1-fips``; the
    legacy table's grouped line ``10.0.x/10.1.x/10.5.e Admin Partition`` keeps
    its whole scope. A permalink therefore survives patch releases and the
    vendor rewording the GA note around the version.
    """
    text = re.sub(r"\s*\(GA:[^)]*\)", "", version)
    return re.sub(r"[^a-z0-9.]+", "-", text.lower()).strip("-")


def is_firmware(cells):
    """Recognize labelled firmware and the legacy matrix's blank version group.

    Blank groups also contain appliances: require a dotted firmware version,
    not a hardware model number. Keep grouped releases as one stated scope.
    """
    product = cells.get(HEADERS[0], "")
    version = cells.get(HEADERS[1], "")
    return (product == "NetScaler ADC and Gateway Firmware" or
            (not product and re.fullmatch(
                r"\d+\.(?:\d+|x)(?:\s*\(GA:[^)]*\))?", version) is not None) or
            (not product and re.fullmatch(
                r"[\d.xe, /]+Admin Partition(?:[\d.xe, /]+|and|Admin Partition)*",
                version) is not None))


class _Tabs(HTMLParser):
    """Collect each labelled tab's tables as raw rows of cell facts.

    Cells keep their ``rowspan``/``colspan`` declarations so the grid can be
    expanded the way the rendered page shows it: a product group's name is
    stated on its first row and carried over the group's remaining rows.
    """

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self._tab = None
        self._label = None
        self._table = None
        self._row = None
        self._cell = None

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        classes = attributes.get("class") or ""
        if tag == "div" and "ctx-tab" in classes.split():
            self._tab = self._tab if self._tab is not None else []
        elif tag == "span" and "tab-text" in classes:
            self._label = ""
        elif tag == "table" and self._tab is not None:
            self._table = []
        elif tag == "tr" and self._table is not None:
            self._row = []
        elif tag in ("td", "th") and self._row is not None:
            self._cell = {"text": "", "rows": int(attributes.get("rowspan") or 1),
                          "cols": int(attributes.get("colspan") or 1)}

    def handle_endtag(self, tag):
        if tag == "span" and self._label is not None:
            label = re.sub(r"\s+", " ", self._label).strip()
            self._label = None
            if label and self._tab is not None:
                self._tab.append({"label": label, "tables": []})
        elif tag == "table" and self._table is not None:
            if self._tab:
                self._tab[-1]["tables"].append(self._table)
            self._table = None
        elif tag == "tr" and self._row is not None:
            self._table.append(self._row)
            self._row = None
        elif tag in ("td", "th") and self._cell is not None:
            self._row.append(self._cell)
            self._cell = None

    def handle_data(self, data):
        if self._label is not None:
            self._label += data
        elif self._cell is not None:
            self._cell["text"] += data


def _tabs(html):
    """Every labelled tab of a matrix page, as parsed."""
    parser = _Tabs()
    parser.feed(html)
    parser.close()
    return parser._tab or []


def _table(html, label, page):
    """The one lifecycle table of the named tab; a reshaped page refuses."""
    tab = next((tab for tab in _tabs(html) if tab["label"] == label), None)
    if tab is None:
        raise ValueError(f"{page}: no {label!r} tab")
    if len(tab["tables"]) != 1:
        raise ValueError(f"{page}: the {label!r} tab states {len(tab['tables'])} tables")
    return tab["tables"][0]


def _header(table, page):
    """The table's header row, matched against this source's declared columns."""
    header = [re.sub(r"\s+", " ", cell["text"]).strip() for cell in table[0]]
    folded = [_normalized(re.sub(r"\*$", "", name)) for name in header]
    wanted = [_normalized(name) for name in HEADERS]
    if folded != wanted:
        raise ValueError(f"{page}: unexpected NetScaler table headers {header}")
    return list(HEADERS)


def _grid(table):
    """The table's data rows as ``{header: text}`` dicts, rowspan cells carried.

    A group's product cell states its text on the group's first row and is
    declared with a ``rowspan`` covering the rest; the grid carries it forward,
    so every row reads with all its columns exactly as the rendered page shows.
    A ``colspan`` cell occupies its span of columns the same way.
    """
    header = _header(table, "")
    grid, pending = [], {}
    for raw in table[1:]:
        line, col, queue = {}, 0, list(raw)
        while queue or col in pending:
            if col in pending:
                cell, remaining = pending[col]
                if remaining > 1:
                    pending[col] = (cell, remaining - 1)
                else:
                    del pending[col]
            else:
                cell = queue.pop(0)
                if cell["rows"] > 1:
                    pending[col] = (cell, cell["rows"] - 1)
            name = header[col] if col < len(header) else f"column {col}"
            line[name] = re.sub(r"\s+", " ", cell["text"]).strip()
            col += cell["cols"]
        grid.append(line)
    return grid




def parse_page(html, page):
    """One matrix page's firmware rows -> ``(releases, exclusions)``.

    Firmware lines retain unknown milestones. Platform, edition and licensing
    scopes are accounted separately, not confused with firmware versions.
    """
    tab_label = CURRENT_TAB if page == SOURCE_URL else LEGACY_TAB
    table = _table(html, tab_label, page)
    releases, excluded, seen = [], [], set()
    for cells in _grid(table):
        product = cells.get("Product/Component Name", "")
        version = cells.get("Version / Model", "")
        row = " | ".join(text for text in cells.values() if text)
        if not version:
            excluded.append({"page": page, "row": row,
                             "reason": "a product grouping row states no firmware version"})
            continue
        where = f"NetScaler {version!r}"
        if not is_firmware(cells):
            excluded.append({"page": page, "row": row,
                             "reason": "outside firmware-version scope: platform model, "
                                       "edition, licensing or other product row"})
            continue
        line = line_id(version)
        if line in seen:
            raise ValueError(f"{page}: firmware line {line!r} stated twice")
        eol = date_value(cells.get("EOL", ""), where)
        seen.add(line)
        ga_match = GA_TEXT.search(version)
        releases.append({
            "id": line,
            "name": f"NetScaler ADC {version.split('(')[0].strip()}".strip(),
            "milestones": {"ga": date_value(ga_match.group(1), where) if ga_match else None,
                           "eos": date_value(cells.get("EOS", ""), where),
                           "eossec": None,
                           "eol": eol},
            "upstream": {"name": version, "cells": cells, "table": tab_label},
        })
    return releases, excluded


def parse_releases(current_html, legacy_html):
    """Both matrix pages -> ``(releases, exclusions)``; no firmware row dropped.

    A line both pages state is a vendor contradiction and refuses the parse
    rather than silently choosing one table's values.
    """
    current, current_excluded = parse_page(current_html, SOURCE_URL)
    legacy, legacy_excluded = parse_page(legacy_html, LEGACY_URL)
    combined = {}
    for release in current + legacy:
        if release["id"] in combined:
            raise ValueError(f"NetScaler firmware line {release['id']!r} stated on "
                             f"both matrix pages")
        combined[release["id"]] = release
    if not combined:
        raise ValueError("The NetScaler matrices produced no firmware releases")
    return _ordered(list(combined.values())), current_excluded + legacy_excluded


def _ordered(releases):
    """Newest firmware line first, as the vendor's own tables list them."""
    def major(release):
        match = re.match(r"(\d+)", release["id"])
        return int(match.group(1)) if match else 0
    return sorted(releases, key=major, reverse=True)


def validate_record(record):
    """Rebuild every stored release from its own published cells, offline."""
    if record["provenance"]["verifier"] != VERIFIER:
        raise ValueError("Invalid NetScaler source identity")
    if record['id'] != PRODUCT_ID or record['provenance']['source_url'] != SOURCE_URL:
        raise ValueError("Invalid NetScaler product identity")
    seen = set()
    for release in record["releases"]:
        cells = release.get("upstream", {}).get("cells")
        if not isinstance(cells, dict) or set(cells) != set(HEADERS) or not is_firmware(cells):
            raise ValueError(f"NetScaler release without source cells: {release['id']}")
        where = f"{record['id']}: release {release['id']}"
        if release["id"] in seen:
            raise ValueError(f"Duplicate NetScaler firmware line: {where}")
        seen.add(release["id"])
        if release["id"] != line_id(cells.get("Version / Model", "")):
            raise ValueError(f"{where} does not name its own version cell")
        ga_match = GA_TEXT.search(cells.get("Version / Model", ""))
        expected_ga = date_value(ga_match.group(1), where) if ga_match else None
        if release["milestones"]["ga"] != expected_ga:
            raise ValueError(f"{where} ga contradicts its stored version cell")
        if release["milestones"]["eol"] != date_value(cells.get("EOL", ""), where):
            raise ValueError(f"{where} eol contradicts its stored cells")
        if release["milestones"]["eos"] != date_value(cells.get("EOS", ""), where):
            raise ValueError(f"{where} eos contradicts its stored cells")
        if release["milestones"]["eossec"] is not None:
            raise ValueError(f"{where} claims a security-support end the source "
                             f"does not publish")
        eom = date_value(cells.get("EOM", ""), where)
        if eom is not None and release["milestones"]["eol"] is not None and eom > release["milestones"]["eol"]:
            raise ValueError(f"{where} stores an end of life before its own "
                             f"end of maintenance")
        if release["upstream"].get("table") not in (CURRENT_TAB, LEGACY_TAB):
            raise ValueError(f"{where} does not name the vendor table it came from")


def record_for(releases, checked):
    """The published ``netscaler-adc`` record for one complete firmware snapshot."""
    return {
        "$schema": RECORD_SCHEMA,
        "id": PRODUCT_ID,
        "name": PRODUCT_NAME,
        "category": "software",
        "upstream_category": UPSTREAM_CATEGORY,
        # The vendor publishes no CPE for the firmware family, and an invented
        # one would be a claim the source does not make.
        "identifiers": [],
        "labels": {},
        "links": {"html": SOURCE_URL},
        "releases": releases,
        "provenance": {"source_url": SOURCE_URL, "verifier": VERIFIER,
                       "last_checked": checked, "upstream_modified": None},
    }


def committed_record(root):
    """The committed ``netscaler-adc`` record, refusing one this source cannot own."""
    return transaction.committed_product_record(root, PRODUCT_ID, VERIFIER,
                                                validate_record, "NetScaler")


def combine_releases(fresh, committed):
    """The complete firmware snapshot: this fetch's rows plus retained history."""
    if committed is None:
        return _ordered(fresh), []
    ids = {release["id"] for release in fresh}
    kept = [release for release in committed["releases"] if release["id"] not in ids]
    return (_ordered(fresh + kept),
            [{"id": release["id"], "name": release["name"],
              "reason": "the current NetScaler matrices do not state this firmware line; "
                        "the committed row and its dates are retained"}
             for release in kept])


def report_for(releases, excluded, kept, checked):
    """The per-row accounting this source publishes beside its record."""
    return {
        "source_url": SOURCE_URL, "legacy_url": LEGACY_URL, "verifier": VERIFIER,
        "checked_at": checked,
        "record_scope": ("NetScaler ADC firmware lines: one software record with one "
                         "release per firmware line, from the vendor's current and "
                         "legacy product matrices, at the day precision they state"),
        "rows": {"seen": len(releases) - len(kept) + len(excluded),
                 "published": len(releases) - len(kept),
                 "retained": len(kept), "excluded": len(excluded)},
        "excluded": excluded,
        "retained": kept,
        "total_records": 1,
        "limitations": [
            "EOM never fills a normalized milestone: the vendor states support programs "
            "continue after End of Maintenance, so it is kept as the vendor's own cell only.",
            "The firmware release cycle (CTX241500, 7-year 3+3+1) is a policy, never a "
            "date; stored milestones are the vendor's own stated days.",
            "The current matrix lists products not yet at end of life by its own design; "
            "retired firmware lines live on the legacy matrix page, which this source "
            "reads beside the current one.",
            "MPX/SDX platform rows carry appliance lifecycle dates and are reported as "
            "excluded rows here; they are a hardware scope, not this firmware record.",
            "The pages' 'Last updated' stamps can lag the tables; a refresh republishes "
            "whatever the tables state.",
        ],
    }


def publish_record(record, report, root):
    """Stage the record beside the committed catalog, validate, then replace it."""
    return transaction.publish_product_record(record, report, root, REPORT)


def import_netscaler(directory=None):
    """Fetch both matrices and publish the ``netscaler-adc`` record.

    Complete-or-nothing: the fetched snapshot is combined with the lines the
    source no longer states, staged beside the committed catalog and validated
    there before anything is written. A parse failure, a reshaped table or an
    inconsistent catalog leaves every committed file untouched.
    """
    root = Path(directory) if directory is not None else ROOT / "data"
    committed = committed_record(root)
    checked = _now()
    fresh, excluded = parse_releases(net.get_text(SOURCE_URL), net.get_text(LEGACY_URL))
    releases, kept = combine_releases(fresh, committed)
    report = report_for(releases, excluded, kept, checked)
    publish_record(record_for(releases, checked), report, root)
    rows = report["rows"]
    return (f"imported {rows['published']} NetScaler ADC firmware lines "
            f"({len(releases)} in the published record); excluded {rows['excluded']} rows, "
            f"retained {rows['retained']} (data/{REPORT})")
