"""Deterministic Opengear hardware lifecycle-table snapshot."""
import hashlib
import json
import re
from datetime import date, datetime, timezone
from urllib.parse import urljoin

from .hardware import _Tables, fetch, publish_records, slugify, RECORD_SCHEMA
from .importer import ROOT, dump

SOURCE = "https://opengear.com/end-life-products"
VERIFIER = "deterministic-opengear"
HEADERS = {
    "hardware": ["Product", "Part #", "End of Sale", "End of Support", "Replacement Product", "Note"],
    "revision": ["Product", "Old Part / Rev #", "Old Part Sales End", "Old Part Support Ends", "New Part / Rev #", "Note"],
}
POLICY = "Published standard support deadline; Opengear honors active support agreements extending beyond End of Support through their contracted term. Grouped parts remain grouped; no individual entitlement is inferred."
SOFTWARE = {"VCMS", "PortShare for Windows", "CMS6100"}


class Tables(_Tables):
    def handle_starttag(self, tag, attrs):
        if tag in ("br", "p", "li") and self._cell is not None:
            self._cell["text"] += " "
        super().handle_starttag(tag, attrs)

    def handle_endtag(self, tag):
        if tag in ("p", "li") and self._cell is not None:
            self._cell["text"] += " "
        super().handle_endtag(tag)


def parse_date(text):
    text = re.sub(r"\s+", " ", text).strip()
    if text.lower() in {"n/a", "tbd", ""}:
        return None
    text = text.replace("Sept", "Sep")
    for fmt in ("%d %b %Y", "%d %B %Y"):
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            pass
    raise ValueError(f"Unrecognized Opengear date: {text!r}")


def identity(section, product, parts):
    # Includes complete part grouping, never mutable dates or row position.
    digest = hashlib.sha256(f"{section}\0{product}\0{parts}".encode()).hexdigest()[:12]
    return f"opengear-{slugify(product)}-{digest}"


def make_record(section, cells, checked):
    headers = HEADERS[section]
    product, parts = cells[0]["text"], cells[1]["text"]
    eos, eol = parse_date(cells[2]["text"]), parse_date(cells[3]["text"])
    if not product or not parts or not eol:
        raise ValueError("Opengear record requires product, part scope and explicit support deadline")
    if eos and eos > eol:
        raise ValueError("Opengear sale date exceeds support deadline")
    upstream = {}
    for idx, (header, cell) in enumerate(zip(headers, cells)):
        upstream[header] = {"text": cell["text"], "value": eos if idx == 2 else eol if idx == 3 else None,
                            "datetime": None, "role": "eos" if idx == 2 else "eol" if idx == 3 else None,
                            "links": [urljoin(SOURCE, link) for link in cell.get("links", [])]}
    upstream["Policy"] = {"text": POLICY, "role": None, "value": None, "links": []}
    notices = list(dict.fromkeys(link for cell in upstream.values() for link in cell["links"]))
    return {"$schema": RECORD_SCHEMA, "id": identity(section, product, parts), "name": product,
            "category": "hardware", "vendor": "Opengear", "product_line": "Opengear",
            "family": section, "model_number": parts,
            "milestones": {"ga": None, "eos": eos, "eossec": None, "eol": eol},
            "status": "eol" if eol < checked[:10] else "expiring", "upstream": upstream,
            "provenance": {"source_urls": [SOURCE] + [u for u in notices if u != SOURCE],
                           "verifier": VERIFIER, "last_checked": checked}}


def parse_page(html, checked):
    parser = Tables()
    parser.feed(html)
    parser.close()
    records, excluded, found, seen = [], [], set(), set()
    for table in parser.tables:
        section = next((key for key, headers in HEADERS.items() if headers == table["headers"]), None)
        if section is None:
            # Software sections are explicitly outside this hardware collector.
            if table["headers"] and table["headers"][0] in {"Software", "Software Subscriptions"}:
                for row in table["rows"]:
                    if row["cells"]:
                        excluded.append({"product": row["cells"][0]["text"], "reason": "Software section; not hardware"})
                continue
            raise ValueError(f"Unexpected Opengear table headers: {table['headers']}")
        if section in found:
            raise ValueError(f"Duplicate Opengear table: {section}")
        found.add(section)
        rows = [row["cells"] for row in table["rows"] if row["cells"]]
        if not rows:
            raise ValueError(f"Empty Opengear table: {section}")
        for cells in rows:
            if len(cells) != len(HEADERS[section]):
                raise ValueError("Opengear row/header width mismatch")
            product = cells[0]["text"]
            # Validate dates even on excluded rows to catch source drift.
            parse_date(cells[2]["text"])
            end = parse_date(cells[3]["text"])
            if product in SOFTWARE or end is None:
                excluded.append({"product": product, "parts": cells[1]["text"],
                                 "reason": "Software product in hardware table" if product in SOFTWARE else "No explicit support deadline; status unknown"})
                continue
            record = make_record(section, cells, checked)
            if record["id"] in seen:
                raise ValueError(f"Duplicate Opengear identity: {record['id']}")
            seen.add(record["id"])
            records.append(record)
    if found != set(HEADERS):
        raise ValueError("Missing Opengear hardware lifecycle or revision table")
    return sorted(records, key=lambda r: r["id"]), excluded


def validate_record(record):
    section = record["family"]
    if section not in HEADERS or record["provenance"]["verifier"] != VERIFIER:
        raise ValueError("Invalid Opengear source identity")
    cells = [record["upstream"][header] for header in HEADERS[section]]
    rebuilt = make_record(section, cells, record["provenance"]["last_checked"])
    if record != rebuilt:
        raise ValueError(f"Opengear record contradicts source evidence: {record['id']}")


def import_opengear():
    checked = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    records, excluded = parse_page(fetch(SOURCE), checked)
    imported = publish_records(records, VERIFIER)
    report = {"source_url": SOURCE, "verifier": VERIFIER, "checked_at": checked,
              "record_scope": "Hardware lifecycle rows and part groups, not an exhaustive SKU inventory",
              "imported_count": len(imported), "excluded_count": len(excluded), "excluded": excluded}
    dump(ROOT / "data" / "opengear-import.json", report)
    print(f"Imported {len(imported)} Opengear hardware rows/groups; excluded {len(excluded)} rows (data/opengear-import.json)")
    return imported
