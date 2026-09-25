"""Regression tests for the site split's own contracts.

The site is split by responsibility — configuration and the Jinja environment
(`site_config`), record presentation (`site_views`), source attribution
(`site_sources`) and build orchestration (`site`) — and two of its properties are
invisible to any other test: that the additive per-vendor hardware shards stay
exact subsets of the combined index, and that identity collisions fail instead
of silently overwriting one vendor's (or model's) published file. Both are data
loss if they regress, which is why they are pinned here rather than left to a
build nobody diffs by hand.
"""
import json
import re
import shutil
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from engine import site, site_config, site_sources, site_views
from engine.importer import API, dump, normalize, ROOT


def summary(record_id, vendor, status="supported"):
    """A stand-in for one `v1/hardware.json` entry (the shard contract only needs identity)."""
    return {"id": record_id, "name": record_id, "vendor": vendor, "status": status}


class VendorSlugTests(unittest.TestCase):
    def test_slug_is_derived_from_the_vendor_name(self):
        self.assertEqual(site_views.vendor_slugs(["Pure Storage"]), {"Pure Storage": "pure-storage"})

    def test_two_vendors_folding_to_one_slug_fail_instead_of_overwriting(self):
        with self.assertRaises(ValueError) as caught:
            site_views.vendor_slugs(["Dell EMC", "Dell-EMC"])
        # The error names both vendors: which one "won" would otherwise be
        # decided by iteration order, which is not a publishing decision.
        self.assertIn("Dell EMC", str(caught.exception))
        self.assertIn("Dell-EMC", str(caught.exception))

    def test_repeated_vendor_name_is_one_vendor_not_a_collision(self):
        self.assertEqual(site_views.vendor_slugs(["Cisco", "Cisco"]), {"Cisco": "cisco"})

    def test_a_name_with_no_slug_is_refused(self):
        with self.assertRaises(ValueError):
            site_views.vendor_slugs(["!!!"])


class VendorShardTests(unittest.TestCase):
    def test_each_shard_is_an_exact_subset_of_the_combined_index(self):
        records = [summary("a", "Cisco"), summary("b", "Apple"), summary("c", "Cisco")]
        facets = site_views.hardware_vendors(records)
        shards = {s["slug"]: s for s in site_views.hardware_vendor_shards(records, facets)}
        self.assertEqual(sorted(shards), ["apple", "cisco"])
        # Subset, same order, same objects: a consumer that reads a shard gets
        # no second opinion about a record the combined index also carries.
        self.assertEqual(shards["cisco"]["records"], [records[0], records[2]])
        self.assertEqual(shards["apple"]["records"], [records[1]])
        self.assertEqual(shards["cisco"]["count"], 2)

    def test_shard_paths_are_derived_from_the_slug(self):
        records = [summary("a", "Dell EMC")]
        shards = site_views.hardware_vendor_shards(records, site_views.hardware_vendors(records))
        self.assertEqual(shards[0]["shard"], "v1/hardware/vendors/dell-emc.json")
        self.assertTrue(shards[0]["url"].endswith("/v1/hardware/vendors/dell-emc.json"))

    def test_every_record_lands_in_exactly_one_shard(self):
        records = [summary(str(i), f"Vendor {i % 3}") for i in range(9)]
        facets = site_views.hardware_vendors(records)
        shards = site_views.hardware_vendor_shards(records, facets)
        self.assertEqual(sum(s["count"] for s in shards), len(records))
        # Shards partition the records: within one vendor the combined index's
        # order is preserved, and across shards each record appears exactly once.
        sharded = [r["id"] for s in shards for r in s["records"]]
        self.assertEqual(sorted(sharded, key=int), [r["id"] for r in records])
        for shard in shards:
            expected = [r["id"] for r in records if r["vendor"] == shard["vendor"]]
            self.assertEqual([r["id"] for r in shard["records"]], expected)

    def test_the_discovery_index_lists_every_shard(self):
        records = [summary("a", "Cisco"), summary("b", "Apple")]
        index = {key: shard[key] for shard in
                 site_views.hardware_vendor_shards(records, site_views.hardware_vendors(records))
                 for key in ("vendor", "slug", "count", "shard", "url")}
        # Vendors are ordered by record count, so the larger catalog leads.
        self.assertEqual(index["vendor"], "Cisco")
        self.assertEqual(index["count"], 1)
        self.assertIn("v1/hardware/vendors/cisco.json", index["shard"])



