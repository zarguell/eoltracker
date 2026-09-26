"""Extreme Networks product lifecycle, from the vendor's own end-of-sale extract.

Source: the two static spreadsheet extracts Extreme Networks publishes from its
end-of-sale index page
(``https://www.extremenetworks.com/support/end-of-sale-and-end-of-support-products/``):

* the **EOS** sheet — ``Marketing Part Number | Product Name | Product Short
  Description | EOS date | EOSM date | EOSL date``, and
* the **EOSL** sheet — the same columns without the software-maintenance one,
  carrying a different and larger set of part numbers.

Both are single-sheet XLSX files served from the vendor's content hub under
``/api/public/``, which that host's robots.txt explicitly allows. Nothing here
needs JavaScript, an account, or a challenge, and the dates are read from the
vendor's own cells rather than computed.

**The mapping, in the vendor's words.** The index page defines each column:

* **EOS** — "The product End of Sale (EOS) date is the last date a product is
  available for sale through Extreme Networks sales systems." That is
  orderability, so it becomes ``eos``.
* **EOSL** — "The End of Service Life (EOSL) date is the last date to receive
  service and support from the Extreme Networks' Global Technical Assistance Team
  (GTAC)." Terminal support end, so it becomes ``eol``.
* **EOSM** — "The End of Software Maintenance (EOSM) is the date that software
  (firmware and applications) will cease providing maintenance releases, bug
  fixes or vulnerability patches for a product that is in the End of Life
  phase." That is a *maintenance* window, which this repository never maps to
  ``eossec``: a software-maintenance date is not a stated security-support end.
  The cell is published verbatim and ``eossec`` is null.

**Nothing is derived.** The index page also states a support rule — "Access to
Extreme's Global Technical Assistance Center (GTAC) will be available for a
period of 5 years from the End of Sale (EOS) date for hardware" — and this
collector applies it nowhere: every published date is a cell the vendor wrote.

**Two things the file does not define, and this collector does not invent.**
The three identifier columns (marketing part number, product name, short
description) carry no data dictionary, so they are carried verbatim and the
part number is the record's identity only because the vendor's own file is keyed
on it. The dates are stored as Excel serial numbers, an encoding the vendor
documents nowhere, so the decoder is explicit about what it accepts, refuses the
serials the 1900 epoch leaves ambiguous, and publishes the raw value beside the
day it read.

**The file's own version signal.** Cell A1 of every sheet is a run date —
"Run date December 16, 2025" on the live file. It is read, required, and
published in the report, because a spreadsheet that changes shape usually
changes its run date first.
"""
from __future__ import annotations

import hashlib
import io
import re
import zipfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from . import net, sources, tables
from .hardware import publish_records, slugify, status_from
from .importer import ROOT

SOURCE = sources.source("import-extreme")
VERIFIER = SOURCE.verifier
REPORT = SOURCE.report
SOURCE_URL = SOURCE.url
INDEX_URL = ("https://www.extremenetworks.com/support/"
             "end-of-sale-and-end-of-support-products/")
RECORD_SCHEMA = "https://zarguell.github.io/eoltracker/v1/schema/hardware.json"
VENDOR = "Extreme Networks"

# The two extracts the vendor publishes. Both are read, and a part number that
# appears in both is reconciled rather than published twice.
FILES = {
    "EOS": ("https://extr-p-001.sitecorecontenthub.cloud/api/public/content/"
            "7625ff270f974e338948ad890b5f9ec4?v=6d523767",
            ("Marketing Part Number", "Product Name", "Product Short Description",
             "EOS date", "EOSM date", "EOSL date")),
    "EOSL": ("https://extr-p-001.sitecorecontenthub.cloud/api/public/content/"
             "0617d83b2519466f83534df56bc3c9c1?v=bc6e33f0",
             ("Marketing Part Number", "Product Name", "Product Short Description",
              "EOS date", "EOSL date")),
}
NAME = "Product Name"
EOS = "EOS date"
EOSM = "EOSM date"
EOSL = "EOSL date"
RUN_DATE = re.compile(r"^Run date (?P<date>.+)$")
# Excel's 1900 date system counts a day that never existed, so a serial at or
# below 59 is ambiguous and is refused rather than resolved to a guess.
EPOCH = date(1899, 12, 30)
AMBIGUOUS_SERIAL = 59
EARLIEST, LATEST = date(1990, 1, 1), date(2100, 1, 1)
SHEET_CELL = re.compile(r'<c r="([A-Z]+)\d+"(?P<attrs>[^>]*)>(?P<body>.*?)</c>', re.S)
SHARED_TEXT = re.compile(r"<t[^>]*>(.*?)</t>", re.S)
SHEET_ROW = re.compile(r"<row[^>]*>(.*?)</row>", re.S)


