"""Import the eosl.date hardware catalog: vendor product families and their models.

eosl.date publishes no API — the server-rendered HTML tables below each family
page are the only interface. Every page carries up to three tables whose row
classes state the lifecycle status outright (``release-row-supported``,
``table-warning-row release-row-warning``, ``table-eol-row release-row-eol``),
and every cell declares its own column through ``data-label``, so columns are
read by role rather than by position.

Column roles, resolved from the declared header row and matched case- and
whitespace-insensitively:

* identity — ``Product``/``Product Name``, ``Model Number``/``Model Name``,
  ``Product Line``
* ``ga`` — ``Release Date``/``Launch Date``
* ``eos`` — a column naming end of sales: ``End of Sale(s) Date`` and
  ``End of Life Date`` (eosl.date's own glossary defines that column as the end
  of sales date, when a product is no longer sold)
* ``eol`` — the terminal support column, eosl.date's EOSL/LDOS:
  ``End of Support``, ``End of Support (EOSL)``, ``End of Support Date``,
  ``End of Service``, ``End of Service Date``

Every other column — ``EOL Announced``, warranty and discontinuance columns,
``Version Number`` — is carried verbatim in ``upstream``, so no published date
is lost and a future re-mapping never requires a re-fetch.

No date is ever invented. A dated value is either a ``<time datetime>``
attribute or a bare ``YYYY-MM-DD``; every other value (``TBD``,
``Not Announced``, an empty cell, or a support.apple.com URL standing in for an
unannounced deadline) becomes ``None``.

The parser fails closed on drift rather than publishing a quietly smaller or
emptier catalog. A row class is read as a lifecycle *token* (``supported``,
``warning``, ``eol``) so a reordered or restyled class list still publishes the
same state, but a labelled data row whose class states no lifecycle this mapper
knows — and a row whose declared width disagrees with the table's header — is
refused instead of skipped. A milestone cell that carries a date shape the
parser cannot read as a real calendar day is refused too, so source drift can
never turn a published deadline into ``None``. The rows a page legitimately
does not publish (column headers, advertisement and layout rows, blank
separator rows) are counted and named in the parse result's ``accounting``
instead of vanishing, together with the per-column values dropped when two
sources merge into one record.
"""
from __future__ import annotations

import json
import re
import shutil
import tempfile
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone
from html.parser import HTMLParser
from pathlib import Path

from . import net, sources
from .importer import ROOT, dump
from .sources import EOSL_DATE, EOSL_DATE_SITEMAP

HARDWARE_SOURCE = EOSL_DATE
SITEMAP = EOSL_DATE_SITEMAP
# The registry owns the id: a record's provenance must name a source it knows.
VERIFIER = sources.source("import-hardware").verifier
RECORD_SCHEMA = "https://zarguell.github.io/eoltracker/v1/schema/hardware.json"
REQUEST_PAUSE = net.profile(SITEMAP).pause
WORKERS = net.workers(SITEMAP)

# A family path is a category (which may itself be nested, such as
# `storage/san-switches`), `/vendor/`, a vendor and a family.
FAMILY_PATH = re.compile(
    r"^(?P<category>[a-z0-9][a-z0-9/-]*)/vendor/(?P<vendor>[^/]+)/(?P<family>[^/]+)/$")
SITEMAP_LOC = re.compile(r"<loc>\s*([^<\s]+)\s*</loc>")
DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
# A lifecycle value that *looks* like a date the parser could not read: a
# fully numeric day shape, or a month-and-day shape. Those are refused rather
# than filed as "no date published", so a reformatted source deadline cannot
# silently become ``None``.
DATE_SHAPED = re.compile(
    r"^\d{4}[-/.]\d{1,2}(?:[-/.]\d{1,2})?(?:[T ].*)?$"
    r"|^\d{1,2}[-/.]\d{1,2}[-/.]\d{2,4}$"
    r"|^\d{1,2}\s+(?:[A-Za-z]{3,9}\.?)\s+\d{4}$"
    # A month name with a year, or a lone year: the month-precision shapes
    # AGENTS.md rule 4 forbids padding into a day.
    r"|^(?:[A-Za-z]{3,9}\.?)\s+\d{4}$"
    r"|^\d{4}$")