class HardwareSummaryTests(unittest.TestCase):
    def test_summary_counts_use_the_full_hardware_population(self):
        def lifecycle(record_id, verifier, family):
            return {"id": record_id, "name": record_id, "vendor": "Vendor", "product_line": "Line",
                    "family": family, "model_number": record_id, "status": "unknown",
                    "milestones": {"ga": None, "eos": None, "eossec": None, "eol": None},
                    "upstream": {"Part #": {"text": record_id}},
                    "provenance": {"verifier": verifier, "last_checked": "2026-09-17T00:00:00Z",
                                   "source_urls": ["https://example.com/source"]}}

        records = [lifecycle("eosl", "deterministic-eosl-date", "Server"),
                   lifecycle("notice", "deterministic-opengear", "hardware"),
                   {"id": "catalog", "name": "catalog", "vendor": "Vendor", "product_line": "Line",
                    "family": "catalog", "model_number": "catalog", "status": "unknown",
                    "milestones": {"ga": None, "eos": None, "eossec": None, "eol": None},
                    "catalog": {"listed": True, "source_url": "https://opengear.com/configure/"},
                    "lifecycle": {"matches": []}, "upstream": {},
                    "provenance": {"verifier": "deterministic-opengear", "last_checked": "2026-09-17T00:00:00Z",
                                   "source_urls": ["https://opengear.com/configure/"]}}]
        stats = site_views.catalog_stats(records, site_views.opengear_index(records))
        self.assertEqual((stats["records"], stats["lifecycle_records"], stats["catalog_records"]), (3, 2, 1))
        self.assertEqual(stats["families"], {"Server": 1, "hardware": 1})

class SourceAttributionTests(unittest.TestCase):
    def test_credits_come_from_the_registry_not_a_site_side_copy(self):
        from engine import sources

        for verifier in ("deterministic-eosl-date", "deterministic-opengear"):
            self.assertEqual(site_sources.source_name(verifier), sources.source_for(verifier).name)
            self.assertEqual(site_sources.source_attribution(verifier),
                             sources.source_for(verifier).attribution)
            self.assertNotEqual(site_sources.source_attribution(verifier), "")

    def test_a_researched_verifier_is_not_credited_to_a_pipeline(self):
        # `researched-*` names a contributor, not a source; it must not be
        # attributed to a collector that never read the record.
        self.assertNotIn("researched", site_sources.source_attribution("researched-zarguell"))

    def test_catalog_records_lead_with_the_page_their_source_reads_first(self):
        from engine import sources

        primary = sources.source_for("deterministic-opengear").pages[0].url
        record = {"provenance": {"verifier": "deterministic-opengear",
                                 "source_urls": ["https://opengear.com/end-life-products", primary]},
                  "catalog": {"listed": True, "source_url": primary}}
        self.assertEqual(site_sources.source_order(record)[0], primary)
        # A lifecycle row is not promoted: the notice page keeps its parsed order.
        row = {"provenance": {"verifier": "deterministic-opengear",
                              "source_urls": ["https://opengear.com/end-life-products", primary]}}
        self.assertEqual(site_sources.source_order(row)[0], "https://opengear.com/end-life-products")

    def test_page_labels_come_from_the_registry_with_a_host_fallback(self):
        self.assertEqual(site_sources.source_label("https://opengear.com/configure/"),
                         "Opengear product configurator")
        self.assertEqual(site_sources.source_label("https://resources.opengear.com/x.pdf"),
                         "resources.opengear.com")