class SheetError(ValueError):
    """The extract is not the sheet this collector reads."""


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def excel_day(value, where):
    """The calendar day one Excel date serial states, or ``None``.

    The encoding is the vendor's, not a documented format, so it is read
    narrowly: a blank cell is absent, a serial at or below 59 is refused
    because Excel's 1900 epoch cannot distinguish those days, and a serial
    outside 1990-2100 is refused as a value this catalog will not publish.
    """
    text = tables.fold(value)
    if not text:
        return None
    if not re.fullmatch(r"\d+(\.\d+)?", text):
        raise SheetError(f"{where}: {text!r} is not an Excel date serial")
    serial = int(float(text))
    if serial == 0:
        return None
    if serial <= AMBIGUOUS_SERIAL:
        raise SheetError(f"{where}: serial {serial} falls in the 1900 epoch's ambiguous range")
    day = EPOCH + timedelta(days=serial)
    if not EARLIEST <= day < LATEST:
        raise SheetError(f"{where}: serial {serial} resolves to {day}, outside the range this "
                         f"catalog publishes")
    return day.isoformat()


def _shared_strings(archive):
    if "xl/sharedStrings.xml" not in archive.namelist():
        return []
    xml = archive.read("xl/sharedStrings.xml").decode("utf-8")
    return [value.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
            for value in SHARED_TEXT.findall(xml)]


def _rows(archive):
    """Every row of the workbook's first sheet, as ``{column: text}``."""
    shared = _shared_strings(archive)
    if "xl/worksheets/sheet1.xml" not in archive.namelist():
        raise SheetError("The extract carries no worksheet")
    xml = archive.read("xl/worksheets/sheet1.xml").decode("utf-8")
    out = []
    for row in SHEET_ROW.findall(xml):
        cells = {}
        for match in SHEET_CELL.finditer(row):
            column, body = match.group(1), match.group("body")
            value = re.search(r"<v>(.*?)</v>", body, re.S)
            text = value.group(1) if value else ""
            if re.search(r't="s"', match.group("attrs")) and text.isdigit():
                index = int(text)
                if index >= len(shared):
                    raise SheetError(f"The extract references shared string {index} that is absent")
                text = shared[index]
            elif re.search(r't="str"', match.group("attrs")):
                text = text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
            cells[column] = text
        if cells:
            out.append(cells)
    return out


def parse(payload, sheet):
    """One extract as ``(run_date, products, tables_seen)``.

    ``run_date`` is the sheet's own ``Run date`` cell, required: a spreadsheet
    that reshapes usually re-dates itself first, so the version signal is read
    rather than assumed.
    """
    expected = FILES[sheet][1]
    try:
        archive = zipfile.ZipFile(io.BytesIO(payload))
    except zipfile.BadZipFile as error:
        raise SheetError(f"The {sheet} extract is not a readable spreadsheet: {error}") from error
    rows = _rows(archive)
    if len(rows) < 3:
        raise SheetError(f"The {sheet} extract states {len(rows)} rows, too few to be a lifecycle sheet")
    run = rows[0].get("A", "")
    match = RUN_DATE.match(tables.fold(run))
    if not match:
        raise SheetError(f"The {sheet} extract states no run date in its first cell: {run!r}")
    header = [tables.fold(rows[1].get(column, "")) for column in "ABCDEF"][:len(expected)]
    if tuple(header) != expected:
        raise SheetError(f"The {sheet} extract's columns changed: {header!r}, expected "
                         f"{list(expected)!r}")
    products = []
    for number, row in enumerate(rows[2:], 3):
        part = tables.fold(row.get("A", ""))
        if not part:
            continue
        at = f"Extreme {sheet} row {number} {part}"
        cells = {}
        for index, column in enumerate("ABCDEF"[:len(expected)]):
            label = expected[index]
            cells[label] = {"text": tables.fold(row.get(column, "")), "value": None,
                            "datetime": None, "role": None, "links": []}
        cells[EOS]["raw"] = tables.fold(row.get("D", ""))
        if EOSM in expected:
            cells[EOSM]["raw"] = tables.fold(row.get("E", ""))
        cells[EOSL]["raw"] = tables.fold(row.get("F" if EOSM in expected else "E", ""))
        try:
            eos = excel_day(cells[EOS]["raw"], f"{at} EOS date")
            eol = excel_day(cells[EOSL]["raw"], f"{at} EOSL date")
            eosm = excel_day(cells[EOSM]["raw"], f"{at} EOSM date") if EOSM in cells else None
        except SheetError as error:
            raise SheetError(f"{error}") from error
        products.append({
            "part": part, "sheet": sheet, "run_date": tables.fold(match.group("date")),
            "name": cells[NAME]["text"] or part,
            "milestones": {"ga": None, "eos": eos, "eossec": None, "eol": eol},
            "software_maintenance": eosm,
            "cells": cells,
        })
    if not products:
        raise SheetError(f"The {sheet} extract states no product row")
    return tables.fold(match.group("date")), products, 1