# Lifecycle values that mean "no date published"; none of them is a date.
SENTINELS = {"", "tbd", "tba", "not announced", "not available", "n/a", "na", "unknown", "none"}
# Row class -> published status, matched on the class list's *tokens* rather
# than on one complete class string. eosl.date's row classes state the
# lifecycle twice (``table-eol-row release-row-eol``) and restyling adds,
# reorders or drops presentation tokens such as ``table-warning-row``; reading
# the semantic tokens keeps a harmless CSS change from rewriting a status or
# dropping the row, which matching the exact attribute value used to do.
# Which token wins when a row carries several is stated once, most severe
# first, so the choice never depends on attribute order; tokens that state no
# lifecycle (layout, advertisement) carry no status at all.
STATUS_TOKENS = (
    ("eol", ("release-row-eol", "row-eol", "table-eol-row")),
    ("expiring", ("release-row-warning", "row-warning", "release-row-expiring")),
    ("supported", ("release-row-supported", "row-supported")),
)
# Class tokens that state no lifecycle status. They are how the source marks a
# row this parser is not meant to publish (an advertisement slot, a layout or
# summary row), so they are recognized rather than refused.
NON_MODEL_TOKENS = {
    "ad-row", "advertisement-row", "ads-row", "summary-row", "total-row",
    "family-summary-row", "filter-row", "layout-row", "header-row", "table-header-row",
}
# Column role -> the declared headers naming it, after normalization.
ROLE_HEADERS = (
    ("product", {"product", "productname"}),
    ("model", {"modelnumber", "modelname"}),
    ("line", {"productline"}),
    ("ga", {"releasedate", "launchdate"}),
    ("eos", {"endofsaledate", "endofsalesdate", "endoflifedate"}),
    ("eol", {"endofsupport", "endofsupport(eosl)", "endofsupportdate",
             "endofservice", "endofservicedate"}),
    # Not a milestone: the row's own identifier on the software-shaped families
    # (one row per released version), kept raw and used as the model fallback.
    # A build number is kept apart from it, being the less meaningful of the
    # two where a family publishes both.
    ("version", {"versionnumber", "version"}),
    ("build", {"buildnumber"}),
)
STATUS_ORDER = ("supported", "expiring", "eol")
MILESTONES = ("ga", "eos", "eossec", "eol")
# Cardinality guards. eosl.date is a small hand-curated site: the largest
# family page in the 2026-09-25 capture publishes 213 models in tables of at
# most 169 rows, and the sitemap lists 238 families. These bounds sit far above
# that but well below "a wrong response" — a refresh cannot be made to consume
# unbounded time and memory by one oversized body (an error page, an index, an
# adversarial payload), and a page past them is refused before its rows reach
# the merge.
MAX_TABLE_ROWS = 2000
MAX_PAGE_MODELS = 5000
MAX_FAMILIES = 2000
MAX_CATALOG_MODELS = 50000
# eosl.date renders relative support prose inside the same cell as the date.
RELATIVE_SUFFIX = re.compile(r"^(?P<date>.*?)\s*Support (?:ended|continues)\b.*$", re.S)

# The link fields this collector stores. eosl.date's own ``<a href>`` values
# can point anywhere the page likes; only an absolute public http(s) URL is
# stored, so a page that starts publishing ``javascript:`` or a host-local path
# cannot put an unsafe target into a record the site later renders. The helper
# is imported with the narrow fallback the other presentation paths use, so this
# collector keeps working (and keeps rejecting userinfo and control characters)
# until the shared module lands.
try:  # pragma: no cover - exercised by the fixture tests via the real module
    from .urls import safe_http_url_or_none as _safe_http_url
except ImportError:  # pragma: no cover - only until engine/urls.py lands
    from urllib.parse import urlsplit

    def _safe_http_url(value):
        """Fallback: keep only plain absolute http(s) URLs, no userinfo/controls."""
        if not isinstance(value, str) or any(ord(ch) < 0x20 or ch == "\x7f" for ch in value):
            return None
        parsed = urlsplit(value.strip())
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            return None
        if "@" in parsed.netloc or not parsed.hostname:
            return None
        return value


def _normalize(text):
    """Fold a header or data-label for comparison: no whitespace, lower case."""
    return re.sub(r"\s+", "", text).lower()


def _text(value):
    return re.sub(r"\s+", " ", value).strip()


def slugify(value):
    """An id slug: ASCII, lower case, hyphen separated and never empty.

    A character outside ASCII (such as the multiplication sign in
    ``MA-MOD-4×10`` or an accented letter) separates words rather than
    vanishing, so ``4×10`` and ``410`` cannot slugify alike.
    """
    folded = unicodedata.normalize("NFKD", value)
    folded = "".join(char for char in folded if not unicodedata.combining(char))
    folded = "".join(char if char.isascii() else "-" for char in folded)
    return re.sub(r"[^a-z0-9]+", "-", folded.lower()).strip("-")


def _date(value):
    """Return ``value`` when it is a real calendar day, else None.

    Any other returned value would be an invented date, and an impossible one
    such as ``2026-02-30`` would fail the record schema anyway.
    """
    if not DATE.fullmatch(value):
        return None
    try:
        date.fromisoformat(value)
    except ValueError:
        return None
    return value


def family_path(url):
    """The (category, vendor, family) of a same-origin family URL, else None."""
    path = url.split("?", 1)[0].split("#", 1)[0]
    if path.startswith(HARDWARE_SOURCE):
        path = path[len(HARDWARE_SOURCE):]
    elif "://" in path:
        return None
    return FAMILY_PATH.match(path.strip("/") + "/")


