"""Regression tests for the GitHub Enterprise Server collector and its registry entry.

The fixture is the vendor page's own Markdown rendering (the tables the refresh
parses), so these tests pin the parse against the real source: every lifecycle
row is accounted for, only the two dates the table states become milestones, a
day-precision date never loses its day, the closing down date is never derived
from a release cadence or a fixed support window, and the legacy row that states
no dates stays in the inventory with null milestones. They also pin the two
ownership rules the shared catalog depends on — this source writes only its own
record, and import-data carries foreign software records through untouched.
"""
import json
import re
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from engine import ghes, importer, net, sources, validation
from engine.importer import API, dump, normalize

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/ghes-all-releases.md"
MARKDOWN = FIXTURE.read_text(encoding="utf-8")
CHECKED = "2026-09-17T12:00:00Z"
DAY = re.compile(r"\d{4}-\d{2}-\d{2}$")


def parsed():
    return ghes.parse_releases(MARKDOWN)


def software_record(name="sample", verifier=sources.source("import-data").verifier):
    record = normalize({"result": {"name": name, "label": name.title(), "category": "lang",
                                   "labels": {"eol": "Security Support"},
                                   "releases": [{"name": "1", "eolFrom": "2028-01-01"}]}}, CHECKED)
    record["provenance"]["verifier"] = verifier
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


