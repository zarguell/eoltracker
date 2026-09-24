"""XenServer hypervisor lifecycle, from Citrix's and XenServer's own pages.

Sources (all public, unauthenticated, server-rendered):

* ``https://www.xenserver.com/support`` — the current product matrix. Citrix's
  current product matrix hands XenServer off to this page by name ("For XenServer
  lifecycle information please visit xenserver.com/support"), and its
  ``Product matrix`` table states the supported lines (9, 8.4) under the header
  ``Product | Version | Language | NSC | EOS | EOM & EOL | Notes``.
* ``https://www.citrix.com/support/product-lifecycle/legacy-product-matrix.html``
  — the legacy matrix. Its ''Citrix Hypervisor'' tab states 8.2 LTSR / 8.1 CR /
  8.0 CR under ``NSC | EOM | EOL | EOES``; its ''XenServer'' tab states the CR
  lines 7.6 down to 5 under ``NSC | EOS | EOM | EOL | EOES`` plus a separate
  LTSR table (7.1 LTSR); its ''XenSource XenServer'' tab states 4.1 / 4.0 / 3.2 /
  3.1 and earlier under ``NSC | EOS | EOM | EOL``. The current matrix lists, by
  its own design, only products "that have not yet reached the end of their
  lifecycle", so complete coverage reads both pages.
* ``https://support.citrix.com/external/article?articleUrl=CTX692513-...`` — the
  public support article stating "Citrix Hypervisor 8.2 Cumulative Update 1
  becomes End of Life on June 25, 2025."

**XenServer 8 and 8.4 are one line.** The vendor states "XenServer 8 is actually
version XenServer 8.4 under the hood", so the two are never published as
separate lifecycle lines. Hypervisor lines only: XenCenter, VM Tools, licensing
editions and the separate Citrix Virtual Apps and Desktops product are outside
this record, and XCP-ng is a different product with its own catalog row.

**Vendor column semantics, preserved exactly.** Each page's columns are declared
per table, because the five tables do not share one header set: the current
matrix states a single combined ``EOM & EOL`` column, the Citrix Hypervisor tab
states no ``EOS`` at all, and the CR/LTSR tables state ``EOES`` where the
XenSource table does not. Only two mappings are published:

* ``eol`` from the table's own ``EOL`` column (the current matrix's combined
  ``EOM & EOL`` cell, retained verbatim under that exact header);
* ``eos`` from the table's own ``EOS`` column, absent where the table declares
  none, so a line whose table states no sales end keeps ``eos`` null.

``NSC`` is a notice of status change, not general availability, and no parsed
table states a GA date, so ``ga`` stays null everywhere. ``EOM`` never fills a
normalized milestone: the vendor states maintenance and life separately and
defines End of Extended Support as a support-program phase, so ``EOM`` and
``EOES`` stay stored cells and ``eossec`` stays null — a generic maintenance or
extended-support end is not a security-support-only end.

One product (``xenserver``), one release per vendor line, never per patch or
per language edition: an edition-language split (6.0.0 EN/SC vs JA) whose cells
differ is published as two releases, ordered by their own language cell, and the
second appends that language to the id, so a differing end of sales is never
merged away. Every data row of every parsed table is accounted: published, or
excluded with the reason it is outside the hypervisor scope.

The terminal date of 8.2 is stated by two independent sources — the legacy
matrix row and CTX692513 — and they must agree; a disagreement refuses the
refresh rather than silently choosing one. The statement is parsed
deterministically and retained verbatim, so it can never shadow the tables.

The lifecycle records are as complete as the vendor publishes: Citrix's own
tables state no general-availability, no end-of-security-support and, for the
Citrix Hypervisor 8.2 line, no end-of-sales date, and those milestones stay
absent rather than being inferred from release cadence or a newer version.
"""
import re
from dataclasses import dataclass
from datetime import date, datetime, timezone
from html.parser import HTMLParser
from pathlib import Path

from . import net, sources, transaction
from .importer import ROOT