def family_url(match):
    """The canonical absolute family URL of a `family_path` match."""
    return "{}{}/vendor/{}/{}/".format(HARDWARE_SOURCE, match.group("category"),
                                       match.group("vendor"), match.group("family"))


def _span(attributes, name):
    """A cell's declared row/column span: 1 when absent, refused when unusable.

    ``rowspan="0"`` means "to the end of the row group" in HTML and a
    non-numeric span means the markup is not what it claims to be; either way
    the logical grid cannot be built honestly, so the parse refuses instead of
    guessing a layout and publishing the wrong cell under the wrong column.
    """
    raw = attributes.get(name)
    if raw is None or raw == "":
        return 1
    try:
        value = int(raw)
    except (TypeError, ValueError):
        raise ValueError(f"Invalid table cell {name}: {raw!r}") from None
    if value < 1:
        raise ValueError(f"Invalid table cell {name}: {raw!r}")
    return value


class _Tables(HTMLParser):
    """Collect table rows and cells with their declared labels, times and spans."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tables = []
        self._table = None
        self._row = None
        self._cell = None
        self._header_cell = False

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag == "table":
            self._table = {"headers": [], "header_cells": [], "rows": []}
        elif tag == "tr" and self._table is not None:
            self._row = {"class": attributes.get("class") or "", "cells": [], "header": [],
                         "header_cells": []}
        elif tag in ("td", "th") and self._row is not None:
            self._cell = {"label": attributes.get("data-label"), "text": "", "time": None,
                          "links": [], "rowspan": _span(attributes, "rowspan"),
                          "colspan": _span(attributes, "colspan")}
            self._header_cell = tag == "th"
        elif tag == "time" and self._cell is not None:
            self._cell["time"] = attributes.get("datetime")
        elif tag == "a" and self._cell is not None and attributes.get("href"):
            self._cell["links"].append(attributes["href"])

    def handle_endtag(self, tag):
        if tag == "table" and self._table is not None:
            self.tables.append(self._table)
            self._table = None
        elif tag == "tr" and self._row is not None and self._table is not None:
            self._table["headers"].extend(self._row["header"])
            self._table["header_cells"].append(self._row["header_cells"])
            self._table["rows"].append(self._row)
            self._row = None
        elif tag in ("td", "th") and self._cell is not None:
            self._close_cell()

    def handle_data(self, data):
        if self._cell is not None:
            self._cell["text"] += data

    def _close_cell(self):
        cell, self._cell = self._cell, None
        text = _text(cell["text"])
        # "Apr. 30, 2026Support ended 4 months ago" keeps only the machine date.
        if cell["time"] is not None:
            match = RELATIVE_SUFFIX.match(text)
            if match:
                text = _text(match.group("date"))
        if self._header_cell:
            self._table["headers"].append(text)
            self._row["header_cells"].append(
                {"text": text, "colspan": cell["colspan"], "rowspan": cell["rowspan"]})
        else:
            cell["text"] = text
            self._row["cells"].append(cell)


def _tables(html):
    parser = _Tables()
    parser.feed(html)
    parser.close()
    return parser.tables


def _grid(rows):
    """Rows laid out on a logical grid, honoring ``rowspan`` and ``colspan``.

    A spanned cell is presentation: ``rowspan`` carries one cell down into the
    rows it covers and ``colspan`` repeats it across the columns it covers.
    Publishing by ``data-label`` means a spanned cell has to be visible in
    every row it really belongs to, or the rows it covers lose their identity
    (and their dates) for a purely cosmetic markup change. Each row therefore
    maps logical column index -> cell, which is also what makes a declared row
    width checkable against the header.
    """
    pending = {}
    laid_out = []
    for row in rows:
        queue = list(row["cells"])
        line = {}
        column = 0
        while queue or any(left > 0 for _, left in pending.values()):
            covered = pending.get(column)
            if covered is not None and covered[1] > 0:
                line[column] = covered[0]
                covered[1] -= 1
                if covered[1] == 0:
                    del pending[column]
                column += 1
                continue
            if not queue:
                later = [index for index, (_, left) in pending.items() if left > 0 and index > column]
                if not later:
                    break
                column = min(later)
                continue
            cell = queue.pop(0)
            for offset in range(cell["colspan"]):
                line[column + offset] = cell
            if cell["rowspan"] > 1:
                for offset in range(cell["colspan"]):
                    pending[column + offset] = [cell, cell["rowspan"] - 1]
            column += cell["colspan"]
        laid_out.append((row, line))
    return laid_out


def _header_width(table):
    """The logical column count of a table's declared header row."""
    header_rows = table.get("header_cells") or []
    widest = 0
    for cells in header_rows:
        width = sum(cell["colspan"] for cell in cells)
        widest = max(widest, width)
    return widest or len(table["headers"])


def cell_raw(cell):
    """The value a cell publishes, before any date interpretation."""
    if cell is None:
        return ""
    return _text(cell["time"] if cell["time"] is not None else cell["text"])


