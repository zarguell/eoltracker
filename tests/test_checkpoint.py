"""Regression tests for the Check Point Security Gateway & Management collector.

The fixture is the vendor policy page's own "Security Gateway & Management"
section markup as served, so these tests pin the parse against the real source:
every train row is accounted for, only the two date columns become milestones,
a month-precision date never gains an invented day, no date is derived from the
published four-year support policy, and the page's appliance and service rows
are reported as excluded rather than silently ignored. They also pin the WAF
guard — this host answers a request burst with a JavaScript challenge, and a
challenge must refuse the parse instead of publishing a partial snapshot.
"""
import json
import re
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from engine import checkpoint, importer, net, sources, validation
from engine.importer import API, dump, normalize

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/checkpoint-lifecycle.html"
SECTION = FIXTURE.read_text(encoding="utf-8")
CHALLENGE = (ROOT / "tests/fixtures/checkpoint-challenge.html").read_text(encoding="utf-8")
CHECKED = "2026-09-17T12:00:00Z"
MONTH = re.compile(r"\d{4}-(?:0[1-9]|1[0-2])$")


def parsed():
    """The fixture section parsed as a whole page.

    The fixture is one section of the real page, so the Software Support section
    heading is supplied around it; the parser still sees only the trains table's
    rows and reports none of them as excluded.
    """
    return checkpoint.parse_trains(_page())


def _page(section=SECTION):
    return ('<h2>Support Life Cycle Policy</h2><h2>Software Support</h2>'
            '<h3>Enterprise Software Support Timeline</h3>' + section)


def software_record(name="sample", verifier=None):
    record = normalize({"result": {"name": name, "label": name.title(), "category": "lang",
                                   "labels": {"eol": "Security Support"},
                                   "releases": [{"name": "1", "eolFrom": "2028-01-01"}]}}, CHECKED)
    record["provenance"]["verifier"] = verifier or sources.source("import-data").verifier
    return record


def catalog_root(directory, records):
    """A data directory holding ``records`` and the manifest the importer writes."""
    (directory / "products").mkdir(parents=True, exist_ok=True)
    for record in records:
        dump(directory / "products" / (record["id"] + ".json"), record)
    counted = [record for record in records
               if record["provenance"]["verifier"] == sources.source("import-data").verifier]
    dump(directory / "manifest.json", {
        "generated_at": CHECKED, "source_url": API, "product_count": len(counted),
        "release_count": sum(len(record["releases"]) for record in counted),
        "excluded_hardware": [], "source": "import-data"})


class SchemaFormatTests(unittest.TestCase):
    """The month precision the schema admits, pinned against the stored values."""

    def test_every_stored_milestone_is_a_month_or_a_day_and_never_padded(self):
        releases, _ = parsed()
        for release in releases:
            for field, value in release["milestones"].items():
                if value is not None:
                    self.assertRegex(value, MONTH, f"{release['id']} {field}")

    def test_month_value_reads_a_published_month_and_refuses_anything_else(self):
        self.assertEqual(checkpoint.month_value("September 2030", "row"), "2030-09")
        self.assertEqual(checkpoint.month_value("Sept 2026", "row"), "2026-09")
        self.assertEqual(checkpoint.month_value("January 2011", "row"), "2011-01")
        self.assertIsNone(checkpoint.month_value("", "row"))
        self.assertIsNone(checkpoint.month_value("N/A", "row"))
        # A day-precision value is never coerced into a month, and a month is
        # never padded into a day.
        for text in ("2030-09", "2030-09-28", "9/2030", "Q3 2030"):
            with self.assertRaisesRegex(ValueError, "unrecognized month-precision date"):
                checkpoint.month_value(text, "row")


