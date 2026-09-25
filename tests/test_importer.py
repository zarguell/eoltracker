"""Importer boundaries: label mapping, source ownership, and cardinality caps."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from engine.importer import (API, MAX_PRODUCTS, MAX_RELEASES, dump, import_data,
                             milestones, normalize, date_value)


class MilestoneTests(unittest.TestCase):
    def test_boolean_status_does_not_invent_a_date(self):
        self.assertIsNone(date_value(True))
        self.assertIsNone(date_value(False))
        with self.assertRaises(ValueError):
            date_value("2026-02-30")

    def test_generic_support_is_not_security_support(self):
        dates = milestones({"eolFrom": "2027-01-01"}, {"eol": "Support"})
        self.assertEqual(dates["eol"], "2027-01-01")
        self.assertIsNone(dates["eossec"])

    def test_unknown_extension_does_not_shorten_total_support(self):
        dates = milestones({"eolFrom": "2027-01-01", "eoesFrom": None},
                           {"eol": "Security Support", "eoes": "Extended Support"})
        self.assertEqual(dates["eossec"], "2027-01-01")
        self.assertIsNone(dates["eol"])

    def test_extended_security_updates_extend_security_deadline(self):
        dates = milestones({"eolFrom": "2027-01-01", "eoesFrom": "2029-01-01"},
                           {"eol": "Security Support", "eoes": "Extended Security Updates"})
        self.assertEqual(dates["eossec"], "2029-01-01")
        self.assertEqual(dates["eol"], "2029-01-01")

    def test_security_only_wording_never_fills_terminal_support(self):
        # adonisjs publishes one date under the label "Security Support" and no
        # extended-support date at all. Security support ends there, but the
        # terminal/full support deadline is not stated by that column, so it
        # must stay absent rather than republish the security deadline as eol.
        dates = milestones({"releaseDate": "2020-10-11", "isEol": True,
                            "eolFrom": "2023-02-20", "eoesFrom": None},
                           {"eoas": None, "discontinued": None,
                            "eol": "Security Support", "eoes": None})
        self.assertEqual(dates, {"ga": "2020-10-11", "eos": None,
                                 "eossec": "2023-02-20", "eol": None})
        # Case and punctuation folding must not change that verdict.
        for label in ("security support", "Security-Support", "SECURITY SUPPORT"):
            self.assertIsNone(milestones({"eolFrom": "2023-02-20"}, {"eol": label})["eol"], label)

    def test_full_support_wording_still_fills_terminal_support(self):
        # The counterpart boundary: wording that states full/terminal support is
        # unaffected by the security-only correction.
        for label in ("Support", "Support Status", "Supported", "End of Life"):
            dates = milestones({"eolFrom": "2027-01-01"}, {"eol": label})
            self.assertEqual(dates["eol"], "2027-01-01", label)

    def test_vendor_wording_variants_reach_the_right_milestone(self):
        # big-ip publishes both dates but labels them "End of Technical Support";
        # the terminal date must map to eol, while software-development end
        # must never become end of sale.
        dates = milestones({"releaseDate": "2026-05-05", "eoasFrom": "2029-05-05", "eolFrom": "2029-05-05"},
                           {"eoas": "End of Software Development", "eol": "End of Technical Support"})
        self.assertEqual(dates["eol"], "2029-05-05")
        self.assertIsNone(dates["eos"])

    def test_label_wording_is_normalized_not_matched_exactly(self):
        for label in ("End-of-life Date", "End Of Life", "end-of-life"):
            dates = milestones({"eolFrom": "2030-01-01"}, {"eol": label})
            self.assertEqual(dates["eol"], "2030-01-01", label)

    def test_security_and_technical_support_is_not_security_support(self):
        # internet-explorer: a security+technical label is a full support end
        # (eol), not a security-only deadline.
        dates = milestones({"eolFrom": "2022-06-15"}, {"eol": "Security and technical support"})
        self.assertEqual(dates["eol"], "2022-06-15")
        self.assertIsNone(dates["eossec"])

    def test_discontinued_does_not_imply_end_of_sales(self):
        dates = milestones({"discontinuedFrom": "2027-01-01"}, {"discontinued": "Discontinued"})
        self.assertIsNone(dates["eos"])


def catalog_root(directory, records):
    """A data directory holding ``records`` plus the manifest and a sidecar."""
    (directory / "products").mkdir(parents=True, exist_ok=True)
    for record in records:
        dump(directory / "products" / (record["id"] + ".json"), record)
    dump(directory / "manifest.json", {
        "generated_at": "2026-09-17T00:00:00Z", "source_url": API, "product_count": 1,
        "release_count": 1, "excluded_hardware": [], "source": "import-data"})


class OwnershipTests(unittest.TestCase):
    """#78: an upstream slug must never overwrite a record this source does not own."""

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        # A registered vendor collector owns the `samba` slug; the baseline
        # endoflife.date importer now acquires the same name upstream. Samba's
        # own record and report sidecar are what a collision would destroy.
        self.foreign = normalize(
            {"result": {"name": "samba", "label": "Samba", "category": "server-app", "labels": {},
                        "releases": [{"name": "4.23", "releaseDate": "2025-09-12"}]}},
            "2026-09-17T00:00:00Z")
        self.foreign["provenance"]["verifier"] = "deterministic-samba"
        catalog_root(self.root, [self.foreign])
        dump(self.root / "samba-import.json", {"verifier": "deterministic-samba", "total_records": 1})
        self.before = {str(path.relative_to(self.root)): path.read_bytes()
                       for path in sorted(self.root.rglob("*")) if path.is_file()}

    def fetch(self, url):
        if url == API:
            return {"total": 1, "result": [{"name": "samba", "category": "server-app"}]}
        return {"result": {"name": "samba", "label": "Samba", "category": "server-app",
                           "labels": {}, "releases": [{"name": "4.23", "releaseDate": "2025-09-12"}]},
                "last_modified": None}

    def test_a_colliding_upstream_slug_is_refused_before_staging_or_fetching_details(self):
        with mock.patch("engine.importer.fetch", side_effect=self.fetch) as fetch:
            with self.assertRaisesRegex(ValueError, "source ownership collision"):
                import_data(self.root)
        # Refused before the detail fan-out: only the listing was read.
        self.assertEqual(fetch.call_count, 1)
        self.assertEqual(fetch.call_args_list[0].args[0], API)

    def test_refusal_preserves_the_foreign_record_and_every_sidecar(self):
        with mock.patch("engine.importer.fetch", side_effect=self.fetch):
            with self.assertRaises(ValueError) as caught:
                import_data(self.root)
        self.assertIn("deterministic-samba", str(caught.exception))
        self.assertIn("deterministic-endoflife-date-v1", str(caught.exception))
        after = {str(path.relative_to(self.root)): path.read_bytes()
                 for path in sorted(self.root.rglob("*")) if path.is_file()}
        self.assertEqual(after, self.before)