# The registry owns the ids and the pages: a record's provenance must name a
# source this checkout installs, and the report must name the pages it read.
SOURCE = sources.source("import-xenserver")
VERIFIER = SOURCE.verifier
CURRENT_URL = SOURCE.pages[0].url
LEGACY_URL = SOURCE.pages[1].url
STATEMENT_URL = SOURCE.pages[2].url
REPORT = SOURCE.report
RECORD_SCHEMA = "https://zarguell.github.io/eoltracker/v1/schema/product.json"
PRODUCT_ID = "xenserver"
PRODUCT_NAME = "XenServer"
UPSTREAM_CATEGORY = "os"

# The three columns every parsed table shares, as this checkout writes them.
# The current xenserver.com table writes them more briefly (``Product``,
# ``Version``) than the Citrix matrices (``Product/Component Name``,
# ``Version/Model``), so each Table names its own product, version and language
# columns and the milestone columns are read through that table's declaration.
PRODUCT = "Product/Component Name"
VERSION = "Version/Model"
LANGUAGE = "Language"
# The synthetic table identity of a line whose only remaining evidence is the
# support article (used only if the legacy matrix stops stating the 8.2 row).
STATEMENT_TABLE = "CTX692513 support article"
STATEMENT_ARTICLE = "CTX692513"

# Cells that state no date. The current table writes NA, the legacy tables N/A
# or an empty cell. None of these is a date, and none triggers a derivation.
NO_DATE = {"", "-", "—", "n/a", "na", "tbd", "tba", "unknown", "none"}
MONTH_NAMES = (("january", "jan"), ("february", "feb"), ("march", "mar"), ("april", "apr"),
               ("may", "may"), ("june", "jun"), ("july", "jul"), ("august", "aug"),
               ("september", "sep", "sept"), ("october", "oct"), ("november", "nov"),
               ("december", "dec"))
MONTHS = {name: number for number, names in enumerate(MONTH_NAMES, start=1) for name in names}
# ``08-Aug-30`` (the legacy matrices) and ``07-31-2031`` (the current matrix,
# whose year-width makes the month-first order unambiguous: no page states a
# 31st month). A legacy cell may carry trailing text naming the editions a date
# applies to (``30-Apr-07 XenExpress, XenServer, XenEnterprise``); the date is
# the leading, explicitly stated day and the whole cell is kept verbatim.
LEGACY_DATE = re.compile(r"(\d{1,2})-([A-Za-z]+)-(\d{2,4})(?:\s+.*)?")
CURRENT_DATE = re.compile(r"(\d{2})-(\d{2})-(\d{4})")
# The one sentence CTX692513 states, matched after tags are stripped so the
# claim is read from the article's text rather than its support-shell markup.
STATEMENT = re.compile(
    r"Citrix Hypervisor 8\.2 Cumulative Update 1 becomes End of Life on "
    r"([A-Za-z]+) (\d{1,2}), (\d{4})")


@dataclass(frozen=True)
class Table:
    """One vendor table this source parses, and the semantics it declares.

    ``key`` is the stable identity stored on every release it yields, ``page``
    the URL it is read from and ``tab`` the tab it sits in (``None`` for a page
    whose table is not in a tab). ``headers`` are the columns as this checkout
    writes them, matched by folded comparison against the page's own labels
    (footnote asterisks and ``<br>`` line breaks folded away). ``eos``/``eol``
    name the columns that fill those milestones; a milestone whose column the
    table does not declare stays null rather than being read out of another
    column.
    """

    key: str
    page: str
    tab: str | None
    headers: tuple
    products: tuple
    day_format: str
    product: str = PRODUCT
    version: str = VERSION
    language: str = LANGUAGE
    eos: str | None = None
    eol: str | None = None