def cell_value(cell, role=None):
    """The published date of one cell, or None when it publishes no date.

    ``None`` covers every unnamed case: an empty cell, a sentinel such as
    ``TBD`` or ``Not Announced``, and free text that is not a date at all.

    For a milestone column (``role`` names one) the reverse case is refused
    rather than filed as "no date published": a value that *is* a date shape
    the parser cannot read as a real calendar day — ``2026-02-30``, a month
    without a day, a numeric day/month/year the source never used before — is
    source drift, and returning ``None`` for it would silently delete a
    published deadline from the catalog.
    """
    if cell is None:
        return None
    value = cell_raw(cell)
    if value.lower() in SENTINELS:
        return None
    parsed = _date(value)
    if parsed is None and role in MILESTONES and DATE_SHAPED.match(value):
        raise ValueError(
            f"Unreadable {role} date in an upstream cell: {value!r} "
            "(a date-shaped value that is not a real calendar day)")
    return parsed


def _roles(headers, url):
    """Map normalized header -> role, rejecting a table whose shape drifted.

    A family table that lost its identity or terminal-support column is never
    published with silently missing dates: the drift raises here instead.
    """
    roles = {}
    for header in headers:
        name = _normalize(header)
        if not name:
            continue
        roles[name] = next((role for role, names in ROLE_HEADERS if name in names), None)
    if "product" not in roles.values() and "model" not in roles.values():
        raise ValueError(f"No product or model column in a table of {url}: {headers}")
    if "eol" not in roles.values():
        raise ValueError(f"No end of support column in a table of {url}: {headers}")
    return roles


def _first(cells, roles, role, nonempty=False):
    """The cell holding ``role``: the first declared column, else the first filled one.

    Two columns can name one role for identity (``Product`` beside
    ``Product Name``, the first often empty on HPE pages), so identity lookups
    ask for the first cell that actually carries a value. A date role is never
    doubled upstream, so dates keep the declared column.
    """
    cells_with_role = [cells[name] for name, mapped in roles.items()
                       if mapped == role and name in cells]
    if not nonempty:
        return cells_with_role[0] if cells_with_role else None
    return next((cell for cell in cells_with_role if cell["text"]), None)


def _identity(cells, roles):
    """The (product, model_number, product_line) triple naming one model.

    A family may publish a product without a model column (the HPE
    software-shaped pages), or, as one Apple row does, a model without a
    product; whichever exists stands in for the other so every published model
    still has an identity. On the software-shaped families a single product
    name covers one row per released version, and that version is what tells
    the rows apart, so it is the model number there.
    """
    product_cell = _first(cells, roles, "product", nonempty=True)
    model_cell = _first(cells, roles, "model", nonempty=True)
    line_cell = _first(cells, roles, "line", nonempty=True)
    version_cell = _first(cells, roles, "version", nonempty=True) or _first(
        cells, roles, "build", nonempty=True)
    product = product_cell["text"] if product_cell else ""
    model = model_cell["text"] if model_cell else ""
    if not model:
        model = version_cell["text"] if version_cell else ""
    return product or model, model or product, (line_cell["text"] if line_cell else "")


def _row_cells(line):
    """One row's logical cells in column order, each distinct cell counted once.

    ``rowspan`` replays one cell into the rows it covers and ``colspan``
    replays it across the columns it covers, so a logical grid holds one cell
    object many times. Every label lookup wants it once.
    """
    seen, ordered = set(), []
    for column in sorted(line):
        cell = line[column]
        if id(cell) in seen:
            continue
        seen.add(id(cell))
        ordered.append((column, cell))
    return ordered


def _cells(line):
    """The row's declared cells by normalized label: ``(cells, duplicates)``.

    A label the row declares twice with two different cells keeps both: the
    first declared column is the one a role lookup reads (as the published
    header order defines), and the extra cell is reported so a source that
    starts publishing a column twice cannot quietly drop a value.
    """
    cells, duplicates = {}, []
    for _, cell in _row_cells(line):
        label = cell["label"]
        if not label:
            continue
        name = _normalize(label)
        if name in cells:
            if cells[name] is not cell:
                duplicates.append((label, cell))
            continue
        cells[name] = cell
    return cells, duplicates


def _upstream(line, roles, dropped):
    """Every declared cell verbatim, including those no milestone claims.

    A duplicated column keeps both cells, the second filed under a
    disambiguated key, so neither value is lost to the other. A cell's link is
    stored only when it is an absolute public http(s) URL: a page publishing a
    ``javascript:`` target or a credential-bearing query would otherwise put it
    into a record the site renders as a link. A dropped link is appended to
    ``dropped`` so the refresh reports it rather than quietly losing evidence.
    """
    upstream = {}
    for _, cell in _row_cells(line):
        if not cell["label"]:
            continue
        label = cell["label"]
        key, position = label, 1
        while key in upstream:
            position += 1
            key = f"{label} ({position})"
        links = []
        for link in cell["links"]:
            safe = _safe_http_url(link)
            if safe is None:
                dropped.append({"column": label, "url": link})
                continue
            links.append(safe)
        upstream[key] = {
            "text": cell["text"],
            "datetime": cell["time"],
            "value": cell_value(cell, roles.get(_normalize(label))),
            "role": roles.get(_normalize(label)),
            "links": links,
        }
    return upstream


