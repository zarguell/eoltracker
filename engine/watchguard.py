"""WatchGuard appliance lifecycle, from WatchGuard's own end-of-life policy page.

Source: ``https://www.watchguard.com/wgrd-trust-center/end-of-life-policy``,
one server-rendered page carrying a milestone-definition table and then one
table per product family — firewalls, access points, endpoint security,
AuthPoint, Datablink and XCS. Every product row states three things: the product,
its ``End of Sale (EOS)`` date and its ``End of Life (EOL)`` date, plus a
migration path.

What becomes a milestone, and why:

* **``End of Sale (EOS)`` → ``eos``.** WatchGuard's own definition: "Last date
  for WatchGuard distribution partners to purchase specific products directly
  from WatchGuard." That is orderability, which is what ``eos`` means here.
* **``End of Life (EOL)`` → ``eol``.** "Conclusion of development and support
  for defined End-of-Sale products and subscriptions." Terminal support end.
* **``Migration Path`` → no milestone.** It is a recommendation, and it is kept
  verbatim under the record's own cells.
* **``ga`` and ``eossec`` are null.** The page states no release date and has no
  engineering-end or security-support column, so there is nothing to read for
  either. Nothing is derived from the EoS/EoL gap: WatchGuard says EOS dates are
  "up to five years prior to product EOL", *up to*, and rows break the
  heuristic — Firebox T25-W is end of sale 01 Apr 2026 and end of life
  01 Jul 2031, more than five years apart.

Every date here is vendor-stated at day precision in the page's own
``DD Mon YYYY`` (and, in one table, ``01 July 2022``) spelling. A date cell that
states prose instead of a date — WatchGuard's endpoint-security tables say
"Latest version available for new customers" and "SaaS solutions are
automatically upgraded" — publishes no milestone and is reported with its reason,
because a support statement this loose is not a deadline.

A product cell may carry a regional qualifier as italic text
("*Excludes T80 in Singapore*", "*Japan Only*"). The qualifier is kept verbatim
in the row's own cells and is not part of the published model name, which is the
product string WatchGuard itself leads the cell with.
"""
from __future__ import annotations

import hashlib
import re
from datetime import date, datetime, timezone
from pathlib import Path

from . import net, sources, tables
from .hardware import publish_records, slugify, status_from
from .importer import ROOT

SOURCE = sources.source("import-watchguard")
VERIFIER = SOURCE.verifier
REPORT = SOURCE.report
SOURCE_URL = SOURCE.url
RECORD_SCHEMA = "https://zarguell.github.io/eoltracker/v1/schema/hardware.json"
VENDOR = "WatchGuard"