def merge(products):
    """One product per part number, with a part in both extracts reconciled.

    A part stated twice with the same date is one product read from two
    extracts, and the second read is reported. A part stated twice with
    *different* dates is a vendor contradiction and refuses: two files that
    disagree about a support end are a review, not a choice.
    """
    merged, restated, excluded = {}, [], []
    for product in sorted(products, key=lambda entry: (entry["part"], entry["sheet"])):
        part = product["part"]
        first = merged.get(part)
        if first is None:
            merged[part] = product
            continue
        claims = {key: value for key, value in product["milestones"].items() if value}
        known = {key: value for key, value in first["milestones"].items() if value}
        conflicting = [key for key, value in claims.items() if known.get(key) not in (None, value)]
        if conflicting:
            raise SheetError(f"Extreme {part} is stated in both extracts with different "
                             f"{', '.join(sorted(conflicting))} dates: {known} then {claims}")
        for key, value in claims.items():
            first["milestones"][key] = value
        if product["software_maintenance"]:
            first["software_maintenance"] = product["software_maintenance"]
        for label, cell in product["cells"].items():
            if cell["text"] and not first["cells"].get(label, {}).get("text"):
                first["cells"][label] = cell
        restated.append({"part": part, "sheet": product["sheet"],
                         "reason": f"this part number is also stated in the {first['sheet']} extract "
                                   f"with the same dates; it is one product read from two files, "
                                   f"and the second read is accounted here"})
    return list(merged.values()), restated, excluded


def identities(products):
    """One record id per part number, disambiguating the vendor's own near-duplicates.

    Two Extreme part numbers can differ only in punctuation — ``RPS9DC-I`` and
    ``RPS9DC+I`` are different hardware, and ``SALSA-Ent-edition-XL`` and
    ``SALSA-Ent-edition XL`` are one product written twice. Merging on a
    punctuation-insensitive key would fuse two real SKUs, so nothing is merged:
    the first spelling keeps the clean slug, and every member of a colliding
    group gets a short digest of its exact part number so the two can never
    share a record. The group is named in the report for a human to look at.
    """
    slugs = {}
    for product in products:
        slugs.setdefault(slugify(product["part"]), []).append(product["part"])
    colliding = {slug for slug, parts in slugs.items() if len(parts) > 1}
    out = {}
    for product in products:
        part = product["part"]
        slug = slugify(part)
        if slug in colliding:
            digest = hashlib.sha256(part.encode()).hexdigest()[:8]
            out[id(product)] = f"extreme-{slug}-{digest}"
        else:
            out[id(product)] = f"extreme-{slug}"
    return out, sorted((slug, sorted(set(slugs[slug]))) for slug in colliding)


def record_for(product, checked, identity=None):
    """The published hardware record for one marketing part number.

    ``identity`` is the id :func:`identities` decided for this part, because a
    near-duplicate part number needs a digest the builder cannot know.
    """
    milestones = product["milestones"]
    upstream = dict(product["cells"])
    upstream["End of Software Maintenance"] = {
        "text": product["software_maintenance"] or "", "value": None, "datetime": None,
        "role": None, "links": [],
        "note": "the date firmware and applications stop receiving maintenance releases. This is a "
                "maintenance window, not a stated security-support end, so it is published and "
                "never mapped to eossec; the vendor's five-year support statement is not applied "
                "to it either.",
    }
    upstream["Run date"] = {
        "text": product["run_date"], "value": None, "datetime": None, "role": None, "links": [],
        "note": "the date the vendor stamped on the sheet this row was read from; it is the only "
                "version signal the extract carries.",
    }
    return {
        "$schema": RECORD_SCHEMA,
        "id": identity or f"extreme-{slugify(product['part'])}",
        "name": product["name"] or product["part"],
        "category": "hardware",
        "vendor": VENDOR,
        "product_line": VENDOR,
        "family": VENDOR,
        "model_number": product["part"],
        "milestones": milestones,
        "status": status_from(milestones["eol"], checked),
        "upstream": upstream,
        "provenance": {"source_urls": [SOURCE_URL, INDEX_URL], "verifier": VERIFIER,
                       "last_checked": checked},
    }


