"""Deterministic Opengear hardware snapshot: lifecycle tables plus catalog SKUs.

Two authoritative sources feed one verifier-owned slice of the hardware
catalog:

* ``https://opengear.com/end-life-products`` — the lifecycle and revision
  tables: dated retirements, and retirements announced without a date, each
  keeping the vendor's complete part grouping verbatim.
* ``https://opengear.com/configure/`` — the product configurator's embedded
  dataset: the exact SKUs Opengear currently lists, one record per SKU.

The two are joined only by exact published part string. A listing is not a
support entitlement and disappearing from the catalog is not an end of life;
a notice that names a revision is never applied to the whole SKU it revises.
"""
import hashlib
import json
import re
from datetime import datetime, timezone
from html.parser import HTMLParser
from urllib.parse import urljoin

from .hardware import _Tables, fetch, get_records, publish_records, slugify, RECORD_SCHEMA
from .importer import ROOT, dump

SOURCE = "https://opengear.com/end-life-products"
VERIFIER = "deterministic-opengear"
HEADERS = {
    "hardware": ["Product", "Part #", "End of Sale", "End of Support", "Replacement Product", "Note"],
    "revision": ["Product", "Old Part / Rev #", "Old Part Sales End", "Old Part Support Ends", "New Part / Rev #", "Note"],
}
POLICY = "Published standard support deadline; Opengear honors active support agreements extending beyond End of Support through their contracted term. Grouped parts remain grouped; no individual entitlement is inferred."
SOFTWARE = {"VCMS", "PortShare for Windows"}
# The configurator publishes what Opengear currently sells; the lifecycle tables
# publish retirements. Listing is a catalog fact, never a support claim, and
# disappearance from the catalog is not an end of life.
CONFIGURE_SOURCE = "https://opengear.com/configure/"
# The configurator dataset this collector is built against. Drift is a source
# change to review, never something to publish silently.
CATALOG_MODELS = 46
CATALOG_FAMILY = "catalog"
CATALOG_POLICY = ("Catalog listing only: the Opengear configurator currently offers this SKU. Listing is not "
                  "support entitlement and removal from the catalog is not an end of life. Any support date comes "
                  "from a lifecycle notice naming this exact SKU, never from listing or absence.")
LIFECYCLE_POLICY = ("Linked lifecycle notice(s) name this exact SKU in their published part scope. Grouped and "
                    "revision-scoped parts are never split, and a replacement part is never a support claim.")
CATALOG_CELLS = ("SKU", "Title", "Support Series", "Families", "Datasheet URL", "Thumbnail", "Short Description", "Policy")
# The lifecycle row a catalog SKU is matched to is embedded in the catalog
# record as raw evidence, so the record's published dates stay traceable to the
# vendor cells that state them and validation rebuilds it offline.
NOTICE_CELLS = ("Product", "Part #", "End of Sale", "End of Support", "Replacement Product", "Note")
NOTICE_ROLES = {"End of Sale": "eos", "End of Support": "eol"}
MILESTONES = ("ga", "eos", "eossec", "eol")
LEDGER = "opengear-changes.json"


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


def catalog_identity(sku):
    """The id of one exact configurator SKU, stable across notice transitions.

    A notice arriving or lapsing changes the record's lifecycle link, never its
    identity, so permalinks and change-ledger ids survive the transition.
    """
    digest = hashlib.sha256(f"catalog\0{sku}\0{sku}".encode()).hexdigest()[:12]
    return f"opengear-catalog-{slugify(sku)}-{digest}"


def status_from(eol, checked):
    """Status from the published support deadline; no deadline means unknown.

    The vocabulary is the hardware catalog's: an announced deadline not yet
    reached is ``expiring`` and a passed one is ``eol``. A row that publishes
    no support deadline at all is ``unknown`` — neither a support claim nor an
    end of life, since the source states neither.
    """
    if eol is None:
        return "unknown"
    return "eol" if eol < checked[:10] else "expiring"


def part_tokens(text):
    """The exact part strings of a published part scope, one token per part.

    A grouped scope publishes its parts separated by cell separators or line
    breaks (``OM2216<br>OM2216-LSP``); each becomes its own token, so a current
    SKU matches a group only when that exact part string is stated. No token is
    ever a substring of another, so a shorter part can never attach itself to a
    longer neighbour's notice.
    """
    cleaned = re.sub(r"[\u00a0\u2013\u2014]", " ", text or "").replace("&", " ")
    if re.sub(r"\s+", " ", cleaned).strip().lower() in {"", "n/a", "na", "tbd", "tba", "none",
                                                        "unknown", "all skus in family"}:
        # A scope that names no part is not a scope: "All SKUs in family" states
        # a whole family and must never be read as any individual part string.
        return set()
    tokens = set()
    for piece in re.split(r"[\s,;]+", cleaned):
        piece = piece.strip()
        if piece and piece.lower() not in {"n/a", "na", "tbd", "tba", "none", "unknown"}:
            tokens.add(piece)
    return tokens


