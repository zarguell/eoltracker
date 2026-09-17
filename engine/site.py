"""Publish the validated catalog: static website, v1 JSON endpoints, schema copies.

`build()` never fetches anything. It validates the committed catalogs through
`engine.validation.validate_data()` and `engine.validation.validate_hardware()`
(raising on any inconsistency), then writes `_site/` from scratch: the catalog
pages, the per-product and per-hardware-model pages, `v1/feed.json` (every
normalized software record), `v1/products.json` (summaries with absolute
product endpoint URLs), `v1/hardware.json` (hardware summaries), byte-identical
`v1/products/{id}.json` and `v1/hardware/{id}.json` records, and copies of
`schema/*.json` at `v1/schema/`.

Two upstream sources are published side by side. Software comes from
endoflife.date (MIT); hardware comes from eosl.date, which aggregates public
vendor announcements and publishes no license, so it is attributed by name and
link rather than relicensed.
"""
import json
import re
import shutil
from datetime import date, datetime, timezone
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .importer import ROOT
from .validation import validate_data, validate_hardware

TEMPLATES = Path(__file__).resolve().parent / "templates"
SCHEMA_DIR = ROOT / "schema"
DEFAULT_DATA = ROOT / "data"
DEFAULT_OUT = ROOT / "_site"

SITE_ORIGIN = "https://zarguell.github.io"
BASE_PATH = "/eoltracker/"
SITE_URL = SITE_ORIGIN + BASE_PATH
SCHEMA_VERSION = "1.0"

SOURCE_NAME = "endoflife.date"
SOURCE_SITE = "https://endoflife.date/"
SOURCE_LICENSE = "MIT"
SOURCE_LICENSE_URL = "https://github.com/endoflife-date/endoflife.date/blob/master/LICENSE"
# The hardware catalog is scraped from eosl.date, which republishes vendor
# announcements and states no license. It is therefore cited, not relicensed:
# name, link and what the data actually is.
HARDWARE_SOURCE_NAME = "eosl.date"
HARDWARE_SOURCE_SITE = "https://eosl.date/"
HARDWARE_SOURCE_ATTRIBUTION = ("Hardware lifecycle data comes from eosl.date by Subash Geetha Krishnan, "
                               "aggregated from public vendor announcements.")
REPOSITORY_URL = "https://github.com/zarguell/eoltracker"
# Root notice files republished unchanged alongside the catalog when present.
NOTICE_FILES = ("THIRD-PARTY-NOTICES.txt", "OASIS-NOTICE.txt")