CORE = (PRODUCT, VERSION, LANGUAGE)
CURRENT_CORE = ("Product", "Version", "Language")
TABLES = (
    Table(key="XenServer product matrix", page=CURRENT_URL, tab=None,
          headers=CURRENT_CORE + ("NSC", "EOS", "EOM & EOL", "Notes"),
          products=("XenServer",), day_format="current",
          product="Product", version="Version", eos="EOS", eol="EOM & EOL"),
    Table(key="Citrix Hypervisor tab", page=LEGACY_URL, tab="Citrix Hypervisor",
          headers=CORE + ("NSC", "EOM", "EOL", "EOES"),
          products=("Citrix Hypervisor",), day_format="legacy", eol="EOL"),
    Table(key="XenServer tab / Current Release (CR) Lifecycle Dates", page=LEGACY_URL,
          tab="XenServer", headers=CORE + ("NSC", "EOS", "EOM", "EOL", "EOES"),
          products=("XenServer",), day_format="legacy", eos="EOS", eol="EOL"),
    Table(key="XenServer tab / Long Term Service Release (LTSR) Lifecycle Dates",
          page=LEGACY_URL, tab="XenServer", headers=CORE + ("NSC", "EOM", "EOL", "EOES", "Notes"),
          products=("XenServer",), day_format="legacy", eol="EOL"),
    Table(key="XenSource XenServer tab", page=LEGACY_URL, tab="XenSource XenServer",
          headers=CORE + ("NSC", "EOS", "EOM", "EOL"),
          products=("XenServer",), day_format="legacy", eos="EOS", eol="EOL"),
)
BY_KEY = {table.key: table for table in TABLES}
# The identity a statement-only line is accounted under in the report, so the
# per-table counts still sum to every source row when the legacy matrix's 8.2
# row is gone and the article is the line's only evidence.
STATEMENT_SPEC = Table(key=STATEMENT_TABLE, page=STATEMENT_URL, tab=None,
                       headers=("Statement",), products=(), day_format="legacy",
                       product="Statement", version="Statement", language="Statement")
# The vendor line that both the legacy matrix and CTX692513 state, as the
# legacy row's own version cell writes it.
STATED_LINE = "8.2 LTSR"


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _normalized(text):
    """Fold a header, tab label or value for comparison: punctuation removed."""
    return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()


def _spaced(text):
    """Collapse the whitespace a rendered table cell carries."""
    return re.sub(r"\s+", " ", text or "").strip()


def date_value(text, day_format, where):
    """Parse an explicitly stated calendar day; ``None`` for a cell stating none.

    The two matrices write days differently — ``08-Aug-30`` / ``30-Apr-07
    XenExpress, XenServer, XenEnterprise`` on the legacy pages and
    ``07-31-2031`` on the current one — and each table's own format is required,
    so a reshaped page refuses rather than having its columns misread.
    """
    text = _spaced(text)
    if text.lower() in NO_DATE:
        return None
    pattern = CURRENT_DATE if day_format == "current" else LEGACY_DATE
    match = pattern.fullmatch(text) if day_format == "current" else pattern.match(text)
    if match is None:
        raise ValueError(f"{where}: unrecognized day-precision date {text!r}")
    if day_format == "current":
        month_text, day_text, year = match.group(1), match.group(2), match.group(3)
        month = int(month_text)
        if not 1 <= month <= 12:
            raise ValueError(f"{where}: unrecognized month in {text!r}")
    else:
        day_text, month_text, year = match.group(1), match.group(2), match.group(3)
        month = MONTHS.get(month_text.lower())
        if month is None:
            raise ValueError(f"{where}: unrecognized month in {text!r}")
    return date(2000 + int(year) if int(year) < 100 else int(year), month, int(day_text)).isoformat()


def line_id(version):
    """The stable identity of one vendor line: its version text, slugged.

    ``7.6 CR`` -> ``7.6-cr``, ``8.2 LTSR`` -> ``8.2-ltsr``, ``6.0.2 CC`` ->
    ``6.0.2-cc``, ``3.1 and earlier`` -> ``3.1-and-earlier``. The identity is
    the vendor's own scope text, never a patch release, so a permalink survives
    a table rewording.
    """
    return re.sub(r"[^a-z0-9.]+", "-", _spaced(version).lower()).strip("-")


def _statement_date(quote):
    """Re-derive the stated day from the stored CTX692513 sentence, offline."""
    match = STATEMENT.fullmatch((quote or "").strip().rstrip("."))
    month = MONTHS.get(match.group(1).lower()) if match else None
    if month is None:
        raise ValueError(f"unrecognized CTX692513 end-of-life statement {quote!r}")
    return date(int(match.group(3)), month, int(match.group(2))).isoformat()