# The columns the product tables state, in the page's own order.
HEADERS = ("Product", "End of Sale (EOS)", "End of Life (EOL)", "Migration Path")
# This page renders each table's column names as a line of page text above the
# table rather than as ``<th>`` cells, so the shape is declared in prose and read
# positionally. The declaration below is therefore required verbatim before any
# row is read, and every row's width must equal it: a table that gained, lost or
# reordered a column refuses instead of shifting a date into another milestone.
COLUMN_DECLARATION = " ".join(HEADERS)
MONTHS = {name: index for index, name in enumerate(
    ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"), 1)}
for _name, _index in (("January", 1), ("February", 2), ("March", 3), ("April", 4), ("May", 5),
                      ("June", 6), ("July", 7), ("August", 8), ("September", 9), ("October", 10),
                      ("November", 11), ("December", 12)):
    MONTHS[_name] = _index
DAY = re.compile(r"(?P<day>\d{1,2})\s+(?P<month>[A-Za-z]+)\s+(?P<year>\d{4})")
# A footnote marker the page appends to a date, and the italic qualifier it
# appends to a product name.
MARKER = re.compile(r"\*+")
# A product cell that says a date is for "new customers" or is conditional is a
# statement about availability, not a lifecycle deadline.
NOT_A_DEADLINE = re.compile(r"latest version|automatically upgraded|new customers|"
                            r"as long as stock|contact sales|tbd", re.IGNORECASE)


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def watchguard_day(text, where):
    """The calendar day one WatchGuard date cell states, or ``None``.

    A cell stating no date at all is absent. A cell stating prose is refused:
    this is a published column, and a value this reader cannot read is never a
    value it may approximate.
    """
    value = MARKER.sub("", tables.fold(text)).strip()
    if not value:
        return None
    match = DAY.fullmatch(value)
    if not match:
        raise ValueError(f"{where}: unrecognized WatchGuard date {value!r}")
    month = MONTHS.get(match.group("month"))
    if month is None:
        raise ValueError(f"{where}: {match.group('month')!r} is not a month name WatchGuard states")
    try:
        return date(int(match.group("year")), month, int(match.group("day"))).isoformat()
    except ValueError:
        raise ValueError(f"{where}: {value!r} is not a real calendar day") from None


def _product(text):
    """The product name a cell states, without its italic qualifier.

    ``Firebox T80`` followed by ``*Excludes T80 in Singapore*`` is one product
    with a regional qualifier. The qualifier stays verbatim in the row's own
    cells; the published name is the product string the cell leads with.
    """
    return tables.fold(MARKER.sub("", tables.fold(text)))


def _cell(text):
    """One page cell as the hardware schema's own cell shape."""
    return {"text": tables.fold(text), "value": None, "datetime": None, "role": None, "links": []}


def parse(html):
    """The page as ``(models, excluded, tables_seen)``.

    ``models`` is one entry per published product row; ``excluded`` is every
    product row that stated no lifecycle date, each with the reason; and
    ``tables_seen`` counts the tables the page published, so a report can state
    how much of the page its rows came from.
    """
    doc = tables.parse_document(html)
    # The columns are declared in the page's own text, not in the table markup,
    # so the declaration is required verbatim before a single row is read.
    if COLUMN_DECLARATION not in doc.page_text:
        raise ValueError(f"The WatchGuard page no longer states its product columns "
                         f"{list(HEADERS)}")
    models, excluded, seen = [], [], 0
    models, excluded, seen = [], [], 0
    # "Older Products" is a continuation heading the page reuses under several
    # families, so a family keeps the name of the section it continues rather
    # than becoming a family of its own.
    current = "appliances"
    for block in doc.blocks:
        rows = [row for row in block["rows"] if not (len(row) == 1)]
        if not rows:
            continue
        if all(cell["th"] for cell in rows[0]):
            # The page's own milestone-definition table: it states what each
            # word means and carries no product row.
            continue
        heading = tables.fold(block["heading"] or "")
        if heading and heading.lower() != "older products":
            current = heading
        widths = {len(row) for row in rows}
        if widths != {len(HEADERS)}:
            excluded.append({"family": current, "rows": len(rows),
                             "caption": tables.fold(rows[0][0]["text"]),
                             "reason": f"the table's rows are {sorted(widths)} cells wide where the "
                                       f"page declares the {len(HEADERS)} product columns "
                                       f"{list(HEADERS)}; its cells are reported here and none of "
                                       f"them is read"})
            continue
        family = current
        seen += 1
        for row in tables.data_rows(rows, "WatchGuard", family, HEADERS):
            product = _product(row["Product"])
            where = f"WatchGuard {product}"
            if not product:
                excluded.append({"family": family, "row": tables.fold(row["Product"]),
                                 "reason": "the row states no product name"})
                continue
            if any(NOT_A_DEADLINE.search(tables.fold(row[column])) for column in HEADERS[1:3]):
                excluded.append({"family": family, "row": product,
                                 "reason": "the row states a support or availability statement "
                                           "rather than a lifecycle deadline, so no milestone is "
                                           "read from it"})
                continue
            try:
                eos = watchguard_day(row["End of Sale (EOS)"], f"{where} End of Sale")
                eol = watchguard_day(row["End of Life (EOL)"], f"{where} End of Life")
            except ValueError as error:
                excluded.append({"family": family, "row": product, "reason": str(error)})
                continue
            if eol is None and eos is None:
                excluded.append({"family": family, "row": product,
                                 "reason": "the row states neither an end-of-sale nor an "
                                           "end-of-life date, so it publishes no milestone"})
                continue
            models.append({"family": family, "product": product,
                           "milestones": {"ga": None, "eos": eos, "eossec": None, "eol": eol},
                           "upstream": {column: _cell(row[column]) for column in HEADERS}})
    if not models:
        raise ValueError("The WatchGuard page states no product row with a lifecycle date")
    return models, excluded, seen


def _identity(model):
    """The slug a product row is published under.

    The product string WatchGuard prints is the identity, and the family it sits
    under is carried in the record's own ``family`` field. When the slug would
    lose a character the vendor printed — ``Firebox II+`` and ``Firebox II``
    slugify identically, and they are different products with different dates — a
    short digest of the exact product string is appended, so the two can never
    share one published record. The digest comes from the product text alone, so
    it is stable across refreshes.
    """
    product = tables.fold(model["product"])
    slug = slugify(product)
    if slug == product.lower().replace(" ", "-"):
        return f"watchguard-{slug}"
    return f"watchguard-{slug}-{hashlib.sha256(product.encode()).hexdigest()[:8]}"


def record_for(model, checked):
    """The published hardware record for one product row."""
    milestones = model["milestones"]
    return {
        "$schema": RECORD_SCHEMA,
        "id": _identity(model),
        "name": model["product"],
        "category": "hardware",
        "vendor": VENDOR,
        "product_line": VENDOR,
        "family": model["family"],
        "model_number": model["product"],
        "milestones": milestones,
        "status": status_from(milestones["eol"], checked),
        "upstream": model["upstream"],
        "provenance": {"source_urls": [SOURCE_URL], "verifier": VERIFIER,
                       "last_checked": checked},
    }


def report_for(models, excluded, tables_seen, checked):
    """The per-row accounting this source publishes beside its records."""
    eos = sum(1 for model in models if model["milestones"]["eos"])
    eol = sum(1 for model in models if model["milestones"]["eol"])
    return {
        "source_url": SOURCE_URL, "verifier": VERIFIER, "checked_at": checked,
        "record_scope": ("WatchGuard appliances: one hardware record per product row of the "
                         "vendor's end-of-life policy page, at the day precision the page states"),
        "rows": {"seen": len(models) + len(excluded), "published": len(models),
                 "excluded": len(excluded), "tables": tables_seen,
                 "with_eos": eos, "with_eol": eol},
        "excluded": excluded,
        "total_records": len(models),
        "limitations": [
            "End of Sale becomes eos and End of Life becomes eol, in WatchGuard's own words: the "
            "last date a partner may purchase, and the conclusion of development and support.",
            "ga and eossec are null: the page states no release date and has no engineering-end or "
            "security-support column.",
            "No date is derived from the gap between the two columns. WatchGuard says end-of-sale "
            "dates are 'up to five years prior to product EOL', and rows exceed five years.",
            "Rows whose date columns state availability prose rather than a date are excluded with "
            "their reason, not read as a deadline.",
            "A product's regional qualifier (for example 'Excludes T80 in Singapore') is kept "
            "verbatim in the row's cells and is not part of the published name.",
            "WatchGuard states no publication schedule for this page; the record's last_checked is "
            "the only freshness signal, and a quiet refresh keeps it byte-identical.",
        ],
    }


def import_watchguard(directory=None):
    """Fetch the policy page and publish every product row it dates."""
    root = Path(directory) if directory is not None else ROOT / "data"
    checked = _now()
    models, excluded, tables_seen = parse(net.get_text(SOURCE_URL))
    records, identities = [], set()
    for model in sorted(models, key=lambda entry: _identity(entry)):
        identity = _identity(model)
        if identity in identities:
            raise ValueError(f"WatchGuard: two product rows publish as {identity}")
        identities.add(identity)
        records.append(record_for(model, checked))
    report = report_for(models, excluded, tables_seen, checked)
    publish_records(records, VERIFIER, root, report)
    return (f"imported {len(records)} WatchGuard products ({report['rows']['with_eos']} with an "
            f"end-of-sale date, {report['rows']['with_eol']} with an end-of-life date); excluded "
            f"{len(excluded)} rows from {tables_seen} tables (data/{REPORT})")