# One entry per normalized milestone: the label shown to readers, the upstream
# fields that can feed it, and the conservative rule that decides whether they do.
MILESTONES = (
    {
        "key": "ga",
        "short": "GA",
        "label": "General availability",
        "detail": "First public release. Taken from the upstream releaseDate.",
    },
    {
        "key": "eos",
        "short": "EoS",
        "label": "End of sale",
        "detail": "Last day new licenses or units are sold. Only mapped from an upstream field whose label names an end of sale.",
    },
    {
        "key": "eossec",
        "short": "EoSS",
        "label": "End of security support",
        "detail": "Last day security fixes are published. Mapped from eolFrom or eoesFrom only when the label names security support.",
    },
    {
        "key": "eol",
        "short": "EoL",
        "label": "End of life",
        "detail": "End of all support. A published extended-support date wins; otherwise eolFrom when its label describes a full support end.",
    },
)
MILESTONE_FIELDS = {
    "ga": ("releaseDate",),
    "eos": ("eoasFrom", "discontinuedFrom"),
    "eossec": ("eolFrom", "eoesFrom"),
    "eol": ("eolFrom", "eoesFrom"),
}
# The hardware catalog uses its own vocabulary: eosl.date publishes a release
# date column, an end-of-sales column and a terminal support column, and no
# security-support column at all, so the same four keys carry different rules.
# Keeping them apart means a hardware page never quotes a software mapping rule
# that does not apply to the source it was built from.
HARDWARE_MILESTONES = (
    {
        "key": "ga",
        "short": "GA",
        "label": "General availability",
        "detail": "First availability, when the source publishes a release or launch date. Opengear does not publish GA in its lifecycle tables.",
    },
    {
        "key": "eos",
        "short": "EoS",
        "label": "End of sale",
        "detail": "Last day sold: eosl.date's end-of-life-date column or Opengear's End of Sale / Old Part Sales End.",
    },
    {
        "key": "eossec",
        "short": "EoSS",
        "label": "End of security support",
        "detail": "No separate security-support deadline is normalized from these sources. Opengear contract exceptions remain in raw policy notes.",
    },
    {
        "key": "eol",
        "short": "EoL",
        "label": "End of support",
        "detail": "Published support end: eosl.date's EOSL/LDOS or Opengear's End of Support / Old Part Support Ends. Individual contract exceptions may apply.",
    },
)
MILESTONE_KEYS = tuple(milestone["key"] for milestone in HARDWARE_MILESTONES)
# eosl.date states lifecycle status through the row class of each model row.
HARDWARE_STATUSES = (
    {"key": "supported", "label": "Supported", "detail": "Published in a supported row: no support end has been announced."},
    {"key": "expiring", "label": "Expiring", "detail": "Source warning row, or Opengear's announced support deadline has not yet passed."},
    {"key": "eol", "label": "End of life", "detail": "Source end-of-life row, or Opengear's published support deadline has passed; contract exceptions may apply."},
)
HARDWARE_STATUS_ORDER = tuple(status["key"] for status in HARDWARE_STATUSES)
# Upstream date fields, in the order they appear in the raw release object, and
# the label field that qualifies each one.
UPSTREAM_DATE_FIELDS = (
    ("releaseDate", None),
    ("eoasFrom", "eoas"),
    ("discontinuedFrom", "discontinued"),
    ("eolFrom", "eol"),
    ("eoesFrom", "eoes"),
)
LABEL_RULES = (
    ("eoas", "End-of-sale date when the text names an end of sale."),
    ("discontinued", "End-of-sale date when the text names an end of sale; otherwise recorded only, never turned into a date."),
    ("eol", "End of security support when the text names security support; end of life only when no extended-support label is set and the text describes a full support end."),
    ("eoes", "Extended support. A published date also sets end of life, and a security-support text supersedes end of security support."),
)

env = Environment(
    loader=FileSystemLoader(str(TEMPLATES)),
    autoescape=select_autoescape(["html", "xml"]),
    trim_blocks=True,
    lstrip_blocks=True,
    keep_trailing_newline=True,
)


def tojson_pretty(value):
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)


env.filters["tojson_pretty"] = tojson_pretty


def url_for(path=""):
    """Site-root URL for a path inside the published site (GitHub Pages subpath)."""
    return BASE_PATH + str(path).lstrip("/")


def site_url(path=""):
    """Absolute URL for a path inside the published site."""
    return SITE_URL + str(path).lstrip("/")


def human_date(value):
    if not value:
        return None
    parsed = date.fromisoformat(value)
    return f"{parsed.strftime('%b')} {parsed.day}, {parsed.year}"


def human_datetime(value):
    if not value:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    return f"{parsed.strftime('%b')} {parsed.day}, {parsed.year} at {parsed.strftime('%H:%M')} UTC"


def plural(count, word):
    return f"{count} {word}" if count == 1 else f"{count} {word}s"


def version_key(value):
    """Sortable key for release labels: numbers compare numerically, text alphabetically."""
    parts = re.split(r"(\d+)", str(value))
    return tuple((0, int(part)) if part.isdigit() else (1, part) for part in parts if part != "")