def catalog_evidence(entry):
    """Every published configurator field as a raw cell hardware_rows can render."""
    datasheet = (entry.get("datasheet_url") or "").strip()
    values = {
        "SKU": entry["sku"],
        "Title": entry.get("title") or None,
        "Support Series": entry.get("support_series") or None,
        "Families": "\n".join(entry.get("families") or []) or None,
        "Datasheet URL": datasheet or None,
        "Thumbnail": entry.get("thumbnail") or None,
        "Short Description": entry.get("short_desc") or None,
    }
    return {column: {"text": values[column], "value": None, "datetime": None, "role": None,
                     "links": [datasheet] if column == "Datasheet URL" and datasheet else []}
            for column in CATALOG_CELLS if column in values}


def catalog_entry(cells):
    """The configurator fields a stored catalog record carries, as published."""
    missing = [column for column in CATALOG_CELLS if column not in cells]
    if missing:
        raise ValueError(f"Opengear catalog record without configurator evidence: {missing}")
    families = cells["Families"]["text"]
    return {"sku": cells["SKU"]["text"], "title": cells["Title"]["text"],
            "support_series": cells["Support Series"]["text"],
            "families": families.split("\n") if families else [],
            "datasheet_url": cells["Datasheet URL"]["text"] or "",
            "thumbnail": cells["Thumbnail"]["text"], "short_desc": cells["Short Description"]["text"]}


def make_record(section, cells, checked):
    headers = HEADERS[section]
    product, parts = cells[0]["text"], cells[1]["text"]
    eos, eol = parse_date(cells[2]["text"]), parse_date(cells[3]["text"])
    # An announced but undated retirement stays published with a null deadline
    # rather than being dropped or given a date the source never stated.
    if not product or not parts:
        raise ValueError("Opengear record requires product and part scope")
    if eos and eol and eos > eol:
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
            "status": status_from(eol, checked), "upstream": upstream,
            "provenance": {"source_urls": [SOURCE] + [u for u in notices if u != SOURCE],
                           "verifier": VERIFIER, "last_checked": checked}}


def announcement_reason(cells):
    """Why a row is published with a null support deadline, in its own words."""
    eos, eol = cells[2]["text"] or "empty", cells[3]["text"] or "empty"
    return (f"Announced retirement without a published support deadline "
            f"(End of Sale {eos!r}, End of Support {eol!r})")


def announcement_source(record_cells):
    """The notice URL a row links, else the lifecycle page it was published on."""
    for cell in record_cells:
        if cell.get("links"):
            return urljoin(SOURCE, cell["links"][0])
    return SOURCE


def parse_page(html, checked):
    parser = Tables()
    parser.feed(html)
    parser.close()
    records, excluded, announced, found, seen = [], [], [], set(), set()
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
            if product in SOFTWARE:
                # Software appliances and utilities sit in the hardware table but
                # are explicitly outside this hardware collector.
                excluded.append({"product": product, "parts": cells[1]["text"],
                                 "reason": "Software product (software appliance or utility), not hardware lifecycle scope"})
                continue
            # A retirement announced without a date is still hardware: it is
            # published with a null deadline, never dropped and never dated. Its
            # identity matches the dated notice it will become, so the permalink
            # survives the date arriving.
            record = make_record(section, cells, checked)
            if record["id"] in seen:
                raise ValueError(f"Duplicate Opengear identity: {record['id']}")
            seen.add(record["id"])
            records.append(record)
            if not end:
                announced.append({"id": record["id"], "name": record["name"],
                                  "part_scope": record["model_number"], "reason": announcement_reason(cells),
                                  "source_url": announcement_source(cells)})
    if found != set(HEADERS):
        raise ValueError("Missing Opengear hardware lifecycle or revision table")
    return sorted(records, key=lambda r: r["id"]), excluded, announced