class ParseTests(unittest.TestCase):

    def test_the_real_fixture_accounts_for_every_row_of_the_page(self):
        releases, excluded, duplicated = parsed()
        # The releases table's rows, the developer table's restatements of the
        # older lines, and the tool-version tables' rows are all accounted for.
        self.assertEqual(len(releases), 47)
        self.assertEqual([entry["row"] for entry in duplicated],
                         ["2.16", "2.15", "2.14", "2.13", "2.12", "2.11", "2.10",
                          "2.9", "2.8", "2.7", "2.6", "2.5", "2.4", "2.3", "2.2", "2.1",
                          "2.0", "11.10.340"])
        self.assertEqual(len(excluded), 28)
        self.assertEqual({entry["table"] for entry in excluded},
                         {"Recommended CodeQL CLI versions for code scanning",
                          "Minimum GitHub Actions Runner application versions"})
        self.assertEqual(len(releases) + len(duplicated) + len(excluded), 93)

    def test_current_and_historical_release_lines_are_both_published(self):
        releases, _, _ = parsed()
        ids = {release["id"] for release in releases}
        # Current, announced, and the historical lines back to 2.0 and the
        # legacy 11.10.340 row.
        for version in ("3.22", "3.21", "3.20", "3.17", "3.0", "2.22", "2.0", "11.10.340"):
            self.assertIn(version, ids)

    def test_the_stated_columns_become_ga_and_eol_at_the_published_precision(self):
        releases, _, _ = parsed()
        stored = {release["id"]: release["milestones"] for release in releases}
        self.assertEqual(stored["3.22"], {"ga": "2026-09-08", "eos": None, "eossec": None,
                                          "eol": "2027-09-08"})
        self.assertEqual(stored["3.17"], {"ga": "2025-06-03", "eos": None, "eossec": None,
                                          "eol": "2026-09-22"})
        self.assertEqual(stored["3.16"]["eol"], "2026-07-01")
        self.assertEqual(stored["3.14"]["eol"], "2026-04-23")
        self.assertEqual(stored["2.0"]["eol"], "2016-02-09")
        for release in releases:
            for field, value in release["milestones"].items():
                if value is not None:
                    self.assertRegex(value, DAY, f"{release['id']} {field}")

    def test_no_milestone_is_derived_from_the_four_release_policy(self):
        # 3.17's closing down date is 2026-09-22, not one year after its
        # 2025-06-03 release; 3.14 and 3.15 share 2026-04-23. A parser applying
        # a support duration would contradict the vendor's own column.
        releases, _, _ = parsed()
        stored = {release["id"]: release["milestones"] for release in releases}
        self.assertNotEqual(stored["3.17"]["eol"], "2026-06-03")
        self.assertEqual(stored["3.15"]["eol"], stored["3.14"]["eol"])

    def test_a_row_that_states_no_dates_keeps_null_milestones_and_stays_in_the_inventory(self):
        releases, excluded, duplicated = parsed()
        legacy = {release["id"]: release for release in releases}["11.10.340"]
        self.assertEqual(legacy["milestones"],
                         {"ga": None, "eos": None, "eossec": None, "eol": None})
        self.assertEqual(legacy["upstream"]["cells"]["Version"], "11.10.340")
        # It is published, never reported as excluded for the missing dates.
        self.assertNotIn("11.10.340", [entry["row"] for entry in excluded])

    def test_the_developer_table_restates_release_lines_rather_than_adding_them(self):
        # The older lines appear in both lifecycle tables; the row is read once
        # and the restatement is accounted under `duplicated`, not dropped.
        releases, _, duplicated = parsed()
        ids = [release["id"] for release in releases]
        self.assertEqual(ids.count("2.16"), 1)
        self.assertEqual([entry["table"] for entry in duplicated][1],
                         "Developer documentation that is closing down")
        # A restatement is accounted, not published a second time.
        self.assertEqual([entry["row"] for entry in duplicated][:2], ["2.16", "2.15"])

    def test_a_contradicting_restatement_refuses_the_parse(self):
        markdown = MARKDOWN.replace("| 2.16      | 2018-12-25 | 2019-01-22 | 2020-01-22        |",
                                    "| 2.16      | 2018-12-25 | 2019-01-22 | 2021-01-22        |", 1)
        with self.assertRaisesRegex(ValueError, "stated twice with contradicting values"):
            ghes.parse_releases(markdown)

    def test_the_vendors_support_wording_is_stored_verbatim_and_never_a_milestone(self):
        releases, _, _ = parsed()
        stored = {release["id"]: release for release in releases}
        self.assertEqual(stored["3.22"]["upstream"]["cells"]["Supported"], "Supported")
        self.assertEqual(stored["3.16"]["upstream"]["cells"]["Supported"], "Not supported")
        # Both supported and unsupported lines keep their published dates; the
        # support wording is never read as a date.
        self.assertEqual(stored["3.16"]["milestones"]["eol"], "2026-07-01")
        self.assertNotIn("Supported", stored["3.16"]["milestones"])

    def test_an_unrecognized_support_cell_refuses_the_parse(self):
        markdown = MARKDOWN.replace('aria-label="Supported"', 'aria-label="Probably fine"', 1)
        with self.assertRaisesRegex(ValueError, "unrecognized Supported cell"):
            ghes.parse_releases(markdown)

    def test_day_value_accepts_only_a_day_and_never_pads_one(self):
        self.assertEqual(ghes.day_value("2027-09-08", "row"), "2027-09-08")
        self.assertIsNone(ghes.day_value("", "row"))
        for text in ("2027-09", "2027", "September 2027", "2027-9-8", "2027-02-30"):
            with self.assertRaisesRegex(ValueError, "unrecognized day-precision date"):
                ghes.day_value(text, "row")

    def test_reshaped_lifecycle_headers_refuse_the_parse(self):
        markdown = MARKDOWN.replace("| Closing down date |", "| End of life |", 1)
        with self.assertRaisesRegex(ValueError, "Missing GitHub Enterprise Server table"):
            ghes.parse_releases(markdown)

    def test_a_missing_releases_table_refuses_the_parse(self):
        markdown = MARKDOWN.split("## Recommended CodeQL")[0].replace(
            "## Releases of GitHub Enterprise Server", "## Something else", 1)
        with self.assertRaisesRegex(ValueError, "Missing GitHub Enterprise Server table"):
            ghes.parse_releases(markdown)

    def test_release_lines_are_ordered_by_the_published_release_date(self):
        releases, _, _ = parsed()
        ids = [release["id"] for release in releases]
        self.assertEqual(ids[:3], ["3.22", "3.21", "3.20"])
        self.assertEqual(ids[-3:], ["2.1", "2.0", "11.10.340"])
        # 11.10.340 states no release date (it shipped in 2015), so its version
        # number never pushes it above the dated lines.
        self.assertEqual(ids[-1], "11.10.340")
        self.assertLess(ids.index("3.22"), ids.index("11.10.340"))

    def test_parsing_twice_is_identical(self):
        self.assertEqual(parsed(), parsed())


