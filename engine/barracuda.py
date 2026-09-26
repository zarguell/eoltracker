"""Barracuda appliance lifecycle, from Barracuda's own end-of-support tables.

Barracuda publishes its end-of-support dates across four product spaces on one
Confluence site, and this source reads all of them. Each space holds one dated
page, discovered through the site's **public** REST API
(``/wiki/rest/api/content?spaceKey=...`` — no account, no authentication):

===================  ==========================================  =============
Space                Page                                       Rows
===================  ==========================================  =============
``NGFEOL``           "NextGen and CloudGen Firewall Appliances    50 model-revisions
                     — EoS / EoL Definitions"
``LBADCv50``         "Hardware End of Sale/End of Life"            load balancer ADC models
``BWAFv76``          "Hardware End of Sale/End of Life"            web application firewall models
``SEPPI``            "SecureEdge Appliances — EoS / EoL           SecureEdge appliances and modems
                     Definitions"
===================  ==========================================  =============

The load balancer and WAF spaces keep their dated table on a *child* page,
which is why reading a space index alone shows no dated page. That was once
reported here as unreachable; it is not. The page trees are assembled
client-side, but the pages and the space API are served in full, so one request
per space enumerates everything. Nothing here needs a browser, a login, or an
impersonated identity, and nothing is read from a third-party catalog.

What becomes a milestone, in the vendor's own words:

* **``EoS & EoHS`` / ``EoS`` → ``eos``** — "Last order date for the product as
  well for all options associated to that product including any maintenance
  contracts, software subscription, content security subscriptions, etc." That is
  orderability, which is what ``eos`` means here. EoHS is the vendor's
  end-of-hardware-support half of the same column, on the same day.
* **``EoFS (EoL: last supporting release)`` / ``EoL`` → ``eol``** — "Last day of
  firmware support for this hardware and firmware product bundle including
  software subscriptions, content security subscriptions and any hardware
  maintenance subscription."
* **``ga`` and ``eossec`` are null.** No page states an availability date or a
  security-support date, and neither is inferred from the gap between the two
  dates that *are* stated.
* **The nuance belongs beside the date, not inside the milestone.** Barracuda is
  explicit that the EoFS column is not the product's total end of life: "The
  End-of-Life (EOL) date of a hardware model indicates the day when the hardware
  will no longer be respected/maintained in future firmware releases, thus it is
  also called End-of-FirmwareSupport", and "The product will be completely
  End-of-Life when the last supporting FW release reaches its End of Support."
  The published ``eol`` is therefore the model's end of firmware support, and
  every record says so in its own cells.

The pages' rows are not uniform, and each shape is taken at its word:

* a **six-cell** row (the firewall and SecureEdge pages) opens a model;
* a **five-cell** row is a *revision* of the model above it — the model cell is
  row-spanned in the markup and its text belongs to the model above, so the
  model carries forward and the revision is what makes the row its own record. A
  model with Rev. A and Rev. B therefore has two records, because the vendor
  gives the revisions different dates.
* the load balancer and WAF pages publish a **five-column** shape with no part
  number; the same row rules apply.
* ``not set`` / ``Not Set`` is the vendor's "no date" cell and publishes nothing.
* the EoFS cell often ends with the last supporting *firmware version* in
  parentheses (``2021-05-31 (7.2.6 EoL)``). The day is read, the version is kept
  verbatim in the same cell, and the two are never merged.
* a model cell may name several models ("SC20, SC21"): one vendor row with one
  pair of dates, so one record keeping the vendor's own label.
"""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
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
REST = "https://documentation.campus.barracuda.com/wiki/rest/api/content"
SPACE_INDEX = "https://documentation.campus.barracuda.com/wiki/spaces/NGFEOL/pages/5505528"
PAGE_SIZE = 100
MAX_PAGES_PER_SPACE = 600

# The dated page in each product space, and the column shape it publishes. The
# firewall and SecureEdge pages title theirs "EoS / EoL Definitions"; the load
# balancer and WAF spaces nest theirs as a child page. A page is accepted only
# when it carries dated rows, so a vendor rename cannot silently shrink the
# catalog — and a space whose dated page has gone missing refuses the run.
SPACES = {
    "NGFEOL": {"product": "Barracuda CloudGen / NextGen Firewall",
               "heading": "EoS / EoL Definitions", "shape": "full"},
    "LBADCv50": {"product": "Barracuda Load Balancer ADC",
                 "heading": "Hardware End of Sale/End of Life", "shape": "short"},
    "BWAFv76": {"product": "Barracuda Web Application Firewall",
                "heading": "Hardware End of Sale/End of Life", "shape": "short"},
    "SEPPI": {"product": "Barracuda SecureEdge",
              "heading": "EoS / EoL Definitions", "shape": "full"},
}
# Barracuda publishes three column arrangements, and one page can carry more
# than one: the load balancer and WAF pages drop the part number, and the
# firewall page's Firewall Control Center table keeps it while using the short
# date labels. So a table is read by the *roles* it declares rather than by a
# fixed width: the successor column is last, the two columns before it are the
# dated pair, and the only other column allowed between the revision and the
# dates is the part number. Anything else refuses.
REVISION_LABEL = "Model Revision"
PART_LABEL = "Part Number"
# The three spellings of the dated pair across the four spaces.
DATE_PAIRS = (("EoS & EoHS", "EoFS (EoL: last supporting release)"),
              ("EoS", "EoL"),
              ("End of Sale", "End of Life"))