class PresentationConfigTests(unittest.TestCase):
    def test_one_environment_serves_every_page(self):
        # The split must not create a second Jinja environment; templates resolve
        # the URL helpers and the pretty-print filter from this one.
        self.assertIs(site.env, site_config.env)
        self.assertIn("tojson_pretty", site.env.filters)
        for name in ("url_for", "site_url", "human_date", "plural"):
            self.assertIn(name, site.env.globals)

    def test_paths_are_base_path_aware(self):
        # Pages are served under a subpath; a hardcoded absolute path breaks them.
        self.assertEqual(site_config.url_for("api/"), "/eoltracker/api/")
        self.assertEqual(site_config.url_for("/api/"), "/eoltracker/api/")
        self.assertTrue(site_config.site_url("api/").startswith("https://"))


class BuildSmokeTests(unittest.TestCase):
    """The build's own contract: `site.build` is public and writes the additive shards."""

    def test_build_is_public_and_root_is_still_exported(self):
        # `python -m engine` addresses both, so neither may move out of `site`.
        self.assertTrue(callable(site.build))
        self.assertTrue(Path(site.ROOT).is_dir())

    def test_the_vendor_index_path_does_not_collide_with_record_endpoints(self):
        # `v1/hardware/vendors.json` shares a directory with `v1/hardware/{id}.json`,
        # so a record id equal to the index stem would overwrite it silently.
        self.assertEqual(Path(site.VENDOR_INDEX).stem, "vendors")
        self.assertEqual(Path(site.VENDOR_INDEX).parent.as_posix(), "v1/hardware")


class CatalogCase(unittest.TestCase):
    """A minimal valid catalog on disk, built through the real `site.build`."""

    # A snapshot day far from the tests' own run date, so a countdown computed
    # from the wall clock instead of the snapshot is visible immediately.
    SNAPSHOT = "2026-09-17T12:00:00Z"

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        (self.root / "products").mkdir()
        self.record("sample", eol="2099-01-01")
        self.write_manifest()

    def record(self, product_id, eol=None, **milestones):
        record = normalize({"result": {"name": product_id, "label": product_id.title(), "category": "lang",
                                       "labels": {"eol": "Security Support"},
                                       "releases": [{"name": "1", "eolFrom": eol}]}}, self.SNAPSHOT)
        dump(self.root / "products" / f"{product_id}.json", record)
        return record

    def write_manifest(self, **overrides):
        count = len(list((self.root / "products").glob("*.json")))
        dump(self.root / "manifest.json", {
            "generated_at": self.SNAPSHOT, "source_url": API,
            "product_count": count, "release_count": count, "excluded_hardware": [], **overrides})

    def build(self):
        self.out = self.root / "_site_out"
        return site.build(data_dir=self.root, out_dir=self.out)


class HardwareIndexScopeTests(CatalogCase):
    """`v1/hardware.json` names its own subject, not the software manifest's (#88)."""

    def test_software_counts_are_not_spread_into_the_hardware_index(self):
        self.build()
        hardware = json.loads((self.out / "v1" / "hardware.json").read_text(encoding="utf-8"))
        # Every top-level count is about hardware, and says so.
        self.assertEqual(hardware["subject"], "hardware catalog")
        self.assertEqual(hardware["counts"]["subject"], "hardware catalog")
        self.assertEqual(hardware["counts"]["hardware_records"], hardware["hardware_count"])
        # The software snapshot is retained, but scoped to its own subject and
        # never mixed into this document's top level.
        self.assertNotIn("products", hardware)
        self.assertEqual(hardware["software_manifest"]["subject"], "software catalog (endoflife.date snapshot)")
        self.assertEqual(hardware["software_manifest"]["product_count"], 1)
        self.assertNotEqual(hardware["subject"], hardware["software_manifest"]["subject"])

    def test_every_top_level_count_can_be_attributed_to_one_subject(self):
        self.build()
        hardware = json.loads((self.out / "v1" / "hardware.json").read_text(encoding="utf-8"))
        products = json.loads((self.out / "v1" / "products.json").read_text(encoding="utf-8"))
        # The two documents do not disagree about a count because neither
        # publishes the other's count as its own.
        self.assertEqual(set(hardware) & {"product_count", "release_count"}, set())
        self.assertEqual(products["product_count"], 1)
        self.assertIn("subject", hardware)
        self.assertIn("counts", hardware)


