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
import unittest
from pathlib import Path

from engine import site, site_config, site_sources, site_views


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


if __name__ == "__main__":
    unittest.main()