env.globals.update(
    url_for=url_for,
    site_url=site_url,
    feed_abs=site_url("v1/feed.json"),
    products_abs=site_url("v1/products.json"),
    hardware_abs=site_url("v1/hardware.json"),
    human_date=human_date,
    human_datetime=human_datetime,
    plural=plural,
    base_path=BASE_PATH,
    repository_url=REPOSITORY_URL,
    source_name=SOURCE_NAME,
    source_site=SOURCE_SITE,
    source_license=SOURCE_LICENSE,
    source_license_url=SOURCE_LICENSE_URL,
    hardware_source_name=HARDWARE_SOURCE_NAME,
    hardware_source_site=HARDWARE_SOURCE_SITE,
    hardware_source_attribution=HARDWARE_SOURCE_ATTRIBUTION,
)


def release_rows(record):
    """Template-ready rows for one product, newest release first."""
    labels = record.get("labels") or {}
    rows = []
    for release in record["releases"]:
        upstream = release["upstream"]
        raw = []
        for field, label_key in UPSTREAM_DATE_FIELDS:
            value = upstream.get(field)
            if isinstance(value, str) and value:
                raw.append({"field": field, "value": value, "label": labels.get(label_key) if label_key else None})
        cells = {}
        for milestone in MILESTONES:
            key = milestone["key"]
            value = release["milestones"][key]
            notes = []
            for entry in raw:
                if entry["field"] not in MILESTONE_FIELDS[key]:
                    continue
                # Keep only the raw values the normalized date does not already show,
                # so a cell explains what was set aside instead of repeating itself.
                if value and entry["value"] == value:
                    continue
                notes.append(f"{entry['field']} {entry['value']}" + (f" ({entry['label']})" if entry["label"] else ""))
            cells[key] = {"value": value, "human": human_date(value), "notes": "; ".join(notes) or None}
        latest = upstream.get("latest") or {}
        rows.append({
            "id": release["id"],
            "name": release["name"] or release["id"],
            "cells": cells,
            "lts": bool(upstream.get("isLts")),
            "eol_flag": bool(upstream.get("isEol")),
            "maintained": bool(upstream.get("isMaintained")),
            "latest": {
                "name": latest.get("name"),
                "date": latest.get("date"),
                "link": latest.get("link"),
            },
            "raw": raw,
        })
    rows.sort(key=lambda row: (row["cells"]["ga"]["value"] is not None, row["cells"]["ga"]["value"] or "", version_key(row["id"])), reverse=True)
    return rows


def milestone_coverage(rows, milestones=MILESTONES):
    total = len(rows)
    coverage = []
    for milestone in milestones:
        known = sum(1 for row in rows if row["cells"][milestone["key"]]["value"])
        coverage.append({
            "key": milestone["key"],
            "short": milestone["short"],
            "label": milestone["label"],
            "detail": milestone["detail"],
            "known": known,
            "total": total,
            "percent": round(100 * known / total) if total else 0,
        })
    return coverage


def upcoming_events(rows, today, limit=None, milestones=MILESTONES):
    """Published milestone dates that have not passed yet, soonest first."""
    events = []
    for row in rows:
        for milestone in milestones:
            if milestone["key"] == "ga":
                continue
            value = row["cells"][milestone["key"]]["value"]
            if not value or value < today.isoformat():
                continue
            events.append({
                "release": row["name"],
                "release_id": row["id"],
                "milestone": milestone["label"],
                "key": milestone["key"],
                "date": value,
                "human": human_date(value),
                "days": (date.fromisoformat(value) - today).days,
            })
    events.sort(key=lambda event: (event["date"], event["release"]))
    return events[:limit] if limit else events


def summarize(record, rows, today):
    latest = rows[0] if rows else None
    next_events = upcoming_events(rows, today, limit=1)
    return {
        "id": record["id"],
        "name": record["name"],
        "upstream_category": record["upstream_category"],
        "search": f"{record['name']} {record['id']} {record['upstream_category']}".lower(),
        "releases": len(rows),
        "coverage": milestone_coverage(rows),
        "latest": {
            "name": latest["name"],
            "id": latest["id"],
            "ga": latest["cells"]["ga"]["value"],
            "ga_human": latest["cells"]["ga"]["human"],
        } if latest else None,
        "next": next_events[0] if next_events else None,
        "json": site_url(f"v1/products/{record['id']}.json"),
        "page": site_url(f"products/{record['id']}/"),
        "source": record["provenance"]["source_url"],
    }