class SnapshotReferenceDateTests(CatalogCase):
    """One reference date drives the displayed provenance and the countdowns (#95)."""

    def test_countdowns_are_measured_from_the_displayed_snapshot_day(self):
        self.build()
        page = (self.out / "products" / "sample" / "index.html").read_text(encoding="utf-8")
        # The page prints its snapshot stamp and a day count; the count is the
        # distance between that stamp and the deadline, not from today.
        snapshot = site.snapshot_date(self.SNAPSHOT)
        deadline = datetime(2099, 1, 1, tzinfo=timezone.utc).date()
        self.assertEqual((deadline - snapshot).days, 26404)
        self.assertIn("in 26404 days", page)
        # The stamp the count was measured from is the one printed beside it.
        self.assertIn(self.SNAPSHOT, page)

    def test_the_reference_date_comes_from_the_manifest_not_the_clock(self):
        # A manifest day in the past must produce the past arithmetic, so a tree
        # built today and a tree built next week agree on the same committed data.
        self.build()
        page = (self.out / "products" / "sample" / "index.html").read_text(encoding="utf-8")
        today = datetime.now(timezone.utc).date()
        from_wall_clock = (datetime(2099, 1, 1, tzinfo=timezone.utc).date() - today).days
        self.assertNotEqual(from_wall_clock, 26404)
        self.assertNotIn(f"in {from_wall_clock} days", page)

    def test_two_builds_of_one_catalog_produce_identical_pages(self):
        first = self.build()
        first_pages = {path.relative_to(self.out).as_posix(): path.read_bytes()
                       for path in self.out.rglob("*") if path.is_file()}
        self.build()
        second_pages = {path.relative_to(self.out).as_posix(): path.read_bytes()
                        for path in self.out.rglob("*") if path.is_file()}
        # Nothing in the tree is derived from wall-clock time, so a rebuild of
        # unchanged data is byte-identical.
        self.assertEqual(first_pages, second_pages)
        self.assertEqual(first["today"], self.SNAPSHOT[:10])