def retention_marker(record):
    """A retained record's own statement that the current snapshot lacks it.

    Retained records are the only ones allowed to carry the marker, and only in
    its neutral form: the marker says the source is silent, never that a date
    passed or that support ended.
    """
    evidence = record.get("evidence")
    if evidence is None:
        return None
    if evidence != {"in_source": False}:
        raise ValueError(f"Invalid Opengear retention evidence: {record['id']} {evidence}")
    return evidence


def validate_record(record):
    """Rebuild one Opengear record from its own published evidence, offline.

    Lifecycle and revision rows rebuild through :func:`make_record` from their
    stored raw cells; catalog records rebuild from the configurator cells and
    the matched lifecycle notices they embed. Any drift between a stored record
    and its own evidence fails here, so a tampered file is never published.
    """
    if record["provenance"]["verifier"] != VERIFIER:
        raise ValueError("Invalid Opengear source identity")
    marker = retention_marker(record)
    if record["family"] == CATALOG_FAMILY:
        expected = rebuilt_catalog(record)
    elif record["family"] in HEADERS:
        headers = HEADERS[record["family"]]
        if any(header not in record["upstream"] for header in headers):
            raise ValueError(f"Opengear record without source cells: {record['id']}")
        cells = [record["upstream"][header] for header in headers]
        expected = make_record(record["family"], cells, record["provenance"]["last_checked"])
    else:
        raise ValueError(f"Invalid Opengear record family: {record['family']!r}")
    if marker is not None:
        expected["evidence"] = marker
    if record != expected:
        raise ValueError(f"Opengear record contradicts source evidence: {record['id']}")


def rebuilt_catalog(record):
    """The catalog record its own configurator cells and notice evidence imply."""
    catalog, lifecycle = record.get("catalog"), record.get("lifecycle")
    if not isinstance(catalog, dict) or not isinstance(lifecycle, dict):
        raise ValueError(f"Opengear catalog record without catalog/lifecycle: {record['id']}")
    if not isinstance(catalog.get("listed"), bool) or catalog.get("source_url") != CONFIGURE_SOURCE:
        raise ValueError(f"Invalid Opengear catalog listing evidence: {record['id']}")
    matches = lifecycle.get("matches")
    if not isinstance(matches, list) or not all(isinstance(match, str) for match in matches):
        raise ValueError(f"Opengear catalog record without lifecycle matches: {record['id']}")
    if lifecycle.get("listed") is not bool(matches):
        raise ValueError(f"Opengear catalog record lifecycle flag contradicts its matches: {record['id']}")
    entry = catalog_entry(record["upstream"])
    notices = rebuild_notices(record["upstream"], matches)
    return catalog_record_from(entry, record["provenance"]["last_checked"], notices, listed=catalog["listed"])


def notice_cells(record):
    """One matched lifecycle row's published cells, verbatim, for embedding."""
    return {header: record["upstream"][header] for header in NOTICE_CELLS if header in record["upstream"]}


def embed_notices(upstream, notices):
    """Attach each matched lifecycle row's cells under a key naming that row."""
    for match, cells in notices:
        for header, cell in cells.items():
            upstream[f"{header} ({match})"] = {
                "text": cell["text"], "value": cell["value"], "datetime": cell["datetime"],
                "role": cell["role"], "links": [urljoin(SOURCE, link) for link in cell.get("links", [])]}
    return upstream


def rebuild_notices(upstream, matches):
    """Re-derive the embedded notice evidence of a stored catalog record.

    Only the notice row's own published text and links survive, exactly as
    ``make_record`` re-derives a lifecycle row's dates from its cells: a stored
    value or role that contradicts the text it sits beside fails validation.
    """
    notices = []
    for match in matches:
        cells = {}
        for header in NOTICE_CELLS:
            stored = upstream.get(f"{header} ({match})")
            if stored is None:
                raise ValueError(f"Opengear catalog record without notice evidence: {header} ({match})")
            role = NOTICE_ROLES.get(header)
            cells[header] = {"text": stored["text"], "datetime": None, "role": role,
                             "value": parse_date(stored["text"]) if role else None,
                             "links": [urljoin(SOURCE, link) for link in stored.get("links", [])]}
        notices.append((match, cells))
    return notices


def notice_milestones(notices):
    """Milestones stated by the matched notices, never inferred from listing.

    Two notices naming one SKU with different dates is a contradiction to
    surface, never to settle by ordering or by picking the nearer date.
    """
    milestones = {field: None for field in MILESTONES}
    for match, cells in notices:
        for header, role in NOTICE_ROLES.items():
            value = cells[header]["value"]
            if value is None:
                continue
            if milestones[role] is not None and milestones[role] != value:
                raise ValueError(f"Conflicting Opengear {role} across notices: "
                                 f"{milestones[role]} != {value} ({match})")
            milestones[role] = value
    return milestones