def hardware_rows(record):
    """Template-ready rows for one hardware model: a single row of milestones.

    A hardware record describes one model, not a family of releases, so the
    shape mirrors a release row instead of repeating one. Every raw upstream
    cell becomes a note when the normalized date for its role differs from the
    value it published, so a date set aside by a rule stays visible.
    """
    milestones = record["milestones"]
    raw = []
    for column, cell in record["upstream"].items():
        raw.append({
            "column": column,
            "text": cell.get("text") or None,
            "value": cell.get("value"),
            "datetime": cell.get("datetime"),
            "role": cell.get("role"),
            "links": cell.get("links") or [],
        })
    cells = {}
    for milestone in HARDWARE_MILESTONES:
        key = milestone["key"]
        value = milestones[key]
        notes = [f"{entry['column']} {entry['value']}" for entry in raw
                 if entry["role"] == key and entry["value"] and entry["value"] != value]
        cells[key] = {"value": value, "human": human_date(value), "notes": "; ".join(notes) or None}
    return {
        "id": record["id"],
        "name": record["name"],
        "cells": cells,
        "raw": raw,
    }


def summarize_hardware(record, rows, today):
    next_events = upcoming_events([rows], today, limit=1, milestones=HARDWARE_MILESTONES)
    return {
        "id": record["id"],
        "name": record["name"],
        "vendor": record["vendor"],
        "product_line": record["product_line"],
        "family": record.get("family"),
        "model_number": record.get("model_number"),
        "status": record["status"],
        "search": f"{record['name']} {record['id']} {record['vendor']} {record['product_line']} "
                  f"{record.get('family') or ''} {record.get('model_number') or ''}".lower(),
        "coverage": milestone_coverage([rows], HARDWARE_MILESTONES),
        "milestones": {key: record["milestones"][key] for key in MILESTONE_KEYS},
        "next": next_events[0] if next_events else None,
        "json": site_url(f"v1/hardware/{record['id']}.json"),
        "page": site_url(f"hardware/{record['id']}/"),
        "source": (record["provenance"]["source_urls"] or [None])[0],
    }


def hardware_vendors(records):
    """Vendor facets with their model counts, largest first then alphabetical."""
    counts = {}
    for record in records:
        vendor = record["vendor"]
        counts[vendor] = counts.get(vendor, 0) + 1
    return [{"name": name, "count": counts[name]}
            for name in sorted(counts, key=lambda name: (-counts[name], name))]


def hardware_statuses(records):
    counts = {}
    for record in records:
        counts[record["status"]] = counts.get(record["status"], 0) + 1
    return [{**status, "count": counts.get(status["key"], 0)} for status in HARDWARE_STATUSES]


def catalog_categories(records):
    counts = {}
    for record in records:
        counts[record["upstream_category"]] = counts.get(record["upstream_category"], 0) + 1
    return [{"name": name, "count": counts[name]} for name in sorted(counts)]


def render(template, **context):
    return env.get_template(template).render(**context)