class AtomicPublicationTests(CatalogCase):
    """A failed later stage leaves the previous tree, not a partial one (#114)."""

    def first_build(self):
        self.build()
        return {path.relative_to(self.out).as_posix(): path.read_bytes()
                for path in self.out.rglob("*") if path.is_file()}

    def test_a_late_stage_failure_preserves_the_previous_tree(self):
        before = self.first_build()
        original = site.feeds.build

        def boom(*args, **kwargs):
            raise OSError("disk full while writing the feeds")

        site.feeds.build = boom
        self.addCleanup(setattr, site.feeds, "build", original)
        with self.assertRaisesRegex(OSError, "disk full while writing the feeds"):
            site.build(data_dir=self.root, out_dir=self.out)
        after = {path.relative_to(self.out).as_posix(): path.read_bytes()
                 for path in self.out.rglob("*") if path.is_file()}
        self.assertEqual(after, before)
        # No staging tree is left behind either.
        self.assertEqual([p.name for p in self.root.iterdir() if "staging" in p.name], [])

    def test_a_change_ledger_failure_preserves_the_previous_tree(self):
        before = self.first_build()
        # The changes stage only runs when a ledger is committed.
        dump(self.root / "opengear-changes.json",
             {"version": 1, "checked_at": "2026-09-17T12:00:00Z",
              "baseline_at": "2026-09-17T12:00:00Z", "events": []})
        original = site.changes.build
        site.changes.build = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("bad ledger"))
        self.addCleanup(setattr, site.changes, "build", original)
        with self.assertRaisesRegex(RuntimeError, "bad ledger"):
            site.build(data_dir=self.root, out_dir=self.out)
        after = {path.relative_to(self.out).as_posix(): path.read_bytes()
                 for path in self.out.rglob("*") if path.is_file()}
        self.assertEqual(after, before)

    def test_the_changes_ledger_is_published_within_the_atomic_build(self):
        result = self.build()
        self.assertIsNone(result["changes"])
        dump(self.root / "opengear-changes.json",
             {"version": 1, "checked_at": "2026-09-17T12:00:00Z",
              "baseline_at": "2026-09-17T12:00:00Z", "events": []})
        result = self.build()
        self.assertIsNotNone(result["changes"])
        self.assertEqual(result["changes"]["events"], 0)
        self.assertTrue((self.out / "v1" / "changes.json").is_file())
        self.assertTrue((self.out / "v1" / "changes.atom").is_file())

    def test_the_staged_tree_is_checked_before_it_is_published(self):
        # A tree missing a required endpoint must not replace a good one.
        before = self.first_build()
        original = site.openeox.build
        site.openeox.build = lambda *a, **k: {}
        self.addCleanup(setattr, site.openeox, "build", original)
        with self.assertRaisesRegex(ValueError, "incomplete"):
            site.build(data_dir=self.root, out_dir=self.out)
        after = {path.relative_to(self.out).as_posix(): path.read_bytes()
                 for path in self.out.rglob("*") if path.is_file()}
        self.assertEqual(after, before)

    def test_the_first_build_publishes_the_complete_tree(self):
        result = self.build()
        self.assertEqual(result["staging"]["files"], len(
            [p for p in self.out.rglob("*") if p.is_file()]))
        for name in ("index.html", "404.html", "v1/feed.json", "v1/products.json",
                     "v1/hardware.json", "v1/feed.atom", "v1/feed.rss", "v1/calendar.ics",
                     "v1/feed-exclusions.json", "v1/openeox/index.json"):
            self.assertTrue((self.out / name).is_file(), name)

    def test_the_cli_build_owns_every_stage(self):
        # The command must not append stages to an already published `_site/`:
        # it calls `site.build`, which stages internally.
        from unittest import mock

        from engine import __main__ as cli
        result = {"out": "x", "records": 1, "hardware_records": 0, "staging": {"files": 3}}
        with mock.patch.object(site, "build", return_value=result) as build:
            cli.main(["build"])
        build.assert_called_once_with()