class RecordTests(unittest.TestCase):
    def test_record_names_its_registered_source_and_publishes_no_identifier(self):
        releases, _, _ = parsed()
        record = ghes.record_for(releases, CHECKED)
        self.assertEqual(record["id"], "github-enterprise-server")
        self.assertEqual(record["category"], "software")
        self.assertEqual(record["provenance"]["verifier"], sources.source("import-ghes").verifier)
        self.assertEqual(record["provenance"]["source_url"], sources.GITHUB_GHES_RELEASES)
        self.assertEqual(record["links"]["html"], sources.GITHUB_GHES_RELEASES)
        # GitHub states no CPE for the appliance; none is invented.
        self.assertEqual(record["identifiers"], [])
        # The vendor wording each milestone was read from.
        self.assertEqual(record["labels"], {"ga": "Release", "eol": "Closing down date"})

    def test_validate_record_rederives_every_milestone_from_the_stored_cells(self):
        releases, _, _ = parsed()
        record = ghes.record_for(releases, CHECKED)
        ghes.validate_record(record)
        drifted = json.loads(json.dumps(record))
        drifted["releases"][0]["milestones"]["eol"] = "2029-09-08"
        with self.assertRaisesRegex(ValueError, "contradicts its stored cells"):
            ghes.validate_record(drifted)

    def test_validate_record_accepts_the_undated_legacy_line(self):
        releases, _, _ = parsed()
        record = ghes.record_for(releases, CHECKED)
        legacy = {release["id"]: release for release in record["releases"]}["11.10.340"]
        self.assertIsNone(legacy["milestones"]["eol"])
        ghes.validate_record(record)

    def test_validate_record_refuses_a_release_claiming_another_version_line(self):
        releases, _, _ = parsed()
        record = ghes.record_for(releases, CHECKED)
        record["releases"][0]["id"] = "9.99"
        with self.assertRaisesRegex(ValueError, "does not name its own version line"):
            ghes.validate_record(record)

    def test_validate_record_refuses_another_sources_verifier(self):
        releases, _, _ = parsed()
        record = ghes.record_for(releases, CHECKED)
        record["provenance"]["verifier"] = sources.source("import-data").verifier
        with self.assertRaisesRegex(ValueError, "Invalid GitHub Enterprise Server source identity"):
            ghes.validate_record(record)

    def test_a_release_line_the_table_no_longer_states_is_retained_not_deleted(self):
        releases, _, _ = parsed()
        committed = ghes.record_for(releases, CHECKED)
        fresh = [release for release in releases if release["id"] != "3.16"]
        combined, kept = ghes.combine_releases(fresh, committed)
        self.assertEqual([entry["id"] for entry in kept], ["3.16"])
        retained = {release["id"]: release for release in combined}["3.16"]
        self.assertIs(retained["upstream"]["in_source"], False)
        self.assertEqual(retained["milestones"]["eol"], "2026-07-01")
        ghes.validate_record(ghes.record_for(combined, CHECKED))

    def test_freshly_parsed_releases_carry_no_retention_marker(self):
        combined, kept = ghes.combine_releases(parsed()[0], None)
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

    def publish(self, markdown=MARKDOWN):
        releases, excluded, duplicated = ghes.parse_releases(markdown)
        record = ghes.record_for(releases, CHECKED)
        report = ghes.report_for(releases, excluded, duplicated, [], CHECKED)
        return ghes.publish_record(record, report, self.root)


