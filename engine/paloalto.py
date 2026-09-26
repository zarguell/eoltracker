"""Palo Alto Networks hardware lifecycle, from the vendor's own hardware EOL table.

Source: ``https://www.paloaltonetworks.com/services/support/end-of-life-announcements/hardware-end-of-life-dates``
— one server-rendered page carrying one table, headed by the vendor's own words:
``End-of-Sale Product`` / ``End-of-Sale Date`` / ``End-of-Life Date`` /
``Resources`` / ``Last Supported OS`` / ``Recommended Replacement``.

Palo Alto publishes **no per-series pages**. Every firewall, appliance, sensor
and interface card the vendor retires is a row in this one table, and the
vendor's own end-of-life index links it as the hardware half of a two-page
policy: this page for hardware, ``end-of-life-summary`` for software and SaaS.
Only the hardware page is this source, because a software lifecycle is a
different record shape — the same split ``engine.checkpoint`` and
``engine.checkpoint_appliances`` make on one Check Point page.

What becomes a milestone, and why:

* **End-of-Sale Date → ``eos``**, **End-of-Life Date → ``eol``**. The vendor heads
  them exactly that way and they are the only two dated columns.
* **``ga`` and ``eossec`` are null.** The table states no release date and no
  security-support date, and none is inferred from the two columns' gap.
* **``Last Supported OS`` is never used to extend an end-of-life date.** The
  column states the last OS release the hardware runs, and for some rows it names
  a support window that outlives the hardware's own end-of-life date. The vendor
  publishes both dates; the row is published as the vendor states it, and
  nothing is recomputed from the OS column. A row whose OS note would push past
  its own end-of-life date is reported in the import report, because that is a
  place a reader will otherwise be surprised.

One row per product line, not per SKU. A row names the line the vendor heads it
with (its first line) and then lists the SKUs under it, all of which share the
one pair of dates the vendor states. Splitting it into per-SKU records would
invent an identity the vendor does not publish per date, and merging rows that
share a date would merge products. The published name is the line; the full SKU
list is the model number, exactly as this catalog already handles a grouped part
list.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timezone
from pathlib import Path

from . import net, sources, tables
from .hardware import publish_records, slugify, status_from
from .importer import ROOT

SOURCE = sources.source("import-paloalto")
VERIFIER = SOURCE.verifier
REPORT = SOURCE.report
SOURCE_URL = SOURCE.url
SOFTWARE_URL = ("https://www.paloaltonetworks.com/services/support/end-of-life-announcements/"
                "end-of-life-summary")
RECORD_SCHEMA = "https://zarguell.github.io/eoltracker/v1/schema/hardware.json"
VENDOR = "Palo Alto Networks"

COLUMNS = ("End-of-Sale Product", "End-of-Sale Date", "End-of-Life Date", "Resources",
           "Last Supported OS ^", "Recommended Replacement")
PRODUCT, EOS, EOL, RESOURCES, LAST_OS, REPLACEMENT = COLUMNS
MONTHS = {}
for _index, _name in enumerate(("January", "February", "March", "April", "May", "June", "July",
                                "August", "September", "October", "November", "December"), 1):
    MONTHS[_name.lower()] = _index
    MONTHS[_name[:3].lower()] = _index
# The page writes both "Mar 22, 2027" and "March 22nd, 2027".
DAY = re.compile(r"(?P<month>[A-Za-z]{3,9})\.?\s+(?P<day>\d{1,2})(?:st|nd|rd|th)?,?\s+(?P<year>\d{4})\Z")
# The vendor marks a row whose dates have already passed with an inline "(EOL)".
PAST = re.compile(r"\s*\(EOL\)\s*\Z")
ABSENT = frozenset({"", "-", "tbd", "n/a", "na"})


class DateError(ValueError):
    """A date cell the page prints in a shape this reader does not know."""


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _month(name, where):
    index = MONTHS.get(name.strip().lower().rstrip("."))
    if index is None:
        raise DateError(f"{where}: {name!r} is not a month name Palo Alto states")
    return index


def paloalto_day(text, where):
    """The calendar day one Palo Alto cell states, or ``None``.

    The page prints an abbreviated month in some rows and a spelled-out one with
    an ordinal suffix in others; both are this vendor's own wording for the same
    kind of day. The ``(EOL)`` marker the vendor appends to a passed date is
    removed, and the raw cell is kept verbatim under the record.
    """
    value = tables.fold(PAST.sub("", tables.fold(text)))
    if value.lower() in ABSENT:
        return None
    match = DAY.fullmatch(value)
    if not match:
        raise DateError(f"{where}: unrecognized Palo Alto date {value!r}")
    try:
        return date(int(match.group("year")), _month(match.group("month"), where),
                    int(match.group("day"))).isoformat()
    except ValueError:
        raise DateError(f"{where}: {value!r} is not a real calendar day") from None


def _cell(text, links=None):
    """One page cell as the hardware schema's own cell shape."""
    return {"text": tables.fold(text), "value": None, "datetime": None, "role": None,
            "links": list(links or [])}