def report_for(products, restated, sheets, checked, collisions=()):
    """The per-row accounting this source publishes beside its records."""
    return {
        "source_url": SOURCE_URL, "index_url": INDEX_URL, "verifier": VERIFIER,
        "checked_at": checked,
        "record_scope": ("Extreme Networks products: one hardware record per marketing part number "
                         "stated in the vendor's end-of-sale and end-of-service-life extracts, at "
                         "the day precision each cell states"),
        "rows": {"seen": len(products) + len(restated), "published": len(products),
                 "restated": len(restated), "sheets": len(sheets),
                 "with_eos": sum(1 for p in products if p["milestones"]["eos"]),
                 "with_eol": sum(1 for p in products if p["milestones"]["eol"])},
        "sheets": sheets,
        "restated": restated,
        "collisions": [{"slug": slug, "part_numbers": parts} for slug, parts in collisions],
        "total_records": len(products),
        "limitations": [
            "EOS date becomes eos and EOSL date becomes eol, in the vendor's own definitions: the "
            "last date the product is available for sale, and the last date to receive service and "
            "support from the vendor's technical assistance team.",
            "EOSM is published verbatim and never mapped. It is the date software stops receiving "
            "maintenance releases, which is a maintenance window and not a stated security-support "
            "end, so eossec is null everywhere.",
            "No date is derived. The index page states a five-year support window from the end of "
            "sale for hardware; this collector applies it nowhere, and every published date is a "
            "cell the vendor wrote.",
            "The dates are stored as Excel serials, an encoding the vendor documents nowhere. The "
            "reader is explicit: a serial at or below 59 is refused because the 1900 epoch cannot "
            "distinguish those days, and a serial resolving outside 1990-2100 is refused rather "
            "than published. Each record keeps the raw serial beside the day read.",
            "The three identifier columns carry no data dictionary, so they are published verbatim "
            "and the part number is the record's identity only because the vendor's own file is "
            "keyed on it. No identifier is invented and no two products are merged.",
            "A part number stated in both extracts is reconciled: the same dates are one product, "
            "and different dates for the same part refuse the run rather than choosing one. As "
            "published the two extracts share no part number - 1,779 rows in EOS and 6,067 in "
            "EOSL - and the vendor states no membership rule for either cut, so the row counts "
            "are reported and the cuts are not characterised.",
            "Part numbers that differ only in punctuation are never merged. The vendor's own file "
            "states RPS9DC-I and RPS9DC+I, which are different hardware, and one product twice "
            "with two spellings; the colliding group is listed in collisions and each part keeps a "
            "distinct record, because fusing two real SKUs would be worse than publishing one "
            "product twice for a human to reconcile.",
            "The sheet's own 'Run date' cell is required and published, because a spreadsheet that "
            "reshapes usually re-dates itself first. The vendor states no publication cadence.",
        ],
    }


def import_extreme(directory=None):
    """Fetch both extracts and publish one record per marketing part number."""
    root = Path(directory) if directory is not None else ROOT / "data"
    checked = _now()
    collected, sheets = [], {}
    for sheet in sorted(FILES):
        run_date, products, _seen = parse(net.get(FILES[sheet][0]).content, sheet)
        sheets[sheet] = {"url": FILES[sheet][0], "run_date": run_date, "rows": len(products)}
        for product in products:
            product["run_date"] = run_date
        collected.extend(products)
    products, restated, _excluded = merge(collected)
    ids, collisions = identities(products)
    records = []
    for product in sorted(products, key=lambda entry: ids[id(entry)]):
        records.append(record_for(product, checked, ids[id(product)]))
    if len({record["id"] for record in records}) != len(records):
        raise SheetError("Two Extreme part numbers publish as one record")
    report = report_for(products, restated, sheets, checked, collisions)
    publish_records(records, VERIFIER, root, report)
    rows = report["rows"]
    return (f"imported {len(records)} Extreme Networks products from {rows['sheets']} extracts "
            f"(run dates {', '.join(sorted(s['run_date'] for s in sheets.values()))}; "
            f"{rows['with_eos']} with an end-of-sale date, {rows['with_eol']} with an "
            f"end-of-service-life date; {rows['restated']} restated) (data/{REPORT})")