def _row_status(row, url):
    """The lifecycle status a row's class tokens state, refusing anything else.

    The tokens are matched, not the complete class string, so adding,
    reordering or dropping a presentation token (``table-warning-row``) leaves
    the published status alone. Anything unrecognized is refused: a row that
    carries declared data cells must say which lifecycle it belongs to, and two
    lifecycle tokens at once contradict each other. Silently skipping such a
    row is how a row count shrinks while a refresh stays green.
    """
    tokens = set(_text(row["class"]).split())
    statuses = {status for status, names in STATUS_TOKENS if tokens.intersection(names)}
    if len(statuses) > 1:
        raise ValueError(f"Contradictory lifecycle row classes in {url}: {row['class']!r}")
    if not statuses:
        raise ValueError(f"Unrecognized lifecycle row class in {url}: {row['class']!r}")
    return statuses.pop()


def parse_family_page(html, url):
    """Parse one family page: ``{family, vendor, source_url, models, accounting}``.

    ``url`` carries the identity the markup does not state outright (category,
    vendor and family slug) while the breadcrumb supplies the displayed names.
    Each model carries ``eossec: None``: eosl.date publishes no security
    support deadline, and claiming one would invent a contract never stated.

    ``accounting`` is the page's row ledger: every data row read, every row
    published, and every row left out with the reason it was left out, so a
    smaller-than-expected model list is visible in the refresh instead of
    being inferred from a count that only ever goes down.
    """
    match = family_path(url)
    if not match:
        raise ValueError(f"Not a product family URL: {url}")
    crumbs = re.findall(r'<li class="breadcrumb-item[^"]*"[^>]*>(?:<a[^>]*>)?([^<]*)', html)
    vendor = _text(crumbs[1]) if len(crumbs) > 1 and _text(crumbs[1]) else match.group("vendor")
    family = _text(crumbs[2]) if len(crumbs) > 2 and _text(crumbs[2]) else match.group("family")

    models = []
    accounting = {"tables": 0, "model_tables": 0, "data_rows": 0, "rows": 0, "skipped": [],
                  "duplicate_columns": [], "unsafe_links": []}
    for table in _tables(html):
        accounting["tables"] += 1
        grid = _grid(table["rows"])
        # A table is a family table when at least one of its rows declares its
        # own columns (``data-label``). That is exactly the shape a model row
        # has, so a table of advertisements or navigation — declared columns
        # and all — is counted and left alone, while a family table whose row
        # classes drifted is still read and refused row by row instead of being
        # mistaken for furniture and skipped whole.
        if not any(row["cells"] and any(cell["label"] for cell in row["cells"])
                   for row in table["rows"]):
            continue
        accounting["model_tables"] += 1
        headers = table["headers"] or next(
            (row["header"] for row in table["rows"] if row["header"]), [])
        roles = _roles(headers, url)
        width = _header_width(table)
        if len(grid) > MAX_TABLE_ROWS:
            raise ValueError(
                f"Table in {url} publishes {len(grid)} rows, above the {MAX_TABLE_ROWS}-row guard")
        for row, line in grid:
            if not row["cells"]:
                # The declared header row (and any empty row) states no data.
                continue
            accounting["data_rows"] += 1
            cells, duplicates = _cells(line)
            for label, cell in duplicates:
                accounting["duplicate_columns"].append(
                    {"row": accounting["data_rows"], "column": label, "text": cell["text"]})
            tokens = set(_text(row["class"]).split())
            if tokens and tokens <= NON_MODEL_TOKENS:
                # A class the source publishes for its own furniture (an
                # advertisement slot): recognized, and not a model row.
                accounting["skipped"].append({"row": accounting["data_rows"],
                                              "reason": f"non-model row class {row['class']!r}"})
                continue
            status = _row_status(row, url)
            if not cells:
                # A row with no declared columns is a layout row: it cannot
                # claim a model, because it names no column to claim it under.
                accounting["skipped"].append({"row": accounting["data_rows"],
                                              "reason": "no declared columns"})
                continue
            if len(line) != width:
                raise ValueError(
                    f"Row width drift in {url}: the row fills {len(line)} logical columns "
                    f"but the header declares {width}")
            product, model, line_name = _identity(cells, roles)
            ga = cell_value(_first(cells, roles, "ga"), "ga")
            eos = cell_value(_first(cells, roles, "eos"), "eos")
            eol = cell_value(_first(cells, roles, "eol"), "eol")
            if not product:
                if ga or eos or eol:
                    # A row that publishes a milestone but names no model is
                    # drift: dropping it would delete a published deadline, so
                    # the parse refuses. A row with neither name nor date is the
                    # published blank separator row and is reported as a skip.
                    raise ValueError(
                        f"Unnamed {status} lifecycle row in {url}: the row publishes "
                        f"{', '.join(d for d in (ga, eos, eol) if d)} but no product or model value")
                accounting["skipped"].append({"row": accounting["data_rows"],
                                              "reason": "blank row without an identity"})
                continue
            models.append({
                "product": product,
                "model_number": model,
                "product_line": line_name,
                "ga": ga,
                "eos": eos,
                "eossec": None,
                "eol": eol,
                "status": status,
                "upstream": _upstream(line, roles, accounting["unsafe_links"]),
            })
            accounting["rows"] += 1
            if len(models) > MAX_PAGE_MODELS:
                raise ValueError(
                    f"{url} publishes more than {MAX_PAGE_MODELS} models, above the page guard")
    return {"family": family, "vendor": vendor, "source_url": url, "models": models,
            "accounting": accounting}