class ParseTests(unittest.TestCase):

    def test_the_real_fixture_accounts_for_every_train_row(self):
        releases, excluded = parsed()
        self.assertEqual(len(releases), 17)
        # Every fixture row is a train row, so nothing in this section is excluded.
        self.assertEqual(excluded, [])
        self.assertEqual(parsed(), parsed())

    def test_current_and_historical_trains_are_both_published(self):
        releases, _ = parsed()
        ids = {release["id"] for release in releases}
        for train in ("r82-20", "r82-10", "r82", "r81-20", "r81-10", "r81", "r80-40",
                      "r80-20", "r80", "r77-30", "ngse", "r77", "r76", "r75-40",
                      "r75-20", "r75", "r75-40vs"):
            self.assertIn(train, ids)

    def test_the_stated_columns_become_ga_and_eol_at_the_published_precision(self):
        releases, _ = parsed()
        stored = {release["id"]: release["milestones"] for release in releases}
        self.assertEqual(stored["r82-20"], {"ga": "2026-09", "eos": None, "eossec": None,
                                            "eol": "2030-09"})
        self.assertEqual(stored["r82"], {"ga": "2024-10", "eos": None, "eossec": None,
                                         "eol": "2029-04"})
        self.assertEqual(stored["r81-20"], {"ga": "2022-11", "eos": None, "eossec": None,
                                            "eol": "2027-05"})
        self.assertEqual(stored["r75"], {"ga": "2011-01", "eos": None, "eossec": None,
                                         "eol": "2015-01"})

    def test_no_milestone_is_derived_from_the_four_year_support_policy(self):
        # The page states support runs "a minimum of four years" from GA, but the
        # columns are the only dates: R81's support end is 2024-10 against a
        # 2020-10 GA (four years) while R82.20's is 2030-09 against 2026-09 --
        # a coincidence in one row is never a rule applied to the rest.
        releases, _ = parsed()
        stored = {release["id"]: release["milestones"] for release in releases}
        self.assertEqual(stored["r82-20"]["eol"], "2030-09")
        self.assertEqual(stored["r82-10"]["eol"], "2030-06")  # not 2029-12
        self.assertNotEqual(stored["r82-10"]["eol"], "2029-12")

    def test_the_vendors_affected_versions_grouping_is_preserved_verbatim(self):
        releases, _ = parsed()
        stored = {release["id"]: release for release in releases}
        # A grouped scope is kept as the vendor's own cell; it is never expanded
        # into invented sub-release records.
        self.assertEqual(stored["r80-20"]["upstream"]["cells"]["Affected Versions"],
                         "R80.20, R80.30***")
        self.assertEqual(stored["r80"]["upstream"]["cells"]["Affected Versions"], "R80, R80.10")
        self.assertEqual(stored["r75-40"]["upstream"]["cells"]["Affected Versions"],
                         "R75.40, R75.45, R75.46, R75.47")
        self.assertEqual(len(releases), 17)

    def test_the_train_identity_survives_a_build_or_take_change(self):
        self.assertEqual(checkpoint.train_id("Check Point R81.20"), "r81-20")
        self.assertEqual(checkpoint.train_id("Check Point R80.40"), "r80-40")
        self.assertEqual(checkpoint.train_id("Check Point R82"), "r82")
        self.assertEqual(checkpoint.train_id("NGSE"), "ngse")
        self.assertEqual(checkpoint.train_id("Check Point R80*"), "r80")
        # A distinct train named beside another keeps its own identity; the two
        # never collide into one release.
        self.assertEqual(checkpoint.train_id("Check Point R75.40VS"), "r75-40vs")
        self.assertNotEqual(checkpoint.train_id("Check Point R75.40VS"),
                            checkpoint.train_id("Check Point R75.40"))

    def test_reshaped_table_headers_refuse_the_parse(self):
        broken = SECTION.replace("<th style=\"background-color: #545454; font-size: 16px;\">"
                                 "Support Until</th>",
                                 "<th style=\"background-color: #545454; font-size: 16px;\">"
                                 "End of life</th>", 1)
        with self.assertRaisesRegex(ValueError, "Unexpected Check Point table headers"):
            checkpoint.parse_trains(_page(broken))

    def test_a_missing_trains_table_refuses_the_parse(self):
        other = ('<h2>Software Support</h2><h3>Check Point Edge</h3><table><thead><tr>'
                 '<th>Service</th><th>End of sale</th></tr></thead><tbody>'
                 '<tr><td>Check Point Edge</td><td>January 2024</td></tr></tbody></table>')
        with self.assertRaisesRegex(ValueError, "Missing Check Point table"):
            checkpoint.parse_trains(other)

    def test_a_page_with_no_tables_at_all_refuses_the_parse(self):
        with self.assertRaisesRegex(ValueError, "states no tables"):
            checkpoint.parse_trains("<html><body><h2>Software Support</h2></body></html>")

    def test_a_waf_challenge_refuses_the_parse_instead_of_publishing_nothing(self):
        with self.assertRaisesRegex(ValueError, "states no tables"):
            checkpoint.parse_trains(CHALLENGE)

    def test_out_of_scope_rows_are_reported_rather_than_dropped(self):
        page = _page(SECTION) + (
            '<h2>Appliances Support</h2><h3>Enterprise Appliances</h3>'
            '<table><thead><tr><th>Appliance Product/Model</th><th>End of Support</th>'
            '</tr></thead><tbody><tr><td>2200 Appliance</td><td>Jun-2022</td></tr></tbody></table>')
        releases, excluded = checkpoint.parse_trains(page)
        self.assertEqual(len(releases), 17)
        self.assertEqual(len(excluded), 1)
        self.assertEqual(excluded[0]["section"], "Appliances Support")
        self.assertEqual(excluded[0]["table"], "Enterprise Appliances")
        self.assertIn("Security Gateway & Management", excluded[0]["reason"])