# Between the model column and the dated pair a table may carry a revision
# column, a part-number column, both or neither, in that order.
OPTIONAL = (REVISION_LABEL, PART_LABEL)
# What this source's first column heads: an appliance. The same spaces also
# publish *service* tables — a cloud subscription with an end-of-renewal rather
# than an end-of-sale — and a service lifecycle is a different record shape from
# a hardware appliance, so those tables are reported rather than read here.
# Every appliance table carries a revision column or a part-number column. The
# licence table on the firewall page carries neither — it heads a licence model
# with an end-of-sales, an end-of-renewal and an end-of-life, which is a
# subscription lifecycle rather than an appliance.
# The web application firewall page writes slashes where the others write
# hyphens; both are this vendor's own wording for the same kind of day.
DAY = re.compile(r"\b\d{4}[-/]\d{2}[-/]\d{2}\b")
DATED = re.compile(r"\b20[12]\d[-/]\d{2}[-/]\d{2}\b")
NOT_SET = frozenset({"not set", "none set", "none", "", "-", "tbd", "n/a", "—", "–"})


class DateError(ValueError):
    """A date cell the page prints in a shape this reader does not know."""


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def barracuda_day(text, where):
    """The calendar day one Barracuda cell states, or ``None``.

    The cell may end with the last supporting firmware version in parentheses
    (``2021-05-31 (7.2.6 EoL)``). The day is what the column states; the version
    is not a date and is kept in the cell, never merged.
    """
    value = tables.fold(text)
    if value.lower() in NOT_SET:
        return None
    found = DAY.search(value)
    if not found or found.start():
        raise DateError(f"{where}: unrecognized Barracuda date {value!r}")
    day = found.group(0).replace("/", "-")
    try:
        return date.fromisoformat(day).isoformat()
    except ValueError:
        raise DateError(f"{where}: {day!r} is not a real calendar day") from None


def _cell(text):
    return {"text": tables.fold(text), "value": None, "datetime": None, "role": None, "links": []}


def _api(url):
    """One public REST response, or a refusal that says what went wrong."""
    try:
        return net.get_json(url)
    except urllib.error.HTTPError as error:
        raise ValueError(f"The Barracuda content API returned HTTP {error.code} for {url}") from error
    except ValueError as error:
        # net.get_json surfaces a non-JSON body as a ValueError; say whose fault.
        raise ValueError(f"The Barracuda content API returned a body that is not JSON for {url}: "
                         f"{error}") from error


def discover(space):
    """The dated end-of-support page id in one space, or ``None``.

    The space's own API lists every page, so the dated page is found by walking
    the space rather than by a hand-kept id. A page qualifies when its title
    names the space's declared lifecycle heading *and* its body carries dated
    rows, which keeps vulnerability bulletins and deployment guides out.
    """
    heading = SPACES[space]["heading"].lower()
    for start in range(0, MAX_PAGES_PER_SPACE, PAGE_SIZE):
        url = (f"{REST}?spaceKey={urllib.parse.quote(space)}&type=page&limit={PAGE_SIZE}"
               f"&start={start}&expand=body.view")
        data = _api(url)
        results = data.get("results") or []
        if not results:
            return None
        for page in results:
            title = (page.get("title") or "").lower()
            if heading not in title:
                continue
            body = ((page.get("body") or {}).get("view") or {}).get("value") or ""
            if "<table" in body and DATED.search(body):
                return str(page["id"]), page.get("title")
    return None


def page_html(page_id):
    """One page's rendered body HTML from the public API."""
    data = _api(f"{REST}/{urllib.parse.quote(str(page_id))}?expand=body.view")
    body = ((data.get("body") or {}).get("view") or {}).get("value")
    if not body:
        raise ValueError(f"Barracuda page {page_id} returned no body from the content API")
    return body