def notice_links(notices):
    """Every notice URL carried by the embedded lifecycle cells, first seen first."""
    return list(dict.fromkeys(link for _, cells in notices
                              for cell in cells.values() for link in cell["links"]))


def catalog_upstream(entry, notices):
    """The catalog record's raw cells: configurator fields plus notice evidence."""
    upstream = catalog_evidence(entry)
    upstream["Policy"] = {"text": f"{CATALOG_POLICY} {LIFECYCLE_POLICY}" if notices else CATALOG_POLICY,
                          "value": None, "datetime": None, "role": None, "links": []}
    return embed_notices(upstream, notices)


def catalog_record_from(entry, checked, notices, listed=True):
    """Build one catalog record from configurator fields and embedded notices."""
    matches = [match for match, _ in notices]
    upstream = catalog_upstream(entry, notices)
    milestones = notice_milestones(notices)
    sources = [CONFIGURE_SOURCE] + ([SOURCE] if notices else [])
    sources += [url for url in notice_links(notices) if url not in sources]
    return {"$schema": RECORD_SCHEMA, "id": catalog_identity(entry["sku"]), "name": entry["sku"],
            "category": "hardware", "vendor": "Opengear", "product_line": "Opengear",
            "family": CATALOG_FAMILY, "model_number": entry["sku"],
            "milestones": milestones,
            "status": status_from(milestones["eol"], checked), "upstream": upstream,
            "catalog": {"listed": listed, "source_url": CONFIGURE_SOURCE},
            "lifecycle": {"listed": bool(matches), "matches": matches},
            "provenance": {"source_urls": sources, "verifier": VERIFIER, "last_checked": checked}}


def catalog_record(entry, checked, matches, listed=True):
    """The published record for one exact configurator SKU.

    Catalog presence is a listing fact: a record carries a date only when a
    lifecycle notice names this exact part string, and then the date is that
    notice's published value, embedded verbatim as evidence. Nothing else is
    ever inferred from listing, absence, or a neighbouring part number.
    """
    matches = sorted(matches, key=lambda record: record["id"])
    return catalog_record_from(entry, checked, [(record["id"], notice_cells(record)) for record in matches],
                               listed)


def catalog_entry(cells):
    """The configurator fields a stored catalog record carries, as published."""
    missing = [column for column in CATALOG_CELLS if column not in cells]
    if missing:
        raise ValueError(f"Opengear catalog record without configurator evidence: {missing}")
    families = cells["Families"]["text"]
    return {"sku": cells["SKU"]["text"], "title": cells["Title"]["text"],
            "support_series": cells["Support Series"]["text"],
            "families": families.split("\n") if families else [],
            "datasheet_url": cells["Datasheet URL"]["text"] or "",
            "thumbnail": cells["Thumbnail"]["text"], "short_desc": cells["Short Description"]["text"]}


def lifecycle_index(records):
    """Exact part string -> hardware lifecycle record, for notice matching.

    Only the hardware section's ``Part #`` column is indexed: a revision notice
    names a revision of a part, never the whole current SKU, so it can never
    imply that the SKU itself is retiring. The replacement column is never
    indexed either, so a successor part can never adopt its predecessor's dates.
    """
    index = {}
    for record in records:
        if record.get("family") != "hardware":
            continue
        for token in part_tokens(record["upstream"].get("Part #", {}).get("text", "")):
            index.setdefault(token, []).append(record)
    return index


def parse_catalog(html, checked, lifecycle):
    """Catalog records for every exact configurator SKU, notice-linked or not.

    ``lifecycle`` is the hardware lifecycle snapshot; a SKU is linked only when
    a notice's published part scope states that exact part string. Every
    configurator entry becomes a record or is reported, so no SKU is dropped.
    """
    entries = parse_catalog_data(html)
    index = lifecycle_index(lifecycle)
    records, unmatched = [], []
    for entry in entries:
        matches = index.get(entry["sku"], [])
        if not matches:
            unmatched.append(entry["sku"])
        records.append(catalog_record(entry, checked, matches))
    return sorted(records, key=lambda record: record["id"]), unmatched


