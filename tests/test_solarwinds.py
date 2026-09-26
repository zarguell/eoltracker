"""Regression tests for the SolarWinds release-history collector (#116, #117).

The saved pages in ``tests/fixtures/solarwinds-*.htm`` are the vendor's own
MadCap output, fetched from ``documentation.solarwinds.com`` on 2026-09-26.
They are the evidence every assertion below reads: no test reaches the network,
and none of them asserts a date the saved page does not state.
"""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from engine import solarwinds, sources
from engine.importer import dump, normalize

FIXTURES = Path(__file__).parent / "fixtures"
SITEMAP = (FIXTURES / "solarwinds-sitemap.xml").read_text(encoding="utf-8")
CHECKED = "2026-09-26T01:00:00Z"
FAMILIES = solarwinds.discover_families(SITEMAP)


def page(family):
    return (FIXTURES / f"solarwinds-{family}.htm").read_text(encoding="utf-8")


def released(family, version):
    """One release of one family page, as the vendor's own table states it."""
    _name, releases, _excluded, _duplicated = solarwinds.parse_history(
        page(family), FAMILIES[family], family)
    return next(release for release in releases if release["id"] == version)


def rows_of(family):
    """One family page as ``(name, releases, excluded, duplicated)``."""
    return solarwinds.parse_history(page(family), FAMILIES[family], family)


class DiscoveryTests(unittest.TestCase):
    def test_every_family_the_sitemap_states_is_keyed_by_its_own_path(self):
        # 33 release-history pages across 32 families: the Platform publishes
        # its own history and its observability sub-family, and SQL Sentry
        # publishes one history and one for Plan Explorer.
        self.assertEqual(len(FAMILIES), 32)
        self.assertIn("orionplatform-swo", FAMILIES)
        self.assertEqual(solarwinds.family_key(FAMILIES["sqlsentry-planexplorer"]),
                         "sqlsentry-planexplorer")
        self.assertEqual(solarwinds.family_key(FAMILIES["kct-legacy"]), "kct-legacy")

    def test_a_url_that_is_not_a_release_history_is_refused(self):
        with self.assertRaises(ValueError):
            solarwinds.family_key("https://documentation.solarwinds.com/en/success_center/"
                                  "ncm/content/release_notes/ncm_release_notes.htm")

    def test_a_sitemap_without_a_history_is_refused(self):
        with self.assertRaisesRegex(ValueError, "no release history"):
            solarwinds.discover_families("<urlset><loc>https://www.solarwinds.com/</loc></urlset>")


class DateTests(unittest.TestCase):
    def test_the_day_is_read_from_the_cell_and_its_sentence_is_not_part_of_it(self):
        # The NCM supported table states the day and then the vendor's own
        # sentence about the phase; the published milestone is the day.
        self.assertEqual(solarwinds.solarwinds_day(
            "July 9, 2027: End-of-Life (EoL) – SolarWinds will no longer provide technical support "
            "for NCM 2024.2.", "NCM"), "2027-07-09")

    def test_a_cell_that_states_no_date_is_absent_not_malformed(self):
        for cell in ("--", "N/A", "All", "-", ""):
            self.assertIsNone(solarwinds.solarwinds_day(cell, "row"))

    def test_a_date_the_calendar_does_not_have_is_refused(self):
        with self.assertRaisesRegex(ValueError, "not a real calendar day"):
            solarwinds.solarwinds_day("February 30, 2024", "row")

    def test_a_date_this_reader_does_not_know_is_refused_rather_than_guessed(self):
        # The SRM page's own typo sits in the announcement column, which is
        # never parsed; the same wording in a published column refuses.
        with self.assertRaisesRegex(ValueError, "unrecognized SolarWinds date"):
            solarwinds.solarwinds_day("February, 6, 2024", "row")
        with self.assertRaisesRegex(ValueError, "unrecognized SolarWinds date"):
            solarwinds.solarwinds_day("APril 1, 2025", "row")


