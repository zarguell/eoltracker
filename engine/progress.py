"""Progress Software product-family lifecycle collectors (#127, #128, #129, #131).

Four public Progress pages, four products sets, one shared reading of the
vendor's own Zoomin/Sitefinity table shapes:

* **OpenEdge + OpenEdge Pro2** — ``docs.progress.com/bundle/openedge-life-cycle``.
  Four tables (current OpenEdge, current Pro2, retired OpenEdge, retired Pro2),
  38 release rows. ``Active`` is the vendor's GA column, ``Retired`` its
  terminal support end. ``Sunset`` is a phase in which updates and
  certifications continue, so it is *not* ``eossec`` (a generic support date
  never fills a security-only end) and it stays the vendor's own cell; the same
  is true of Pro2's ``Sunset*``, whose footnote makes it contingent on the next
  LTS GA and therefore never a plain date. The page mixes month precision
  (``2024-Jan``, ``2023-May``) and day precision (``2028-Jan-01``,
  ``2030-Jan-31``) in one column: each cell keeps the width it states and none
  is padded into the other (AGENTS.md rule 4). ``TBD*`` is a release trigger
  with no announced release, so ``eol`` stays null and the vendor's cell is
  kept verbatim. The page's third-party section is not a Progress lifecycle and
  is excluded with the vendor's own sentence as its reason.

* **Corticon + Corticon.js** — two bundles, one table shape, 28 release rows.
  The sibling pages differ in the vendor's own month spelling (``2025-Nov`` and
  ``2025-April``) and in their layout row (``RETIRED`` on the Corticon page,
  ``Retired:`` on the Corticon.js page), and the Corticon.js rows carry a
  ```- ``` identity prefix. Both spellings are accepted, an unknown month word
  refuses the whole page, the layout row is counted and named rather than
  parsed as a release, and the prefix is normalized while the raw cell is kept
  under ``upstream.cells``.

* **WhatsUp Gold** — ``docs.progress.com/bundle/whatsup-gold-life-cycle``,
  three release tables (current, retired, deprecated) plus an
  ``End-of-Sale (EoS) Offerings`` table. The deprecated table's phase columns
  are printed ``Retired | Deprecated`` — the reverse of the two tables above —
  so its columns are resolved by *label*: 24.0 is Retired 2025-Jun and
  Deprecated 2026-Apr, and only the ``Retired`` column may become ``eol``. The
  deprecated date is a phase change, not a support end, and the vendor's own
  policy page defines Deprecated as "critical security fixes on a case-by-case
  basis" rather than an end. ``Next-GA`` is a named trigger whose calendar date
  the page states is not yet announced, so 26.0's ``eol`` stays null.
  **Offering/release scope decision** (issue #129's open question): the six
  EoS rows are *offerings* — editions and add-on licenses — not releases, and
  the vendor's End-of-Sale Policy states that an EoS offering "is no longer
  available for new purchase" and "cannot be renewed at the next support and
  maintenance anniversary". That is orderability, not a support end, and the
  schema models ``eos`` per release. They are therefore excluded from the
  release record, each with its offering name, its EoS month, its suggested
  replacement and a reason, and the policy sentence that licenses the reason is
  required verbatim from the policy page. Nothing in this module ever maps an
  EoS date to ``eol``.

* **Sitefinity** — ``progress.com/support/sitefinity-lifecycle-policy``, 19
  data rows that the vendor's own grouped rows expand to 23 distinct versions
  (the collector's issue counted 17 rows / 21 versions; the saved page states
  19 rows and the grouping rule yields 23, and the fixture is the authority —
  see the report). ``Active (GA)`` is a named month, ``Retired`` the terminal
  support end, ``Sunset`` the vendor's own critical-updates-only phase, and
  ``Limited Backport Requests Through`` an entitlement window with no milestone
  of its own, so it is retained verbatim and never mapped. Two cells state no
  deadline: ``N/A`` (no date stated) and ``No earlier than Jan 2030***``, a
  floor the vendor says "may be extended further" — a floor is not a deadline,
  so 15.4's ``eol`` stays null. The page also states the one explicit
  day-derivation rule in this vendor ("Sunset and Retired phases start on the
  first day of the month indicated in the table"); it lives here as the
  separate :func:`sitefinity_first_of_month` helper, it is never applied by the
  collector's own refresh, and the report records the decision as Main's
  (issue #132). The "Show all versions" control row is counted as an excluded
  control row, and the tail it may hide is named as a limitation instead of
  being guessed.

Row accounting and fail-closed behaviour are shared: every parser reads the
vendor's declared tables by heading, resolves each column by its *label*,
refuses a renamed/dropped/duplicated table, a renamed column, a span where the
source states none, a row whose width disagrees with its header, an unknown
month word, an impossible calendar day, and a date-shaped value outside the
reviewed vocabularies — and every data row it saw is either published or
reported as an exclusion with a truthful reason (AGENTS.md rule 6).

The registry owns the ids, pages and verifiers; their values are declared here
as the contract Main registers (``engine.sources``) and are listed in
``SPECS``. Nothing here references an upstream tracker.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path

from . import derived, net, sources, tables, transaction
from .importer import ROOT

# The registry owns the pages, verifiers and report names: this module reads
# them from there rather than restating a URL or an id the site also publishes.
OPENEDGE = sources.source("import-progress-openedge")
CORTICON = sources.source("import-progress-corticon")
WHATSUP = sources.source("import-progress-whatsup-gold")
SITEFINITY = sources.source("import-progress-sitefinity")

OPENEDGE_URL = OPENEDGE.url
CORTICON_URL = CORTICON.url
CORTICON_JS_URL = CORTICON.pages[1].url
WHATSUP_URL = WHATSUP.url
WHATSUP_POLICY_URL = WHATSUP.pages[1].url
SITEFINITY_URL = SITEFINITY.url

OPENEDGE_VERIFIER = OPENEDGE.verifier
CORTICON_VERIFIER = CORTICON.verifier
WHATSUP_VERIFIER = WHATSUP.verifier
SITEFINITY_VERIFIER = SITEFINITY.verifier
OPENEDGE_REPORT = OPENEDGE.report
CORTICON_REPORT = CORTICON.report
WHATSUP_REPORT = WHATSUP.report
SITEFINITY_REPORT = SITEFINITY.report
RECORD_SCHEMA = "https://zarguell.github.io/eoltracker/v1/schema/product.json"
UPSTREAM_CATEGORY = "app"

# What each registered source publishes: the registry entry a test drives, the
# records it owns and the report it accounts for.
SPECS = (
    {"id": "import-progress-openedge", "entry": "import_openedge",
     "verifier": OPENEDGE_VERIFIER, "report": OPENEDGE_REPORT,
     "records": ("openedge", "openedge-pro2")},
    {"id": "import-progress-corticon", "entry": "import_corticon",
     "verifier": CORTICON_VERIFIER, "report": CORTICON_REPORT,
     "records": ("corticon", "corticon-js")},
    {"id": "import-progress-whatsup-gold", "entry": "import_whatsup",
     "verifier": WHATSUP_VERIFIER, "report": WHATSUP_REPORT,
     "records": ("whatsup-gold",)},
    {"id": "import-progress-sitefinity", "entry": "import_sitefinity",
     "verifier": SITEFINITY_VERIFIER, "report": SITEFINITY_REPORT,
     "records": ("sitefinity",)},
)

# --- The vendor's date grammars --------------------------------------------
MONTH_NAMES = ("January", "February", "March", "April", "May", "June", "July",
               "August", "September", "October", "November", "December")
# Both spellings the sibling Progress pages state are resolved by one lookup:
# ``2025-Nov`` (OpenEdge, Corticon) and ``2025-April`` (Corticon.js). A word
# that is not a month name is not in the table, so it refuses the parse.
MONTHS = {}
for _index, _name in enumerate(MONTH_NAMES, 1):
    MONTHS[_name] = _index
    MONTHS[_name[:3]] = _index
MONTHS["Sept"] = 9
DAY_FORM = re.compile(r"(?P<year>\d{4})-(?P<month>[A-Z][a-z]+)-(?P<day>\d{2})\Z")
MONTH_FORM = re.compile(r"(?P<year>\d{4})-(?P<month>[A-Z][a-z]+)\Z")
NAMED_MONTH_FORM = re.compile(r"(?P<month>[A-Z][a-z]+) (?P<year>\d{4})\Z")
# Cells that state no date at all, in the spelling the Progress tables use.
# Deliberately narrow: ``TBD``, ``Next-GA``, ``No earlier than ...`` and the
# contingent Pro2/13.0 cells are *not* here, because each carries a vendor
# statement this module has to handle explicitly rather than pass as unknown.
NO_DATE = frozenset({"", "-", "–", "—", "n/a", "n/a.", "na"})
# The vendor's own "not yet scheduled" cell in a terminal column. It is a
# release trigger with no announced calendar date, so it publishes a null
# milestone; the vendor's footnote explaining it is required verbatim.
TBD = "tbd"
TRIGGER_CELLS = frozenset({"tbd", "tbd*", "next-ga"})
# The two anchors that identify the EoS/lifecycle vocabulary the vendor states.
OPENEDGE_TBD_QUOTE = ("OpenEdge 13.0 will retire when the next OpenEdge release becomes "
                      "generally available")
OPENEDGE_CONTINGENT_QUOTE = ("Sunset date is contingent on GA of the next LTS release, "
                             "subject to revision")
OPENEDGE_THIRD_PARTY_HEADING = "OpenEdge Third-Party Product Life Cycle"
OPENEDGE_THIRD_PARTY_QUOTE = "Progress resells third-party products along with OpenEdge"
WHATSUP_NEXT_GA_QUOTE = ("Actual calendar date will be substituted when the next release date "
                         "is announced")
# The vendor's own statement that an EoS offering can no longer be bought or
# renewed. The page prints its policy text with literal escape sequences inside
# longer sentences, so the quote is the contiguous fragment the page states
# verbatim rather than a reflowed sentence it never prints.
WHATSUP_EOS_QUOTE = ("cannot be renewed at the next support and maintenance anniversary")
SITEFINITY_GA_QUOTE = "Active phase starts on the GA date. The month is provided for reference"
SITEFINITY_PHASE_QUOTE = ("Sunset and Retired phases start on the first day of the month "
                          "indicated in the table")
SITEFINITY_FLOOR_QUOTE = ("At this point, the expected retirement date for Sitefinity 15.4 LTS is "
                          "open and may be extended further past Jan 2030 depending on business "
                          "conditions")
SITEFINITY_RETIRED_QUOTE = ("Releases and versions not included in the table below should be "
                            "considered retired")
# The vendor's own way of stating that a version is unavailable/undated without
# naming a deadline. ``Until retired`` and ``Month of ... release`` prose live in
# the backport column, which states no milestone and is never parsed as a date.
SITEFINITY_FLOOR = re.compile(r"No earlier than (?P<floor>[A-Z][a-z]{2} \d{4})\**\Z")
SITEFINITY_VERSION = re.compile(r"Sitefinity\s+(?P<version>\d+(?:\.\d+)*(?:\.x)?)")
# Two stated shapes this schedule uses that the schema cannot hold: a bare year
# ("2020" for the 13.0/13.1/13.2 row) and a month window shared by a grouped
# row ("March-Nov 2022" for 14.1/14.2/14.3). Both publish no milestone and are
# named in the report; anything else outside the month grammar refuses.
SITEFINITY_YEAR = re.compile(r"\d{4}")
SITEFINITY_WINDOW = re.compile(r"[A-Z][a-z]{2,8}-[A-Z][a-z]{2,8} \d{4}")
SITEFINITY_CONTROL = "Show all versions"
# Every version row the saved page states, and the grouping rule that expands
# it. Declared so a silently shrunk table refuses rather than publishing a
# smaller inventory.
SITEFINITY_TABLE = "Supported and Retired Versions Schedule"
# The only table caption/heading Progress gives these tables.
OPENEDGE_NAV_HEADINGS = ("OpenEdge Life Cycle",)
WHATSUP_NAV_HEADINGS = ("Life Cycle",)

# --- Table/column declarations ---------------------------------------------
# ``role`` decides what a leaf column may become. ``subject`` is the release
# identity, ``update`` a patch-version cell, ``compat`` the OpenEdge database
# compatibility cell, ``replacement`` the EoS table's suggestion, ``vendor`` a
# vendor phase with no normalized milestone of its own, and ``ga``/``eol`` the
# two labels that do map. Every table's leaves are matched exactly, so a
# renamed or reordered column refuses instead of shifting a date into another
# milestone (this is the WhatsUp ``Retired | Deprecated`` hazard).
SUBJECT, UPDATE, COMPAT, REPLACEMENT, VENDOR, GA, EOL = (
    "subject", "update", "compat", "replacement", "vendor", "ga", "eol")
OPENEDGE_COLUMNS = (("Product Release", SUBJECT), ("Latest Product Update (U)", UPDATE),
                    ("Active", GA), ("Sunset", VENDOR), ("Retired", EOL))
OPENEDGE_PRO2_LTS_COLUMNS = (
    ("Version Family", SUBJECT), ("Latest Version", UPDATE), ("Active", GA),
    ("Sunset*", VENDOR), ("Retired", EOL),
    ("Source OpenEdge Database Version Compatibility", COMPAT))
OPENEDGE_PRO2_RETIRED_COLUMNS = (
    ("Version Family", SUBJECT), ("Latest Version", UPDATE), ("Active", GA),
    ("Retired", EOL), ("Source OpenEdge Database Version Compatibility", COMPAT))
CORTICON_COLUMNS = (("Product Release", SUBJECT), ("Latest Product Update (U)", UPDATE),
                    ("Active", GA), ("Sunset (Mature)", VENDOR), ("Retired", EOL))
WHATSUP_COLUMNS = (("Product Release", SUBJECT), ("Latest Product Update", UPDATE),
                   ("Active", GA), ("Retired", EOL))
WHATSUP_DEPRECATED_COLUMNS = (("Product Release", SUBJECT), ("Latest Product Update", UPDATE),
                              ("Retired", EOL), ("Deprecated", VENDOR))
WHATSUP_OFFERING_COLUMNS = (("Offering", SUBJECT), ("EoS Date", VENDOR),
                            ("Suggested Replacement", REPLACEMENT))
SITEFINITY_COLUMNS = (("Version", SUBJECT), ("Active (GA)", GA),
                      ("Limited Backport Requests Through*", VENDOR),
                      ("Sunset", VENDOR), ("Retired", EOL))
# Which layout label separates the current rows from the retired rows on each
# Corticon-family page. Both are in-body group labels, not releases.
LAYOUT_LABELS = {CORTICON_URL: "RETIRED", CORTICON_JS_URL: "Retired:"}


@dataclass(frozen=True)
class Table:
    """One declared vendor table: its heading and its exact leaf columns."""

    heading: str
    columns: tuple
    # Whether a cell in this table's ``Retired`` column may be the vendor's
    # "not yet scheduled" trigger instead of a date.
    trigger: bool = False


OPENEDGE_TABLES = (
    Table("OpenEdge Product Life Cycle", OPENEDGE_COLUMNS, trigger=True),
    Table("OpenEdge Pro2 Life Cycle", OPENEDGE_PRO2_LTS_COLUMNS),
    Table("Retired OpenEdge Releases", OPENEDGE_COLUMNS),
    Table("Retired OpenEdge Pro2 Releases", OPENEDGE_PRO2_RETIRED_COLUMNS),
)
CORTICON_TABLES = {CORTICON_URL: Table("Corticon Life Cycle", CORTICON_COLUMNS),
                   CORTICON_JS_URL: Table("Corticon.js", CORTICON_COLUMNS)}
WHATSUP_TABLES = (
    Table("WhatsUp Gold Life Cycle", WHATSUP_COLUMNS, trigger=True),
    Table("Retired WhatsUp Gold Releases", WHATSUP_COLUMNS),
    Table("Deprecated WhatsUp Gold Releases", WHATSUP_DEPRECATED_COLUMNS),
)
WHATSUP_OFFERINGS = Table("End-of-Sale (EoS) Offerings", WHATSUP_OFFERING_COLUMNS)
SITEFINITY_TABLE_SPEC = Table(SITEFINITY_TABLE, SITEFINITY_COLUMNS)


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


# Text folding, the page reader and the row readers live in engine.tables, so a
# second vendor collector reads tables with the same code rather than a copy.
_fold = tables.fold
_lines = tables.lines
parse_document = tables.parse_document
heading_table = tables.heading_table
header_rows = tables.header_rows
spanned_rows = tables.spanned_rows


def data_rows(rows, where, spec, labels):
    """Every data row as a ``{label: cell text}`` mapping; width is exact."""
    return tables.data_rows(rows, where, spec.heading, labels)


def header_labels(block, where, spec):
    """The leaf column labels of a grouped vendor header, in order.

    The first header row carries the subject columns and a spanned group label
    (``Life Cycle by Product Release``); the second row spells the group's own
    leaves (``Active``/``Sunset``/``Retired``). The labels are compared to the
    declared table verbatim, so a renamed group member — or a reordered pair
    like WhatsUp's ``Retired | Deprecated`` — is a refusal, never a shifted
    date.
    """
    headers, start = header_rows(block, where)
    if len(headers) > 2:
        raise ValueError(f"{where}: {spec.heading} header has {len(headers)} rows")
    top = headers[0]
    groups = [cell for cell in top if cell["span"][1] > 1]
    if groups and len(headers) != 2:
        raise ValueError(f"{where}: {spec.heading} spans a column group with no leaf row")
    if len(groups) > 1:
        raise ValueError(f"{where}: {spec.heading} spans more than one column group")
    leaves = []
    if not groups:
        leaves = [_fold(cell["text"]) for cell in top]
        spanned = [cell for cell in top if cell["span"][0] > 1]
        if spanned:
            raise ValueError(f"{where}: {spec.heading} spans a header cell vertically")
    else:
        group = groups[0]
        second = headers[1]
        if any(cell["span"] != (1, 1) for cell in second):
            raise ValueError(f"{where}: {spec.heading} leaf header carries a span")
        if len(second) != group["span"][1]:
            raise ValueError(f"{where}: {spec.heading} group spans {group['span'][1]} columns "
                             f"but its leaf row states {len(second)}")
        for cell in top:
            if cell is group:
                leaves.extend(_fold(leaf["text"]) for leaf in second)
            elif cell["span"][0] != 2:
                raise ValueError(f"{where}: {spec.heading} header cell {cell['text']!r} carries "
                                 f"an unexpected span {cell['span']}")
            else:
                leaves.append(_fold(cell["text"]))
        if _fold(group["text"]) in leaves:
            raise ValueError(f"{where}: {spec.heading} group label is also a leaf")
    labels = tuple(leaves)
    declared = tuple(label for label, _role in spec.columns)
    if labels != declared:
        raise ValueError(f"{where}: {spec.heading} columns changed: {labels!r}, "
                         f"expected {declared!r}")
    return labels, start


# --- Shared date reading ----------------------------------------------------
def _month(value, where):
    try:
        return MONTHS[value]
    except KeyError:
        raise ValueError(f"{where}: {value!r} is not a month name this source states") from None


def progress_date(text, where, named=False):
    """One Progress date cell at the precision the vendor writes.

    ``2028-Jan-01`` is a day, ``2024-Jan`` a month, ``2025-April`` the same
    month in the sibling page's spelling, and ``January 2024`` the named form
    the offering tables use. A month is never widened into a day and a day is
    never narrowed into a month (AGENTS.md rule 4). The reviewed no-date tokens
    publish ``None``; anything else — a bare year, a month spelling the vendor
    does not use, a day the calendar does not have — refuses the parse rather
    than passing as an unknown.
    """
    value = _fold(text)
    if value.lower() in NO_DATE:
        return None
    match = DAY_FORM.fullmatch(value)
    if match:
        month = _month(match.group("month"), where)
        try:
            return date(int(match.group("year")), month, int(match.group("day"))).isoformat()
        except ValueError:
            raise ValueError(f"{where}: {value!r} is not a real calendar day") from None
    match = MONTH_FORM.fullmatch(value)
    if match:
        return f"{int(match.group('year')):04d}-{_month(match.group('month'), where):02d}"
    if named:
        match = NAMED_MONTH_FORM.fullmatch(value)
        if match:
            return f"{int(match.group('year')):04d}-{_month(match.group('month'), where):02d}"
    raise ValueError(f"{where}: unrecognized Progress date {value!r}")


def milestone_cell(cells, label, role, where, trigger=False):
    """The milestone a cell states, or ``None`` when it states none.

    Only the two labels the vendor uses for general availability and terminal
    support become milestones. A vendor phase column (``Sunset``, ``Deprecated``)
    is validated as a date at its stated precision — so a reshaped cell cannot
    pass unnoticed — and then retained verbatim as the vendor's own cell, never
    mapped to ``eossec`` or ``eol``. The remaining columns are not dates at
    all: ``Latest Product Update (U)`` is a patch version, the Pro2
    compatibility column is a database-version list, and ``Suggested
    Replacement`` is prose, so each is carried verbatim without a date grammar
    that would refuse the vendor's own wording.
    """
    text = cells[label]
    value = _fold(text)
    if role == VENDOR:
        token = value.lower()
        if token in TRIGGER_CELLS or token in NO_DATE:
            return None
        return progress_date(text, f"{where} {label}")
    if role == GA:
        return progress_date(text, f"{where} {label}")
    if role == EOL:
        token = value.lower()
        if token in TRIGGER_CELLS:
            if token.endswith("*") and not trigger:
                raise ValueError(f"{where}: {label} states {value!r}, which this table's own "
                                 f"footnote does not license")
            # A bare 'TBD' is an unannounced date and 'TBD*' is the vendor's
            # footnoted release trigger. Both publish no milestone, and the
            # page-level check requires the footnote that explains the latter.
            return None
        return progress_date(text, f"{where} {label}")
    if role in (UPDATE, COMPAT, REPLACEMENT):
        # The vendor may publish no update for a release, so an empty cell is
        # an absent value, not a reshaped one.
        return None
    raise ValueError(f"{where}: unknown column role {role!r}")


def require_quote(page_text, quote, where):
    """Refuse when the vendor page no longer states ``quote`` word for word."""
    if quote not in page_text:
        raise ValueError(f"{where}: the vendor page no longer states {quote!r}")


def _clean_subject(text, where):
    """A release identity cell with the vendor's own list prefix removed.

    The Corticon.js page prefixes every retired row's identity with ``- ``; the
    prefix is stripped for the release id while the raw cell is kept verbatim
    under ``upstream.cells`` (issue #128).
    """
    value = _fold(text)
    if value.startswith("- "):
        value = value[2:].strip()
    if not value:
        raise ValueError(f"{where}: row states no release identity")
    return value


def _release(release_id, name, milestones, cells, table, extra=None):
    upstream = {"name": name, "cells": cells, "table": table}
    if extra:
        upstream.update(extra)
    return {"id": release_id, "name": name, "milestones": milestones, "upstream": upstream}


def _milestones(ga, eol):
    return {"ga": ga, "eos": None, "eossec": None, "eol": eol}


def read_phase_table(block, spec, where, subject_clean=None):
    """One declared phase table as ``(releases, cells_rows, controls)``.

    ``cells_rows`` is every data row's own ``{label: text}`` mapping, so a
    caller can report layout rows and count source rows independently of the
    releases it built from them. ``controls`` are the table's full-width
    control rows, which no declared phase table states today; a caller either
    accounts for them by name or refuses the page.
    """
    labels, start = header_labels(block, where, spec)
    body, controls = spanned_rows(block, labels, start)
    rows = data_rows(body, where, spec, labels)
    subject = next(label for label, role in spec.columns if role == SUBJECT)
    releases = []
    for index, cells in enumerate(rows, 1):
        at = f"{where} {spec.heading} row {index}"
        raw = _fold(cells[subject])
        if not raw:
            raise ValueError(f"{at}: row states no release identity")
        declared = dict(spec.columns)
        milestones = _milestones(
            milestone_cell(cells, next(label for label, role in spec.columns if role == GA),
                           GA, at) if GA in declared.values() else None,
            milestone_cell(cells, next(label for label, role in spec.columns if role == EOL),
                           EOL, at, trigger=spec.trigger))
        # Every non-milestone column is date-validated here, so a reshaped
        # vendor cell refuses the whole table instead of being carried blind.
        for label, role in spec.columns:
            if role in (VENDOR, COMPAT, REPLACEMENT, UPDATE):
                milestone_cell(cells, label, role, at)
        name = (subject_clean or _clean_subject)(cells[subject], at)
        releases.append(_release(name, name, milestones, cells, spec.heading))
    return releases, rows, controls



def _ids_unique(releases, where):
    seen = set()
    for release in releases:
        if release["id"] in seen:
            raise ValueError(f"{where}: duplicate release scope {release['id']!r}")
        seen.add(release["id"])
    return releases


# --- OpenEdge + OpenEdge Pro2 (issue #127) ---------------------------------


def parse_openedge(html):
    """The four OpenEdge tables as ``(releases, excluded, accounting)``.

    The page's own third-party section states no Progress lifecycle: it links a
    separate guide and says so, so it is excluded with that sentence as the
    reason (a section-level entry whose ``rows`` is 0, because the section
    publishes no row). The two jump-list tables are excluded as navigation.
    Every other row is published, including the retired-history tables, so
    ``accounting['rows']['seen']`` is the page's own data-row count.
    """
    doc = parse_document(html)
    where = "OpenEdge"
    releases, excluded, tables = [], [], []
    for spec in OPENEDGE_TABLES:
        block = heading_table(doc, spec.heading, where)
        rows, cells_rows, controls = read_phase_table(block, spec, where)
        if controls:
            raise ValueError(f"{where}: the {spec.heading!r} table states unrecognized control "
                             f"row(s) {controls}")
        for release in rows:
            release["upstream"]["family"] = (
                "openedge-pro2" if spec.columns == OPENEDGE_PRO2_LTS_COLUMNS
                or spec.columns == OPENEDGE_PRO2_RETIRED_COLUMNS else "openedge")
        releases.extend(rows)
        tables.append({"table": spec.heading, "rows": len(cells_rows), "published": len(rows),
                       "excluded": 0})
    if any(cell.lower().startswith(TBD) for release in releases
           for label, cell in release["upstream"]["cells"].items() if label == "Retired"):
        require_quote(doc.page_text, OPENEDGE_TBD_QUOTE, where)
    require_quote(doc.page_text, OPENEDGE_CONTINGENT_QUOTE, "OpenEdge Pro2")
    for heading in OPENEDGE_NAV_HEADINGS:
        block = heading_table(doc, heading, where)
        nav = [row for row in block["rows"]]
        if any(cell["th"] for row in nav for cell in row):
            raise ValueError(f"{where}: the {heading!r} jump list gained a header")
        for row in nav:
            excluded.append({"table": heading, "context": "navigation", "rows": 1,
                             "cells": [_fold(cell["text"]) for cell in row],
                             "reason": "the page's jump list of section links is navigation, "
                                       "not a lifecycle row"})
    if OPENEDGE_THIRD_PARTY_HEADING in doc.headings:
        require_quote(doc.page_text, OPENEDGE_THIRD_PARTY_QUOTE, where)
        excluded.append({"table": OPENEDGE_THIRD_PARTY_HEADING, "context": "third-party",
                         "rows": 0, "quote": OPENEDGE_THIRD_PARTY_QUOTE,
                         "reason": "the vendor states this section covers third-party products "
                                   "Progress resells, whose lifecycles Progress does not govern; "
                                   "it publishes no OpenEdge lifecycle row"})
    _ids_unique(releases, where)
    accounting = {"tables": tables, "rows": _rows(len(releases), excluded)}
    return releases, excluded, accounting


def _rows(published, excluded, retained=0):
    """The report's row arithmetic: every source row counted exactly once."""
    dropped = sum(entry["rows"] for entry in excluded)
    return {"seen": published + dropped, "published": published, "retained": retained,
            "excluded": dropped}


def openedge_record(releases, checked):
    return _record("openedge", "Progress OpenEdge", releases, OPENEDGE_URL,
                   OPENEDGE_VERIFIER, checked,
                   labels={"ga": "Active", "eol": "Retired"},
                   links={"html": OPENEDGE_URL, "pro2 life cycle":
                          "https://docs.progress.com/bundle/openedge-life-cycle/page/"
                          "OpenEdge-Life-Cycle.html#OpenEdge-Pro2-Life-Cycle"})


def openedge_pro2_record(releases, checked):
    return _record("openedge-pro2", "Progress OpenEdge Pro2", releases, OPENEDGE_URL,
                   OPENEDGE_VERIFIER, checked,
                   labels={"ga": "Active", "eol": "Retired"},
                   links={"html": OPENEDGE_URL})


def _record(product_id, name, releases, source_url, verifier, checked, labels=None, links=None,
            upstream_category=UPSTREAM_CATEGORY):
    return {
        "$schema": RECORD_SCHEMA,
        "id": product_id,
        "name": name,
        "category": "software",
        "upstream_category": upstream_category,
        # The vendor publishes no CPE for these products, and an invented one
        # would be a claim the source does not make.
        "identifiers": [],
        "labels": labels or {},
        "links": links or {"html": source_url},
        "releases": releases,
        "provenance": {"source_url": source_url, "verifier": verifier,
                       "last_checked": checked, "upstream_modified": None},
    }


def combine(releases, committed, where):
    """This fetch's rows plus the committed history the source no longer states."""
    if committed is None:
        return releases, []
    ids = {release["id"] for release in releases}
    kept = [{**release, "upstream": {**release["upstream"], "in_source": False}}
            for release in committed["releases"] if release["id"] not in ids]
    if not kept:
        return releases, []
    # The source states its own order (newest first, as the page renders it);
    # retained history is appended so a dropped row is visible, never hidden.
    return releases + kept, [{"id": release["id"], "name": release["name"],
                              "reason": f"the {where} page no longer states this scope; the "
                                        f"committed row and its dates are retained"}
                             for release in kept]


def _check_release(release, expected, where):
    if release["id"] != expected["id"] or release["name"] != expected["name"]:
        raise ValueError(f"{where}: {release['id']!r} does not re-derive from its stored cells "
                         f"({expected['id']!r})")
    if release["milestones"] != expected["milestones"]:
        raise ValueError(f"{where}: {release['id']} milestones contradict its stored vendor cells")
    if release["upstream"] != expected["upstream"]:
        raise ValueError(f"{where}: {release['id']} upstream record contradicts its stored cells")


def _check_identity(record, product_id, verifier, source_url):
    if (record.get("id") != product_id or record.get("category") != "software"
            or (record.get("provenance") or {}).get("verifier") != verifier
            or (record.get("provenance") or {}).get("source_url") != source_url
            or not record.get("releases")):
        raise ValueError(f"Invalid Progress source identity for {product_id}")
    seen = set()
    for release in record["releases"]:
        if release["id"] in seen:
            raise ValueError(f"{product_id}: duplicate release {release['id']!r}")
        seen.add(release["id"])


def _check_retained(release):
    marker = release["upstream"].get("in_source")
    if marker not in (None, False):
        raise ValueError(f"{release['id']}: upstream.in_source must be absent or False")


def validate_openedge(record):
    """Rebuild every OpenEdge and Pro2 row from its own stored cells, offline.

    One source owns both product lines, so one validator serves both records:
    it reads each row from the table the row names, and a row whose table
    belongs to the other product line is a record claiming a row it does not
    own.
    """
    product_id = record.get("id")
    if product_id not in ("openedge", "openedge-pro2"):
        raise ValueError(f"Unknown OpenEdge record {product_id!r}")
    _check_identity(record, product_id, OPENEDGE_VERIFIER, OPENEDGE_URL)
    specs = {spec.heading: spec for spec in OPENEDGE_TABLES}
    for release in record["releases"]:
        _check_retained(release)
        upstream = release["upstream"]
        spec = specs.get(upstream.get("table"))
        if spec is None:
            raise ValueError(f"{record['id']}/{release['id']} does not name the OpenEdge table it "
                             f"came from")
        labels, _roles = _declared(spec)
        cells = upstream.get("cells")
        if not isinstance(cells, dict) or tuple(cells) != labels:
            raise ValueError(f"{record['id']}/{release['id']} does not carry its table's columns")
        family = "openedge-pro2" if spec in (OPENEDGE_TABLES[1], OPENEDGE_TABLES[3]) else "openedge"
        if upstream.get("family") != family:
            raise ValueError(f"{record['id']}/{release['id']} names the wrong product family")
        if family != product_id:
            raise ValueError(f"{record['id']}/{release['id']} belongs to {family}, not to this "
                             f"record")
        _check_release(release, _expected_from_cells(spec, cells,
                                                     f"{record['id']}/{release['id']}",
                                                     {"family": family}), record["id"])


def _declared(spec):
    return tuple(label for label, _role in spec.columns), dict(spec.columns)


def _expected_from_cells(spec, cells, where, extra=None):
    """One release re-derived from its own stored vendor cells."""
    roles = dict(spec.columns)
    subject = next(label for label, role in roles.items() if role == SUBJECT)
    ga_label = next((label for label, role in roles.items() if role == GA), None)
    eol_label = next(label for label, role in roles.items() if role == EOL)
    for label, role in roles.items():
        if role == VENDOR:
            milestone_cell(cells, label, role, where)
    name = _clean_subject(cells[subject], where)
    return _release(name, name, _milestones(
        milestone_cell(cells, ga_label, GA, where) if ga_label else None,
        milestone_cell(cells, eol_label, EOL, where, trigger=spec.trigger)),
        cells, spec.heading, extra)


def import_openedge(directory=None):
    """Fetch the OpenEdge page and publish the two Progress-owned records."""
    root = Path(directory) if directory is not None else ROOT / "data"
    committed = {product_id: transaction.committed_product_record(
        root, product_id, OPENEDGE_VERIFIER, validate_openedge, "Progress OpenEdge")
        for product_id in ("openedge", "openedge-pro2")}
    checked = _now()
    releases, excluded, accounting = parse_openedge(net.get_text(OPENEDGE_URL))
    families = {family: [release for release in releases
                         if release["upstream"]["family"] == family]
                for family in ("openedge", "openedge-pro2")}
    for family in families:
        if not families[family]:
            raise ValueError(f"OpenEdge page states no {family} release row")
    counts = {family: len(families[family]) for family in families}
    kept = []
    records = []
    for product_id, builder in (("openedge", openedge_record),
                                ("openedge-pro2", openedge_pro2_record)):
        rows, history = combine(families[product_id], committed[product_id],
                                f"OpenEdge {product_id}")
        record = builder(rows, checked)
        validate_openedge(record)
        records.append(record)
        kept.extend(history)
    report = {
        "source_url": OPENEDGE_URL, "verifier": OPENEDGE_VERIFIER, "checked_at": checked,
        "record_scope": ("Progress OpenEdge and OpenEdge Pro2 release families: two software "
                         "records, one release per vendor row, at the month or day precision the "
                         "vendor's own cell states"),
        "rows": accounting["rows"], "tables": accounting["tables"], "excluded": excluded,
        "retained": kept,
        "products": {"openedge": counts["openedge"], "openedge-pro2": counts["openedge-pro2"]},
        "total_records": 2,
        "limitations": [
            "Sunset is the vendor's own phase, not a normalized milestone: the page states that "
            "updates and certifications continue in it, so it never fills eossec (a generic "
            "support date) and stays verbatim under upstream.cells.",
            "OpenEdge 13.0's Retired cell is TBD*, and the page's footnote states the release "
            "trigger ('will retire when the next OpenEdge release becomes generally available') "
            "without a dated release; no eol is published, and no date is derived.",
            "Pro2 6.5's Sunset cell is a date whose column the page footnotes as contingent on "
            "the next LTS GA and 'subject to revision', so it is retained as a cell and never "
            "published as a settled date.",
            "Month and day precision are both present in one column on this page; each cell keeps "
            "the width the vendor states and neither width is padded into the other.",
            "The page's third-party section is not a Progress lifecycle and is excluded with the "
            "vendor's own sentence as its reason.",
            "Progress publishes no eos for any OpenEdge release, so eos is null everywhere.",
        ],
    }
    transaction.publish_product_records(records, report, root, OPENEDGE_REPORT)
    return (f"imported {counts['openedge']} OpenEdge and {counts['openedge-pro2']} OpenEdge Pro2 "
            f"release scopes; excluded {accounting['rows']['excluded']} rows, retained "
            f"{len(report['retained'])} (data/{OPENEDGE_REPORT})")


# --- Corticon + Corticon.js (issue #128) -----------------------------------
def parse_corticon(html, url=CORTICON_URL):
    """One Corticon-family page as ``(releases, accounting)``.

    The shared shape covers both pages; ``url`` selects the page's own declared
    table heading and layout label. The layout row that separates current from
    retired rows is counted and named, never parsed as a release, and a page
    that loses it refuses (a group label that vanishes is a reshaped table).
    """
    where = "Corticon.js" if url == CORTICON_JS_URL else "Corticon"
    spec = CORTICON_TABLES[url]
    layout = LAYOUT_LABELS[url]
    doc = parse_document(html)
    block = heading_table(doc, spec.heading, where)
    labels, start = header_labels(block, where, spec)
    body, controls = spanned_rows(block, labels, start)
    if controls:
        raise ValueError(f"{where}: the lifecycle table states unrecognized control row(s) "
                         f"{controls}")
    rows = data_rows(body, where, spec, labels)
    subject = next(label for label, role in spec.columns if role == SUBJECT)
    releases, layout_rows = [], 0
    for index, cells in enumerate(rows, 1):
        at = f"{where} row {index}"
        if _fold(cells[subject]) == layout:
            if any(_fold(value) for label, value in cells.items() if label != subject):
                raise ValueError(f"{at}: the {layout!r} layout row states other cells")
            layout_rows += 1
            continue
        releases.append(read_one(spec, cells, at))
    if layout_rows != 1:
        raise ValueError(f"{where}: expected exactly one {layout!r} layout row, found {layout_rows}")
    _ids_unique(releases, where)
    return releases, {"table": spec.heading, "rows": len(rows), "published": len(releases),
                      "layout": layout_rows}


def read_one(spec, cells, where):
    """One phase-table row as a release, without duplicating the column rules."""
    roles = dict(spec.columns)
    subject = next(label for label, role in roles.items() if role == SUBJECT)
    ga_label = next((label for label, role in roles.items() if role == GA), None)
    eol_label = next(label for label, role in roles.items() if role == EOL)
    for label, role in roles.items():
        if role in (VENDOR, COMPAT, REPLACEMENT, UPDATE):
            milestone_cell(cells, label, role, where)
    name = _clean_subject(cells[subject], where)
    return _release(name, name, _milestones(
        milestone_cell(cells, ga_label, GA, where) if ga_label else None,
        milestone_cell(cells, eol_label, EOL, where, trigger=spec.trigger)), cells, spec.heading)




def corticon_records(releases, page, checked):
    """Split one page's rows into the product that page documents."""
    js = page == CORTICON_JS_URL
    product_id = "corticon-js" if js else "corticon"
    name = "Progress Corticon.js" if js else "Progress Corticon"
    return _record(product_id, name, releases, page, CORTICON_VERIFIER,
                   checked, labels={"ga": "Active", "eol": "Retired"},
                   links={"html": page},
                   upstream_category="framework" if js else "app")


def validate_corticon(record):
    """Rebuild every Corticon/Corticon.js row from its own stored cells, offline."""
    _check_identity(record, record.get("id"), CORTICON_VERIFIER, record["provenance"]["source_url"])
    if record["id"] not in ("corticon", "corticon-js"):
        raise ValueError(f"Unknown Corticon record {record['id']!r}")
    if record["provenance"]["verifier"] != CORTICON_VERIFIER:
        raise ValueError("Corticon record does not carry the Corticon verifier")
    url = CORTICON_JS_URL if record["id"] == "corticon-js" else CORTICON_URL
    if record["provenance"]["source_url"] != url:
        raise ValueError(f"{record['id']} does not name its own vendor page")
    spec = CORTICON_TABLES[url]
    labels = tuple(label for label, _role in spec.columns)
    for release in record["releases"]:
        _check_retained(release)
        upstream = release["upstream"]
        if upstream.get("table") != spec.heading:
            raise ValueError(f"{record['id']}/{release['id']} does not name its vendor table")
        cells = upstream.get("cells")
        if not isinstance(cells, dict) or tuple(cells) != labels:
            raise ValueError(f"{record['id']}/{release['id']} does not carry its table's columns")
        if release["id"] == LAYOUT_LABELS[url] or _fold(cells["Product Release"]) == \
                LAYOUT_LABELS[url]:
            raise ValueError(f"{record['id']}/{release['id']} publishes the vendor's layout row")
        _check_release(release, read_one(spec, cells, f"{record['id']}/{release['id']}"),
                       record["id"])


def import_corticon(directory=None):
    """Fetch both Corticon pages and publish both records and one report."""
    root = Path(directory) if directory is not None else ROOT / "data"
    committed = {product_id: transaction.committed_product_record(
        root, product_id, CORTICON_VERIFIER, validate_corticon, "Progress Corticon")
        for product_id in ("corticon", "corticon-js")}
    checked = _now()
    pages = ((CORTICON_URL, "corticon"), (CORTICON_JS_URL, "corticon-js"))
    parsed, report_tables = {}, []
    for url, product_id in pages:
        releases, accounting = parse_corticon(net.get_text(url), url)
        if not releases:
            raise ValueError(f"{url} states no release row")
        parsed[product_id] = releases
        report_tables.append(dict(accounting, url=url, product=product_id))
    retained = []
    records = []
    for url, product_id in pages:
        rows, kept = combine(parsed[product_id], committed[product_id], product_id)
        record = corticon_records(rows, url, checked)
        validate_corticon(record)
        records.append(record)
        retained.extend(kept)
    total_rows = sum(table["rows"] for table in report_tables)
    published = sum(table["published"] for table in report_tables)
    if total_rows != published + sum(table["layout"] for table in report_tables):
        raise ValueError("Corticon row accounting does not reconcile")
    report = {
        "verifier": CORTICON_VERIFIER, "checked_at": checked,
        "source_url": CORTICON_URL, "corticon_js_url": CORTICON_JS_URL,
        "record_scope": ("Progress Corticon and Corticon.js release families: two software "
                         "records, one per vendor page, at the month precision both pages state"),
        "rows": {"seen": total_rows, "published": published,
                 "retained": len(retained), "excluded": sum(t["layout"] for t in report_tables)},
        "tables": report_tables, "retained": retained,
        "excluded": [{"table": entry["table"], "url": entry["url"], "context": "layout",
                      "rows": entry["layout"], "text": entry["layout"],
                      "reason": "the vendor's own in-table group label separating current from "
                                "retired rows: it states no release identity or date, and is "
                                "counted and named rather than published as a release"}
                     for entry in report_tables],
        "products": {product_id: len(parsed[product_id]) for _url, product_id in pages},
        "total_records": 2,
        "limitations": [
            "The two pages differ in the vendor's own month spelling ('2025-Nov' on the Corticon "
            "page, '2025-April' on the Corticon.js page); both are accepted and an unknown month "
            "word refuses the page instead of being read as an absent date.",
            "Corticon.js retired rows prefix the release identity with '- '; the prefix is "
            "normalized for the release id and the raw cell stays verbatim under upstream.cells.",
            "Sunset (Mature) is the vendor's own phase and never fills eossec or eol; eos is "
            "absent because neither page states an end of sale.",
            "'-' and 'TBD' state no date: they publish a null milestone while the vendor's own "
            "cell is retained verbatim.",
        ],
    }
    transaction.publish_product_records(records, report, root, CORTICON_REPORT)
    return (f"imported {len(parsed['corticon'])} Corticon and {len(parsed['corticon-js'])} "
            f"Corticon.js release scopes; excluded {report['rows']['excluded']} layout rows, "
            f"retained {len(retained)} (data/{CORTICON_REPORT})")


# --- WhatsUp Gold (issue #129) ---------------------------------------------
def parse_whatsup(html):
    """The WhatsUp release tables as ``(releases, excluded, accounting)``.

    Only the ``Retired`` column becomes ``eol``. The deprecated table's own
    columns are ``Retired | Deprecated`` — resolved by label, so 24.0 is
    Retired 2025-Jun and Deprecated 2026-Apr — and its ``Deprecated`` cell is
    retained as the vendor's phase cell because the vendor defines Deprecated
    as a migration signal with case-by-case critical fixes, not a support end.
    The EoS offerings table is excluded row by row with its offering name, its
    EoS month and its suggested replacement retained (the offering/release
    scope decision recorded for issue #129).
    """
    doc = parse_document(html)
    where = "WhatsUp Gold"
    releases, excluded, tables = [], [], []
    for spec in WHATSUP_TABLES:
        block = heading_table(doc, spec.heading, where)
        rows, cells_rows, controls = read_phase_table(block, spec, where)
        if controls:
            raise ValueError(f"{where}: the {spec.heading!r} table states unrecognized control "
                             f"row(s) {controls}")
        releases.extend(rows)
        tables.append({"table": spec.heading, "rows": len(cells_rows), "published": len(rows),
                       "excluded": 0})
    any_trigger = any(_fold(cell).lower() == "next-ga" for release in releases
                      for cell in release["upstream"]["cells"].values())
    if any_trigger:
        require_quote(doc.page_text, WHATSUP_NEXT_GA_QUOTE, where)
    offerings = heading_table(doc, WHATSUP_OFFERINGS.heading, where)
    offering_labels, offering_start = header_labels(offerings, where, WHATSUP_OFFERINGS)
    offering_body, offering_controls = spanned_rows(offerings, offering_labels, offering_start)
    if offering_controls:
        raise ValueError(f"{where}: the EoS offerings table states unrecognized control row(s) "
                         f"{offering_controls}")
    offerings_seen = 0
    for index, cells in enumerate(data_rows(offering_body, where, WHATSUP_OFFERINGS,
                                            offering_labels), 1):
        at = f"{where} EoS offerings row {index}"
        month = progress_date(cells["EoS Date"], at, named=True)
        if month is None:
            raise ValueError(f"{at}: the offering states no EoS month")
        offerings_seen += 1
        excluded.append({"table": WHATSUP_OFFERINGS.heading, "context": "offering", "rows": 1,
                         "offering": _fold(cells["Offering"]), "eos": month,
                         "suggested_replacement": _fold(cells["Suggested Replacement"]),
                         "reason": "an offering (edition, add-on or license type), not a release: "
                                   "the vendor's End-of-Sale Policy defines the EoS date as "
                                   "orderability, not support end, and the schema models eos per "
                                   "release"})
    for heading in WHATSUP_NAV_HEADINGS:
        block = heading_table(doc, heading, where)
        if any(cell["th"] for row in block["rows"] for cell in row):
            raise ValueError(f"{where}: the {heading!r} jump list gained a header")
        for row in block["rows"]:
            excluded.append({"table": heading, "context": "navigation", "rows": 1,
                             "cells": [_fold(cell["text"]) for cell in row],
                             "reason": "the page's jump list of section links is navigation, not "
                                       "a lifecycle row"})
    _ids_unique(releases, where)
    accounting = {"tables": tables, "rows": _rows(len(releases), excluded),
                  "offerings": offerings_seen}
    return releases, excluded, accounting


def whatsup_record(releases, checked):
    return _record("whatsup-gold", "Progress WhatsUp Gold", releases, WHATSUP_URL,
                   WHATSUP_VERIFIER, checked, labels={"ga": "Active", "eol": "Retired"},
                   links={"html": WHATSUP_URL, "end-of-sale policy": WHATSUP_POLICY_URL})


def validate_whatsup(record):
    """Rebuild every WhatsUp row from its own stored cells, offline."""
    _check_identity(record, "whatsup-gold", WHATSUP_VERIFIER, WHATSUP_URL)
    specs = {spec.heading: spec for spec in WHATSUP_TABLES}
    for release in record["releases"]:
        _check_retained(release)
        upstream = release["upstream"]
        spec = specs.get(upstream.get("table"))
        if spec is None:
            raise ValueError(f"{record['id']}/{release['id']} does not name the WhatsUp table it "
                             f"came from")
        labels = tuple(label for label, _role in spec.columns)
        cells = upstream.get("cells")
        if not isinstance(cells, dict) or tuple(cells) != labels:
            raise ValueError(f"{record['id']}/{release['id']} does not carry its table's columns")
        if "Active" not in labels and release["milestones"]["ga"] is not None:
            raise ValueError(f"{record['id']}/{release['id']} claims a ga the deprecated table "
                             f"does not state")
        _check_release(release, _expected_from_cells(spec, cells,
                                                     f"{record['id']}/{release['id']}"),
                       record["id"])
        if release["upstream"]["cells"]["Retired"].lower() == "next-ga" \
                and release["milestones"]["eol"] is not None:
            raise ValueError(f"{record['id']}/{release['id']} publishes a date for the unannounced "
                             f"Next-GA trigger")


def import_whatsup(directory=None):
    """Fetch the WhatsUp page and its EoS policy, and publish the record."""
    root = Path(directory) if directory is not None else ROOT / "data"
    committed = transaction.committed_product_record(
        root, "whatsup-gold", WHATSUP_VERIFIER, validate_whatsup, "Progress WhatsUp Gold")
    checked = _now()
    html = net.get_text(WHATSUP_URL)
    policy = " ".join(net.get_text(WHATSUP_POLICY_URL).replace("\xa0", " ").split())
    require_quote(policy, WHATSUP_EOS_QUOTE, "WhatsUp Gold End-of-Sale Policy")
    releases, excluded, accounting = parse_whatsup(html)
    if not releases:
        raise ValueError("WhatsUp Gold page states no release row")
    rows, kept = combine(releases, committed, "WhatsUp Gold")
    record = whatsup_record(rows, checked)
    validate_whatsup(record)
    report = {
        "source_url": WHATSUP_URL, "policy_url": WHATSUP_POLICY_URL,
        "verifier": WHATSUP_VERIFIER, "checked_at": checked,
        "record_scope": ("Progress WhatsUp Gold release families and deprecated releases: one "
                         "software record, one release per vendor row, at the month precision the "
                         "page states"),
        "rows": accounting["rows"], "tables": accounting["tables"], "excluded": excluded,
        "retained": kept, "total_records": 1,
        "offering_scope_decision": {
            "decision": "excluded",
            "offerings": accounting["offerings"],
            "quote": WHATSUP_EOS_QUOTE,
            "policy_url": WHATSUP_POLICY_URL,
            "reason": "the six EoS rows name offerings (editions, add-on licenses), not releases; "
                      "the vendor's policy defines the EoS date as the end of orderability and "
                      "renewal, and the schema has no offering scope, so they are reported as "
                      "exclusions rather than republished as invented releases",
        },
        "limitations": [
            "The deprecated table states its phase columns as 'Retired | Deprecated', the reverse "
            "of the tables above; columns are resolved by label, so 24.0 is Retired 2025-Jun and "
            "Deprecated 2026-Apr.",
            "Deprecated is not a support end: the vendor's policy defines it as no new features "
            "with critical security fixes on a case-by-case basis, so the cell stays a vendor "
            "cell and never fills eol or eossec.",
            "26.0's Retired cell is Next-GA, a named release trigger whose calendar date the page "
            "states is not yet announced, so its eol is null and no date is derived.",
            "The deprecated table states no 'Active' column, so those releases have no ga date "
            "and none is inferred from their retirement date.",
            "eos is null for every release: the page's only end-of-sale data is offering-level, "
            "and an offering EoS date is never mapped to a release milestone.",
        ],
    }
    transaction.publish_product_record(record, report, root, WHATSUP_REPORT)
    return (f"imported {len(releases)} WhatsUp Gold release scopes; excluded "
            f"{accounting['rows']['excluded']} rows ({accounting['offerings']} EoS offerings); "
            f"retained {len(kept)} (data/{WHATSUP_REPORT})")


# --- Sitefinity (issue #131) -----------------------------------------------
def sitefinity_versions(cell, where):
    """The versions one Version cell states, in the vendor's own order."""
    lines = _lines(cell) or [_fold(cell)]
    versions = []
    for line in lines:
        found = SITEFINITY_VERSION.findall(line)
        if not found:
            raise ValueError(f"{where}: version cell line {line!r} names no Sitefinity version")
        versions.extend(found)
        # A line that names a version and states anything else substantive is a
        # shape this reader does not know. The page's own annotations are the
        # LTS marker, the current-release marker and its footnote asterisks;
        # they are consumed here and kept verbatim in the row's own cells.
        residue = SITEFINITY_VERSION.sub("", line)
        residue = (residue.replace("Sitefinity", "").replace("(LTS)", "").replace("LTS", "")
                   .replace("(Current Release)", "").replace("**", "").replace("*", "").strip())
        if residue:
            raise ValueError(f"{where}: version cell line {line!r} states unrecognized text "
                             f"{residue!r}")
    for previous, version in zip(versions, versions[1:]):
        if _version_key(version) <= _version_key(previous):
            raise ValueError(f"{where}: version cell {cell!r} is out of order")
    return versions


def _version_key(version):
    if version.endswith(".x"):
        return tuple(int(part) for part in version[:-2].split(".")) + (0,)
    return tuple(int(part) for part in version.split("."))


def parse_sitefinity(html):
    """The Sitefinity schedule as ``(releases, excluded, accounting)``.

    Grouped version rows are expanded under the vendor's own grouping: a row
    whose Version cell names several versions states one GA, one backport
    window, one Sunset and one Retired date for all of them, so each version
    becomes a release carrying the row's shared cells and the row's own version
    cell under ``upstream.group``. ``N/A`` states no date, and a cell of the
    form ``No earlier than <month>`` is a floor the vendor says may be
    extended, so it publishes a null milestone while the cell stays verbatim.
    """
    doc = parse_document(html)
    where = "Sitefinity"
    require_quote(doc.page_text, SITEFINITY_GA_QUOTE, where)
    require_quote(doc.page_text, SITEFINITY_PHASE_QUOTE, where)
    require_quote(doc.page_text, SITEFINITY_RETIRED_QUOTE, where)
    block = heading_table(doc, SITEFINITY_TABLE, where)
    labels, start = header_labels(block, where, SITEFINITY_TABLE_SPEC)
    body, controls = spanned_rows(block, labels, start)
    rows = data_rows(body, where, SITEFINITY_TABLE_SPEC, labels)
    releases, excluded, grouped = [], [], 0
    for text in controls:
        if text != SITEFINITY_CONTROL:
            raise ValueError(f"{where}: the schedule states an unrecognized control row {text!r}")
        excluded.append({"table": SITEFINITY_TABLE, "context": "control", "rows": 1,
                         "text": text,
                         "reason": "the page's 'Show all versions' control row toggles the "
                                   "rendered schedule; it states no version or date"})
    withheld = []
    for index, cells in enumerate(rows, 1):
        at = f"{where} row {index}"
        versions = sitefinity_versions(cells["Version"], at)
        ga = _sitefinity_date(cells["Active (GA)"], f"{at} Active (GA)", withheld)
        # Sunset is validated at its stated precision and then kept only as the
        # vendor's own cell: a critical-updates-only phase is not a milestone.
        _sitefinity_date(cells["Sunset"], f"{at} Sunset", withheld)
        retired = _sitefinity_phase(cells["Retired"], f"{at} Retired", withheld)
        if len(versions) > 1:
            grouped += 1
        for version in versions:
            extra = {"group": _fold(cells["Version"])} if len(versions) > 1 else None
            releases.append(_release(version, f"Progress Sitefinity {version}",
                                     _milestones(ga, retired), cells, SITEFINITY_TABLE, extra))
    _ids_unique(releases, where)
    if any(_fold(cell).startswith("No earlier than")
           for release in releases for label, cell in release["upstream"]["cells"].items()
           if label == "Retired"):
        require_quote(doc.page_text, SITEFINITY_FLOOR_QUOTE, where)
    accounting = {"table": SITEFINITY_TABLE, "rows": len(rows), "published": len(releases),
                  "grouped_rows": grouped, "control": len(excluded),
                  "not_representable": withheld,
                  "rows_arithmetic": _rows(len(releases), excluded)}
    return releases, excluded, accounting


def _sitefinity_date(text, where, withheld):
    """One Sitefinity schedule cell, or ``None`` for a stated shape we cannot hold.

    A month is a milestone; a bare year and a month window are stated dates the
    schema has no width for, so they publish nothing and are named in the
    report instead of being narrowed to a month or widened to a day
    (AGENTS.md rules 2 and 4). Every other unrecognised shape refuses.
    """
    value = _fold(text)
    try:
        return progress_date(text, where, named=True)
    except ValueError:
        row = re.search(r"row (?P<row>\d+)", where)
        entry = {"row": int(row.group("row")) if row else None,
                 "column": where.rsplit(" ", 1)[-1], "cell": value}
        if SITEFINITY_WINDOW.fullmatch(value):
            entry["shape"] = "month window"
            entry["reason"] = ("the vendor states one Active date spanning several months for the "
                               "versions grouped in this row; a window is not a milestone, and "
                               "narrowing it to either end would invent a date the vendor does "
                               "not state")
            withheld.append(entry)
            return None
        if SITEFINITY_YEAR.fullmatch(value):
            entry["shape"] = "year"
            entry["reason"] = ("the vendor states a year with no month; the schema holds a day or "
                               "a month, and choosing a month would state a date the vendor does "
                               "not give")
            withheld.append(entry)
            return None
        raise


def _sitefinity_phase(text, where, withheld=None):
    """A Sunset/Retired cell: a stated month, a floor, or no date at all."""
    value = _fold(text)
    if SITEFINITY_FLOOR.fullmatch(value):
        # 'No earlier than <month>' is a lower bound the vendor states may be
        # extended: a floor is not a deadline, so nothing is published from it.
        return None
    if withheld is None:
        return progress_date(text, where, named=True)
    return _sitefinity_date(text, where, withheld)


def sitefinity_record(releases, checked):
    return _record("sitefinity", "Progress Sitefinity", releases, SITEFINITY_URL,
                   SITEFINITY_VERIFIER, checked,
                   labels={"ga": "Active (GA)", "eol": "Retired"},
                   links={"html": SITEFINITY_URL})


def validate_sitefinity(record):
    """Rebuild every Sitefinity row from its own stored cells, offline."""
    _check_identity(record, "sitefinity", SITEFINITY_VERIFIER, SITEFINITY_URL)
    labels, _roles = _declared(SITEFINITY_TABLE_SPEC)
    for release in record["releases"]:
        _check_retained(release)
        upstream = release["upstream"]
        if upstream.get("table") != SITEFINITY_TABLE:
            raise ValueError(f"{record['id']}/{release['id']} does not name the vendor table")
        cells = upstream.get("cells")
        if not isinstance(cells, dict) or tuple(cells) != labels:
            raise ValueError(f"{record['id']}/{release['id']} does not carry its table's columns")
        at = f"{record['id']}/{release['id']}"
        versions = sitefinity_versions(cells["Version"], at)
        if release["id"] not in versions:
            raise ValueError(f"{at} is not one of its own row's versions {versions}")
        group = upstream.get("group")
        if (len(versions) > 1) != bool(group):
            raise ValueError(f"{at} does not carry its row's grouped-version text")
        if group is not None and group != _fold(cells["Version"]):
            raise ValueError(f"{at} grouped-version text is not its row's own cell")
        # The same reviewed grammar the refresh reads: a stated month, or one of
        # the two stated shapes the schema cannot hold (a bare year, a month
        # window), which publish no milestone and are named in the report.
        withheld = []
        ga = _sitefinity_date(cells["Active (GA)"], f"{at} Active (GA)", withheld)
        _sitefinity_date(cells["Sunset"], f"{at} Sunset", withheld)
        expected = _release(release["id"], release["name"],
                            _milestones(ga, _sitefinity_phase(cells["Retired"],
                                                             f"{at} Retired", withheld)),
                            cells, SITEFINITY_TABLE, {"group": group} if group else None)
        _check_release(release, expected, record["id"])
        # The vendor's first-of-month rule is a derivation, and a record that
        # ever publishes it must carry the rule that re-derives it; the
        # collector publishes stated months only, so this is absent today.
        derived.validate_milestone_provenance(
            release["milestones"], release.get(derived.DERIVED_KEY), at,
            {other["id"] for other in record["releases"]})


def sitefinity_first_of_month(release, page_text=None, phases=False):
    """The first-of-month days the vendor's own phase rule derives, per release.

    The vendor states the rule verbatim: "Sunset and Retired phases start on
    the first day of the month indicated in the table" (and, for the beginning,
    "Active phase starts on the GA date. The month is provided for reference"
    — either way the *month* is what the table states, at month precision).
    This helper is deliberately separate from the collector's refresh: applying
    it turns a month-precision cell into a derived calendar day, which is
    issue #132's decision, and the report records that the decision is Main's.

    It returns the derived days plus the rule fields, and ``None`` for a cell
    that states no deadline — including ``No earlier than Jan 2030***``, whose
    floor the vendor says may be extended and which is therefore never a
    derived deadline. When ``page_text`` is supplied the licensing sentence is
    required verbatim, so this cannot derive under a rule the vendor dropped.
    When ``phases`` is true the Sunset/Retired rule is required too, because
    only that sentence licenses deriving those two dates.
    """
    if page_text is not None:
        require_quote(_fold(page_text), SITEFINITY_GA_QUOTE, "Sitefinity")
        if phases:
            require_quote(_fold(page_text), SITEFINITY_PHASE_QUOTE, "Sitefinity")
    ga = progress_date(release["upstream"]["cells"]["Active (GA)"], "Sitefinity ga", named=True)
    if ga is None:
        raise ValueError("Sitefinity row states no Active (GA) month to derive from")
    result = {
        "release_id": release["id"],
        "derived": {"ga": f"{ga}-01"},
        "rule": {"ga": SITEFINITY_GA_QUOTE, "source_url": SITEFINITY_URL,
                 "base_month": release["upstream"]["cells"]["Active (GA)"],
                 "base_label": "the month indicated in the table"},
        "unsupported": ["eos", "eossec"],
        "not_derived": [],
    }
    if phases:
        for key, label in (("sunset", "Sunset"), ("eol", "Retired")):
            cell = release["upstream"]["cells"][label]
            month = _sitefinity_phase(cell, f"Sitefinity {label}")
            if month is None:
                result["not_derived"].append({"milestone": key, "cell": _fold(cell)})
                continue
            result["derived"][key] = f"{month}-01"
            result["rule"][key] = SITEFINITY_PHASE_QUOTE
    return result


def import_sitefinity(directory=None):
    """Fetch the Sitefinity policy page and publish the record at stated precision."""
    root = Path(directory) if directory is not None else ROOT / "data"
    committed = transaction.committed_product_record(
        root, "sitefinity", SITEFINITY_VERIFIER, validate_sitefinity, "Progress Sitefinity")
    checked = _now()
    html = net.get_text(SITEFINITY_URL)
    releases, excluded, accounting = parse_sitefinity(html)
    if not releases:
        raise ValueError("Sitefinity page states no version row")
    rows, kept = combine(releases, committed, "Sitefinity")
    record = sitefinity_record(rows, checked)
    validate_sitefinity(record)
    report = {
        "source_url": SITEFINITY_URL, "verifier": SITEFINITY_VERIFIER, "checked_at": checked,
        "record_scope": ("Progress Sitefinity release versions stated by the vendor's Supported and "
                         "Retired Versions Schedule: one software record, one release per version, "
                         "at the month precision the table states"),
        "rows": {**accounting["rows_arithmetic"], "retained": len(kept)},
        "table": {k: v for k, v in accounting.items() if k != "rows_arithmetic"},
        "grouping_rule": ("a row whose Version cell names several versions states one Active (GA), "
                          "one backport window, one Sunset and one Retired date for all of them, so "
                          "the row is expanded into one release per version, each carrying the "
                          "row's shared cells and the row's own version cell under upstream.group"),
        "excluded": excluded, "retained": kept, "total_records": 1,
        "derivation_decision": {
            "owner": "Main (issue #132)",
            "published": "stated months only",
            "helper": "engine.progress.sitefinity_first_of_month",
            "quote": SITEFINITY_PHASE_QUOTE,
            "reason": "the vendor states that Sunset and Retired start on the first day of the "
                      "month indicated, so those cells could be published as derived day "
                      "milestones with milestone_provenance; this collector publishes the stated "
                      "months and the helper performs the derivation, leaving the decision to "
                      "publish derived dates (and their feed/OpenEoX exclusions) to #132",
            "floor_not_derived": SITEFINITY_FLOOR_QUOTE,
        },
        "limitations": [
            "The issue that asked for this collector counted 17 rows expanding to 21 versions; "
            "the saved page states 19 data rows and the grouping rule yields 23 versions. The "
            "fixture is the authority and the difference is reported rather than reconciled by "
            "inventing rows.",
            "The vendor states the version table's dates at month precision only; no day is "
            "padded into any milestone.",
            "'No earlier than Jan 2030***' is a floor the vendor says may be extended, not a "
            "deadline, so 15.4 (LTS)'s eol is null.",
            "'Limited Backport Requests Through*' states an entitlement window, not a lifecycle "
            "end; it is retained verbatim and never mapped to a milestone.",
            "Sunset is the vendor's own critical-updates-only phase (at Progress's discretion), "
            "never eossec; eos is absent because the page states none.",
            "The table ends at 4.x and presents a 'Show all versions' control; the page's "
            "server-rendered table states no row older than 4.x, and any tail behind that "
            "control is not retrievable from the fetched document, so it is named here and "
            "nothing is inferred from the control's existence.",
        ],
    }
    transaction.publish_product_record(record, report, root, SITEFINITY_REPORT)
    return (f"imported {len(releases)} Sitefinity versions from {accounting['rows']} rows "
            f"({accounting['grouped_rows']} grouped); excluded {accounting['control']} control "
            f"row, retained {len(kept)} (data/{SITEFINITY_REPORT})")