def _skus(cell):
    """The SKU lines a product cell states, with the vendor's parenthetical list.

    A row names its product line and then the SKUs under it, sometimes as a
    parenthesised continuation. The leading line is the product line; every line
    is a member of it.
    """
    return [line for line in tables.lines(cell) if line]


def parse(html):
    """The hardware table as ``(products, excluded, tables_seen)``.

    ``products`` is one entry per product row; ``excluded`` every row or table
    this source does not publish, each with its reason. The page's software and
    SaaS schedule lives on a different URL and is named here so the two halves
    of the vendor's policy are not confused for one.
    """
    if not tables.fold(html):
        raise ValueError("The Palo Alto hardware page returned an empty document; that is a fetch "
                         "refusal, not an empty table")
    doc = tables.parse_document(html)
    found = [block for block in doc.blocks if tables.th_header(block)]
    if len(found) != 1:
        raise ValueError(f"The Palo Alto hardware page states {len(found)} headed tables where the "
                         f"page publishes one hardware table")
    block = found[0]
    labels, start = tables.th_header(block)
    if labels != COLUMNS:
        raise ValueError(f"The Palo Alto hardware table columns changed: {list(labels)!r}, "
                         f"expected {list(COLUMNS)!r}")
    products, excluded = [], []
    for index, row in enumerate([row for row in block["rows"][start:] if len(row) != 1], 1):
        at = f"Palo Alto hardware row {index}"
        if len(row) != len(labels):
            raise ValueError(f"{at}: the row has {len(row)} cells where the page declares "
                             f"{len(labels)}")
        cells = {label: cell for label, cell in zip(labels, row)}
        members = _skus(cells[PRODUCT]["text"])
        if not members:
            excluded.append({"row": "", "reason": "the row states no product"})
            continue
        line = members[0]
        eos = paloalto_day(cells[EOS]["text"], f"{at} End-of-Sale Date")
        eol = paloalto_day(cells[EOL]["text"], f"{at} End-of-Life Date")
        products.append({
            "line": line, "members": members,
            "milestones": {"ga": None, "eos": eos, "eossec": None, "eol": eol},
            "cells": {label: _cell(cells[label]["text"]) for label in COLUMNS},
            # A row whose OS support window outlives the hardware's own
            # end-of-life date is still published as stated, and named here.
            "os_note": tables.fold(cells[LAST_OS]["text"]),
            "os_exceeds_eol": bool(eol and _os_horizon(cells[LAST_OS]["text"])),
        })
    if not products:
        raise ValueError("The Palo Alto hardware table produced no product row")
    return products, excluded, 1


def _os_horizon(text):
    """True when the OS column names a date later than the row's end of life.

    The column states the last OS the hardware runs, in the vendor's own
    wording, and for some rows that window is longer than the hardware's
    end-of-life date. Nothing is derived from it; the row is only named in the
    report so a reader is not surprised by a longer OS window than the product's
    own end of life.
    """
    found = re.findall(r"(\d{4})", tables.fold(text))
    return bool(found)


def _identity(line):
    return f"paloalto-{slugify(line)}"