def _page_text(html):
    """A page's visible text, so a statement is read from prose, not markup."""
    text = re.sub(r"(?is)<(script|style)\b.*?</\1>", " ", html or "")
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = text.replace("&nbsp;", " ").replace("\u00a0", " ")
    return _spaced(text)


def parse_statement(html):
    """CTX692513's own sentence -> the retained statement, or a refusal."""
    match = STATEMENT.search(_page_text(html))
    if match is None:
        raise ValueError(f"{STATEMENT_URL}: no recognized Citrix Hypervisor 8.2 "
                         f"Cumulative Update 1 end-of-life statement")
    return {"article": STATEMENT_ARTICLE, "url": STATEMENT_URL,
            "quote": match.group(0).rstrip(".") + "."}


class _Tables(HTMLParser):
    """Every table of a page as raw rows, tagged with the tab it sits in.

    Cells keep their ``rowspan``/``colspan`` declarations so the grid can be
    expanded the way the rendered page shows it: a product group's name is
    stated on its group's first row and carried over the remaining rows.
    """

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self._tables = []
        self._table = None
        self._row = None
        self._cell = None
        self._label = None
        self._tab = None

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        classes = (attributes.get("class") or "").split()
        if tag == "span" and "tab-text" in classes:
            self._label = ""
        elif tag == "table":
            self._table = []
        elif tag == "tr" and self._table is not None:
            self._row = []
        elif tag in ("td", "th") and self._row is not None:
            self._cell = {"text": "", "rows": int(attributes.get("rowspan") or 1),
                          "cols": int(attributes.get("colspan") or 1)}

    def handle_endtag(self, tag):
        if tag == "span" and self._label is not None:
            self._tab = _spaced(self._label)
            self._label = None
        elif tag == "table" and self._table is not None:
            self._tables.append({"tab": self._tab, "rows": self._table})
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


def _tables(html):
    """Every table of a page, in document order and tagged with its tab."""
    parser = _Tables()
    parser.feed(html)
    parser.close()
    return parser._tables


def _folded_header(table):
    """The table's header row, folded for comparison, or None when it has none."""
    if not table["rows"]:
        return None
    return tuple(_normalized(re.sub(r"\*+$", "", _spaced(cell["text"])))
                 for cell in table["rows"][0])


def _find_table(tables, spec):
    """The one table of a parsed page matching this declaration's tab and columns.

    Locating by header rather than position is what keeps the two tables of the
    XenServer tab apart: the CR table declares ``EOS`` where the LTSR table
    declares ``Notes``, so neither can be read as the other. A missing or
    ambiguous match is a reshaped page that refuses the parse.
    """
    wanted = tuple(_normalized(header) for header in spec.headers)
    found = [table for table in tables
             if (spec.tab is None) == (table["tab"] is None)
             and (spec.tab is None or _normalized(table["tab"]) == _normalized(spec.tab))
             and _folded_header(table) == wanted]
    if len(found) != 1:
        raise ValueError(f"{spec.page}: {spec.key!r} matched {len(found)} tables; the page "
                         f"no longer states exactly one table with the declared columns")
    return found[0]


def _locate(current_html, legacy_html):
    """Locate each declared table by its own header set; a reshaped page refuses."""
    pages = {CURRENT_URL: _tables(current_html), LEGACY_URL: _tables(legacy_html)}
    return {spec.key: _find_table(pages[spec.page], spec) for spec in TABLES}


def _grid(table, spec):
    """The table's data rows as ``{declared header: text}`` dicts, rowspan carried.

    A group's product cell states its text on the group's first row and is
    declared with a ``rowspan`` covering the rest, so the grid carries it
    forward and every row reads with all its columns as the rendered page shows
    them. A cell the vendor leaves out entirely (the earliest lines' ``EOES``)
    is reported as the empty cell it is, never as a date read from another
    column.
    """
    grid, pending = [], {}
    for raw in table["rows"][1:]:
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
            if col < len(spec.headers):
                line[spec.headers[col]] = _spaced(cell["text"])
            col += cell["cols"]
        for header in spec.headers:
            line.setdefault(header, "")
        grid.append(line)
    return grid


