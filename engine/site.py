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
from . import contribute
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
# Catalog rows have no status of their own — a current catalogue listing says
# nothing about support — so `unknown` is a first-class, neutral value rather
# than a default. It is deliberately not in HARDWARE_STATUS_ORDER: neutral
# records sort last instead of landing between two dated claims.
HARDWARE_STATUSES = (
    {"key": "supported", "label": "Supported", "detail": "Published in a supported row: no support end has been announced."},
    {"key": "expiring", "label": "Expiring", "detail": "Source warning row, or Opengear's announced support deadline has not yet passed."},
    {"key": "eol", "label": "End of life", "detail": "Source end-of-life row, or Opengear's published support deadline has passed; contract exceptions may apply."},
    {"key": "unknown", "label": "Status unknown", "detail": "No support deadline and no lifecycle notice published for this record, so it carries no support claim in either direction. A current catalogue listing, or a revision-only notice, does not end support."},
)
HARDWARE_STATUS_ORDER = tuple(status["key"] for status in HARDWARE_STATUSES if status["key"] != "unknown")
# ---------------------------------------------------------------------------
# Exact Opengear catalogue models (vendor configurator).
#
# These records are not lifecycle rows: each one is one exact vendor model
# string, and it stays that record even after a notice names it. It carries no
# milestone of its own and no support status — the pairs below say only whether
# it is currently listed by the vendor and whether an exact notice for it
# exists right now. Everything here is absent rather than guessed for records
# from other sources.
CONFIGURE_SOURCE_URL = "https://opengear.com/configure/"
CONFIGURE_SOURCE_NAME = "Opengear product configurator"
END_LIFE_SOURCE_URL = "https://opengear.com/end-life-products"
OPENGEAR_VERIFIER = "deterministic-opengear"
CHANGES_ATOM = "v1/changes.atom"
CHANGES_JSON = "v1/changes.json"
# One entry per catalog state: the filter key, its label, and the sentence the
# page prints. `listed` is the catalogue half only — never a support claim.
CATALOG_LISTING_STATES = (
    {"key": "listed", "label": "Listed in vendor catalog",
     "detail": "The vendor configurator currently lists this exact model."},
    {"key": "absent", "label": "Previously listed; absent from latest catalog",
     "detail": "This record was listed when it was first captured and is not in the current catalogue. Absence is not an end-of-sale or end-of-support announcement."},
)
# The notice half. `noticed` needs a published announcement that names this
# exact model; a current listing on its own never sets it.
CATALOG_NOTICE_STATES = (
    {"key": "noticed", "label": "Notice names this exact model",
     "detail": "A published lifecycle notice resolves to this exact model string. The notice's own dates and scope are on the linked record."},
    {"key": "no-notice", "label": "No matching notice",
     "detail": "No published lifecycle notice resolves to this exact model, so no support end is known for it. The vendor lists it; that is not an entitlement."},
)
# One row per possible pair: catalogue listing, then notice state. The filter
# value is the pair, so a reader can ask for exactly the combination they mean.
CATALOG_STATES = tuple(
    {"key": f"{listing['key']}-{notice['key']}", "listing": listing, "notice": notice}
    for listing in CATALOG_LISTING_STATES for notice in CATALOG_NOTICE_STATES
)
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