class RecordTests(unittest.TestCase):

    def test_record_names_its_registered_source_and_publishes_no_identifier(self):
        releases, _ = parsed()
        record = checkpoint.record_for(releases, CHECKED)
        self.assertEqual(record["id"], "checkpoint-security-gateway")
        self.assertEqual(record["category"], "software")
        self.assertEqual(record["provenance"]["verifier"],
                         sources.source("import-checkpoint").verifier)
        self.assertEqual(record["provenance"]["source_url"], sources.CHECKPOINT_LIFECYCLE)
        self.assertEqual(record["links"]["html"], sources.CHECKPOINT_LIFECYCLE)
        # Check Point states no CPE for this product; none is invented.
        self.assertEqual(record["identifiers"], [])
        # The vendor wording each milestone was read from.
        self.assertEqual(record["labels"], {"ga": "General Availability", "eol": "Support Until"})

    def test_validate_record_rederives_every_milestone_from_the_stored_cells(self):
        releases, _ = parsed()
        record = checkpoint.record_for(releases, CHECKED)
        checkpoint.validate_record(record)
        drifted = json.loads(json.dumps(record))
        drifted["releases"][0]["milestones"]["eol"] = "2031-09"
        with self.assertRaisesRegex(ValueError, "contradicts its stored cells"):
            checkpoint.validate_record(drifted)

    def test_validate_record_refuses_a_release_claiming_another_train(self):
        releases, _ = parsed()
        record = checkpoint.record_for(releases, CHECKED)
        record["releases"][0]["id"] = "r99-9"
        with self.assertRaisesRegex(ValueError, "does not name its own train"):
            checkpoint.validate_record(record)

    def test_validate_record_refuses_another_sources_verifier(self):
        releases, _ = parsed()
        record = checkpoint.record_for(releases, CHECKED)
        record["provenance"]["verifier"] = sources.source("import-data").verifier
        with self.assertRaisesRegex(ValueError, "Invalid Check Point source identity"):
            checkpoint.validate_record(record)

    def test_a_train_the_table_no_longer_states_is_retained_not_deleted(self):
        releases, _ = parsed()
        committed = checkpoint.record_for(releases, CHECKED)
        fresh = [release for release in releases if release["id"] != "r81"]
        combined, kept = checkpoint.combine_releases(fresh, committed)
        self.assertEqual([entry["id"] for entry in kept], ["r81"])
        retained = {release["id"]: release for release in combined}["r81"]
        self.assertIs(retained["upstream"]["in_source"], False)
        self.assertEqual(retained["milestones"]["eol"], "2024-10")
        checkpoint.validate_record(checkpoint.record_for(combined, CHECKED))

    def test_freshly_parsed_releases_carry_no_retention_marker(self):
        combined, kept = checkpoint.combine_releases(parsed()[0], None)
        self.assertEqual(kept, [])
        self.assertTrue(all("in_source" not in release["upstream"] for release in combined))


class CatalogRootCase(unittest.TestCase):
    """A data directory holding an import-data product, as the committed one does."""

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.sibling = software_record()
        catalog_root(self.root, [self.sibling])
        self.sibling_bytes = (self.root / "products/sample.json").read_bytes()

    def publish(self, page=None):
        releases, excluded = checkpoint.parse_trains(page or _page())
        record = checkpoint.record_for(releases, CHECKED)
        report = checkpoint.report_for(releases, excluded, [], CHECKED)
        return checkpoint.publish_record(record, report, self.root)