def parse(html, space):
    """One space's page as ``(products, excluded, tables_seen)``.

    ``products`` is one entry per model-revision row; ``excluded`` the group
    labels and any row this reader does not understand, each with its reason.
    """
    if not tables.fold(html):
        raise ValueError(f"The Barracuda {space} page returned an empty document; that is a fetch "
                         f"refusal, not an empty table")
    doc = tables.parse_document(html)
    headed = [block for block in doc.blocks if tables.th_header(block)]
    if not headed:
        raise ValueError(f"The Barracuda {space} page states no headed table")
    products, excluded, seen, current = [], [], 0, None
    for block in headed:
        labels, start = tables.th_header(block)
        if not set(labels[1:-3]) & {REVISION_LABEL, PART_LABEL}:
            excluded.append({"space": space, "table": labels[0], "rows": 0,
                             "reason": f"the table heads {labels[0]!r} and carries neither a "
                                       f"revision nor a part-number column: its rows are a licence "
                                       f"or subscription lifecycle, a different record shape from "
                                       f"a hardware appliance, so they are reported here and none "
                                       f"of them is read"})
            continue
        date_at, declared = _shape_of(labels, space)
        # The first column's own heading is the vendor's name for the product in
        # that table, which is more faithful than the space's name: the firewall
        # page also carries a Firewall Control Center table.
        product_line = labels[0]
        seen += 1
        body = [row for row in block["rows"][start:] if len(row) != 1]
        for index, row in enumerate(body, 1):
            at = f"Barracuda {space} table {seen} row {index}"
            texts = [tables.fold(cell["text"]) for cell in row]
            if len(texts) == len(declared) and not texts[0] and current:
                # The model cell is present but empty because it is row-spanned
                # upstream: this row is another revision of the model above.
                parts = (current, *texts[1:])
            elif len(texts) == len(declared):
                current = texts[0]
                parts = tuple(texts)
            elif current:
                # The page renders the revision row one cell short, with the
                # row-spanned model cell omitted entirely rather than blanked.
                parts = (current, *texts)
            else:
                excluded.append({"space": space, "row": " | ".join(texts),
                                 "reason": f"the row has {len(texts)} cells where the table "
                                           f"declares {len(declared)}: it is a group label or a "
                                           f"shape this reader does not know, so no milestone is "
                                           f"read from it"})
                continue
            revision = parts[1] if len(parts) == len(declared) and \
                declared[1] == REVISION_LABEL else ""
            model = parts[0]
            if not model:
                excluded.append({"space": space, "row": " | ".join(parts),
                                 "reason": "the row states no model, so it is not a data row"})
                continue
            # The dated columns are the two before the successor column.
            eos_text, eol_text = parts[date_at], parts[date_at + 1]
            try:
                eos_day = barracuda_day(eos_text, f"{at} end of sale")
                eol_day = barracuda_day(eol_text, f"{at} end of life")
            except DateError as error:
                excluded.append({"space": space, "row": f"{model} {revision}".strip(),
                                 "reason": str(error)})
                continue
            label = f"{model} {revision}".strip() if revision else model
            products.append({
                "space": space, "product_line": product_line, "labels": declared,
                "label": label, "model": model, "revision": revision,
                "part": parts[declared.index(PART_LABEL) + 1]
                        if PART_LABEL in declared else "",
                "milestones": {"ga": None, "eos": eos_day, "eossec": None, "eol": eol_day},
                "cells": {cell_name(product_line, index, declared): _cell(text)
                          for index, text in enumerate(parts)},
                "firmware": tables.fold(eol_text),
            })
    if not products:
        raise ValueError(f"The Barracuda {space} page produced no product row")
    return products, excluded, seen


def _shape_of(labels, space):
    """Where a table's dated columns start, and the labels it published.

    The first column names the product, the second is the revision, the last is the
    successor, the two before that are the dated pair, and only a part-number
    column may sit between the revision and the dates. A table that breaks any of
    that refuses rather than having its cells fitted into these roles.
    """
    if len(labels) < 4 or not labels[-1].startswith("Successor"):
        raise ValueError(f"The Barracuda {space} table declares columns {list(labels)!r}, which is "
                         f"not a dated model table: it does not end in a successor column")
    pair = tuple(labels[-3:-1])
    if pair not in DATE_PAIRS:
        raise ValueError(f"The Barracuda {space} table declares the date columns {list(pair)!r}, "
                         f"which is not one of the published pairs {sorted(DATE_PAIRS)}")
    middle = tuple(labels[1:-3])
    if any(column not in OPTIONAL for column in middle):
        raise ValueError(f"The Barracuda {space} table declares {list(middle)!r} between its model "
                         f"and its dated columns; only {list(OPTIONAL)} may sit there")
    return len(labels) - 3, labels