def retain_record(record, index):
    """Re-publish a committed record its source no longer states, explicitly marked.

    The record is rebuilt from its own stored evidence exactly as
    :func:`validate_record` would, so retention cannot smuggle in a date or a
    detail the source never published; only the marker saying the current
    snapshot lacks the row is added. Milestones stay what the vendor published —
    an absent row is not an end of life, and a SKU leaving the catalog is not
    one either. ``last_checked`` is carried over rather than refreshed: the
    source was not observed to state this row, so claiming a fresh check would
    be false. A retained catalog record still takes its notice links from the
    fresh lifecycle snapshot, so a notice naming a delisted SKU is not missed.
    """
    checked = record["provenance"]["last_checked"]
    if record["family"] == CATALOG_FAMILY:
        entry = catalog_entry(record["upstream"])
        return catalog_record(entry, checked, index.get(entry["sku"], []), listed=False)
    cells = [record["upstream"][header] for header in HEADERS[record["family"]]]
    return {**make_record(record["family"], cells, checked), "evidence": {"in_source": False}}


def combine_records(lifecycle, catalog, previous, checked):
    """The complete Opengear snapshot: lifecycle rows plus exact-SKU listings.

    ``previous`` is the committed snapshot. A committed record the fresh sources
    do not repeat is retained and marked (``catalog.listed`` false for a listing,
    ``evidence.in_source`` false for a lifecycle row) rather than deleted, so a
    published permalink never disappears because a vendor dropped a row.
    """
    fresh = {}
    for record in list(lifecycle) + list(catalog):
        if record["id"] in fresh:
            raise ValueError(f"Duplicate Opengear identity: {record['id']}")
        fresh[record["id"]] = record
    index = lifecycle_index(lifecycle)
    retained = [retain_record(record, index) for record in previous if record["id"] not in fresh]
    return sorted(list(fresh.values()) + retained, key=lambda record: record["id"])


def source_report(report, catalog, unmatched, records, previous):
    """Per-source accounting for one Opengear import; every record is reported.

    The identity that must hold: every lifecycle or software data row becomes a
    published record, an announcement, or an exclusion, and every configurator
    entry becomes a published catalog record, listed or retained.
    """
    committed = {record["id"] for record in previous}
    retained_unlisted = sorted(({"id": record["id"], "name": record["name"]}
                                for record in records if record["family"] == CATALOG_FAMILY
                                and not record["catalog"]["listed"]), key=lambda entry: entry["id"])
    report["catalog"] = {
        "source_url": CONFIGURE_SOURCE, "models": len(catalog), "expected_models": CATALOG_MODELS,
        "listed": len([record for record in catalog if record["catalog"]["listed"]]),
        "matched_lifecycle": sum(1 for record in catalog if record["lifecycle"]["matches"]),
        "unmatched_lifecycle": len(unmatched),
        "unmatched_skus": unmatched,
        "retained_unlisted": len(retained_unlisted),
        "retained_unlisted_records": retained_unlisted,
    }
    report["lifecycle"]["retained_absent"] = sorted(
        ({"id": record["id"], "name": record["name"], "family": record["family"]}
         for record in records if record.get("evidence", {}).get("in_source") is False),
        key=lambda entry: entry["id"])
    report["record_counts"] = {
        "hardware": sum(1 for r in records if r["family"] == "hardware"),
        "revision": sum(1 for r in records if r["family"] == "revision"),
        "catalog": sum(1 for r in records if r["family"] == CATALOG_FAMILY),
        "added": sorted(r["id"] for r in records if r["id"] not in committed),
        "retained": sorted(record["id"] for record in records if record["id"] in committed
                           and (record.get("evidence", {}).get("in_source") is False
                                or (record["family"] == CATALOG_FAMILY
                                    and not record["catalog"]["listed"]))),
        "status_unknown": sum(1 for r in records if r["status"] == "unknown"),
    }
    report["total_records"] = len(records)
    if len(catalog) != CATALOG_MODELS:
        report["catalog"]["drift"] = (f"Configurator publishes {len(catalog)} exact SKUs; this collector is "
                                      f"built against {CATALOG_MODELS}. Review the change before publishing.")
    report["limitations"] = [
        "Catalog listing is a current-sale fact from the Opengear configurator, not a support entitlement.",
        "Removal from the catalog is not an end of life: retained records keep catalog.listed false.",
        "Lifecycle notices are matched by exact published part string only, never by replacement part, "
        "family or substring, so grouped and revision scopes stay grouped.",
        "A revision-only notice is never applied to the whole SKU it revises.",
        "A SKU absent from the lifecycle tables has no published support date here; none is inferred.",
        "Support dates come from Opengear's public lifecycle tables; contract extensions are out of scope.",
        "Software sections, and software products listed in the hardware table, stay out of hardware scope.",
    ]
    return report