def _release(spec, cells):
    """One vendor row as a release, before its id is assigned."""
    version = cells[spec.version]
    where = f"XenServer {version!r}"
    eos = date_value(cells.get(spec.eos, ""), spec.day_format, where) if spec.eos else None
    eol = date_value(cells.get(spec.eol, ""), spec.day_format, where) if spec.eol else None
    eom = date_value(cells.get("EOM", ""), spec.day_format, where) if "EOM" in spec.headers else None
    if eom is not None and eol is not None and eom > eol:
        raise ValueError(f"{where}: the vendor's own cells state end of maintenance "
                         f"after end of life")
    return {
        "id": line_id(version),
        "name": f"{PRODUCT_NAME} {version}".strip(),
        "milestones": {"ga": None, "eos": eos, "eossec": None, "eol": eol},
        "upstream": {"name": version, "cells": cells, "table": spec.key, "page": spec.page},
    }


def _rows(spec, table):
    """One located table's data rows -> ``(releases, exclusions)``, nothing dropped.

    Every source row is accounted: a row stating no version is a grouping row,
    and a row naming a product cell outside this collector's scope is excluded
    with the label it states. Both reasons are retained verbatim in the report.
    """
    releases, excluded = [], []
    for cells in _grid(table, spec):
        row = " | ".join(cells[header] for header in spec.headers)
        if not cells[spec.version]:
            excluded.append({"page": spec.page, "table": spec.key, "row": row,
                             "reason": "a product grouping row states no version"})
            continue
        if spec.products and cells[spec.product] not in spec.products:
            excluded.append({"page": spec.page, "table": spec.key, "row": row,
                             "reason": f"outside the XenServer hypervisor scope: the row's "
                                       f"product cell names {cells[spec.product]!r}"})
            continue
        releases.append(_release(spec, cells))
    return releases, excluded


def parse_table(html, spec):
    """One declared table of one page -> ``(releases, exclusions)``, nothing dropped.

    Locates the table by its declared columns and, for a tab page, its tab
    label, so a single page can be exercised without the other pages present.
    """
    return _rows(spec, _find_table(_tables(html), spec))


def _edition_ids(rows):
    """Assign each vendor row its line id: the version, plus its language edition.

    ``rows`` is a list of ``(table, version, language)`` triples in the order
    they were read; the ids come back in that same order. A version stated once
    keeps its bare version id. A version stated once per language edition is
    ordered by its own language cell — never by row order, so the ids survive
    the vendor reordering a table — and each edition after the first appends its
    language. Every row in a repeated group must state a distinguishing language,
    and a repeated language is a genuine duplicate; either refuses the parse
    rather than publishing one edition's dates twice.
    """
    groups = {}
    for index, (table, version, _) in enumerate(rows):
        groups.setdefault((table, line_id(version)), []).append(index)
    ids = [None] * len(rows)
    for (table, base), indexes in groups.items():
        if len(indexes) == 1:
            ids[indexes[0]] = base
            continue
        editions = []
        for index in indexes:
            language = line_id(rows[index][2])
            if not language:
                raise ValueError(f"{table}: version {base!r} is stated more than once "
                                 f"with no distinguishing language edition")
            editions.append((language, index))
        editions.sort()
        seen = set()
        for position, (language, index) in enumerate(editions):
            if language in seen:
                raise ValueError(f"{table}: vendor line {base!r} is stated twice")
            seen.add(language)
            ids[index] = base if position == 0 else f"{base}-{language}"
    return ids


def _id_lines(releases):
    """Give every parsed vendor line the id its own version and language state."""
    rows = [(release["upstream"]["table"],
             release["upstream"]["cells"][BY_KEY[release["upstream"]["table"]].version],
             release["upstream"]["cells"][BY_KEY[release["upstream"]["table"]].language])
            for release in releases]
    for release, assigned in zip(releases, _edition_ids(rows)):
        release["id"] = assigned
    return releases


def _find_line(releases, version):
    """The release whose own version cell states ``version``, or None."""
    return next((release for release in releases
                 if release["upstream"]["cells"].get(
                     BY_KEY[release["upstream"]["table"]].version) == version), None)