def parse_vendor_page(html):
    """The product family slugs a vendor overview page links, in page order.

    The visible dropdown items are ``href="#"`` placeholders, but every family
    carries its real path in ``data-family-url``; both are read, so either
    markup change keeps discovery working.
    """
    slugs = []
    for href in re.findall(r'data-family-url="([^"]+)"', html) + re.findall(
            r'<a[^>]*href="([^"]+)"', html):
        match = family_path(href)
        if match and match.group("family") not in slugs:
            slugs.append(match.group("family"))
    return slugs


def iter_family_urls(sitemap=None):
    """Yield every product family URL of the family sitemap, in sitemap order."""
    document = fetch(SITEMAP) if sitemap is None else sitemap
    for loc in SITEMAP_LOC.findall(document):
        match = family_path(loc)
        if match:
            yield family_url(match)


def fetch(url):
    """GET one page politely: identified, bounded, retried once on a network error."""
    return net.get_text(url, encoding="utf-8")


def merge_models(models):
    """Merge duplicate models and assign each one its published id.

    One model can appear in several families — a Cisco MDS switch is also a
    Dell EMC Connectrix-Cisco model — so models merge on
    ``(product_line, product, model_number)`` and every source URL is kept.
    Milestones only ever gain a value: two sources publishing different dates
    for one model is a contradiction to surface, never to settle by ordering.
    """
    merged = {}
    for model in models:
        product = _text(model["product"])
        if not product:
            raise ValueError(f"Hardware model without a product name: {model.get('source_url')}")
        identity = (_text(model["product_line"]), product, _text(model["model_number"]))
        existing = merged.get(identity)
        if existing is None:
            base = slugify(f"{model['vendor']}-{identity[2] or identity[1]}")
            if not base:
                raise ValueError(
                    f"Hardware model without a usable id: {product!r} in {model.get('source_url')}")
            merged[identity] = {
                "base": base, "identity": identity, "vendor": model["vendor"],
                "family": model["family"], "milestones": dict(model["milestones"]),
                "status": model["status"], "upstream": dict(model["upstream"]),
                "source_urls": [model["source_url"]],
            }
            continue
        _absorb(merged[identity], model)
    return _address(merged)


def _absorb(record, model):
    """Fold one more source's model into an already merged record.

    Evidence is kept per source. A column both pages declare is two published
    values, not one value to overwrite: where the second page's cell differs
    from the first's it is stored under a key naming that page, so the merge
    can never drop a date, a link or a note the catalog is supposed to show
    beside the normalized record.
    """
    for field in MILESTONES:
        value = model["milestones"][field]
        if value is None:
            continue
        current = record["milestones"][field]
        if current is None:
            record["milestones"][field] = value
        elif current != value:
            raise ValueError(
                f"Conflicting {field} for {record['identity']}: {current} != {value} "
                f"({record['source_urls'][0]} vs {model['source_url']})")
    if model["source_url"] not in record["source_urls"]:
        record["source_urls"].append(model["source_url"])
    for label, cell in model["upstream"].items():
        if label not in record["upstream"]:
            record["upstream"][label] = cell
            continue
        if record["upstream"][label] == cell:
            continue
        key, position = f"{label} ({model['source_url']})", 2
        while key in record["upstream"]:
            key = f"{label} ({model['source_url']} #{position})"
            position += 1
        record["upstream"][key] = cell
    _absorb_status(record, model)


def _absorb_status(record, model):
    """Fold one more source's row status, refusing a contradiction.

    Two pages can place one model in different lifecycle rows. A disagreement
    that only changes how cautious the record reads (``supported`` beside
    ``expiring``) settles by severity, since neither page claims support has
    ended. A disagreement about whether support has ended at all settles by
    severity only when a deadline corroborates the terminal side: an ``eol``
    row beside a date the model publishes is the vendor's own statement, while
    an ``eol`` row with no deadline anywhere is one page contradicting another
    with nothing to check it against, and is refused rather than classified by
    the order the sources happened to merge in.
    """
    current, other = record["status"], model["status"]
    if current == other:
        return
    if "eol" not in (current, other) or record["milestones"]["eol"]:
        record["status"] = max(current, other, key=STATUS_ORDER.index)
        return
    raise ValueError(
        f"Contradictory statuses for {record['identity']}: {current} != {other} "
        f"({record['source_urls'][0]} vs {model['source_url']}) with no published support date")