def import_opengear():
    """Fetch both Opengear sources, publish once, then record what changed.

    Nothing is written until both sources parse and every record validates: the
    catalog, the lifecycle tables and the change ledger are one snapshot, so a
    half-fetched source can never leave the committed data inconsistent.
    """
    from .changes import load_history, update_history

    checked = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    lifecycle, excluded, announced = parse_page(fetch(SOURCE), checked)
    catalog, unmatched = parse_catalog(fetch(CONFIGURE_SOURCE), checked, lifecycle)
    destination = ROOT / "data"
    # Only this source's own records: a refresh never reasons about another
    # verifier's snapshot (eosl.date owns the rest of data/hardware/).
    previous = [record for record in get_records(destination)
                if record["provenance"]["verifier"] == VERIFIER]
    records = combine_records(lifecycle, catalog, previous, checked)
    imported = publish_records(records, VERIFIER, destination)
    # The ledger records what the published snapshot changed. Nothing is written
    # before the records are: a ledger entry whose record is not on disk would
    # claim an observation the catalog cannot show.
    ledger_path = destination / LEDGER
    history = update_history(previous, imported, checked, load_history(ledger_path))
    dump(ledger_path, history)
    report = {"source_url": SOURCE, "verifier": VERIFIER, "checked_at": checked,
              "record_scope": ("Opengear hardware lifecycle rows and part groups (dated retirements and "
                               "undated announcements, exact part strings) plus the current configurator's "
                               "exact SKU listings, which carry no support deadline of their own"),
              "lifecycle": {"source_url": SOURCE,
                            # Every lifecycle/software data row becomes a record or an
                            # exclusion, so this identity is the row accounting.
                            "rows": len(lifecycle) + len(excluded),
                            "published_records": len(lifecycle),
                            "dated_records": len(lifecycle) - len(announced),
                            "unknown_date_records": len(announced),
                            "excluded_rows": len(excluded),
                            "announcements": announced},
              "imported_count": len(imported), "excluded_count": len(excluded), "excluded": excluded}
    source_report(report, catalog, unmatched, imported, previous)
    dump(destination / "opengear-import.json", report)
    counts = report["record_counts"]
    print(f"Imported {len(imported)} Opengear records ({counts['hardware']} lifecycle hardware, "
          f"{counts['revision']} revision, {counts['catalog']} catalog SKUs; "
          f"{report['catalog']['matched_lifecycle']} catalog SKUs named by a lifecycle notice); "
          f"excluded {len(excluded)} rows (data/opengear-import.json)")
    return imported


class CatalogData(HTMLParser):
    """Read only the configurator's authoritative embedded product dataset."""

    def __init__(self):
        super().__init__()
        self.active = False
        self.scripts = []

    def handle_starttag(self, tag, attrs):
        if tag == "script" and dict(attrs).get("id") == "og-data-js-extra":
            self.active = True
            self.scripts.append("")

    def handle_data(self, data):
        if self.active:
            self.scripts[-1] += data

    def handle_endtag(self, tag):
        if tag == "script":
            self.active = False


def parse_catalog_data(html):
    """Return exact vendor SKU objects, never navigation or image-name matches."""
    parser = CatalogData()
    parser.feed(html)
    parser.close()
    if len(parser.scripts) != 1:
        raise ValueError("Expected one Opengear configurator dataset")
    match = re.search(r"\bvar\s+ogData\s*=\s*", parser.scripts[0])
    if not match:
        raise ValueError("Missing Opengear ogData assignment")
    payload, end = json.JSONDecoder().raw_decode(parser.scripts[0][match.end():])
    if not isinstance(payload, dict):
        raise ValueError("Invalid Opengear configurator dataset")
    products = payload.get("products")
    if not isinstance(products, list) or not products:
        raise ValueError("Empty or invalid Opengear configurator products")
    seen = set()
    for product in products:
        if not isinstance(product, dict):
            raise ValueError("Invalid Opengear configurator product")
        sku = product.get("sku")
        if not isinstance(sku, str) or not re.fullmatch(r"[A-Z0-9]+(?:-[A-Z0-9]+)*", sku):
            raise ValueError("Invalid Opengear configurator SKU")
        if sku in seen:
            raise ValueError(f"Duplicate Opengear configurator SKU: {sku}")
        seen.add(sku)
    return sorted(products, key=lambda product: product["sku"])