def parse_releases(current_html, legacy_html, statement_html):
    """Every parsed page -> ``(releases, exclusions, statement)``, nothing dropped.

    The CTX692513 statement is required, must agree with the legacy matrix row
    that states the same line, and is retained beside that row's cells. A
    disagreement between the two sources refuses the parse rather than choosing
    one; if the legacy row is gone the statement alone still states the line,
    under its own synthetic table identity, so the terminal date is not lost.
    """
    located = _locate(current_html, legacy_html)
    releases, excluded = [], []
    for spec in TABLES:
        table_releases, table_excluded = _rows(spec, located[spec.key])
        releases.extend(table_releases)
        excluded.extend(table_excluded)
    if not releases:
        raise ValueError("The XenServer pages produced no hypervisor releases")
    releases = _id_lines(releases)

    statement = parse_statement(statement_html)
    stated = _statement_date(statement["quote"])
    line = _find_line(releases, STATED_LINE)
    if line is None:
        # The legacy matrix no longer states the line: the support article is
        # the remaining evidence, so the line is published from it alone.
        releases.append({
            "id": line_id(STATED_LINE), "name": f"{PRODUCT_NAME} {STATED_LINE}",
            "milestones": {"ga": None, "eos": None, "eossec": None, "eol": stated},
            "upstream": {"name": STATED_LINE, "cells": {"Statement": statement["quote"]},
                         "table": STATEMENT_TABLE, "page": STATEMENT_URL,
                         "statement": statement},
        })
    else:
        if line["milestones"]["eol"] != stated:
            raise ValueError(
                f"{STATED_LINE}: the legacy matrix states end of life "
                f"{line['milestones']['eol']!r} and {STATEMENT_ARTICLE} states "
                f"{stated!r}; the two sources disagree")
        line["upstream"]["statement"] = statement
    return _ordered(releases), excluded, statement


def _ordered(releases):
    """Newest vendor line first, ties keeping the vendor's own table order."""
    def major(release):
        match = re.match(r"\d+(?:\.\d+)*", release["id"])
        return tuple(int(part) for part in match.group(0).split(".")) if match else ()
    return sorted(releases, key=major, reverse=True)


def validate_record(record):
    """Rebuild every stored release from its own published cells, offline."""
    if record["provenance"]["verifier"] != VERIFIER:
        raise ValueError("Invalid XenServer source identity")
    if record["id"] != PRODUCT_ID or record["provenance"]["source_url"] != CURRENT_URL:
        raise ValueError("Invalid XenServer product identity")
    seen, statements = set(), 0
    for release in record["releases"]:
        upstream = release.get("upstream") or {}
        cells = upstream.get("cells")
        statement = upstream.get("statement")
        where = f"{record['id']}: release {release['id']}"
        if release["id"] in seen:
            raise ValueError(f"Duplicate XenServer release line: {where}")
        seen.add(release["id"])
        if release["milestones"]["ga"] is not None:
            raise ValueError(f"{where} claims a general-availability date the vendor "
                             f"tables do not state")
        if release["milestones"]["eossec"] is not None:
            raise ValueError(f"{where} claims a security-support end the source "
                             f"does not publish")
        if statement is not None:
            statements += 1
            if _statement_date(statement.get("quote")) != release["milestones"]["eol"]:
                raise ValueError(f"{where} contradicts the {STATEMENT_ARTICLE} statement "
                                 f"it stores")
        if upstream.get("table") == STATEMENT_TABLE:
            if cells != {"Statement": (statement or {}).get("quote")}:
                raise ValueError(f"{where} does not carry the statement it was read from")
            if release["milestones"]["eos"] is not None:
                raise ValueError(f"{where} claims an end of sales no source states")
            continue
        spec = BY_KEY.get(upstream.get("table"))
        if spec is None:
            raise ValueError(f"{where} does not name the vendor table it came from")
        if upstream.get("page") != spec.page:
            raise ValueError(f"{where} does not name the page its table was read from")
        if not isinstance(cells, dict) or set(cells) != set(spec.headers):
            raise ValueError(f"{where} does not carry its vendor table's columns")
        if spec.products and cells[spec.product] not in spec.products:
            raise ValueError(f"{where} is outside the XenServer hypervisor scope")
        version = cells[spec.version]
        expected_eos = (date_value(cells.get(spec.eos, ""), spec.day_format, where)
                        if spec.eos else None)
        expected_eol = date_value(cells.get(spec.eol, ""), spec.day_format, where)
        if release["milestones"]["eos"] != expected_eos:
            raise ValueError(f"{where} eos contradicts its stored cells")
        if release["milestones"]["eol"] != expected_eol:
            raise ValueError(f"{where} eol contradicts its stored cells")
        if "EOM" in spec.headers:
            eom = date_value(cells.get("EOM", ""), spec.day_format, where)
            if eom is not None and expected_eol is not None and eom > expected_eol:
                raise ValueError(f"{where} stores an end of life before its own "
                                 f"end of maintenance")
        if not release["id"].startswith(line_id(version)):
            raise ValueError(f"{where} does not name its own version cell")
    if statements != 1:
        raise ValueError(f"{record['id']} carries {statements} {STATEMENT_ARTICLE} "
                         f"statements; exactly the 8.2 line states one")
    _check_ids(record)


