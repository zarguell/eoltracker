"""Publish the validated catalog: static website, v1 JSON endpoints, schema copies.

`build()` never fetches anything. It validates the committed catalog through
`engine.validation.validate_data()` (raising on any inconsistency), then writes
`_site/` from scratch: the catalog pages, the per-product pages, `v1/feed.json`
(every normalized record), `v1/products.json` (summaries with absolute product
endpoint URLs), byte-identical `v1/products/{id}.json` records, and copies of
`schema/*.json` at `v1/schema/`.
"""
import json
import re
import shutil
from datetime import date, datetime, timezone
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .importer import ROOT
from .validation import validate_data

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
MILESTONES_BY_KEY = {m["key"]: m for m in MILESTONES}
MILESTONE_FIELDS = {
    "ga": ("releaseDate",),
    "eos": ("eoasFrom", "discontinuedFrom"),
    "eossec": ("eolFrom", "eoesFrom"),
    "eol": ("eolFrom", "eoesFrom"),
}
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
    human_date=human_date,
    human_datetime=human_datetime,
    plural=plural,
    base_path=BASE_PATH,
    repository_url=REPOSITORY_URL,
    source_name=SOURCE_NAME,
    source_site=SOURCE_SITE,
    source_license=SOURCE_LICENSE,
    source_license_url=SOURCE_LICENSE_URL,
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


def milestone_coverage(rows):
    total = len(rows)
    coverage = []
    for milestone in MILESTONES:
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


def upcoming_events(rows, today, limit=None):
    """Published milestone dates that have not passed yet, soonest first."""
    events = []
    for row in rows:
        for milestone in MILESTONES:
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
    manifest = json.loads((data_dir / "manifest.json").read_text(encoding="utf-8"))
    if manifest["product_count"] != len(records):
        raise ValueError(f"Manifest advertises {manifest['product_count']} products, found {len(records)}")
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
    common = {
        "manifest": manifest,
        "product_count": manifest["product_count"],
        "release_count": manifest["release_count"],
        "excluded_count": len(manifest["excluded_hardware"]),
        "refresh": refresh,
        "milestone_meta": MILESTONES,
        "schema_version": SCHEMA_VERSION,
        "notices": notices,
        "schema_files": [f"v1/schema/{f.name}" for f in schema_files],
    }

    write(out / "index.html", render(
        "index.html",
        **common,
        active="index",
        canonical=site_url(),
        title="EOL Tracker — software lifecycle dates from endoflife.date",
        description=(f"Normalized general availability, end-of-sale, security-support and end-of-life dates "
                     f"for {manifest['product_count']} software products, republished from endoflife.date with per-record provenance."),
        products=summaries,
        coverage=coverage,
        categories=categories,
        feed_url=url_for("v1/feed.json"),
        products_url=url_for("v1/products.json"),
        feed_abs=site_url("v1/feed.json"),
        products_abs=site_url("v1/products.json"),
        schema_abs=site_url("v1/schema/product.json"),
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
        description="JSON endpoints, the normalized record shape, and the conservative upstream mapping rules behind EOL Tracker.",
        feed_url=url_for("v1/feed.json"),
        products_url=url_for("v1/products.json"),
        sample_product=records[0]["id"] if records else None,
        openeox_url=url_for("v1/openeox/index.json"),
    ))

    write(out / "404.html", render(
        "404.html",
        **common,
        active=None,
        canonical=site_url("404.html"),
        title="Page not found — EOL Tracker",
        description="No page at this address. Browse the software lifecycle catalog instead.",
        products=summaries[:5],
    ))