def _address(merged):
    """Give every merged model an id, resolving slug collisions deterministically.

    Two genuinely distinct published models can slugify alike (an Apple row
    whose model number and its sibling's disagree, a Brocade pair differing in
    whitespace). The collision is settled in identity order and against every
    id already taken, so the result never depends on fetch order and a
    generated suffix cannot land on another model's natural slug.
    """
    groups = {}
    for record in merged.values():
        groups.setdefault(record["base"], []).append(record)
    addressed = {}
    for base in sorted(groups):
        records = sorted(groups[base], key=lambda record: record["identity"])
        for position, record in enumerate(records):
            key = base if position == 0 else f"{base}-{position + 1}"
            while key in addressed:
                position += 1
                key = f"{base}-{position + 1}"
            record["id"] = key
            addressed[key] = record
    return addressed


def _record(record, checked):
    """The published hardware record for one merged model."""
    product_line, product, model_number = record["identity"]
    return {
        "$schema": RECORD_SCHEMA,
        "id": record["id"],
        "name": product,
        "category": "hardware",
        "vendor": record["vendor"],
        # The schema requires a non-empty product line, and a family that
        # publishes none is identified by its vendor.
        "product_line": product_line or record["vendor"],
        "family": record["family"],
        "model_number": model_number,
        "milestones": record["milestones"],
        "status": record["status"],
        "upstream": record["upstream"],
        "provenance": {
            "source_urls": record["source_urls"],
            "verifier": VERIFIER,
            "last_checked": checked,
        },
    }


def get_records(directory=None):
    """The committed hardware records, in slug order, for the catalog manifest."""
    directory = Path(directory) if directory is not None else ROOT / "data"
    return [json.loads(file.read_text(encoding="utf-8"))
            for file in sorted((directory / "hardware").glob("*.json"))]


def committed_counts(records):
    """How many committed records each source page owns, from their own URLs."""
    counts = {}
    for record in records:
        for url in record["provenance"]["source_urls"]:
            counts[url] = counts.get(url, 0) + 1
    return counts


def check_family_drift(pages, committed):
    """Refuse a refresh that would prune a family the source stopped publishing.

    Two ways a family goes missing, both of which the complete-or-nothing write
    would turn into an unannounced disappearance: the page still exists but no
    longer yields models (its table vanished, or the body this parser received
    is not a family page at all), and the page is gone from the sitemap
    entirely. The comparison is per page and only in the pruning direction — a
    family gaining models, or a page whose records were already pruned and so
    owns none in the catalog, is a normal source update and is not this check's
    business. Returns ``{url: parsed page}`` plus one accounting ledger per
    page, so a page that legitimately publishes nothing stays distinguishable
    from one whose rows could not be read.
    """
    parsed_pages, accounting, lost = {}, {}, []
    for url, html in pages:
        parsed = parse_family_page(html, url)
        parsed_pages[url] = parsed
        expected = committed.get(url, 0)
        accounting[url] = {**parsed["accounting"], "committed": expected}
        if expected and not parsed["models"]:
            lost.append((url, expected, "publishes no models"))
    for url, expected in committed.items():
        if url not in parsed_pages and expected:
            lost.append((url, expected, "is no longer in the family sitemap"))
    if lost:
        detail = ", ".join(f"{url} ({reason}; was {count})" for url, count, reason in lost)
        raise ValueError(f"Product families the refresh would prune: {detail}")
    return parsed_pages, accounting