class SafeUrlPresentationTests(CatalogCase):
    """Unsafe URL fields never reach a rendered link (#98)."""

    def test_a_javascript_upstream_url_is_not_rendered_as_an_href(self):
        # Validation refuses a mismatched provenance URL for a committed record,
        # so the sink is exercised with the shape a vendor collector actually
        # produces: a record whose source_urls carry an attacker-controlled value.
        record = {"id": "hostile", "name": "Hostile", "vendor": "ACME", "product_line": "ACME",
                  "family": "hardware", "model_number": "H1", "status": "unknown",
                  "milestones": {"ga": None, "eos": None, "eossec": None, "eol": "2099-01-01"},
                  "upstream": {"SKU": {"text": "H1", "value": None, "datetime": None, "role": None,
                                       "links": [{"url": "javascript:alert(1)", "label": "docs"},
                                                 {"url": "https://example.test/docs", "label": "docs2"}]}},
                  "provenance": {"source_urls": ["javascript:alert(document.cookie)", "https://example.test/page"],
                                 "verifier": "deterministic-eosl-date",
                                 "last_checked": "2026-09-17T00:00:00Z"}}
        rows = site_views.hardware_rows(record)
        summary = site_views.summarize_hardware(record, rows, site.snapshot_date(self.SNAPSHOT))
        html = site_config.env.get_template("hardware.html").render(**self.hardware_context(record, rows, summary))
        # No link sink carries the unsafe value. The verbatim evidence block
        # still shows the raw cell (that is its job), as escaped, inert text.
        hrefs = re.findall(r'(?:href|cite)="([^"]*)"', html)
        self.assertFalse([href for href in hrefs if href.startswith("javascript:")], hrefs)
        self.assertIn("https://example.test/page", hrefs)
        self.assertIn("https://example.test/docs", hrefs)
        # The unsafe entries are dropped from the model the template reads, not
        # merely escaped in one place.
        self.assertEqual([link["url"] for link in rows["raw"][0]["links"]], ["https://example.test/docs"])
        self.assertEqual(summary["source_urls"], ["https://example.test/page"])
        self.assertIsNone(summary["source"])

    def hardware_context(self, record, rows, summary):
        """The minimum `hardware.html` context, with the model under test."""
        return {
            "active": "hardware", "canonical": site_config.site_url("hardware/hostile/"),
            "title": "Hostile", "description": "url sink test", "notices": {},
            "manifest": {"generated_at": self.SNAPSHOT, "excluded_hardware": []},
            "schema_version": "1.0", "schema_files": [],
            "refresh": {"iso": self.SNAPSHOT, "human": "Sep 17, 2026"},
            "product_count": 1, "release_count": 1, "excluded_count": 0,
            "researched_count": 0, "researched_hardware_count": 0, "hardware_count": 1,
            "milestone_meta": site_config.MILESTONES,
            "hardware_milestone_meta": site_config.HARDWARE_MILESTONES,
            "hardware_status_meta": site_config.HARDWARE_STATUSES,
            "hardware_status_order": site_config.HARDWARE_STATUS_ORDER,
            "catalog_states": site_config.CATALOG_STATES,
            "catalog_state_counts": {state["key"]: 1 for state in site_config.CATALOG_STATES},
            "catalog_state_order": {state["key"]: index for index, state in enumerate(site_config.CATALOG_STATES)},
            "catalog_source_name": "Opengear product configurator",
            "catalog_source_site": "https://opengear.com/configure/",
            "catalog_stats": {}, "import_report": None, "report_families": [],
            "research_stale_days": 30, "changes_available": False,
            "changes_json_url": site_config.url_for("v1/changes.json"),
            "changes_atom_url": site_config.url_for("v1/changes.atom"),
            "hardware_vendors": [], "hardware_statuses": [],
            "model": record, "rows": rows, "identity": site_views.catalog_identity(record),
            "exact_matches": [], "unresolved_matches": [], "claimed_by": [], "shared_models": [],
            "coverage": site_views.milestone_coverage([rows], site_config.HARDWARE_MILESTONES),
            "json_url": "/eoltracker/v1/hardware/hostile.json",
            "json_abs": site_config.site_url("v1/hardware/hostile.json"),
            "upstream_links": summary["source_links"],
            "hardware_source_name": "eosl.date",
            "hardware_source_site": summary["source"],
            "hardware_source_attribution": "", "research": None,
        }

    def test_safe_link_helpers_keep_only_absolute_http_and_https(self):
        safe = site_views.safe_link
        self.assertIsNone(safe("javascript:alert(1)"))
        self.assertIsNone(safe("data:text/html,x"))
        self.assertIsNone(safe("vbscript:msgbox"))
        self.assertIsNone(safe("https://user:pass@example.test/"))
        self.assertIsNone(safe("//example.test/x"))
        self.assertIsNone(safe("not a url"))
        self.assertIsNone(safe(None))
        self.assertEqual(safe("https://example.test/a"), "https://example.test/a")
        self.assertEqual(safe("http://example.test/a"), "http://example.test/a")

    def test_source_links_drop_unsafe_entries_and_keep_order(self):
        links = site_sources.source_links(["javascript:x", "https://b.test/", "ftp://c.test/"])
        self.assertEqual([link["url"] for link in links], ["https://b.test/"])

    def test_the_record_link_object_keeps_safe_values_and_its_labels(self):
        mapped = site_views.safe_link_map({"homepage": "javascript:x", "docs": "https://d.test/", "none": None})
        self.assertEqual(mapped, {"docs": "https://d.test/"})


if __name__ == "__main__":
    unittest.main()