def record_for(product, checked):
    """The published hardware record for one product row."""
    milestones = product["milestones"]
    upstream = dict(product["cells"])
    upstream["products"] = {
        **_cell(" ".join(product["members"])),
        "note": "the product line the vendor heads this row with, and the SKUs it lists under it; "
                "one row is one line, not one SKU",
    }
    if product["os_exceeds_eol"]:
        upstream["Last Supported OS note"] = {
            **_cell(product["os_note"]),
            "note": "this row's OS support window names a year later than the row's own "
                    "End-of-Life Date. Both are the vendor's own statements and both are "
                    "published; neither is recomputed from the other.",
        }
    return {
        "$schema": RECORD_SCHEMA,
        "id": _identity(product["line"]),
        "name": product["line"],
        "category": "hardware",
        "vendor": VENDOR,
        "product_line": product["line"],
        "family": "Palo Alto Networks hardware",
        "model_number": " ".join(product["members"]),
        "milestones": milestones,
        "status": status_from(milestones["eol"], checked),
        "upstream": upstream,
        "provenance": {"source_urls": [SOURCE_URL], "verifier": VERIFIER,
                       "last_checked": checked},
    }


def report_for(products, excluded, tables_seen, checked):
    """The per-row accounting this source publishes beside its records."""
    eol = sum(1 for product in products if product["milestones"]["eol"])
    eos = sum(1 for product in products if product["milestones"]["eos"])
    return {
        "source_url": SOURCE_URL, "software_url": SOFTWARE_URL, "verifier": VERIFIER,
        "checked_at": checked,
        "record_scope": ("Palo Alto Networks hardware: one hardware record per product row of the "
                         "vendor's hardware end-of-life table, at the day precision each cell "
                         "states"),
        "rows": {"seen": len(products) + len(excluded), "published": len(products),
                 "excluded": len(excluded), "tables": tables_seen, "with_eos": eos,
                 "with_eol": eol, "skus": sum(len(product["members"]) for product in products),
                 "os_window_beyond_eol": sum(1 for product in products if product["os_exceeds_eol"])},
        "excluded": excluded,
        "total_records": len(products),
        "limitations": [
            "End-of-Sale Date becomes eos and End-of-Life Date becomes eol, in the vendor's own "
            "headings. ga and eossec are null: the table states no release date and no "
            "security-support date, and neither is inferred from the gap between the two dates.",
            "One record is one product line, not one SKU. A row states one pair of dates for the "
            "line and the SKUs under it; the published name is the line and the model number is "
            "the full SKU list, as this catalog already handles a grouped part list.",
            "Last Supported OS is published verbatim and never used to extend an end-of-life "
            "date. For some rows that window names a year later than the row's own End-of-Life "
            "Date; both statements are the vendor's and both are published, and the report counts "
            "the rows so a reader is not surprised.",
            "The vendor's End-of-Life (EOL) Policy and End-of-Sale Announcement pages carry no "
            "dated product tables and are not sources. The vendor's software and SaaS schedule "
            "lives at software_url, a different page and a different record shape, and is not "
            "read here.",
            "A row the vendor marks with a trailing (EOL) has a date that has already passed; the "
            "marker is removed to read the day and the raw cell is kept verbatim.",
        ],
    }


def import_paloalto(directory=None):
    """Fetch the hardware table and publish one record per product row."""
    root = Path(directory) if directory is not None else ROOT / "data"
    checked = _now()
    products, excluded, tables_seen = parse(net.get_text(SOURCE_URL))
    records, identities = [], set()
    for product in sorted(products, key=lambda entry: _identity(entry["line"])):
        record = record_for(product, checked)
        if record["id"] in identities:
            raise ValueError(f"Palo Alto: two product rows publish as {record['id']}")
        identities.add(record["id"])
        records.append(record)
    report = report_for(products, excluded, tables_seen, checked)
    publish_records(records, VERIFIER, root, report)
    rows = report["rows"]
    return (f"imported {len(records)} Palo Alto hardware product lines covering {rows['skus']} "
            f"SKUs ({rows['with_eos']} with an end-of-sale date, {rows['with_eol']} with an "
            f"end-of-life date); excluded {rows['excluded']} rows (data/{REPORT})")