class PublicationTests(CatalogRootCase):
    def test_publish_writes_only_its_own_record_and_report(self):
        self.publish()
        record = json.loads((self.root / "products/github-enterprise-server.json").read_text())
        self.assertEqual(record["id"], "github-enterprise-server")
        self.assertEqual((self.root / "products/sample.json").read_bytes(), self.sibling_bytes)
        report = json.loads((self.root / ghes.REPORT).read_text())
        self.assertEqual(report["total_records"], 1)
        self.assertEqual(report["rows"]["published"], 47)
        self.assertEqual(report["rows"]["undated"], 1)
        self.assertEqual(report["rows"]["duplicated"], 18)
        self.assertEqual(len(validation.validate_data(self.root)), 2)

    def test_report_accounts_for_every_row_it_saw(self):
        releases, excluded, duplicated = parsed()
        report = ghes.report_for(releases, excluded, duplicated, [], CHECKED)
        rows = report["rows"]
        self.assertEqual(rows["seen"], rows["published"] + rows["duplicated"] + rows["excluded"])
        self.assertEqual(rows["seen"], 93)
        self.assertEqual(rows["lifecycle"], rows["published"] + rows["duplicated"])
        self.assertTrue(any("Closing down date" in line for line in report["limitations"]))
        self.assertTrue(any("null milestones" in line for line in report["limitations"]))
        self.assertTrue(any("duplicated" in line for line in report["limitations"]))

    def test_republishing_an_unchanged_source_is_byte_identical(self):
        published = self.publish()
        before = (self.root / "products/github-enterprise-server.json").read_bytes()
        again = self.publish()
        self.assertEqual((self.root / "products/github-enterprise-server.json").read_bytes(), before)
        self.assertEqual(published["provenance"]["last_checked"],
                         again["provenance"]["last_checked"])
        self.assertEqual(again["provenance"]["last_checked"], CHECKED)

    def test_a_record_another_source_owns_is_never_overwritten(self):
        self.sibling["id"] = "github-enterprise-server"
        dump(self.root / "products/github-enterprise-server.json", self.sibling)
        with mock.patch.object(net, "get_text") as fetch:
            with self.assertRaisesRegex(ValueError, "ownership collision"):
                ghes.import_ghes(self.root)
        fetch.assert_not_called()
        self.assertEqual(json.loads((self.root / "products/github-enterprise-server.json")
                                    .read_text()), self.sibling)

    def test_a_parse_failure_writes_nothing(self):
        broken = MARKDOWN.replace("| Closing down date |", "| End of life |", 1)
        with mock.patch.object(net, "get_text", return_value=broken):
            with self.assertRaisesRegex(ValueError, "Missing GitHub Enterprise Server table"):
                ghes.import_ghes(self.root)
        self.assertEqual(sorted(path.name for path in (self.root / "products").glob("*.json")),
                         ["sample.json"])
        self.assertFalse((self.root / ghes.REPORT).exists())

    def test_import_publishes_the_record_and_its_registry_report(self):
        with mock.patch.object(net, "get_text", return_value=MARKDOWN) as fetch:
            detail = ghes.import_ghes(self.root)
        fetch.assert_called_once_with(ghes.MARKDOWN_URL)
        self.assertEqual(ghes.MARKDOWN_URL, sources.GITHUB_GHES_RELEASES + ".md")
        self.assertEqual((self.root / "products/sample.json").read_bytes(), self.sibling_bytes)
        self.assertIn("imported 47 GitHub Enterprise Server release lines", detail)
        self.assertIn(ghes.REPORT, detail)
        self.assertEqual(json.loads((self.root / ghes.REPORT).read_text())["verifier"],
                         ghes.VERIFIER)

    def test_import_retains_a_committed_line_the_table_dropped(self):
        with mock.patch.object(net, "get_text", return_value=MARKDOWN):
            ghes.import_ghes(self.root)
        dropped = [line for line in MARKDOWN.splitlines() if line.startswith("| 3.16 ")][0]
        with mock.patch.object(net, "get_text", return_value=MARKDOWN.replace(dropped + "\n", "")):
            detail = ghes.import_ghes(self.root)
        self.assertIn("retained 1", detail)
        record = json.loads((self.root / "products/github-enterprise-server.json").read_text())
        retained = {release["id"]: release for release in record["releases"]}["3.16"]
        self.assertIs(retained["upstream"]["in_source"], False)
        report = json.loads((self.root / ghes.REPORT).read_text())
        self.assertEqual(report["retained"][0]["id"], "3.16")
        # The retained line is accounted apart from the rows this fetch saw.
        self.assertEqual(report["rows"]["published"], 47)
        self.assertEqual(report["rows"]["retained"], 1)
        validation.validate_data(self.root)


class RegistryIntegrationTests(CatalogRootCase):
    def save_ghes(self, verifier=None):
        releases, _, _ = parsed()
        record = ghes.record_for(releases, CHECKED)
        if verifier:
            record["provenance"]["verifier"] = verifier
        dump(self.root / "products/github-enterprise-server.json", record)
        return record

    def test_validate_data_dispatches_to_the_owning_sources_validator(self):
        self.save_ghes()
        records = validation.validate_data(self.root)
        self.assertEqual(sorted(record["id"] for record in records),
                         ["github-enterprise-server", "sample"])

    def test_validate_data_refuses_a_ghes_milestone_that_drifted(self):
        record = self.save_ghes()
        record["releases"][0]["milestones"]["eol"] = "2029-09-08"
        dump(self.root / "products/github-enterprise-server.json", record)
        with self.assertRaisesRegex(ValueError, "contradicts its stored cells"):
            validation.validate_data(self.root)

    def test_sidecar_must_account_for_the_records_its_source_owns(self):
        self.save_ghes()
        dump(self.root / ghes.REPORT, {"verifier": ghes.VERIFIER, "total_records": 1})
        validation.validate_data(self.root)
        dump(self.root / ghes.REPORT, {"verifier": ghes.VERIFIER, "total_records": 2})
        with self.assertRaisesRegex(ValueError, "reports 2 records but 1 carry"):
            validation.validate_data(self.root)


class ImportPreservationTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        releases, _, _ = parsed()
        self.ghes = ghes.record_for(releases, CHECKED)
        catalog_root(self.root, [software_record(), self.ghes])
        self.bytes = (self.root / "products/github-enterprise-server.json").read_bytes()

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
        self.assertEqual((self.root / "products/github-enterprise-server.json").read_bytes(),
                         self.bytes)
        manifest = json.loads((self.root / "manifest.json").read_text())
        self.assertEqual((manifest["product_count"], manifest["release_count"]), (1, 1))
        self.assertEqual(len(validation.validate_data(self.root)), 2)


if __name__ == "__main__":
    unittest.main()