def import_hardware(directory=None):
    """Fetch every family page and write ``data/hardware/{id}.json``.

    Complete-or-nothing, like the software import: every page is fetched and
    parsed before the committed directory is touched, and a record's previous
    revision time is preserved while its content is unchanged, so a quiet
    source never looks freshly re-verified.
    """
    destination = Path(directory) if directory is not None else ROOT / "data"
    urls = list(iter_family_urls())
    if not urls:
        raise ValueError("No product family URLs in the upstream sitemap")
    if len(set(urls)) != len(urls):
        raise ValueError("Duplicate product family URLs in the upstream sitemap")
    if len(urls) > MAX_FAMILIES:
        raise ValueError(
            f"The upstream sitemap publishes {len(urls)} product families, above the "
            f"{MAX_FAMILIES}-family guard")
    checked = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")

    # Two workers and a pause before each request: eosl.date is a small
    # server-rendered site that publishes no rate limit, so stay well inside one.
    def page(url):
        time.sleep(REQUEST_PAUSE)
        return url, fetch(url)

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        pages = list(pool.map(page, urls))

    committed = committed_counts(
        [record for record in get_records(destination)
         if record["provenance"]["verifier"] == VERIFIER])
    found, accounting = check_family_drift(pages, committed)
    models = []
    for url, parsed in found.items():
        for model in parsed["models"]:
            models.append({
                "vendor": parsed["vendor"], "family": parsed["family"], "source_url": url,
                "product": model["product"], "model_number": model["model_number"],
                "product_line": model["product_line"],
                "milestones": {field: model[field] for field in MILESTONES},
                "status": model["status"], "upstream": model["upstream"],
            })
    if len(models) > MAX_CATALOG_MODELS:
        raise ValueError(
            f"The upstream catalog publishes {len(models)} models, above the "
            f"{MAX_CATALOG_MODELS}-model guard")
    merged = merge_models(models)
    if not merged:
        raise ValueError("No hardware models parsed from any product family page")

    records = [_record({**merged[key], "id": key}, checked) for key in sorted(merged)]
    publish_records(records, VERIFIER, destination)
    skipped = sum(len(page["skipped"]) for page in accounting.values())
    duplicate_columns = sum(len(page["duplicate_columns"]) for page in accounting.values())
    unsafe_links = sum(len(page["unsafe_links"]) for page in accounting.values())
    return (f"imported {len(records)} hardware models from {len(urls)} product families "
            f"({skipped} non-model rows skipped, {duplicate_columns} duplicate columns retained, "
            f"{unsafe_links} unsafe links dropped)")


def report_name(verifier):
    """The accounting sidecar the registry names for a verifier, else ``""``.

    The sidecar's name is the registry's fact, not the collector's: a source
    that publishes per-row accounting declares it beside the rest of its
    descriptor, and a source that declares none (eosl.date today) is checked
    for nothing here. Reading it from the registry means adding one is a
    descriptor edit, not a second filename in this module.
    """
    for found in sources.sources_for(verifier):
        if found.report:
            return found.report
    return ""


def publish_records(records, verifier, directory=None, report=None):
    """Validate a complete source snapshot before replacing only its owned records.

    ``report`` is the refreshing source's prospective accounting sidecar. The
    registry may name a sidecar for ``verifier``; a source the gate requires one
    from cannot be validated without it, because the gate compares the sidecar's
    own record count against the records being written. So the sidecar is staged
    beside the staged records before validation — the prospective one when the
    caller passes it, else the committed one, which is what makes a refresh that
    adds or removes a record without republishing its accounting fail loudly
    instead of shipping a catalog its own report does not describe. The count
    comparison itself stays in one place: the catalog gate.
    """
    from .validation import validate_hardware

    root = Path(directory) if directory is not None else ROOT / "data"
    destination = root / "hardware"
    if not records:
        raise ValueError(f"Empty hardware snapshot from {verifier}")
    previous = {file.stem: json.loads(file.read_text(encoding="utf-8"))
                for file in destination.glob("*.json")}
    sidecar = report_name(verifier)
    if report is not None and not sidecar:
        raise ValueError(f"{verifier} publishes no accounting sidecar to write")
    seen = set()
    with tempfile.TemporaryDirectory(prefix="eoltracker-hardware-") as temp:
        staged = Path(temp)
        for record in records:
            key = record["id"]
            if key in seen or record["provenance"]["verifier"] != verifier:
                raise ValueError(f"Duplicate or foreign hardware record: {key}")
            if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", key):
                raise ValueError(f"Unsafe hardware identity: {key}")
            seen.add(key)
            old = previous.get(key)
            if old:
                if old["provenance"]["verifier"] != verifier:
                    raise ValueError(f"Hardware source ownership collision: {key}")
                unchanged = {**record, "provenance": {**record["provenance"],
                                                      "last_checked": old["provenance"]["last_checked"]}}
                if old == unchanged:
                    record = unchanged
            dump(staged / "hardware" / (key + ".json"), record)
        staged_sidecar = False
        if sidecar:
            if report is not None:
                dump(staged / sidecar, report)
                staged_sidecar = True
            elif (root / sidecar).exists():
                # Nothing new to say: stage the committed accounting so the gate
                # still compares its count against this snapshot's records.
                shutil.copyfile(root / sidecar, staged / sidecar)
        validated = validate_hardware(staged)
        destination.mkdir(parents=True, exist_ok=True)
        for file in (staged / "hardware").glob("*.json"):
            shutil.copyfile(file, destination / file.name)
        for key, old in previous.items():
            if old["provenance"]["verifier"] == verifier and key not in seen:
                (destination / (key + ".json")).unlink()
        if staged_sidecar:
            shutil.copyfile(staged / sidecar, root / sidecar)
    manifest_path = root / "manifest.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text())
        if "hardware_count" in manifest:
            manifest["hardware_count"] = len(list(destination.glob("*.json")))
            dump(manifest_path, manifest)
    return validated