def cell_name(product_line, index, labels):
    """The column name one cell belongs to, as the table headed it."""
    return labels[index] if index < len(labels) else f"column {index}"


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
        "id": product["id"],
        "name": product["label"],
        "category": "hardware",
        "vendor": VENDOR,
        "product_line": product["product_line"],
        "family": VENDOR,
        "model_number": product["part"] or product["model"],
        "milestones": milestones,
        "status": status_from(milestones["eol"], checked),
        "upstream": upstream,
        "provenance": {"source_urls": [SOURCE_URL], "verifier": VERIFIER,
                       "last_checked": checked},
    }


def report_for(products, excluded, pages, checked):
    """The per-row accounting this source publishes beside its records."""
    return {
        "source_url": SOURCE_URL, "space_index": SPACE_INDEX, "content_api": REST,
        "verifier": VERIFIER, "checked_at": checked,
        "record_scope": ("Barracuda appliances: one hardware record per model-revision row of the "
                         "vendor's end-of-support tables, across the CloudGen/NextGen firewall, "
                         "load balancer ADC, web application firewall and SecureEdge product "
                         "spaces, at the day precision each cell states"),
        "rows": {"seen": len(products) + len(excluded), "published": len(products),
                 "excluded": len(excluded), "spaces": len(pages),
                 "with_eos": sum(1 for p in products if p["milestones"]["eos"]),
                 "with_eol": sum(1 for p in products if p["milestones"]["eol"]),
                 "revisions": sum(1 for p in products if p["revision"])},
        "spaces": pages,
        "excluded": excluded,
        "total_records": len(products),
        "limitations": [
            "The end-of-sale column becomes eos and the end-of-firmware-support column becomes "
            "eol, in the vendor's own definitions. Where the column is headed EoS & EoHS, the "
            "hardware-support half of the same orderability date is on the same day.",
            "The eol published here is the model's end of firmware support, not the product's "
            "total end of life: Barracuda states the product is not completely End-of-Life until "
            "that release itself reaches its end of support. The distinction is published beside "
            "the date rather than folded into the milestone.",
            "ga and eossec are null: no page states an availability date or a security-support "
            "date, and neither is inferred from the gap between the two dates that are stated.",
            "One record is one model revision. A model with Rev. A and Rev. B has two records, "
            "because the vendor gives the revisions different dates; the model name is carried "
            "forward from the row-spanned cell above, which is how the page states it.",
            "A model cell naming several models ('SC20, SC21') is one vendor row with one pair "
            "of dates, so it is one record keeping the vendor's own label.",
            "not set and Not Set are the vendor's 'no date' cells and publish nothing; they are "
            "never coerced into a sentinel date. The parenthesised firmware version in the "
            "end-of-firmware-support cell is kept verbatim and never merged into the date.",
            "Each space's dated page is found by walking that space through the site's public "
            "content API and accepting a page only when it carries dated rows. The load balancer "
            "and WAF spaces keep that page as a child of their policy page, so reading a space "
            "index alone does not show it.",
            "The Barracuda Cloud Control space (BCC) publishes an end-of-life notice for a cloud "
            "service rather than dated appliance models, so it is not this source's; its notice is "
            "named in limitations rather than read into an appliance record.",
        ],
    }


def import_barracuda(directory=None):
    """Fetch every declared space's dated page and publish every model row."""
    root = Path(directory) if directory is not None else ROOT / "data"
    checked = _now()
    products, excluded, pages, identities = [], [], {}, {}
    for space in sorted(SPACES):
        found = discover(space)
        if found is None:
            raise ValueError(f"The Barracuda {space} space states no dated end-of-support page; a "
                             f"vendor change must be reviewed, not absorbed")
        page_id, title = found
        pages[space] = {"page_id": page_id, "title": title,
                        "product": SPACES[space]["product"]}
        rows, refusals, _seen = parse(page_html(page_id), space)
        products.extend(rows)
        excluded.extend(refusals)
    for product in sorted(products, key=lambda entry: (_identity(entry), entry["space"])):
        identity = _identity(product)
        if identity in identities and identities[identity] != (product["space"], product["label"]):
            # Two product lines state the same model name. The first keeps the
            # short identity it was first published under, so its permalink does
            # not move; the second is qualified by its product line.
            identity = f"barracuda-{slugify(SPACES[product['space']]['product'])}-" \
                       f"{slugify(product['label'])}"
        identities[identity] = (product["space"], product["label"])
        product["id"] = identity
    records = []
    for product in sorted(products, key=lambda entry: entry["id"]):
        record = record_for(product, checked)
        records.append(record)
    report = report_for(products, excluded, pages, checked)
    publish_records(records, VERIFIER, root, report)
    rows = report["rows"]
    return (f"imported {len(records)} Barracuda appliances across {rows['spaces']} product spaces "
            f"({rows['revisions']} revisions, {rows['with_eos']} with an end-of-sale date, "
            f"{rows['with_eol']} with an end of firmware support); excluded {rows['excluded']} rows "
            f"(data/{REPORT})")