class PublicationTests(CatalogRootCase):
    def test_publish_writes_only_its_own_record_and_report(self):
        self.publish()
        record = json.loads((self.root / "products/checkpoint-security-gateway.json").read_text())
        self.assertEqual(record["id"], "checkpoint-security-gateway")
        self.assertEqual((self.root / "products/sample.json").read_bytes(), self.sibling_bytes)
        report = json.loads((self.root / checkpoint.REPORT).read_text())
        self.assertEqual(report["total_records"], 1)
        self.assertEqual(report["rows"]["published"], 17)
        self.assertEqual(report["rows"]["trains"], 17)
        self.assertEqual(report["rows"]["undated"], 0)
        self.assertEqual(len(validation.validate_data(self.root)), 2)

    def test_report_accounts_for_every_row_it_saw(self):
        releases, excluded = parsed()
        report = checkpoint.report_for(releases, excluded, [], CHECKED)
        rows = report["rows"]
        self.assertEqual(rows["seen"], rows["trains"] + rows["excluded"])
        self.assertEqual(rows["seen"], 17)
        self.assertTrue(any("Month precision" in line for line in report["limitations"]))
        self.assertTrue(any("four years" in line for line in report["limitations"]))
        self.assertTrue(any("Appliances Support" in line for line in report["limitations"]))

    def test_republishing_an_unchanged_source_is_byte_identical(self):
        published = self.publish()
        before = (self.root / "products/checkpoint-security-gateway.json").read_bytes()
        again = self.publish()
        self.assertEqual((self.root / "products/checkpoint-security-gateway.json").read_bytes(),
                         before)
        self.assertEqual(published["provenance"]["last_checked"],
                         again["provenance"]["last_checked"])
        self.assertEqual(again["provenance"]["last_checked"], CHECKED)

    def test_a_record_another_source_owns_is_never_overwritten(self):
        self.sibling["id"] = "checkpoint-security-gateway"
        dump(self.root / "products/checkpoint-security-gateway.json", self.sibling)
        with mock.patch.object(net, "get_text") as fetch:
            with self.assertRaisesRegex(ValueError, "ownership collision"):
                checkpoint.import_checkpoint(self.root)
        fetch.assert_not_called()
        self.assertEqual(json.loads((self.root / "products/checkpoint-security-gateway.json")
                                    .read_text()), self.sibling)

    def test_a_challenged_response_writes_nothing(self):
        with mock.patch.object(net, "get_text", return_value=CHALLENGE):
            with self.assertRaisesRegex(ValueError, "did not serve the lifecycle table"):
                checkpoint.import_checkpoint(self.root)
        self.assertEqual(sorted(path.name for path in (self.root / "products").glob("*.json")),
                         ["sample.json"])
        self.assertFalse((self.root / checkpoint.REPORT).exists())

    def test_an_empty_response_writes_nothing(self):
        with mock.patch.object(net, "get_text", return_value=""):
            with self.assertRaisesRegex(ValueError, "did not serve the lifecycle table"):
                checkpoint.import_checkpoint(self.root)
        self.assertEqual(sorted(path.name for path in (self.root / "products").glob("*.json")),
                         ["sample.json"])
        self.assertFalse((self.root / checkpoint.REPORT).exists())

    def test_a_parse_failure_writes_nothing(self):
        broken = SECTION.replace(">Support Until</th>", ">End of life</th>", 1)
        with mock.patch.object(net, "get_text", return_value=_page(broken)):
            with self.assertRaisesRegex(ValueError, "Unexpected Check Point table headers"):
                checkpoint.import_checkpoint(self.root)
        self.assertEqual(sorted(path.name for path in (self.root / "products").glob("*.json")),
                         ["sample.json"])
        self.assertFalse((self.root / checkpoint.REPORT).exists())

    def test_import_fetches_once_and_publishes_the_record_and_report(self):
        with mock.patch.object(net, "get_text", return_value=_page()) as fetch:
            detail = checkpoint.import_checkpoint(self.root)
        # One fetch per run: this host challenges bursts.
        fetch.assert_called_once_with(checkpoint.SOURCE_URL, encoding="utf-8")
        self.assertEqual((self.root / "products/sample.json").read_bytes(), self.sibling_bytes)
        self.assertIn("imported 17 Check Point release trains", detail)
        self.assertIn(checkpoint.REPORT, detail)
        self.assertEqual(json.loads((self.root / checkpoint.REPORT).read_text())["verifier"],
                         checkpoint.VERIFIER)

    def test_import_retains_a_committed_train_the_table_dropped(self):
        with mock.patch.object(net, "get_text", return_value=_page()):
            checkpoint.import_checkpoint(self.root)
        dropped = [row for row in SECTION.split("<tr>") if "R81</td>" in row][0]
        with mock.patch.object(net, "get_text",
                               return_value=_page(SECTION.replace("<tr>" + dropped, "", 1))):
            detail = checkpoint.import_checkpoint(self.root)
        self.assertIn("retained 1", detail)
        record = json.loads((self.root / "products/checkpoint-security-gateway.json").read_text())
        retained = {release["id"]: release for release in record["releases"]}["r81"]
        self.assertIs(retained["upstream"]["in_source"], False)
        report = json.loads((self.root / checkpoint.REPORT).read_text())
        self.assertEqual(report["retained"][0]["id"], "r81")
        self.assertEqual(report["rows"]["published"], 17)
        self.assertEqual(report["rows"]["retained"], 1)
        validation.validate_data(self.root)