class MappingTests(unittest.TestCase):
    def test_the_eol_effective_date_is_the_published_milestone_and_nothing_else_is(self):
        release = released("ncm", "2024.2")
        self.assertEqual(release["milestones"],
                         {"ga": None, "eos": None, "eossec": None, "eol": "2027-07-09"})
        # The engineering-end and announcement cells stay the vendor's own.
        self.assertIn("End-of-Engineering (EoE)", release["upstream"]["cells"]["eoe"])
        self.assertIn("End-of-Life (EoL) announcement",
                      release["upstream"]["cells"]["announcement"])

    def test_an_announced_end_of_engineering_never_becomes_a_security_support_end(self):
        # The negative case the mapping decision turns on: across every family
        # the vendor states a dated engineering-end cell, and eossec stays null
        # on every one of them, because SolarWinds never calls it a
        # security-support end.
        stated = 0
        for family in FAMILIES:
            _name, releases, _excluded, _duplicated = rows_of(family)
            for release in releases:
                self.assertIsNone(release["milestones"]["eossec"], family)
                self.assertIsNone(release["milestones"]["eos"], family)
                if solarwinds.solarwinds_day(release["upstream"]["cells"]["eoe"], "eoe"):
                    stated += 1
        self.assertGreater(stated, 100)

    def test_no_record_in_the_snapshot_is_derived(self):
        for family in FAMILIES:
            _name, releases, _excluded, _duplicated = rows_of(family)  # noqa: F841
            for release in releases:
                self.assertNotIn("milestone_provenance", release)
                self.assertIsNone(release["milestones"]["ga"])


class ShapeTests(unittest.TestCase):
    def test_a_page_with_no_supported_table_still_publishes_its_unsupported_rows(self):
        # SEM states no supported table at all: 22 unsupported rows, no refusal.
        _name, releases, excluded, _duplicated = rows_of("sem")
        self.assertEqual(len(releases), 22)
        self.assertEqual(excluded, [])

    def test_a_grouped_version_row_is_excluded_and_named_not_expanded(self):
        # Database Mapper's only row is the range "2020.1 - 2023.1".
        _name, releases, excluded, _duplicated = rows_of("databasemapper")
        self.assertEqual(releases, [])
        self.assertEqual(len(excluded), 1)
        self.assertIn("more than one release", excluded[0]["reason"])
        self.assertIn("2020.1 - 2023.1", excluded[0]["row"])

    def test_a_version_stated_by_both_tables_is_read_once(self):
        # The ETS Desktop page states 2023.1 in its supported and its
        # unsupported table, with the same dates in both.
        _name, releases, _excluded, duplicated = rows_of("ets-desk")
        ids = [release["id"] for release in releases]
        self.assertEqual(ids.count("2023.1"), 1)
        self.assertEqual([entry["row"] for entry in duplicated], ["2023.1"])

    def test_a_restatement_that_contradicts_the_first_statement_refuses_the_page(self):
        # The ETS Desktop page states 2023.1 in both tables. Move the terminal
        # date of its second statement and the two tables contradict each other.
        original = page("ets-desk")
        self.assertEqual(original.count("March 13, 2026"), 2)
        head, _, tail = original.partition("March 13, 2026")
        tampered = head + "March 13, 2026" + tail.replace("March 13, 2026", "March 14, 2026", 1)
        with self.assertRaisesRegex(ValueError, "contradicting values"):
            solarwinds.parse_history(tampered, FAMILIES["ets-desk"], "ets-desk")

    def test_a_renamed_column_refuses_the_page(self):
        tampered = page("ncm").replace("EoL&#160;effective date", "EoL&#160;date", 1)
        with self.assertRaisesRegex(ValueError, "unrecognized column"):
            solarwinds.parse_history(tampered, FAMILIES["ncm"], "ncm")

    def test_a_vendor_header_typo_is_the_vendors_own_wording_and_is_accepted(self):
        # Database Mapper heads its announcement column "EoL annoucement" and
        # IPAM heads its columns in the plural; both are real pages, so neither
        # refuses a spelling the vendor prints. Database Mapper's only row is a
        # range, so it publishes nothing — the header still has to read.
        _name, _releases, excluded, _duplicated = rows_of("databasemapper")
        self.assertEqual(len(excluded), 1)
        _name, releases, _excluded, _duplicated = rows_of("ipam")
        self.assertEqual(len(releases), 20)

    def test_a_table_of_another_scope_is_reported_rather_than_published(self):
        # The SQL Sentry page's bundle table keys on Product Bundle.
        _name, releases, excluded, _duplicated = rows_of("sqlsentry")
        self.assertEqual(len(releases), 17)
        self.assertEqual(len(excluded), 1)
        self.assertIn("product bundle", excluded[0]["reason"])

    def test_a_family_whose_page_states_no_table_publishes_no_record(self):
        # The Plan Explorer page names its version sections and states no
        # table under either.
        name, releases, excluded, _duplicated = rows_of("sqlsentry-planexplorer")  # noqa: F841
        self.assertEqual(name, "SolarWinds Plan Explorer")
        self.assertEqual(releases, [])
        self.assertEqual(len(excluded), 1)
        self.assertIn("no table", excluded[0]["reason"])

    def test_a_page_with_no_lifecycle_table_and_no_section_refuses(self):
        with self.assertRaisesRegex(ValueError, "no SolarWinds lifecycle table"):
            solarwinds.parse_history("<html><body><p>nothing here</p></body></html>",
                                     FAMILIES["ncm"], "ncm")

    def test_every_family_page_publishes_or_names_its_own_rows(self):
        for family in FAMILIES:
            _name, releases, excluded, duplicated = rows_of(family)
            rows = len(releases) + len(excluded) + len(duplicated)
            self.assertGreater(rows, 0, family)


