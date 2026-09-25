"""Build the published site: pages, v1 endpoints, schema copies and vendor shards.

`build()` never fetches anything. It validates the committed catalogs through
`engine.validation`, then writes `_site/` from scratch: the catalog pages, the
per-product and per-hardware-model pages, `v1/feed.json` (every normalized
software record), `v1/products.json`, `v1/hardware.json` (hardware summaries),
the additive per-vendor hardware shards under `v1/hardware/vendors/`, the
byte-identical per-record endpoints, and copies of `schema/*.json`.

This module owns orchestration only: what is written where, and the context each
page is rendered with. How a record becomes a row or a summary is
`engine.site_views`; how a source is named, linked and credited is
`engine.site_sources`; paths, catalog vocabulary and the Jinja environment are
`engine.site_config`. Every side effect of a build lives here, and nothing here
decides what a date means.
"""
import json
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from .site_config import (CATALOG_STATES, CHANGES_ATOM, CHANGES_JSON, DEFAULT_DATA, DEFAULT_OUT,
                          HARDWARE_MILESTONES, HARDWARE_STATUSES, HARDWARE_STATUS_ORDER, LABEL_RULES,
                          MILESTONES, NOTICE_FILES, OPENGEAR_SOURCE, SCHEMA_DIR, SCHEMA_VERSION,
                          TEMPLATES, VENDOR_INDEX, env, human_datetime, site_url, url_for)
from .site_sources import (source_attribution, source_links, source_name, source_order, source_url as safe_source_url)
from .site_views import (catalog_categories, catalog_identity, catalog_stats, derived_count,
                         derived_rows, hardware_rows, hardware_statuses, hardware_vendor_shards,
                         hardware_vendors, milestone_coverage, opengear_index, release_rows,
                         report_families, research_count, research_view, RESEARCH_STALE_DAYS,
                         safe_link_map, safe_links, summarize, summarize_hardware, upcoming_events)
from .importer import ROOT
from . import changes, contribute, feeds, openeox, sources
from .validation import validate_data, validate_hardware
def render(template, **context):
    return env.get_template(template).render(**context)


def snapshot_date(value):
    """The single reference day a build measures countdowns from (#95).

    The manifest's `generated_at` is the catalog snapshot the pages display as
    their refresh provenance, so it is also the day relative counts are
    computed against. Deriving the day from the snapshot instead of the wall
    clock means the printed stamp and the arithmetic beside it always agree,
    and two builds of the same committed catalog produce the same numbers.
    """
    if isinstance(value, datetime):
        moment = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    else:
        moment = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc).date()