def write(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def write_json(path, value):
    write(path, json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def build(data_dir=None, out_dir=None):
    """Write the complete static site and v1 endpoints to `_site/`."""
    data_dir = Path(data_dir) if data_dir is not None else DEFAULT_DATA
    out = Path(out_dir) if out_dir is not None else DEFAULT_OUT
    records = validate_data(data_dir)
    hardware = validate_hardware(data_dir)
    manifest = json.loads((data_dir / "manifest.json").read_text(encoding="utf-8"))
    if manifest["product_count"] != len(records):
        raise ValueError(f"Manifest advertises {manifest['product_count']} products, found {len(records)}")
    # The manifest may predate the hardware catalog, so its count is advisory.
    if manifest.get("hardware_count", len(hardware)) != len(hardware):
        raise ValueError(f"Manifest advertises {manifest['hardware_count']} hardware models, found {len(hardware)}")
    today = datetime.now(timezone.utc).date()

    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)

    # ---- machine-readable endpoints -------------------------------------
    write(out / ".nojekyll", "")
    write(out / "robots.txt", "User-agent: *\nAllow: /\n")
    notices = {}
    for name in NOTICE_FILES:
        source = ROOT / name
        if source.exists():
            shutil.copyfile(source, out / name)
            notices[name] = url_for(name)
    (out / "v1" / "schema").mkdir(parents=True)
    schema_files = sorted(SCHEMA_DIR.glob("*.json"))
    for schema_file in schema_files:
        shutil.copyfile(schema_file, out / "v1" / "schema" / schema_file.name)

    feed = {"schema_version": SCHEMA_VERSION, **manifest, "products": records}
    write_json(out / "v1" / "feed.json", feed)
    rows_by_id = {record["id"]: release_rows(record) for record in records}
    summaries = [summarize(record, rows_by_id[record["id"]], today) for record in records]
    write_json(out / "v1" / "products.json", {"schema_version": SCHEMA_VERSION, **manifest, "products": summaries})
    (out / "v1" / "products").mkdir(parents=True)
    for record in records:
        shutil.copyfile(data_dir / "products" / f"{record['id']}.json", out / "v1" / "products" / f"{record['id']}.json")

    hardware_rows_by_id = {record["id"]: hardware_rows(record) for record in hardware}
    hardware_summaries = [summarize_hardware(record, hardware_rows_by_id[record["id"]], today)
                          for record in hardware]
    # The JSON index keeps slug order, like the product index. The rendered
    # tables ship in model-name order instead, which is the default sort of the
    # filter script, so a page costs no reordering work when it loads.
    hardware_page = sorted(hardware_summaries, key=lambda model: model["name"].lower())
    write_json(out / "v1" / "hardware.json", {
        "schema_version": SCHEMA_VERSION, **manifest,
        "hardware_count": len(hardware), "hardware": hardware_summaries})
    (out / "v1" / "hardware").mkdir(parents=True)
    for record in hardware:
        shutil.copyfile(data_dir / "hardware" / f"{record['id']}.json",
                        out / "v1" / "hardware" / f"{record['id']}.json")
    opengear_report = data_dir / "opengear-import.json"
    if opengear_report.exists():
        shutil.copyfile(opengear_report, out / "v1" / "opengear-import.json")

    # ---- shared assets ---------------------------------------------------
    write(out / "style.css", (TEMPLATES / "style.css").read_text(encoding="utf-8"))
    write(out / "app.js", (TEMPLATES / "app.js").read_text(encoding="utf-8"))

    # ---- pages -----------------------------------------------------------
    refresh = {
        "iso": manifest["generated_at"],
        "human": human_datetime(manifest["generated_at"]),
    }
    coverage = milestone_coverage([row for rows in rows_by_id.values() for row in rows])
    categories = catalog_categories(records)
    hardware_coverage = milestone_coverage([row for row in hardware_rows_by_id.values()])
    hardware_vendor_facets = hardware_vendors(hardware)
    hardware_status_facets = hardware_statuses(hardware)
    common = {
        "product_count": manifest["product_count"],
        "release_count": manifest["release_count"],
        "excluded_count": len(manifest["excluded_hardware"]),
        "hardware_count": len(hardware),
        "refresh": refresh,
        "milestone_meta": MILESTONES,
        "hardware_milestone_meta": HARDWARE_MILESTONES,
        "hardware_status_meta": HARDWARE_STATUSES,
        "hardware_vendors": hardware_vendor_facets,
        "hardware_statuses": hardware_status_facets,
        "schema_version": SCHEMA_VERSION,
        "notices": notices,
        "schema_files": [f"v1/schema/{f.name}" for f in schema_files],
    }

    write(out / "index.html", render(
        "index.html",
        **common,
        active="index",
        canonical=site_url(),
        title="EOL Tracker — software and hardware lifecycle dates",
        description=(f"Normalized general availability, end-of-sale, security-support and end-of-life dates "
                     f"for {manifest['product_count']} software products and {len(hardware)} hardware models, "
                     f"republished from community catalogs and vendor notices with per-record provenance."),
        products=summaries,
        coverage=coverage,
        categories=categories,
        hardware=hardware_page,
        hardware_coverage=hardware_coverage,
        feed_url=url_for("v1/feed.json"),
        products_url=url_for("v1/products.json"),
        hardware_url=url_for("v1/hardware.json"),
    ))

    write(out / "hardware" / "index.html", render(
        "hardware-index.html",
        **common,
        active="hardware",
        canonical=site_url("hardware/"),
        title="Hardware lifecycle dates — EOL Tracker",
        description=(f"General availability, end of sale and end-of-support dates for {len(hardware)} hardware "
                     f"models and product groups from {len(hardware_vendor_facets)} vendors, with source-specific provenance."),
        hardware=hardware_page,
        hardware_coverage=hardware_coverage,
        hardware_url=url_for("v1/hardware.json"),
    ))

    for record in hardware:
        rows = hardware_rows_by_id[record["id"]]
        source_urls = record["provenance"]["source_urls"]
        write(out / "hardware" / record["id"] / "index.html", render(
            "hardware.html",
            **common,
            active="hardware",
            canonical=site_url(f"hardware/{record['id']}/"),
            title=f"{record['name']} lifecycle dates — EOL Tracker",
            description=(f"General availability, end of sale and end-of-support dates for the {record['name']} "
                         f"{record['product_line']} model or product group, with raw source values and provenance."),
            model=record,
            rows=rows,
            coverage=milestone_coverage([rows], HARDWARE_MILESTONES),
            json_url=url_for(f"v1/hardware/{record['id']}.json"),
            json_abs=site_url(f"v1/hardware/{record['id']}.json"),
            upstream_urls=source_urls,
            hardware_source_name="Opengear" if record["provenance"]["verifier"] == "deterministic-opengear" else HARDWARE_SOURCE_NAME,
            hardware_source_site=source_urls[0],
            hardware_source_attribution=("Lifecycle dates published directly by Opengear; grouped parts and contract exceptions are retained below."
                                         if record["provenance"]["verifier"] == "deterministic-opengear" else HARDWARE_SOURCE_ATTRIBUTION),
        ))

    for record in records:
        rows = rows_by_id[record["id"]]
        page_events = upcoming_events(rows, today, limit=8)
        write(out / "products" / record["id"] / "index.html", render(
            "product.html",
            **common,
            active=None,
            canonical=site_url(f"products/{record['id']}/"),
            title=f"{record['name']} lifecycle dates — EOL Tracker",
            description=(f"General availability, end-of-sale, security-support and end-of-life dates for every "
                         f"{record['name']} release, with raw endoflife.date values and provenance."),
            product=record,
            releases=rows,
            coverage=milestone_coverage(rows),
            events=page_events,
            labels=record.get("labels") or {},
            label_rules=LABEL_RULES,
            identifiers=record.get("identifiers") or [],
            links=record.get("links") or {},
            json_url=url_for(f"v1/products/{record['id']}.json"),
            json_abs=site_url(f"v1/products/{record['id']}.json"),
            upstream_url=record["provenance"]["source_url"],
        ))

    write(out / "api" / "index.html", render(
        "api.html",
        **common,
        active="api",
        canonical=site_url("api/"),
        title="API and schema — EOL Tracker",
        description="JSON endpoints, the normalized record shapes, and the conservative upstream mapping rules behind EOL Tracker.",
        feed_url=url_for("v1/feed.json"),
        products_url=url_for("v1/products.json"),
        hardware_url=url_for("v1/hardware.json"),
        sample_product=records[0]["id"] if records else None,
        sample_hardware=hardware[0]["id"] if hardware else None,
        openeox_url=url_for("v1/openeox/index.json"),
    ))

    write(out / "404.html", render(
        "404.html",
        **common,
        active=None,
        canonical=site_url("404.html"),
        title="Page not found — EOL Tracker",
        description="No page at this address. Browse the software and hardware catalogs instead.",
        products=summaries[:5],
    ))