class RegistryIntegrationTests(CatalogRootCase):
    def save_checkpoint(self, verifier=None):
        releases, _ = parsed()
        record = checkpoint.record_for(releases, CHECKED)
        if verifier:
            record["provenance"]["verifier"] = verifier
        dump(self.root / "products/checkpoint-security-gateway.json", record)
        return record

    def test_validate_data_dispatches_to_the_owning_sources_validator(self):
        self.save_checkpoint()
        records = validation.validate_data(self.root)
        self.assertEqual(sorted(record["id"] for record in records),
                         ["checkpoint-security-gateway", "sample"])

    def test_validate_data_refuses_a_checkpoint_milestone_that_drifted(self):
        record = self.save_checkpoint()
        record["releases"][0]["milestones"]["eol"] = "2031-09"
        dump(self.root / "products/checkpoint-security-gateway.json", record)
        with self.assertRaisesRegex(ValueError, "contradicts its stored cells"):
            validation.validate_data(self.root)

    def test_sidecar_must_account_for_the_records_its_source_owns(self):
        self.save_checkpoint()
        dump(self.root / checkpoint.REPORT, {"verifier": checkpoint.VERIFIER, "total_records": 1})
        validation.validate_data(self.root)
        dump(self.root / checkpoint.REPORT, {"verifier": checkpoint.VERIFIER, "total_records": 2})
        with self.assertRaisesRegex(ValueError, "reports 2 records but 1 carry"):
            validation.validate_data(self.root)


class ImportPreservationTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        releases, _ = parsed()
        self.checkpoint = checkpoint.record_for(releases, CHECKED)
        catalog_root(self.root, [software_record(), self.checkpoint])
        self.bytes = (self.root / "products/checkpoint-security-gateway.json").read_bytes()

    def test_import_data_carries_a_foreign_software_record_through_untouched(self):
        listing = {"result": [{"name": "sample", "category": "lang"}], "total": 1}
        detail = {"result": {"name": "sample", "label": "Sample", "category": "lang",
                             "labels": {"eol": "Security Support"},
                             "releases": [{"name": "1", "eolFrom": "2028-01-01"}]},
                  "last_modified": None}

        def fetch(url):
            return listing if url == API else detail

        with mock.patch.object(importer, "fetch", side_effect=fetch):
            summary = importer.import_data(self.root)
        self.assertIn("imported 1 software products", summary)
        self.assertEqual((self.root / "products/checkpoint-security-gateway.json").read_bytes(),
                         self.bytes)
        manifest = json.loads((self.root / "manifest.json").read_text())
        self.assertEqual((manifest["product_count"], manifest["release_count"]), (1, 1))
        self.assertEqual(len(validation.validate_data(self.root)), 2)


if __name__ == "__main__":
    unittest.main()