def write(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def write_json(path, value):
    write(path, json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def replace_tree(staging, out):
    """Move a fully built staging tree onto the published path (#114).

    The staged tree is renamed onto `out`, so the swap is one filesystem
    operation and no consumer can observe a half-written `_site/`. Any previous
    tree is removed first (a `_site` that exists cannot be renamed over), which
    means the only window with no published tree is between the removal and the
    rename of a tree that is already complete on disk.
    """
    out = Path(out)
    staging = Path(staging)
    if not staging.is_dir():
        raise ValueError(f"Nothing to publish: staging tree {staging} does not exist")
    if out.exists():
        shutil.rmtree(out)
    staging.rename(out)


def check_staged_tree(out, products, hardware):
    """Refuse a staged tree that is missing or miscounts what it should hold (#114, #99).

    Every stage writes into the staging tree, so a stage that failed to write,
    wrote an empty file, or silently dropped records would otherwise be renamed
    onto the published path and look like a successful build. The check names
    the subject of each count and compares it with the catalog that was read,
    and it fails on an empty or implausibly small tree rather than publishing
    one. It is a cardinality guard, not a schema check: validation already ran
    on the records, and the endpoint shapes are covered by their own tests.
    """
    out = Path(out)
    required = ["index.html", "404.html", "style.css", "app.js",
                "v1/feed.json", "v1/products.json", "v1/hardware.json",
                "v1/feed.atom", "v1/feed.rss", "v1/calendar.ics",
                "v1/feed-exclusions.json", "v1/openeox/index.json"]
    missing = [name for name in required if not (out / name).is_file()]
    if missing:
        raise ValueError(f"Staged build is incomplete; missing after every stage: {', '.join(missing)}")
    files = [path for path in out.rglob("*") if path.is_file()]
    if not files:
        raise ValueError("Staged build wrote no files at all")
    # A bounded-staging sanity check: an empty or near-empty tree is a stage
    # failure, not a small site. The publication budget itself is enforced by
    # `engine.site_budget` in the workflow.
    total = sum(path.stat().st_size for path in files)
    if total == 0:
        raise ValueError("Staged build wrote only empty files")
    products_index = json.loads((out / "v1" / "products.json").read_text(encoding="utf-8"))
    hardware_index = json.loads((out / "v1" / "hardware.json").read_text(encoding="utf-8"))
    if len(products_index["products"]) != len(products):
        raise ValueError(f"Staged products index publishes {len(products_index['products'])} summaries "
                         f"for {len(products)} software records")
    if hardware_index["counts"]["subject"] != "hardware catalog":
        raise ValueError("Staged hardware index does not declare its subject")
    if hardware_index["hardware_count"] != len(hardware):
        raise ValueError(f"Staged hardware index publishes {hardware_index['hardware_count']} records "
                         f"for {len(hardware)} hardware records")
    for record in products:
        if not (out / "v1" / "products" / f"{record['id']}.json").is_file():
            raise ValueError(f"Staged build is missing the endpoint for software record {record['id']!r}")
        if not (out / "products" / record["id"] / "index.html").is_file():
            raise ValueError(f"Staged build is missing the page for software record {record['id']!r}")
    for record in hardware:
        if not (out / "v1" / "hardware" / f"{record['id']}.json").is_file():
            raise ValueError(f"Staged build is missing the endpoint for hardware record {record['id']!r}")
    return {"files": len(files), "bytes": total}


def build(data_dir=None, out_dir=None):
    """Write the complete static site, endpoints, feeds and ledgers (#114).

    Every stage of the publication — the HTML pages and v1 endpoints
    (`_render_tree`), the OpenEoX export, the three syndication documents with
    their exclusion account, and the change ledger — runs against a sibling
    staging directory. `_site/` is replaced only once all of them succeeded and
    the staged tree passed `check_staged_tree`, so a failure in any later stage
    leaves the previously published tree exactly as it was instead of a
    plausible-looking partial one.

    This module owns the whole publication because it owns the staging
    directory: a caller that ran a later stage against the live `_site/` would
    reintroduce exactly the partial-tree window this closes. Returns a summary
    dict of every stage's result.
    """
    data_dir = Path(data_dir) if data_dir is not None else DEFAULT_DATA
    out = Path(out_dir) if out_dir is not None else DEFAULT_OUT
    out.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{out.name}.staging-", dir=out.parent))
    try:
        summary = _render_tree(data_dir, staging)
        products, hardware, manifest = summary["products"], summary["hardware"], summary["manifest"]
        # The remaining stages write into the same staging tree, in the order
        # the published endpoints depend on: OpenEoX and the feeds read the
        # validated catalog, and the change ledger reads only its own history.
        summary["openeox"] = openeox.build(products, site=staging)
        summary["feeds"] = feeds.build(products, hardware, out_dir=staging, manifest=manifest)
        history_path = data_dir / "opengear-changes.json"
        summary["changes"] = (changes.build(changes.load_history(history_path), staging)
                              if history_path.exists() else None)
        summary["staging"] = check_staged_tree(staging, products, hardware)
        replace_tree(staging, out)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    summary["out"] = str(out)
    return summary


def _render_tree(data_dir, out):
    """Render the pages and v1 endpoints into ``out``; returns what it read."""
    records = validate_data(data_dir)
    hardware = validate_hardware(data_dir)
    manifest = json.loads((data_dir / "manifest.json").read_text(encoding="utf-8"))
    # validate_data checks the manifest against its owning source only;
    # other deterministic sources and researched records are additive.
    # The manifest may predate the hardware catalog, so its count is advisory.
    if manifest.get("hardware_count", len(hardware)) != len(hardware):
        raise ValueError(f"Manifest advertises {manifest['hardware_count']} hardware models, found {len(hardware)}")
    # One explicit reference date for the whole build (#95): the displayed
    # provenance is the catalog snapshot the manifest names, so the countdowns
    # must be measured from that same day rather than from wall-clock build
    # time. Using `now()` here made a page's "in N days" disagree with the
    # snapshot stamp printed beside it (and with every other page in the same
    # tree, since each build chose its own midnight).
    today = snapshot_date(manifest["generated_at"])

    # The staging directory was created empty by `build`; this only makes a
    # directly chosen `out_dir` behave the same way, so `_render_tree` always
    # renders into an empty tree and never mixes with a previous render.
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

    rows_by_id = {record["id"]: release_rows(record) for record in records}
    catalog_counts = {
        "product_count": len(records),
        "release_count": sum(len(record["releases"]) for record in records),
        "researched_count": research_count(records),
        # The count of products publishing at least one derived date, so a
        # consumer reading either catalog document sees how many carry a
        # computed milestone without fetching all 480 record endpoints.
        "derived_count": derived_count(rows_by_id),
    }
    feed = {"schema_version": SCHEMA_VERSION, **manifest, **catalog_counts, "products": records}
    write_json(out / "v1" / "feed.json", feed)
    summaries = [summarize(record, rows_by_id[record["id"]], today) for record in records]
    write_json(out / "v1" / "products.json", {
        "schema_version": SCHEMA_VERSION, **manifest, **catalog_counts, "products": summaries})
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
    hardware_vendor_facets = hardware_vendors(hardware)
    vendor_shards = hardware_vendor_shards(hardware_summaries, hardware_vendor_facets)
    # `v1/hardware.json` publishes a different catalog from `v1/products.json`,
    # so it must not inherit the software manifest's counts (#88): a consumer
    # reading `product_count: 455` here would attribute it to the hardware
    # endpoint or to a catalog this document does not contain. Each top-level
    # count names its subject, and the software snapshot the build read — the
    # endoflife.date manifest, which is *not* this catalog — is carried in a
    # clearly named sub-object rather than spread into this one.
    write_json(out / "v1" / "hardware.json", {
        "schema_version": SCHEMA_VERSION,
        "generated_at": manifest["generated_at"],
        "subject": "hardware catalog",
        "counts": {
            "subject": "hardware catalog",
            "hardware_records": len(hardware),
            "hardware_vendors": len(hardware_vendor_facets),
            "researched_records": research_count(hardware),
        },
        "hardware_count": len(hardware),
        "hardware_vendor_count": len(hardware_vendor_facets),
        "researched_count": research_count(hardware),
        "hardware": hardware_summaries,
        # The endoflife.date software snapshot the build also read. Its counts
        # describe the *software* catalog (`v1/products.json`, `v1/feed.json`),
        # not this document, and are retained only so the one input the hardware
        # build validated against stays visible and attributable.
        "software_manifest": {
            "subject": "software catalog (endoflife.date snapshot)",
            "generated_at": manifest["generated_at"],
            "source_url": manifest["source_url"],
            "source": manifest.get("source"),
            "product_count": manifest["product_count"],
            "release_count": manifest["release_count"],
            "excluded_hardware": manifest["excluded_hardware"],
        },
    })
    (out / "v1" / "hardware").mkdir(parents=True)
    for record in hardware:
        shutil.copyfile(data_dir / "hardware" / f"{record['id']}.json",
                        out / "v1" / "hardware" / f"{record['id']}.json")
    # Additive vendor shards: each holds exactly the summaries `v1/hardware.json`
    # already carries for that vendor, so the combined index stays the complete
    # catalog and its identity, while a consumer can fetch one vendor's slice
    # without reading 20 MB. The discovery document names every shard and its
    # count; a slug collision fails the build rather than overwriting a vendor.
    # `v1/hardware/vendors.json` sits in the same directory as the per-record
    # endpoints, and one record id would land exactly on it. That collision
    # would publish a vendor's shard index as a model record (or the reverse)
    # with no error, so it is refused here, naming the record that caused it.
    clash = next((record["id"] for record in hardware
                  if record["id"] == Path(VENDOR_INDEX).stem), None)
    if clash:
        raise ValueError(
            f"Hardware record {clash!r} collides with the vendor discovery file {VENDOR_INDEX!r}; "
            f"one path cannot hold both")
    (out / "v1" / "hardware" / "vendors").mkdir(parents=True)
    for shard in vendor_shards:
        write_json(out / shard["shard"], {
            "schema_version": SCHEMA_VERSION,
            "generated_at": manifest["generated_at"],
            "hardware_count": shard["count"],
            "vendor": shard["vendor"],
            "hardware": shard["records"],
            "researched_count": research_count(shard["records"])})
    write_json(out / VENDOR_INDEX, {
        "schema_version": SCHEMA_VERSION,
        "generated_at": manifest["generated_at"],
        "hardware_count": len(hardware),
        "vendor_count": len(vendor_shards),
        "vendors": [{key: shard[key] for key in ("vendor", "slug", "count", "shard", "url")}
                    for shard in vendor_shards]})
    for source in sources.all_sources():
        if source.report and (data_dir / source.report).exists():
            shutil.copyfile(data_dir / source.report, out / "v1" / source.report)
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
    opengear_report = data_dir / "opengear-import.json"
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
        "catalog_source_name": OPENGEAR_SOURCE.pages[0].label,
        "catalog_source_site": OPENGEAR_SOURCE.pages[0].url,
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
        vendor_shards=vendor_shards,
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
            upstream_links=source_links(source_urls),
            # The source a record credits itself to comes from the registry, so
            # a new collector's pages are attributed without a site-side branch.
            # The link stays the record's own leading page — the page it was read
            # from — rather than the source's root, so a reader can check the row.
            hardware_source_name=source_name(record["provenance"]["verifier"]),
            # A record's own source pages are external input, so only the safe
            # absolute http(s) URLs reach the template's `href` (#98).
            hardware_source_site=safe_source_url(source_urls[0]) if source_urls else None,
            hardware_source_attribution=source_attribution(record["provenance"]["verifier"]),
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
                         f"{record['name']} release, with raw source values and provenance."),
            product=record,
            releases=rows,
            coverage=milestone_coverage(rows),
            events=page_events,
            labels=record.get("labels") or {},
            label_rules=LABEL_RULES,
            derived_rows=derived_rows(rows),
            identifiers=record.get("identifiers") or [],
            links=safe_link_map(record.get("links") or {}),
            json_url=url_for(f"v1/products/{record['id']}.json"),
            json_abs=site_url(f"v1/products/{record['id']}.json"),
            # The record's upstream URL and its link object are external input;
            # a `javascript:` value must never reach the template's `href` (#98).
            upstream_url=safe_source_url(record["provenance"]["source_url"]),
            software_source_name=source_name(record["provenance"]["verifier"]),
            software_source_attribution=source_attribution(record["provenance"]["verifier"]),
            software_source_links=source_links([record["provenance"]["source_url"]]),
            software_pipeline=(record["provenance"]["verifier"] == sources.source("import-data").verifier),
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
        vendor_shards=vendor_shards,
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
    # What the later stages read: the validated catalogs and the manifest whose
    # snapshot day every countdown in this tree already used.
    return {"out": str(out), "products": records, "hardware": hardware,
            "manifest": manifest, "today": today.isoformat(),
            "records": len(records), "hardware_records": len(hardware)}
