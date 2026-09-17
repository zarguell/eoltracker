"""Turn validated catalog records into the rows, summaries and facets the pages render.

Everything here is a pure function of records already read from disk: no
fetching, no validation, no file writes. Each function answers one question a
template asks — what does this release row look like, which milestones does this
model carry, which vendors exist, what does a raw upstream cell mean — and
returns plain dicts, so a template never computes a fact and a JSON endpoint
never renders HTML.

Three rules the functions here keep, because the published endpoints depend on
them:

* An absent date stays absent. A `None` milestone renders as unknown and is
  never filled from a neighbouring column, a newer release or a guess.
* A listing is not a support claim. `catalog_identity` reports catalogue
  presence and notice matching separately and derives no status from either, so
  `unknown` stays a first-class neutral answer.
* Vendor identity is keyed, never overwritten. `vendor_slugs` assigns each
  vendor one slug and refuses a collision instead of letting two vendors share
  a published file.
"""
from .hardware import slugify
from . import contribute
from .site_sources import is_catalog_record, source_links, source_label, source_order
from .site_config import (CATALOG_LISTING_STATES, CATALOG_NOTICE_STATES,
                          HARDWARE_MILESTONES, HARDWARE_STATUSES, MILESTONE_FIELDS, MILESTONE_KEYS,
                          MILESTONES, OPENGEAR_VERIFIER, UPSTREAM_DATE_FIELDS, human_date, human_stamp,
                          is_month, published_period, site_url, version_key)

def vendor_cells(upstream):
    """A vendor collector's own raw row cells, as evidence rows, or an empty list.

    A vendor collector stores the source row's declared columns verbatim under
    ``upstream.cells`` instead of restating endoflife.date's field names. Those
    columns are the record's evidence — the page prints the vendor's own wording
    beside the normalized date — so they are surfaced as their own list rather
    than left to a mapping that does not apply to this pipeline.
    """
    cells = upstream.get("cells") if isinstance(upstream, dict) else None
    if not isinstance(cells, dict):
        return []
    return [{"column": column, "value": value} for column, value in cells.items()]


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
            cells[key] = {"value": value, "human": human_date(value), "month": is_month(value),
                          "notes": "; ".join(notes) or None}
        latest = upstream.get("latest") or {}
        # A researched record's release carries the contribution's verbatim
        # quote as an upstream cell instead of upstream date fields; it is
        # surfaced as its own field so the table can show the evidence rather
        # than an empty status column.
        contribution = upstream.get("Contribution") or None
        evidence = vendor_cells(upstream)
        rows.append({
            "id": release["id"],
            "name": release["name"] or release["id"],
            "cells": cells,
            "contribution": contribution,
            "evidence": evidence,
            # What the page prints under the record: the upstream release object
            # for a pipeline-derived record, the stored contribution entry for a
            # researched one (which has no upstream release object at all), or
            # the vendor's own cells, which are the whole evidence for a vendor
            # record and so are shown verbatim rather than reduced to date fields.
            "verbatim": upstream if contribution or evidence else raw,
            "lts": bool(upstream.get("isLts")),
            "eol_flag": bool(upstream.get("isEol")),
            "maintained": bool(upstream.get("isMaintained")),
            "latest": {
                "name": latest.get("name") or upstream.get("name"),
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
    """Published milestone dates that have not passed yet, soonest first.

    A month-precision value covers its whole month, so the window uses the last
    day the source's value covers (see `site_config.published_period`) and the
    countdown is to that day. Ordering still compares the stored strings, which
    sorts YYYY-MM before YYYY-MM-DD inside the same month, the conservative
    direction: an undated deadline is announced before the month is over.
    """
    events = []
    for row in rows:
        for milestone in milestones:
            if milestone["key"] == "ga":
                continue
            value = row["cells"][milestone["key"]]["value"]
            if not value:
                continue
            covers = published_period(value)
            if covers < today:
                continue
            events.append({
                "release": row["name"],
                "release_id": row["id"],
                "milestone": milestone["label"],
                "key": milestone["key"],
                "date": value,
                "month": is_month(value),
                "human": human_date(value),
                "days": (covers - today).days,
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
    source_urls = source_order(record)
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
        "source": source_urls[0],
        "source_urls": source_urls,
        "source_links": source_links(source_urls),
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


def vendor_slugs(vendors):
    """One URL-safe slug per vendor name, refusing to publish two vendors under one file.

    A slug is the vendor's name folded to ASCII, lower case and hyphen
    separated — the same folding the catalog uses for record ids — so the
    published filename is derivable from the vendor name a reader sees. The
    schemes must be injective for that to hold, and folding is not injective in
    general: `Dell EMC` and `Dell-EMC` fold together. Two vendors sharing one
    slug would silently overwrite one vendor's summary with another's, which is
    a data loss published as a fact, so it fails the build and names both
    vendors instead of picking a winner.
    """
    slugs, owners = {}, {}
    for vendor in vendors:
        slug = slugify(vendor)
        if not slug:
            raise ValueError(f"Vendor {vendor!r} has no URL-safe slug; it cannot be published as a shard")
        if slugs.get(vendor) is None:
            slugs[vendor] = slug
        owner = owners.get(slug)
        if owner is not None and owner != vendor:
            raise ValueError(
                f"Vendors {owner!r} and {vendor!r} both fold to the slug {slug!r}; "
                f"one published file cannot hold both")
        owners[slug] = vendor
    return slugs


def hardware_vendor_shards(records, vendors):
    """The per-vendor hardware summaries, with the discovery index that lists them.

    One shard per vendor, each holding the same summary objects the combined
    `v1/hardware.json` carries for that vendor — same shape, same order, byte
    for byte, so a consumer can read a vendor's slice without filtering the
    whole catalog and gets no second opinion about a record. The index is the
    discovery document: which vendors exist, how many records each holds and
    where its shard lives.
    """
    slugs = vendor_slugs(vendor["name"] for vendor in vendors)
    groups = {}
    for record in records:
        groups.setdefault(record["vendor"], []).append(record)
    shards = []
    for vendor in vendors:
        name = vendor["name"]
        slug = slugs[name]
        shards.append({
            "vendor": name,
            "slug": slug,
            "count": vendor["count"],
            "shard": f"v1/hardware/vendors/{slug}.json",
            "url": site_url(f"v1/hardware/vendors/{slug}.json"),
            "records": groups[name],
        })
    return shards