def human_stamp(value):
    """A readable stamp for a value that may be a date or a date-time.

    Provenance mixes the two — a reading date is a day, a check timestamp is an
    instant — and both are shown to readers, so the width is decided by the
    value rather than by the field it came from.
    """
    if not value:
        return None
    return human_datetime(value) if "T" in str(value) else human_date(str(value))


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
    human_stamp=human_stamp,
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
        # A researched record's release carries the contribution's verbatim
        # quote as an upstream cell instead of upstream date fields; it is
        # surfaced as its own field so the table can show the evidence rather
        # than an empty status column.
        contribution = upstream.get("Contribution") or None
        rows.append({
            "id": release["id"],
            "name": release["name"] or release["id"],
            "cells": cells,
            "contribution": contribution,
            # What the page prints under the record: the upstream release object
            # for a pipeline-derived record, the stored contribution entry for a
            # researched one (which has no upstream release object at all).
            "verbatim": upstream if contribution else raw,
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
        # A consumer reading the index can tell a researched record apart from a
        # pipeline-derived one without fetching every record; the record itself
        # carries the citation and stays linked from here.
        "research": has_research(record),
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
            "links": merge_links(cell.get("links") or []),
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


def merge_links(values):
    """Deduplicated link list, order preserved. Pairs a URL with its label once."""
    merged, seen = [], set()
    for value in values:
        if isinstance(value, dict):
            url, label = value.get("url"), value.get("label") or value.get("url")
        else:
            url, label = value, value
        if not url or url in seen:
            continue
        seen.add(url)
        merged.append({"url": url, "label": label})
    return merged


def is_catalog_record(record):
    """True for an exact catalogue model.

    The contract's marker is the presence of the optional `catalog` /
    `lifecycle` fields — `family` naming the record `catalog` is the same fact
    stated for readers. Presence decides, so a record is never treated as a
    lifecycle row merely because its family is spelled differently.
    """
    return record.get("catalog") is not None or record.get("lifecycle") is not None


def source_label(url):
    """A readable name for one source page.

    A bare host would label the configurator and the end-of-life list
    identically on the same page, so the two Opengear pages this collector
    reads are named for what they are and anything else falls back to its host.
    """
    if url == CONFIGURE_SOURCE_URL:
        return CONFIGURE_SOURCE_NAME
    if url == END_LIFE_SOURCE_URL:
        return "Opengear end-of-life product list"
    if url == HARDWARE_SOURCE_SITE:
        return HARDWARE_SOURCE_NAME
    return url.split("//")[-1].split("/")[0]


def source_order(record):
    """The record's source pages, with the page it was actually read from first.

    A catalog record is read from the vendor configurator, so the configurator
    stays its source even after a notice names the exact model — the notice is
    additional evidence, not a replacement for where the record came from. A
    lifecycle row keeps its own order, so a notice page never gets promoted
    ahead of the table the row was parsed from.
    """
    urls = list(record["provenance"]["source_urls"])
    if is_catalog_record(record):
        urls = [CONFIGURE_SOURCE_URL] + [url for url in urls if url != CONFIGURE_SOURCE_URL]
    return urls


# ---------------------------------------------------------------------------
# Researched provenance (AGENTS.md rule 8, tier b).
#
# Some products have no deterministic source at all: their record came from a
# one-time reading of a vendor notice, with the sentence the date came from
# stored verbatim beside it. The site does not re-read that notice and cannot,
# so it prints the reading date, the quote and a warning once the reading has
# aged. Which records those are, and when a reading counts as stale, is
# `engine/contribute.py`'s question — the page only renders its answer.
RESEARCH_STALE_DAYS = contribute.STALE_DAYS


def research_view(record, today):
    """Template-ready researched provenance for one record, or None.

    A researched record carries its citation at record level, so there is at
    most one view per record. Dates are formatted here because they are markup
    concerns; the staleness verdict, the quote and the evidence list are the
    contribution module's.
    """
    view = contribute.research_view(record, today)
    if not view:
        return None
    return {
        **view,
        "verifier": (record.get("provenance") or {}).get("verifier"),
        "stale_days": RESEARCH_STALE_DAYS,
        "source_label": source_label(view["source_url"]) if view["source_url"] else None,
        "retrieved_human": human_stamp(view["retrieved_at"]),
        "verified_human": human_stamp(view["verified_at"]),
        "checked_human": human_stamp(view["last_checked"]),
        "stale_after_human": human_stamp(view["stale_after"]),
        "sources": [{**source,
                     "source_label": source_label(source["source_url"]),
                     "retrieved_human": human_stamp(source["retrieved_at"])}
                    for source in view["sources"]],
    }


def has_research(record):
    """True when a record carries researched provenance.

    The catalog index and the v1 summaries publish this as a flag so a consumer
    can spot records that came from a one-time reading without fetching each
    record; the record itself always carries the full citation.
    """
    return contribute.is_researched(record)


def research_count(records):
    return sum(1 for record in records if has_research(record))


# Collector report keys that sit beside the per-family record counts rather than
# being family names: two record-id lists and the neutral-status tally.
NON_FAMILY_KEYS = ("added", "retained", "status_unknown")


def report_families(report):
    """The record families a collector's report counts, as template rows.

    The report also carries lists (`added`, `retained`) and a scalar
    (`status_unknown`) beside its family counts, so the families are separated
    here rather than filtered in the template, where the punctuation would have
    to be recomputed per iteration.
    """
    counts = (report or {}).get("record_counts") or {}
    return [{"family": family, "count": count}
            for family, count in counts.items() if family not in NON_FAMILY_KEYS]


def catalog_identity(record):
    """The catalogue listing state and the current notice match for one record.

    `record.catalog` and `record.lifecycle` are the collector's optional
    contract fields, and they are only ever read here — a missing field means
    "not a catalog record", never "not listed". Nothing in this function infers
    a support state: a listing is a listing, a missing listing is a missing
    listing, and a notice match is exact-or-absent.
    """
    catalog = record.get("catalog") or None
    lifecycle = record.get("lifecycle") or None
    listed = bool(catalog.get("listed")) if catalog else None
    matched = bool(lifecycle.get("listed")) if lifecycle else False
    if listed is None:
        listing = None
    else:
        listing = CATALOG_LISTING_STATES[0] if listed else CATALOG_LISTING_STATES[1]
    notice = CATALOG_NOTICE_STATES[0] if matched else CATALOG_NOTICE_STATES[1]
    return {
        # `is_catalog` is false when the record carries neither optional field,
        # which is how the pages tell a catalogue model apart from a lifecycle
        # row without defaulting the fields to a listing state nobody stated.
        "is_catalog": catalog is not None or lifecycle is not None,
        "catalog": catalog,
        "lifecycle": lifecycle,
        "listed": listed,
        "listing": listing,
        "notice": notice,
        "matched": matched,
        "matches": list(lifecycle.get("matches") or []) if lifecycle else [],
        "source_url": (catalog or {}).get("source_url") or None,
        "state": (f"{listing['key']}-{notice['key']}" if listing else None),
    }


def opengear_index(records):
    """The Opengear graphs the hardware copy, the filter and the pages need.

    Every Opengear model string is mapped to the records that publish it, using
    exact equality only: no family prefix, no substring, no fuzzy match. That
    map is what proves — or refuses to prove — that a notice names an exact
    catalogue model, so the pages can say which of the two they are doing.
    """
    opengear = [record for record in records if record["provenance"]["verifier"] == OPENGEAR_VERIFIER]
    catalog = [record for record in opengear if is_catalog_record(record)]
    catalog_ids = {record["id"] for record in catalog}
    lifecycle = [record for record in opengear if record["id"] not in catalog_ids]
    catalog_by_id = {record["id"]: record for record in catalog}
    lifecycle_by_id = {record["id"]: record for record in lifecycle}
    # Exact model string -> the records that publish it. A model string with
    # several publishers is kept plural instead of resolved to one winner.
    groups, models = set(), {}
    for record in lifecycle:
        groups.add(record.get("family"))
        candidates = [record.get("name"), record.get("model_number")]
        cells = record.get("upstream") or {}
        for column in ("Product", "Part #", "Old Part #"):
            cell = cells.get(column)
            if isinstance(cell, dict):
                candidates.append(cell.get("text"))
        tokens = set()
        for candidate in candidates:
            if isinstance(candidate, str) and candidate.strip():
                tokens.add(candidate.strip())
                if candidate.strip() == candidate:
                    tokens.add(candidate)
        for token in tokens:
            models.setdefault(token, []).append(record["id"])
    backlinks = {}  # lifecycle record id -> catalog record ids claiming it
    for record in catalog:
        for group in (record.get("lifecycle") or {}).get("matches") or []:
            backlinks.setdefault(group, []).append(record["id"])
    return {
        "opengear": opengear,
        "catalog": catalog,
        "lifecycle": lifecycle,
        "catalog_by_id": catalog_by_id,
        "lifecycle_by_id": lifecycle_by_id,
        "models": {token: sorted(set(ids)) for token, ids in models.items()},
        "groups": sorted(groups, key=str),
        "backlinks": {group: sorted(ids) for group, ids in backlinks.items()},
    }


def catalog_stats(records, hardware_index):
    """Counts for the hardware coverage block, derived from the records read."""
    catalog, lifecycle = hardware_index["catalog"], hardware_index["lifecycle"]
    groups = hardware_index["groups"]
    listed = sum(1 for record in catalog if (record.get("catalog") or {}).get("listed"))
    matched = sum(1 for record in catalog if (record.get("lifecycle") or {}).get("matches"))
    known_matches = sum(1 for record in catalog
                        if set((record.get("lifecycle") or {}).get("matches") or []) <= set(hardware_index["lifecycle_by_id"]))
    # A model string published by more than one row is reported, never silently
    # collapsed to one owner: which row's dates apply would then be a judgement.
    shared = {token: ids for token, ids in hardware_index["models"].items() if len(ids) > 1 and token in
              {candidate for record in catalog for candidate in
               [record.get("name"), record.get("model_number"), (record.get("upstream") or {}).get("SKU", {}).get("text")]}}
    return {
        "records": len(records),
        "catalog_records": len(catalog),
        "lifecycle_records": len(lifecycle),
        "families": {group: sum(1 for record in lifecycle if record.get("family") == group) for group in groups},
        "listed": listed,
        "absent": len(catalog) - listed,
        "matched": matched,
        "unmatched": len(catalog) - matched,
        "matched_known": known_matches,
        "shared_models": {token: ids for token, ids in sorted(shared.items()) if token},
    }


def summarize_hardware(record, rows, today, hardware_index=None):
    next_events = upcoming_events([rows], today, limit=1, milestones=HARDWARE_MILESTONES)
    catalog = catalog_identity(record) if hardware_index else {
        "is_catalog": is_catalog_record(record),
        "catalog": record.get("catalog") or None, "lifecycle": record.get("lifecycle") or None,
        "listed": None, "listing": None, "notice": None, "matched": False, "matches": [],
        "source_url": None, "state": None}
    if hardware_index:
        matches = [{"id": rid, "name": hardware_index["lifecycle_by_id"][rid]["name"],
                    "url": site_url(f"hardware/{rid}/")}
                   for rid in catalog["matches"] if rid in hardware_index["lifecycle_by_id"]]
    else:
        matches = []
    # The name is printed with any catalog state on the page, so it is written
    # once here rather than rebuilt in three templates.
    catalog["match_links"] = matches
    catalog["unresolved_matches"] = [rid for rid in catalog["matches"] if rid not in {row["id"] for row in matches}]
    search = (f"{record['name']} {record['id']} {record['vendor']} {record['product_line']} "
              f"{record.get('family') or ''} {record.get('model_number') or ''}")
    if catalog["is_catalog"]:
        search += " " + (catalog["listing"]["label"] if catalog["listing"] else "") + " " + catalog["notice"]["label"]
    return {
        "id": record["id"],
        "name": record["name"],
        "vendor": record["vendor"],
        "product_line": record["product_line"],
        "family": record.get("family"),
        "model_number": record.get("model_number"),
        "status": record["status"],
        "search": search.lower(),
        "coverage": milestone_coverage([rows], HARDWARE_MILESTONES),
        "milestones": {key: record["milestones"][key] for key in MILESTONE_KEYS},
        "next": next_events[0] if next_events else None,
        "json": site_url(f"v1/hardware/{record['id']}.json"),
        "page": site_url(f"hardware/{record['id']}/"),
        "source": source_order(record)[0],
        "source_urls": source_order(record),
        "source_links": [{"url": url, "label": source_label(url)} for url in source_order(record)],
        "catalog": catalog,
        "research": has_research(record),
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
    # The manifest counts the endoflife.date snapshot, which is rewritten from
    # upstream by import-data and knows nothing about researched records, so it
    # is compared against the deterministic records alone.
    deterministic = contribute.deterministic_records(records)
    if manifest["product_count"] != len(deterministic):
        raise ValueError(f"Manifest advertises {manifest['product_count']} products, found {len(deterministic)}")
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

    feed = {"schema_version": SCHEMA_VERSION, **manifest, "products": records,
            # `product_count` in the manifest counts the refreshable upstream
            # snapshot; the array below also carries researched records, so the
            # difference is stated rather than left for a consumer to guess.
            "researched_count": research_count(records)}
    write_json(out / "v1" / "feed.json", feed)
    rows_by_id = {record["id"]: release_rows(record) for record in records}
    summaries = [summarize(record, rows_by_id[record["id"]], today) for record in records]
    write_json(out / "v1" / "products.json", {"schema_version": SCHEMA_VERSION, **manifest, "products": summaries,
                                              "researched_count": research_count(records)})
    (out / "v1" / "products").mkdir(parents=True)
    for record in records:
        shutil.copyfile(data_dir / "products" / f"{record['id']}.json", out / "v1" / "products" / f"{record['id']}.json")

    hardware_rows_by_id = {record["id"]: hardware_rows(record) for record in hardware}
    hardware_index = opengear_index(hardware)
    hardware_summaries = [summarize_hardware(record, hardware_rows_by_id[record["id"]], today, hardware_index)
                          for record in hardware]
    # The JSON index keeps slug order, like the product index. The rendered
    # tables ship in model-name order instead, which is the default sort of the
    # filter script, so a page costs no reordering work when it loads.
    hardware_page = sorted(hardware_summaries, key=lambda model: model["name"].lower())
    write_json(out / "v1" / "hardware.json", {
        "schema_version": SCHEMA_VERSION, **manifest,
        "hardware_count": len(hardware), "hardware": hardware_summaries,
        "researched_count": research_count(hardware)})
    (out / "v1" / "hardware").mkdir(parents=True)
    for record in hardware:
        shutil.copyfile(data_dir / "hardware" / f"{record['id']}.json",
                        out / "v1" / "hardware" / f"{record['id']}.json")
    opengear_report = data_dir / "opengear-import.json"
    if opengear_report.exists():
        shutil.copyfile(opengear_report, out / "v1" / "opengear-import.json")
    # The changes ledger and its Atom feed are produced by the changes module
    # against the previous records; the site only republishes what is on disk.
    # When no ledger has been recorded yet there is no history to link to, so
    # the navigation says that instead of pointing at a document nobody wrote.
    changes_json = data_dir / "opengear-changes.json"
    changes_available = changes_json.exists()
    if changes_available:
        shutil.copyfile(changes_json, out / "v1" / "changes.json")
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
    stats = catalog_stats(hardware, hardware_index)
    # Sort order for the catalog column: the catalog states first — they are
    # what the column is about — then notice-table rows, which have no catalog
    # state at all.
    state_counts, order = {}, {}
    for state in CATALOG_STATES:
        order[state["key"]] = len(order)
        state_counts[state["key"]] = 0
    order["lifecycle-row"] = len(order)
    state_counts["lifecycle-row"] = 0
    for summary in hardware_summaries:
        key = summary["catalog"]["state"] or "lifecycle-row"
        state_counts[key] = state_counts.get(key, 0) + 1
    # The import report is the collector's own account of what it read and what
    # it dropped; republished verbatim so the hardware page can show coverage
    # without restating it in prose the reader cannot check.
    report = json.loads(opengear_report.read_text(encoding="utf-8")) if opengear_report.exists() else None
    common = {
        "manifest": manifest,
        # The manifest counts the upstream snapshot; these counts are the
        # catalog the site actually publishes, which also contains researched
        # records the manifest knows nothing about. The two are meant to differ,
        # and `researched_count` says by how much.
        "product_count": len(records),
        "release_count": sum(len(record.get("releases") or []) for record in records),
        "excluded_count": len(manifest["excluded_hardware"]),
        "hardware_count": len(hardware),
        "refresh": refresh,
        "milestone_meta": MILESTONES,
        "hardware_milestone_meta": HARDWARE_MILESTONES,
        "hardware_status_meta": HARDWARE_STATUSES,
        "hardware_status_order": HARDWARE_STATUS_ORDER,
        "catalog_states": CATALOG_STATES,
        "catalog_state_counts": state_counts,
        "catalog_state_order": order,
        "catalog_source_name": CONFIGURE_SOURCE_NAME,
        "catalog_source_site": CONFIGURE_SOURCE_URL,
        "catalog_stats": stats,
        "import_report": report,
        "report_families": report_families(report),
        "changes_available": changes_available,
        "changes_json_url": url_for(CHANGES_JSON),
        "changes_atom_url": url_for(CHANGES_ATOM),
        "hardware_vendors": hardware_vendor_facets,
        "hardware_statuses": hardware_status_facets,
        "schema_version": SCHEMA_VERSION,
        "notices": notices,
        "schema_files": [f"v1/schema/{f.name}" for f in schema_files],
        # Researched provenance is a catalog-level fact, so the window and the
        # counts are shared with every page that mentions it rather than
        # recomputed per template.
        "research_stale_days": RESEARCH_STALE_DAYS,
        "researched_count": research_count(records),
        "researched_hardware_count": research_count(hardware),
    }

    write(out / "index.html", render(
        "index.html",
        **common,
        active="index",
        canonical=site_url(),
        title="EOL Tracker — software and hardware lifecycle dates",
        description=(f"Normalized general availability, end-of-sale, security-support and end-of-life dates "
                     f"for {len(records)} software products and {len(hardware)} hardware models, "
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
        # A catalog record names the lifecycle groups a notice resolved to, so
        # every match becomes a link to that group's own page; a lifecycle row
        # names the exact catalog models whose notices point back at it. Both
        # directions are exact-id joins, which is why the page can print them as
        # facts instead of hints.
        matches = [{"id": rid,
                    "name": hardware_index["lifecycle_by_id"][rid]["name"],
                    "family": hardware_index["lifecycle_by_id"][rid].get("family"),
                    "vendor": hardware_index["lifecycle_by_id"][rid]["vendor"],
                    "status": hardware_index["lifecycle_by_id"][rid]["status"],
                    "url": url_for(f"hardware/{rid}/"),
                    "json": url_for(f"v1/hardware/{rid}.json")}
                   for rid in (record.get("lifecycle") or {}).get("matches") or []
                   if rid in hardware_index["lifecycle_by_id"]]
        unresolved = [rid for rid in (record.get("lifecycle") or {}).get("matches") or []
                      if rid not in hardware_index["lifecycle_by_id"]]
        claimed_by = [{"id": cid,
                       "name": hardware_index["catalog_by_id"][cid]["name"],
                       "sku": hardware_index["catalog_by_id"][cid].get("model_number"),
                       "listed": (hardware_index["catalog_by_id"][cid].get("catalog") or {}).get("listed"),
                       "url": url_for(f"hardware/{cid}/")}
                      for cid in hardware_index["backlinks"].get(record["id"], [])]
        source_urls = source_order(record)
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
            identity=catalog_identity(record),
            exact_matches=matches,
            unresolved_matches=unresolved,
            claimed_by=claimed_by,
            shared_models=[{"model": token, "ids": ids,
                            "names": [hardware_index["lifecycle_by_id"][rid]["name"] for rid in ids
                                      if rid in hardware_index["lifecycle_by_id"]]}
                           for token, ids in sorted(hardware_index["models"].items())
                           if record["id"] in ids and len(ids) > 1],
            coverage=milestone_coverage([rows], HARDWARE_MILESTONES),
            json_url=url_for(f"v1/hardware/{record['id']}.json"),
            json_abs=site_url(f"v1/hardware/{record['id']}.json"),
            upstream_links=[{"url": url, "label": source_label(url)} for url in source_urls],
            hardware_source_name="Opengear" if record["provenance"]["verifier"] == OPENGEAR_VERIFIER else HARDWARE_SOURCE_NAME,
            hardware_source_site=source_urls[0],
            hardware_source_attribution=("Lifecycle dates published directly by Opengear; grouped parts and contract exceptions are retained below."
                                         if record["provenance"]["verifier"] == OPENGEAR_VERIFIER else HARDWARE_SOURCE_ATTRIBUTION),
            research=research_view(record, today),
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
            research=research_view(record, today),
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
