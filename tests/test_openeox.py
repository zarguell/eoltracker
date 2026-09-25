"""OpenEoX index provenance, the composite catalog, and the export contract.

The index is the discovery document for the whole export: it is where a consumer
learns which products and releases exist, why some are absent, and — the subject
here — *where the dates came from*. The catalog is composite (the endoflife.date
importer, registered vendor collectors, and researched records), so an index
that named one upstream would misstate every record the others own. These tests
also pin the parts of the index contract the exports rely on: the counts, the
preserved keys, and the per-release records themselves (#89).
"""
import json
import tempfile
import unittest
from pathlib import Path

from engine import openeox, sources

DAY = "2030-04-01"


def record(product_id, verifier="deterministic-endoflife-date-v1", eol=DAY, eossec=DAY):
    """One minimal publishable software record for the export."""
    return {
        "id": product_id, "name": product_id.title(), "category": "software",
        "provenance": {"source_url": "https://example.test/" + product_id, "verifier": verifier,
                       "last_checked": "2026-09-17T00:00:00Z", "upstream_modified": None},
        "releases": [{"id": "1", "name": "1",
                      "milestones": {"ga": None, "eos": None, "eossec": eossec, "eol": eol}}],
    }


class OpenEoxProvenanceTests(unittest.TestCase):
    """The index describes the composite catalog it actually exported (#89)."""

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.out = Path(temp.name)

    def build(self, products):
        return openeox.build(products, site=self.out)

    def test_the_index_is_not_attributed_to_one_upstream(self):
        index = self.build([record("python")])
        source = index["source"]
        # The composite claim is explicit and machine-readable.
        self.assertTrue(source["composite"])
        self.assertIn("composite", source["statement"].lower())
        # The endoflife.date upstream is still named, but scoped to the pipeline
        # that owns it rather than presented as the export's only source.
        self.assertEqual(source["upstream"], openeox.UPSTREAM)
        self.assertEqual(source["upstream_of"]["name"], sources.source("import-data").name)
        self.assertEqual(source["upstream_of"]["url"], openeox.UPSTREAM)
        self.assertEqual(source["upstream_of"]["products"], 1)

    def test_every_verifier_family_in_the_catalog_is_enumerated(self):
        # At least two verifier families, as the issue requires for coverage.
        index = self.build([
            record("python"),
            record("vgpu", verifier="deterministic-nvidia-vgpu"),
            record("synology", verifier="researched-zarguell"),
        ])
        families = {row["verifier"]: row for row in index["source"]["families"]}
        self.assertEqual(set(families), {"deterministic-endoflife-date-v1",
                                         "deterministic-nvidia-vgpu", "researched-zarguell"})
        self.assertEqual(index["source"]["family_count"], 3)
        # A registered pipeline is named from the registry, with its pages.
        nvidia = families["deterministic-nvidia-vgpu"]
        registry = sources.source_for("deterministic-nvidia-vgpu")
        self.assertEqual(nvidia["name"], registry.name)
        self.assertEqual(nvidia["kind"], "registered")
        self.assertEqual(nvidia["attribution"], registry.attribution)
        self.assertEqual(nvidia["pages"], [page.url for page in registry.pages])
        self.assertEqual(nvidia["products"], 1)
        # A researched verifier names a contributor, not a pipeline: the index
        # must not credit it to a registry source that never read the record.
        researched = families["researched-zarguell"]
        self.assertEqual(researched["kind"], "researched")
        self.assertEqual(researched["name"], "researched contribution")
        self.assertIsNone(researched["attribution"])
        self.assertEqual(researched["pages"], [])
        self.assertIsNone(researched["category"])
        # Every registered family's name is a registry name; the researched one
        # deliberately is not one, so no pipeline is falsely credited.
        registered_names = {source.name for source in sources.all_sources()}
        self.assertNotIn(researched["name"], registered_names)

    def test_the_per_family_counts_account_for_every_product(self):
        products = [record("a"), record("b"), record("c", verifier="deterministic-nvidia-vgpu")]
        index = self.build(products)
        source = index["source"]
        self.assertEqual(sum(source["counts_by_verifier"].values()), len(products))
        self.assertEqual(sum(row["products"] for row in source["families"]), len(products))
        self.assertEqual(source["upstream_of"]["products"], 2)

    def test_an_unregistered_verifier_is_reported_not_credited_to_a_pipeline(self):
        # A verifier the registry does not know is stated as unknown rather than
        # silently folded into another source's row.
        index = self.build([record("mystery", verifier="deterministic-unregistered")])
        family = index["source"]["families"][0]
        self.assertEqual(family["kind"], "unregistered")
        self.assertIsNone(family["name"])
        self.assertEqual(family["products"], 1)

    def test_the_counts_and_the_preserved_keys_still_describe_the_export(self):
        index = self.build([record("python")])
        # The pre-existing count keys are unchanged.
        self.assertEqual(index["counts"], {"products": 1, "releases": 1, "exported": 1, "excluded": 0})
        self.assertEqual(len(index["records"]), 1)
        self.assertEqual(index["excluded"], [])
        # Every published record really is at its indexed path and conforms.
        path = self.out / index["records"][0]["path"]
        self.assertTrue(path.is_file())
        self.assertEqual(openeox.validate_core(json.loads(path.read_text(encoding="utf-8"))), [])

    def test_a_single_family_catalog_still_says_composite(self):
        # Even a one-pipeline catalog is described by the family list rather
        # than by the single upstream named in `upstream`, so the shape does not
        # change with the data.
        source = self.build([record("python")])["source"]
        self.assertEqual(source["family_count"], 1)
        self.assertTrue(source["composite"])
        self.assertIn("statement", source)


if __name__ == "__main__":
    unittest.main()