class CarriedSourceSidecarTests(unittest.TestCase):
    """A carried foreign record's report sidecar must be staged before validation."""

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)

    def test_a_carried_sources_report_sidecar_is_staged_for_validation(self):
        # A registered report-bearing source (Samba) owns a committed record the
        # upstream listing does not mention. Validation requires that source's
        # sidecar beside the record it accounts for, so a refresh that carries
        # the record must carry its report too — otherwise the internal
        # validate_data refuses the snapshot for a missing sidecar.
        from engine import samba

        html = (Path(__file__).parent / "fixtures/samba-release-planning.html").read_text(
            encoding="utf-8")
        releases = samba.parse_releases(html)
        checked = "2026-09-17T00:00:00Z"
        record = samba.record_for(releases, checked)
        report = samba.report_for(releases, [], checked)
        catalog_root(self.root, [record])
        dump(self.root / samba.REPORT, report)
        before_record = (self.root / "products/samba.json").read_bytes()
        before_report = (self.root / samba.REPORT).read_bytes()

        listing = {"total": 1, "result": [{"name": "sample", "category": "lang"}]}
        detail = {"result": {"name": "sample", "label": "Sample", "category": "lang", "labels": {},
                             "releases": [{"name": "1", "releaseDate": "2020-01-01"}]},
                  "last_modified": None}

        with mock.patch("engine.importer.fetch",
                        side_effect=lambda url: listing if url == API else detail):
            summary = import_data(self.root)
        self.assertIn("imported 1 software products", summary)
        # The carried record and its sidecar survived byte-for-byte.
        self.assertEqual((self.root / "products/samba.json").read_bytes(), before_record)
        self.assertEqual((self.root / samba.REPORT).read_bytes(), before_report)