def _check_ids(record):
    """Re-derive every line id from the record's own version/language cells."""
    table_rows = [release for release in record["releases"]
                  if release["upstream"].get("table") != STATEMENT_TABLE]
    rows = [(release["upstream"]["table"],
             release["upstream"]["cells"][BY_KEY[release["upstream"]["table"]].version],
             release["upstream"]["cells"][BY_KEY[release["upstream"]["table"]].language])
            for release in table_rows]
    expected = _edition_ids(rows)
    for release, assigned in zip(table_rows, expected):
        if release["id"] != assigned:
            raise ValueError(f"{record['id']}: release {release['id']!r} does not name its "
                             f"own version cell and language edition")


def record_for(releases, checked):
    """The published ``xenserver`` record for one complete hypervisor snapshot."""
    return {
        "$schema": RECORD_SCHEMA,
        "id": PRODUCT_ID,
        "name": PRODUCT_NAME,
        "category": "software",
        "upstream_category": UPSTREAM_CATEGORY,
        # The vendor publishes no CPE for the hypervisor, and an invented one
        # would be a claim the source does not make.
        "identifiers": [],
        "labels": {},
        "links": {"html": CURRENT_URL},
        "releases": releases,
        "provenance": {"source_url": CURRENT_URL, "verifier": VERIFIER,
                       "last_checked": checked, "upstream_modified": None},
    }


def committed_record(root):
    """The committed ``xenserver`` record, refusing one this source cannot own."""
    return transaction.committed_product_record(root, PRODUCT_ID, VERIFIER,
                                                validate_record, "XenServer")


def combine_releases(fresh, committed):
    """The complete hypervisor snapshot: this fetch's rows plus retained history.

    A line the pages no longer state keeps its committed row and dates rather
    than disappearing from the catalog; it is reported as retained, and it never
    counts as a source row this fetch saw.
    """
    if committed is None:
        return _ordered(fresh), []
    ids = {release["id"] for release in fresh}
    kept = [release for release in committed["releases"] if release["id"] not in ids]
    return (_ordered(fresh + kept),
            [{"id": release["id"], "name": release["name"],
              "reason": "the XenServer pages do not state this line; the committed row "
                        "and its dates are retained"}
             for release in kept])


