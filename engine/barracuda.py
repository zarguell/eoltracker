"""Barracuda firewall lifecycle, from Barracuda's own end-of-support tables.

Source: ``https://documentation.campus.barracuda.com/wiki/spaces/NGFEOL/pages/5505036``
— the vendor's "Barracuda NextGen and CloudGen Firewall Appliances - EoS / EoL
Definitions" page, one headed table of model rows.

What becomes a milestone, in the vendor's own words. The table states two dates
and defines each on the page:

* **``EoS & EoHS`` → ``eos``** — "Last order date for the product as well for
  all options associated to that product including any maintenance contracts,
  software subscription, content security subscriptions, etc." That is
  orderability, which is what ``eos`` means here. EoHS is the vendor's
  end-of-hardware-support half of the same column, and it is the same day.
* **``EoFS (EoL: last supporting release)`` → ``eol``** — "Last day of firmware
  support for this hardware and firmware product bundle including software
  subscriptions, content security subscriptions and any hardware maintenance
  subscription."
* **``ga`` and ``eossec`` are null.** The table states no availability date and
  no security-support date, and neither is inferred from the gap between the two
  dates it does state.
* **The nuance belongs in the record, not in the milestone.** The vendor is
  explicit that this column is *not* the product's total end of life: "The End-of-
  Life (EOL) date of a hardware model indicates the day when the hardware will no
  longer be respected/maintained in future firmware releases, thus it is also
  called End-of-FirmwareSupport", and "The product will be completely End-of-Life
  when the last supporting FW release reaches its End of Support." So the
  published ``eol`` is this hardware model's end of firmware support, and the
  distinction is published verbatim beside it rather than folded into a claim
  the vendor did not make.

The page's rows are not uniform, and the reader takes each shape at its word:

* a **six-cell** row opens a model;
* a **five-cell** row is a *revision* of the model in the row above — the model
  cell is row-spanned in the page's markup and its text belongs to the model
  above, so the model is carried forward and the revision is what makes the row
  its own record. A model with Rev. A and Rev. B has two records, because the
  vendor gives them different dates.
* a **narrower** row is a group label ("Rev. C" with no model and no dates) and
  is reported, never read as a data row.
* ``not set`` is the vendor's "no date" cell, so it publishes nothing; it is not
  coerced into a sentinel date.
* the ``EoFS`` cell often ends with the last supporting *firmware version* in
  parentheses (``2025-02-28 (2.0.10)``). The day is read, the version is kept
  verbatim in the same cell, and neither is merged into the other.

A model cell may name several models ("SC20, SC21"). That is one vendor row
with one pair of dates, so it is one record with the vendor's own label, in the
same way the Palo Alto collector keeps a product line together with its SKUs.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timezone
from pathlib import Path

from . import net, sources, tables
from .hardware import publish_records, slugify, status_from
from .importer import ROOT

SOURCE = sources.source("import-barracuda")
VERIFIER = SOURCE.verifier
REPORT = SOURCE.report
SOURCE_URL = SOURCE.url
RECORD_SCHEMA = "https://zarguell.github.io/eoltracker/v1/schema/hardware.json"
VENDOR = "Barracuda"
PRODUCT_LINE = "Barracuda CloudGen / NextGen Firewall"
SPACE_INDEX = "https://documentation.campus.barracuda.com/wiki/spaces/NGFEOL/pages/5505528"
# The other product spaces Barracuda publishes an end-of-support table in. They
# are named so a reader knows they exist and are not this source's; finding
# their page ids needs a browser, because the space trees render client-side.
OTHER_SPACES = {
    "LBADCv50": "Load Balancer ADC",
    "BWAFv76": "Web Application Firewall",
    "BCC": "Cloud Control",
    "SEPPI": "SecureEdge / Perimeter",
}

COLUMNS = ("Barracuda CloudGen Firewall", "Model Revision", "Part Number", "EoS & EoHS",
           "EoFS (EoL: last supporting release)", "Successor Model")
MODEL, REVISION, PART, EOS, EOL, SUCCESSOR = range(len(COLUMNS))
MODEL_WIDTH = 6
CONTINUATION_WIDTH = 5
DAY = re.compile(r"(?P<date>\d{4}-\d{2}-\d{2})")
NOT_SET = frozenset({"not set", "none set", "", "-", "tbd", "n/a"})


class DateError(ValueError):
    """A date cell the page prints in a shape this reader does not know."""


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def barracuda_day(text, where):
    """The calendar day one Barracuda cell states, or ``None``.

    The cell may end with the last supporting firmware version in parentheses
    (``2021-05-31 (7.2.6 EoL)``). The day is what the column states; the
    version is not a date and is kept in the cell, never merged.
    """
    value = tables.fold(text)
    if value.lower() in NOT_SET:
        return None
    found = DAY.findall(value)
    if len(found) != 1 or not value.startswith(found[0]):
        raise DateError(f"{where}: unrecognized Barracuda date {value!r}")
    try:
        return date.fromisoformat(found[0]).isoformat()
    except ValueError:
        raise DateError(f"{where}: {found[0]!r} is not a real calendar day") from None


def _cell(text):
    return {"text": tables.fold(text), "value": None, "datetime": None, "role": None, "links": []}


def parse(html):
    """The page as ``(products, excluded, tables_seen)``.

    ``products`` is one entry per model-revision row; ``excluded`` the group
    labels and any row this reader does not understand, each with its reason.
    """
    if not tables.fold(html):
        raise ValueError("The Barracuda end-of-support page returned an empty document; that is a "
                         "fetch refusal, not an empty table")
    doc = tables.parse_document(html)
    headed = [block for block in doc.blocks if tables.th_header(block)]
    if not headed:
        raise ValueError("The Barracuda end-of-support page states no headed table")
    for block in headed:
        labels, start = tables.th_header(block)
        if labels != COLUMNS:
            raise ValueError(f"The Barracuda table columns changed: {list(labels)!r}, expected "
                             f"{list(COLUMNS)!r}")
    products, excluded, seen, current = [], [], 0, None
    for block in headed:
        labels, start = tables.th_header(block)
        seen += 1
        for index, row in enumerate([row for row in block["rows"][start:] if len(row) != 1], 1):
            at = f"Barracuda table {seen} row {index}"
            texts = [tables.fold(cell["text"]) for cell in row]
            if len(texts) == MODEL_WIDTH:
                current = texts[MODEL]
                parts = (current, texts[REVISION], texts[PART], texts[EOS], texts[EOL],
                         texts[SUCCESSOR])
            elif len(texts) == CONTINUATION_WIDTH and current:
                # A revision row: the model cell is row-spanned upstream, so the
                # model carries forward and the revision names this row.
                parts = (current, texts[0], texts[1], texts[2], texts[3], texts[4])
            else:
                excluded.append({"row": " | ".join(texts),
                                 "reason": f"the row has {len(texts)} cells where the table "
                                           f"declares {MODEL_WIDTH}: it is a group label or a "
                                           f"shape this reader does not know, so no milestone is "
                                           f"read from it"})
                continue
            model, revision, part, eos, eof, successor = parts
            if not model:
                excluded.append({"row": " | ".join(parts),
                                 "reason": "the row states no model, so it is not a data row"})
                continue
            try:
                eos_day = barracuda_day(eos, f"{at} EoS & EoHS")
                eol_day = barracuda_day(eof, f"{at} EoFS")
            except DateError as error:
                excluded.append({"row": f"{model} {revision}".strip(), "reason": str(error)})
                continue
            label = f"{model} {revision}".strip() if revision else model
            products.append({
                "label": label, "model": model, "revision": revision, "part": part,
                "firmware": tables.fold(eof),
                "milestones": {"ga": None, "eos": eos_day, "eossec": None, "eol": eol_day},
                "cells": {column: _cell(text) for column, text in zip(COLUMNS, parts)},
            })
    if not products:
        raise ValueError("The Barracuda end-of-support page produced no product row")
    identities = {_identity(product) for product in products}
    if len(identities) != len(products):
        raise ValueError(f"Barracuda: {len(products)} rows collapse to {len(identities)} identities")
    return products, excluded, seen


def _identity(product):
    return f"barracuda-{slugify(product['label'])}"


def record_for(product, checked):
    """The published hardware record for one model-revision row."""
    milestones = product["milestones"]
    upstream = dict(product["cells"])
    upstream["End of Firmware Support note"] = {
        **_cell(product["firmware"]),
        "note": "this is the last firmware release that supports the model. Barracuda states the "
                "product is not completely End-of-Life until that release itself reaches its end "
                "of support, so this date is the model's end of firmware support rather than a "
                "claim about the product's last day.",
    }
    return {
        "$schema": RECORD_SCHEMA,
        "id": _identity(product),
        "name": product["label"],
        "category": "hardware",
        "vendor": VENDOR,
        "product_line": PRODUCT_LINE,
        "family": VENDOR,
        "model_number": product["part"] or product["model"],
        "milestones": milestones,
        "status": status_from(milestones["eol"], checked),
        "upstream": upstream,
        "provenance": {"source_urls": [SOURCE_URL], "verifier": VERIFIER,
                       "last_checked": checked},
    }


def report_for(products, excluded, tables_seen, checked):
    """The per-row accounting this source publishes beside its records."""
    return {
        "source_url": SOURCE_URL, "space_index": SPACE_INDEX, "verifier": VERIFIER,
        "checked_at": checked,
        "record_scope": ("Barracuda CloudGen and NextGen firewall appliances: one hardware record "
                         "per model-revision row of the vendor's end-of-support table, at the day "
                         "precision the vendor's own cell states"),
        "rows": {"seen": len(products) + len(excluded), "published": len(products),
                 "excluded": len(excluded), "tables": tables_seen,
                 "with_eos": sum(1 for p in products if p["milestones"]["eos"]),
                 "with_eol": sum(1 for p in products if p["milestones"]["eol"]),
                 "revisions": sum(1 for p in products if p["revision"])},
        "excluded": excluded,
        "total_records": len(products),
        "other_spaces": [{"space": space, "product": name}
                         for space, name in sorted(OTHER_SPACES.items())],
        "limitations": [
            "EoS & EoHS becomes eos and EoFS (the last supporting release) becomes eol, in the "
            "vendor's own column definitions. EoHS is the end-of-hardware-support half of the "
            "same orderability date.",
            "The EoFS date is this model's end of firmware support, not the product's total end "
            "of life: Barracuda states the product is not completely End-of-Life until that "
            "release itself reaches its end of support. That distinction is published beside the "
            "date rather than folded into the milestone.",
            "ga and eossec are null: the table states neither an availability date nor a "
            "security-support date, and neither is inferred from the gap between the two dates it "
            "does state.",
            "One record is one model revision. A model with Rev. A and Rev. B has two records, "
            "because the vendor gives the revisions different dates; the model name is carried "
            "forward from the row-spanned cell above, which is how the page states it.",
            "A model cell naming several models ('SC20, SC21') is one vendor row with one pair "
            "of dates, so it is one record keeping the vendor's own label.",
            "not set is the vendor's 'no date' cell and publishes nothing; it is never coerced "
            "into a sentinel date. The parenthesised firmware version in the EoFS cell is kept "
            "verbatim and never merged into the date.",
            "Only the firewall space is read. Barracuda publishes end-of-support tables for its "
            "load balancer ADC, web application firewall, cloud control and SecureEdge products "
            "in separate spaces, and those spaces' page trees render client-side, so their dated "
            "pages cannot be enumerated from here; they are named in other_spaces rather than "
            "claimed as covered.",
        ],
    }


def import_barracuda(directory=None):
    """Fetch the firewall end-of-support table and publish every model row."""
    root = Path(directory) if directory is not None else ROOT / "data"
    checked = _now()
    products, excluded, tables_seen = parse(net.get_text(SOURCE_URL))
    records = [record_for(product, checked)
               for product in sorted(products, key=_identity)]
    report = report_for(products, excluded, tables_seen, checked)
    publish_records(records, VERIFIER, root, report)
    rows = report["rows"]
    return (f"imported {len(records)} Barracuda firewall models ({rows['revisions']} revisions, "
            f"{rows['with_eos']} with an end-of-sale date, {rows['with_eol']} with an end of "
            f"firmware support); excluded {rows['excluded']} rows (data/{REPORT})")