class SelfOwnedSlugTests(unittest.TestCase):
    """The guard must not refuse the baseline's own records."""

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)

    def test_a_slug_this_source_already_owns_is_not_a_collision(self):
        listing = {"total": 1, "result": [{"name": "sample", "category": "lang"}]}
        detail = {"result": {"name": "sample", "label": "Sample", "category": "lang", "labels": {},
                             "releases": [{"name": "1", "releaseDate": "2020-01-01"}]},
                  "last_modified": None}
        catalog_root(self.root, [normalize(detail, "2026-01-01T00:00:00Z")])

        with mock.patch("engine.importer.fetch",
                        side_effect=lambda url: listing if url == API else detail):
            summary = import_data(self.root)
        self.assertIn("imported 1 software products", summary)
        # The refresh rewrote its own record; unchanged content keeps the
        # revision time, so this is a quiet refresh rather than a new revision.
        stored = json.loads((self.root / "products/sample.json").read_text())
        self.assertEqual(stored["provenance"]["last_checked"], "2026-01-01T00:00:00Z")
        self.assertEqual(stored["releases"][0]["milestones"],
                         {"ga": "2020-01-01", "eos": None, "eossec": None, "eol": None})


class CardinalityTests(unittest.TestCase):
    """A corrupted or adversarial upstream fails closed before the fan-out."""

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        catalog_root(self.root, [])

    def test_an_oversized_listing_is_refused_before_any_detail_fetch(self):
        oversized = {"total": MAX_PRODUCTS + 1,
                     "result": [{"name": f"p{index}", "category": "lang"}
                                for index in range(MAX_PRODUCTS + 1)]}
        with mock.patch("engine.importer.fetch", return_value=oversized) as fetch:
            with self.assertRaisesRegex(ValueError, "exceeds"):
                import_data(self.root)
        self.assertEqual(fetch.call_count, 1)

    def test_an_oversized_product_is_refused(self):
        payload = {"result": {"name": "sample", "label": "Sample", "category": "lang", "labels": {},
                              "releases": [{"name": str(index), "releaseDate": "2020-01-01"}
                                           for index in range(MAX_RELEASES + 1)]}}
        with self.assertRaisesRegex(ValueError, "releases"):
            normalize(payload, "2026-09-17T00:00:00Z")

    def test_the_cap_is_a_ceiling_not_a_limit_on_a_real_catalog(self):
        # Exactly MAX_PRODUCTS entries must not trip the cap: the refusal is
        # strictly above the ceiling. The detail fetch is a sentinel, so the
        # assertion is that the cap check itself let the listing through.
        at_cap = {"total": MAX_PRODUCTS,
                  "result": [{"name": f"p{index}", "category": "lang"}
                             for index in range(MAX_PRODUCTS)]}

        def fetch(url):
            if url == API:
                return at_cap
            raise RuntimeError("detail fetch reached")

        with mock.patch("engine.importer.fetch", side_effect=fetch):
            with self.assertRaises(RuntimeError):
                import_data(self.root)

    def test_a_real_listing_shape_is_accepted(self):
        # The caps must never reject the catalog the pipeline actually imports.
        listing = {"total": 1, "result": [{"name": "sample", "category": "lang"}]}
        detail = {"result": {"name": "sample", "label": "Sample", "category": "lang", "labels": {},
                             "releases": [{"name": "1", "releaseDate": "2020-01-01"}]},
                  "last_modified": None}
        with mock.patch("engine.importer.fetch",
                        side_effect=lambda url: listing if url == API else detail):
            self.assertIn("imported 1 software products", import_data(self.root))


if __name__ == "__main__":
    unittest.main()