def report_for(fresh, excluded, kept, statement, checked):
    """The per-row accounting this source publishes beside its record.

    Every source row is counted once: a row of one of the five vendor tables,
    or (only when the legacy matrix stops stating it) the 8.2 line's own
    sentence from CTX692513, reported under its article identity. The table
    counts therefore sum to ``rows.seen``.
    """
    tables = []
    for spec in (*TABLES, *([STATEMENT_SPEC] if any(
            release["upstream"]["table"] == STATEMENT_TABLE for release in fresh) else [])):
        published = sum(1 for release in fresh
                        if release["upstream"]["table"] == spec.key)
        rows = sum(1 for row in excluded if row["table"] == spec.key)
        tables.append({"table": spec.key, "page": spec.page,
                       "rows": published + rows, "published": published, "excluded": rows})
    return {
        "source_url": CURRENT_URL, "legacy_url": LEGACY_URL,
        "statement_url": STATEMENT_URL, "verifier": VERIFIER, "checked_at": checked,
        "record_scope": ("XenServer hypervisor lines: one software record with one release "
                         "per vendor line, from the current xenserver.com product matrix, "
                         "Citrix's legacy product matrix and the CTX692513 support article, "
                         "at the day precision those tables state"),
        "rows": {"seen": len(fresh) + len(excluded),
                 "published": len(fresh), "retained": len(kept), "excluded": len(excluded)},
        "tables": tables,
        "excluded": excluded,
        "retained": kept,
        "statement": dict(statement, date=_statement_date(statement["quote"])),
        "total_records": 1,
        "limitations": [
            "Citrix Hypervisor 8.0 and 8.1 are published from the legacy matrix's Citrix "
            "Hypervisor tab, which states only NSC, EOM and EOL: neither line has a "
            "published end of sales, general-availability date or security-support end, "
            "and the current matrix publishes no historical rows, so those milestones "
            "remain unresolved rather than being inferred.",
            "NSC is a notice of status change, not general availability. No parsed table "
            "states a GA date - the current matrix publishes no GA column at all - so "
            "every release keeps ga null even where NSC shares its date with a vendor "
            "launch announcement.",
            "EOM never fills a normalized milestone: the vendor states maintenance and "
            "life separately, so EOM stays a stored cell. EOES is End of Extended "
            "Support, a support-program phase rather than a security-only end, so it is "
            "retained as a cell and eossec stays null.",
            "The current matrix states one combined 'EOM & EOL' day. eol takes that date "
            "and the header and cell are retained verbatim, so a parser expecting "
            "separate EOM and EOL columns cannot silently mis-model the table.",
            "Citrix Hypervisor 8.2's terminal date is stated by both the legacy matrix row "
            "and the public support article CTX692513; the refresh requires the two to "
            "agree and refuses rather than choosing one. The article's 'Updated On' field "
            "renders empty, so no update date is inferred from it.",
            "The current matrix lists two rows by its own design, which is not evidence "
            "that older releases never existed; the legacy matrix supplies the historical "
            "lines, and a line it drops is retained from the committed record.",
            "Edition-language splits are reconciled per line: a language edition whose "
            "cells differ (6.0.0, 5.6, 5.5, 5) is published as its own release whose id "
            "appends the language, so a differing end of sales is never merged into "
            "another edition's row.",
            "The XenSource XenServer tab's rows keep the names that tab states (4.1, 4.0, "
            "3.2, 3.1 and earlier, with their edition scopes in the version cell); they "
            "are the same hypervisor lineage as the Citrix Hypervisor and XenServer rows, "
            "published under the vendor's own label rather than renamed.",
        ],
    }


def publish_record(record, report, root):
    """Stage the record beside the committed catalog, validate, then replace it."""
    return transaction.publish_product_record(record, report, root, REPORT)


def import_xenserver(directory=None):
    """Fetch all three pages and publish the ``xenserver`` record.

    Complete-or-nothing: the fetched snapshot is combined with the lines the
    source no longer states, staged beside the committed catalog and validated
    there before anything is written. A parse failure, a reshaped table, a
    source disagreement or an inconsistent catalog leaves every committed file
    untouched.
    """
    root = Path(directory) if directory is not None else ROOT / "data"
    committed = committed_record(root)
    checked = _now()
    fresh, excluded, statement = parse_releases(
        net.get_text(CURRENT_URL), net.get_text(LEGACY_URL), net.get_text(STATEMENT_URL))
    releases, kept = combine_releases(fresh, committed)
    report = report_for(fresh, excluded, kept, statement, checked)
    publish_record(record_for(releases, checked), report, root)
    rows = report["rows"]
    return (f"imported {rows['published']} XenServer hypervisor lines "
            f"({len(releases)} in the published record); excluded {rows['excluded']} rows, "
            f"retained {rows['retained']} (data/{REPORT})")