class ValidatorTests(unittest.TestCase):
    def record(self, family="ncm"):
        name, releases, _excluded, _duplicated = rows_of(family)
        return solarwinds._record(f"solarwinds-{family}", name, releases, FAMILIES[family],
                                  solarwinds.HISTORY_VERIFIER, CHECKED,
                                  {"eol": solarwinds.EOL_LABEL})

    def test_a_published_record_re_derives_from_its_own_cells(self):
        solarwinds.validate_history(self.record())

    def test_a_record_whose_date_no_longer_follows_its_cells_is_refused(self):
        record = self.record()
        record["releases"][0]["milestones"]["eol"] = "2030-01-01"
        with self.assertRaisesRegex(ValueError, "contradicts its stored cells"):
            solarwinds.validate_history(record)

    def test_a_record_whose_row_loses_its_cells_is_refused(self):
        record = self.record()
        record["releases"][0]["upstream"]["cells"] = {}
        with self.assertRaisesRegex(ValueError, "carries no source cells"):
            solarwinds.validate_history(record)

    def test_a_record_whose_own_row_can_no_longer_be_read_is_refused(self):
        record = self.record()
        record["releases"][0]["upstream"]["cells"]["eol"] = "when the contract ends"
        with self.assertRaisesRegex(ValueError, "unrecognized SolarWinds date"):
            solarwinds.validate_history(record)

    def test_a_record_claiming_another_source_is_refused(self):
        record = self.record()
        record["provenance"]["verifier"] = "deterministic-openeuler"
        with self.assertRaisesRegex(ValueError, "source identity"):
            solarwinds.validate_history(record)

    def test_a_record_naming_another_column_for_its_eol_is_refused(self):
        record = self.record()
        record["labels"] = {"eol": "EoE effective date"}
        with self.assertRaisesRegex(ValueError, "column its eol is read from"):
            solarwinds.validate_history(record)


class PublicationTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        sibling = normalize({"result": {"name": "sample", "label": "Sample", "category": "lang",
                                        "labels": {},
                                        "releases": [{"name": "1", "releaseDate": "2026-01-01"}]}},
                            CHECKED)
        dump(self.root / "products/sample.json", sibling)
        dump(self.root / "manifest.json", {
            "generated_at": CHECKED, "source_url": sources.ENDOFLIFE_DATE_API,
            "source": "import-data", "product_count": 1, "release_count": 1,
            "excluded_hardware": []})

    def snapshot(self):
        return {str(path.relative_to(self.root)): path.read_bytes()
                for path in self.root.rglob("*.json")}

    def refresh(self, checked=CHECKED, pages=None):
        pages = pages or {solarwinds.SITEMAP_URL: SITEMAP,
                          **{url: page(family) for family, url in FAMILIES.items()}}
        with mock.patch.object(solarwinds, "net") as net, \
                mock.patch.object(solarwinds, "_now", return_value=checked):
            net.get_text.side_effect = lambda url: pages[url]
            return sources.source("import-solarwinds").run(self.root)

    def test_the_registered_source_publishes_one_record_per_family(self):
        detail = self.refresh()
        self.assertIn("product families", detail)
        published = sorted(path.stem for path in (self.root / "products").glob("solarwinds-*.json"))
        self.assertIn("solarwinds-ncm", published)
        self.assertIn("solarwinds-orionplatform-swo", published)
        # The two families whose pages state no publishable row publish no
        # record, and the report says so rather than leaving them silent.
        self.assertNotIn("solarwinds-databasemapper", published)
        self.assertNotIn("solarwinds-sqlsentry-planexplorer", published)
        record = json.loads((self.root / "products/solarwinds-ncm.json").read_text())
        solarwinds.validate_history(record)
        self.assertEqual(record["provenance"]["verifier"], solarwinds.HISTORY_VERIFIER)
        self.assertEqual(record["labels"], {"eol": "EoL effective date"})

    def test_the_report_accounts_for_every_source_row(self):
        self.refresh()
        report = json.loads((self.root / solarwinds.HISTORY_REPORT).read_text())
        rows = report["rows"]
        self.assertEqual(rows["seen"],
                         rows["published"] + rows["excluded"] + rows["duplicated"])
        self.assertEqual(sum(family["rows"]["published"] for family in report["families"]),
                         rows["published"])
        self.assertEqual(rows["families"], len(FAMILIES))
        self.assertEqual(report["total_records"], len(report["families"]) - 2)
        self.assertEqual(report["verifier"], solarwinds.HISTORY_VERIFIER)
        self.assertEqual(report["milestone_mapping"]["eol"], "EoL effective date")
        self.assertTrue(report["limitations"])

    def test_a_quiet_refresh_republishes_byte_identical_files(self):
        self.refresh()
        published = self.snapshot()
        self.refresh("2026-09-27T01:00:00Z")
        self.assertEqual(self.snapshot(), published)
        record = json.loads(published["products/solarwinds-ncm.json"])
        self.assertEqual(record["provenance"]["last_checked"], CHECKED)

    def test_a_changed_page_advances_the_revision(self):
        self.refresh()
        before = self.snapshot()
        pages = {solarwinds.SITEMAP_URL: SITEMAP,
                 **{url: page(family) for family, url in FAMILIES.items()}}
        pages[FAMILIES["ncm"]] = pages[FAMILIES["ncm"]].replace("July 9, 2027", "July 9, 2028", 1)
        self.refresh("2026-09-27T03:00:00Z", pages)
        after = self.snapshot()
        self.assertNotEqual(after, before)
        record = json.loads(after["products/solarwinds-ncm.json"])
        self.assertIn("2028-07-09", {release["milestones"]["eol"]
                                     for release in record["releases"]})

    def test_a_refused_page_leaves_every_committed_file_untouched(self):
        self.refresh()
        before = self.snapshot()
        pages = {solarwinds.SITEMAP_URL: SITEMAP,
                 **{url: page(family) for family, url in FAMILIES.items()}}
        pages[FAMILIES["ncm"]] = "<html><body>gone</body></html>"
        with self.assertRaises(ValueError):
            self.refresh("2026-09-27T02:00:00Z", pages)
        self.assertEqual(self.snapshot(), before)

    def test_a_committed_record_that_no_longer_derives_refuses_the_run_before_any_fetch(self):
        # A record this source owns but whose date no longer follows its own
        # cells is unpublishable, and the run aborts before the sitemap is read.
        self.refresh()
        tampered = json.loads((self.root / "products/solarwinds-ncm.json").read_text())
        tampered["releases"][0]["milestones"]["eol"] = "2030-01-01"
        dump(self.root / "products/solarwinds-ncm.json", tampered)
        with mock.patch.object(solarwinds.net, "get_text") as get_text:
            with self.assertRaisesRegex(ValueError, "contradicts its stored cells"):
                solarwinds.import_solarwinds(self.root)
        get_text.assert_not_called()


if __name__ == "__main__":
    unittest.main()
