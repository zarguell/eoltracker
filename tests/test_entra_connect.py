"""Regression tests for the Microsoft Entra Connect lifecycle collector.

The saved fixtures are real Microsoft Learn pages (``entra-connect-lifecycle``,
``entra-connect-version-history``, ``entra-connect-version-history-archive``), so
the inventory assertions are about what the vendor actually publishes, and the
refusal tests mutate those same pages. No test touches the network.
"""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from engine import derived, entra_connect
from engine.importer import API, dump, normalize

FIXTURES = Path(__file__).parent / "fixtures"
LIFECYCLE = FIXTURES / "entra-connect-lifecycle.html"
HISTORY = FIXTURES / "entra-connect-version-history.html"
ARCHIVE = FIXTURES / "entra-connect-version-history-archive.html"
CHECKED = "2026-09-23T01:00:00Z"


def fixture(path):
    return path.read_text(encoding="utf-8")


def pages():
    return fixture(LIFECYCLE), fixture(HISTORY), fixture(ARCHIVE)


def parse():
    return entra_connect.snapshot(*pages())


def table(data, name):
    return {release["id"]: release for release in data["releases"]
            if release["upstream"]["table"] == name}


class InventoryTests(unittest.TestCase):
    """What the three real pages publish, row for row."""

    def test_support_table_publishes_all_seventeen_supported_builds(self):
        supported = table(parse(), entra_connect.SUPPORT_TABLE)
        self.assertEqual(sorted(supported), [
            "2.3.2.0", "2.3.20.0", "2.3.6.0", "2.3.8.0", "2.4.129.0", "2.4.131.0",
            "2.4.18.0", "2.4.21.0", "2.4.27.0", "2.5.190.0", "2.5.3.0", "2.5.76.0",
            "2.5.79.0", "2.6.1.0", "2.6.3.0", "2.6.84.0", "2.6.91.0"])
        self.assertEqual(supported["2.3.2.0"]["milestones"],
                         {"ga": "2023-12-12", "eos": None, "eossec": None, "eol": "2025-04-30"})
        self.assertEqual(supported["2.5.76.0"]["milestones"],
                         {"ga": "2025-07-31", "eos": None, "eossec": None, "eol": "2026-09-01"})
        self.assertEqual(supported["2.6.84.0"]["milestones"],
                         {"ga": "2026-07-07", "eos": None, "eossec": None, "eol": "2027-09-16"})

    def test_current_build_has_empty_end_cell_so_eol_stays_absent(self):
        supported = table(parse(), entra_connect.SUPPORT_TABLE)
        self.assertEqual(supported["2.6.91.0"]["milestones"]["ga"], "2026-09-16")
        self.assertIsNone(supported["2.6.91.0"]["milestones"]["eol"])
        self.assertEqual(supported["2.6.91.0"]["upstream"]["cells"]["End of support date"], "")

    def test_support_cell_rationale_stays_raw_and_is_never_read_as_the_date(self):
        supported = table(parse(), entra_connect.SUPPORT_TABLE)
        cells = supported["2.5.79.0"]["upstream"]["cells"]
        self.assertEqual(cells["End of support date"],
                         "23 Oct 2026 (12 months after release of 2.5.190.0)")
        self.assertEqual(supported["2.5.79.0"]["milestones"]["eol"], "2026-10-23")

    def test_current_history_publishes_stated_ga_with_unknown_eol(self):
        history = table(parse(), entra_connect.HISTORY_TABLE)
        self.assertEqual(len(history), 23)
        self.assertEqual(history["2.2.8.0"]["milestones"],
                         {"ga": "2023-10-11", "eos": None, "eossec": None, "eol": None})
        self.assertEqual(history["2.0.3.0"]["milestones"]["ga"], "2021-07-20")

    def test_every_published_day_form_is_parsed_at_day_precision(self):
        data = parse()
        supported = table(data, entra_connect.SUPPORT_TABLE)
        # "1 Apr 2024"/"21 Feb 2024": day-first, spelled month.
        self.assertEqual(supported["2.3.8.0"]["milestones"]["ga"], "2024-04-01")
        self.assertEqual(supported["2.3.6.0"]["milestones"]["ga"], "2024-02-21")
        # "12/12/2023": US numeric form.
        self.assertEqual(supported["2.3.2.0"]["milestones"]["ga"], "2023-12-12")
        history = table(data, entra_connect.HISTORY_TABLE)
        # "6/19/2023": the same numeric form without zero padding.
        self.assertEqual(history["2.2.1.0"]["milestones"]["ga"], "2023-06-19")
        archive = table(data, entra_connect.ARCHIVE_TABLE)
        # "December 12th, 2017": month-first with an ordinal suffix.
        self.assertEqual(archive["1.1.654.0"]["milestones"]["ga"], "2017-12-12")

    def test_archive_keeps_month_precision_exactly(self):
        archive = table(parse(), entra_connect.ARCHIVE_TABLE)
        self.assertEqual(archive["1.1.524.0"]["milestones"]["ga"], "2017-05")
        self.assertEqual(archive["1.1.553.0"]["milestones"]["ga"], "2017-06")
        self.assertEqual(archive["1.0.419.0911"]["milestones"]["ga"], "2014-09")
        self.assertEqual(archive["1.1.524.0"]["upstream"]["cells"]["Status"], "Released: May 2017")

    def test_archive_parses_the_day_forms_too(self):
        archive = table(parse(), entra_connect.ARCHIVE_TABLE)
        self.assertEqual(archive["1.1.561.0"]["milestones"]["ga"], "2017-07-23")
        self.assertEqual(archive["1.1.654.0"]["milestones"]["ga"], "2017-12-12")
        self.assertEqual(archive["1.1.614.0"]["milestones"]["ga"], "2017-09-05")
        self.assertEqual(archive["1.1.649.0"]["milestones"]["ga"], "2017-10-27")
        self.assertEqual(archive["1.4.25.0"]["milestones"]["ga"], "2019-09-28")

    def test_archive_build_without_any_stated_date_keeps_ga_unknown(self):
        archive = table(parse(), entra_connect.ARCHIVE_TABLE)
        self.assertIsNone(archive["1.1.749.0"]["milestones"]["ga"])
        self.assertEqual(archive["1.1.749.0"]["upstream"]["cells"]["Status"],
                         "Status: Released to select customers")

    def test_no_archive_build_claims_an_end_of_support_date(self):
        archive = table(parse(), entra_connect.ARCHIVE_TABLE)
        self.assertEqual(len(archive), 55)
        self.assertTrue(all(release["milestones"]["eol"] is None for release in archive.values()))

    def test_lifecycle_family_rows_retain_support_start_without_labeling_ga(self):
        scopes = table(parse(), entra_connect.LIFECYCLE_TABLE)
        self.assertEqual(sorted(scopes), ["1.x", "2.x"])
        self.assertEqual(scopes["1.x"]["milestones"],
                         {"ga": None, "eos": None, "eossec": None, "eol": None})
        self.assertEqual(scopes["2.x"]["milestones"],
                         {"ga": None, "eos": None, "eossec": None, "eol": None})
        self.assertEqual(scopes["1.x"]["upstream"]["cells"]["Start Date"], "9/1/2014 8:00:00 AM")
        self.assertEqual(scopes["2.x"]["upstream"]["cells"]["Start Date"], "9/30/2021 8:00:00 AM")
        self.assertEqual(scopes["1.x"]["upstream"]["cells"]["End Date"], "9/1/2022 6:59:59 AM")

    def test_no_one_x_release_publishes_a_normalized_end_of_life(self):
        # The Lifecycle page's prose and its 1.x row disagree, so no 1.x record
        # carries an eol; the 2.x rows that state their own end dates still do.
        for release in parse()["releases"]:
            if release["id"].startswith("1.") or release["id"] == "1.x":
                self.assertIsNone(release["milestones"]["eol"], release["id"])

    def test_every_release_carries_its_own_source_cells_and_a_unique_id(self):
        data = parse()
        ids = [release["id"] for release in data["releases"]]
        self.assertEqual(len(ids), len(set(ids)))
        for release in data["releases"]:
            upstream = release["upstream"]
            self.assertIn(upstream["table"], entra_connect.PAGE_OF)
            self.assertEqual(upstream["name"], upstream["cells"]["Version"])
            self.assertEqual(release["name"], f"Microsoft Entra Connect {upstream['name']}")

    def test_health_is_never_published_as_an_alias(self):
        for release in parse()["releases"]:
            self.assertNotIn("health", release["id"].lower())
            self.assertNotIn("health", release["name"].lower())


class ConflictTests(unittest.TestCase):
    """The vendor's disagreements are published, not silently resolved."""

    def test_one_x_eol_stays_null_with_all_three_statements_retained(self):
        data = parse()
        conflict = data["conflicts"][0]
        self.assertEqual(conflict["scope"], "Version 1.x eol")
        self.assertIsNone(conflict["published"])
        self.assertEqual([statement["kind"] for statement in conflict["statements"]],
                         ["prose", "structured", "release prose"])
        self.assertEqual(conflict["statements"][0]["stated"], "2022-08-31")
        self.assertIn("August 31, 2022", conflict["statements"][0]["quote"])

    def test_pacific_end_instant_is_read_as_its_last_full_calendar_day(self):
        data = parse()
        structured = data["conflicts"][0]["statements"][1]
        # The vendor prints 9/1/2022 6:59:59 AM Pacific: the support it closes
        # covers the day before, which is the repository's convention.
        self.assertEqual(structured["value"], "9/1/2022 6:59:59 AM")
        self.assertEqual(structured["last_full_day"], "2022-08-31")

    def test_build_level_retirement_prose_is_retained_as_a_cell_not_a_milestone(self):
        data = parse()
        release = table(data, entra_connect.HISTORY_TABLE)["1.6.16.0"]
        notice = release["upstream"]["cells"][entra_connect.RETIREMENT_CELL]
        self.assertIn("was retired on August 31, 2022", notice)
        self.assertIsNone(release["milestones"]["eol"])
        self.assertEqual(data["conflicts"][0]["statements"][2]["stated"], "2022-08-31")
        self.assertEqual(data["conflicts"][0]["statements"][2]["release"], "1.6.16.0")

    def test_two_x_family_start_and_first_build_are_both_published(self):
        data = parse()
        conflict = data["conflicts"][1]
        self.assertEqual(conflict["scope"], "Version 2.x family start vs 2.0.3.0")
        statements = {statement["kind"]: statement for statement in conflict["statements"]}
        self.assertEqual(statements["family"]["stated"], "2021-09-30")
        self.assertEqual(statements["release"]["stated"], "2021-07-20")
        releases = {release["id"]: release for release in data["releases"]}
        self.assertIsNone(releases["2.x"]["milestones"]["ga"])
        self.assertEqual(releases["2.0.3.0"]["milestones"]["ga"], "2021-07-20")

    def test_a_changed_one_x_end_cell_is_reported_not_silently_taken(self):
        # The conflict's structured statement follows the page: changing the
        # cell changes the reported instant, and still publishes no 1.x eol.
        html = fixture(LIFECYCLE).replace("9/1/2022 6:59:59 AM", "9/1/2023 6:59:59 AM")
        data = entra_connect.snapshot(html, fixture(HISTORY), fixture(ARCHIVE))
        structured = data["conflicts"][0]["statements"][1]
        self.assertEqual(structured["value"], "9/1/2023 6:59:59 AM")
        self.assertEqual(structured["last_full_day"], "2023-08-31")
        for release in data["releases"]:
            if release["id"].startswith("1.") or release["id"] == "1.x":
                self.assertIsNone(release["milestones"]["eol"], release["id"])


class ExclusionTests(unittest.TestCase):
    """The withdrawn build is excluded, with the vendor's own sentence as reason."""

    def test_never_released_build_is_excluded_rather_than_dated(self):
        data = parse()
        self.assertEqual([entry["row"] for entry in data["excluded"]], ["1.1.558.0"])
        excluded = data["excluded"][0]
        self.assertIn("won't be released", excluded["cell"])
        self.assertIn("not a release of the product", excluded["reason"])
        self.assertEqual(excluded["page"], entra_connect.ARCHIVE_URL)
        self.assertNotIn("1.1.558.0", {release["id"] for release in data["releases"]})

    def test_accounting_reconciles_every_parsed_source_row(self):
        data = parse()
        report = entra_connect.report_for(data, data["releases"], [], CHECKED)
        rows = report["rows"]
        counted = sum(rows[key] for key in ("lifecycle_scopes", "lifecycle_listing",
                                            "support_table", "release_history", "archive"))
        self.assertEqual(rows["seen"], counted + rows["excluded"])
        self.assertEqual(rows["seen"], rows["fresh"] + rows["excluded"] + rows["duplicate_views"])
        self.assertEqual(rows["fresh"], len(data["releases"]))
        self.assertEqual(rows["support_table"], 17)
        self.assertEqual(rows["release_history"], 40)
        self.assertEqual(rows["archive"], 55)
        self.assertEqual(rows["lifecycle_scopes"], 2)
        self.assertEqual(rows["lifecycle_listing"], 1)
        self.assertEqual(rows["excluded"], 1)
        self.assertEqual(rows["duplicate_views"], 18)

    def test_milestone_counts_state_how_much_is_unknown(self):
        data = parse()
        report = entra_connect.report_for(data, data["releases"], [], CHECKED)
        self.assertEqual(report["milestones"]["ga_stated"], len(data["releases"]) - 3)
        self.assertEqual(report["milestones"]["ga_unknown"], 3)
        self.assertEqual(report["milestones"]["eol_stated"], 16)

    def test_report_publishes_the_vendors_rules_without_dating_from_them(self):
        data = parse()
        report = entra_connect.report_for(data, data["releases"], [], CHECKED)
        self.assertIn("12 months from the date that a newer version is released",
                      report["rules"]["retirement"]["quote"])
        self.assertIn("September 30, 2026", report["rules"]["synchronization_cutoff"]["quote"])
        self.assertEqual(report["total_records"], 1)
        self.assertEqual(report["verifier"], "deterministic-entra-connect")
        for release in data["releases"]:
            self.assertNotEqual(release["milestones"]["eol"], "2026-09-30")

    def test_duplicate_views_are_the_history_sections_and_the_listing_row(self):
        data = parse()
        self.assertEqual({entry["page"] for entry in data["duplicates"]},
                         {entra_connect.HISTORY_URL, entra_connect.LIFECYCLE_URL})
        # The 17 support-table builds are each also a history section, and the
        # Lifecycle listing row repeats the 1.x family start.
        self.assertEqual(sum(1 for entry in data["duplicates"]
                             if entry["page"] == entra_connect.HISTORY_URL), 17)
        self.assertEqual([entry["row"] for entry in data["duplicates"]
                          if entry["page"] == entra_connect.LIFECYCLE_URL],
                         ["Azure Active Directory (AD) Connect"])


class RefusalTests(unittest.TestCase):
    """A reshaped page fails the parse instead of yielding a guessed date."""

    def test_missing_lifecycle_table_refuses(self):
        html = fixture(LIFECYCLE).replace("Start Date", "Begin Date")
        with self.assertRaises(ValueError):
            entra_connect.parse_lifecycle(html)

    def test_reshaped_support_columns_refuse(self):
        html = fixture(HISTORY).replace("End of support date", "Support end")
        with self.assertRaises(ValueError):
            entra_connect.parse_support(html)

    def test_unrecognized_date_cell_refuses(self):
        html = fixture(ARCHIVE).replace("Released: May 2017", "Released: May, 2017")
        with self.assertRaises(ValueError):
            entra_connect.parse_sections(html, entra_connect.ARCHIVE_URL,
                                         entra_connect.ARCHIVE_TABLE, "Status")

    def test_wrong_page_identity_refuses(self):
        with self.assertRaises(ValueError):
            entra_connect.parse_support(fixture(ARCHIVE))
        with self.assertRaises(ValueError):
            entra_connect.parse_lifecycle(fixture(HISTORY))

    def test_missing_lifecycle_notice_refuses(self):
        html = fixture(LIFECYCLE).replace("will be retired because", "will retire because")
        with self.assertRaises(ValueError):
            entra_connect.parse_lifecycle(html)

    def test_an_unrecognized_start_instant_refuses(self):
        html = fixture(LIFECYCLE).replace("9/1/2014 8:00:00 AM", "9/1/2014 9:30:00 AM")
        with self.assertRaises(ValueError):
            entra_connect.parse_lifecycle(html)

    def test_a_build_section_without_a_status_line_refuses(self):
        html = fixture(ARCHIVE).replace("Status: July 2017", "Note: no status here", 1)
        with self.assertRaises(ValueError):
            entra_connect.parse_sections(html, entra_connect.ARCHIVE_URL,
                                         entra_connect.ARCHIVE_TABLE, "Status")

    def test_a_product_listing_row_that_states_a_date_refuses(self):
        # "In Support" is an open status, not a deadline; a dated retirement cell
        # is a different source shape and must be reviewed rather than mapped.
        html = fixture(LIFECYCLE).replace("In Support", "10/15/2031 6:59:59 AM")
        with self.assertRaises(ValueError):
            entra_connect.parse_lifecycle(html)


class CatalogHarness(unittest.TestCase):
    """A throwaway catalog with one sibling record, and a refresh of this source."""

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        sibling = normalize({"result": {"name": "sample", "label": "Sample", "category": "lang",
                                        "labels": {},
                                        "releases": [{"name": "1", "releaseDate": "2026-01-01"}]}},
                            "2026-09-17T00:00:00Z")
        dump(self.root / "products/sample.json", sibling)
        dump(self.root / "manifest.json", {
            "generated_at": "2026-09-17T00:00:00Z", "source_url": API,
            "source": "import-data", "product_count": 1, "release_count": 1,
            "excluded_hardware": []})

    def snapshot(self):
        return {str(path.relative_to(self.root)): path.read_bytes()
                for path in self.root.rglob("*.json")}

    def refresh(self, checked, lifecycle=None, history=None, archive=None):
        with mock.patch.object(entra_connect.net, "get_text",
                               side_effect=[lifecycle or fixture(LIFECYCLE),
                                            history or fixture(HISTORY),
                                            archive or fixture(ARCHIVE)]), \
                mock.patch.object(entra_connect, "datetime") as clock:
            clock.now.return_value.isoformat.return_value = checked
            return entra_connect.import_entra_connect(self.root)

    def record_path(self):
        return self.root / "products/microsoft-entra-connect.json"

    def record(self):
        return json.loads(self.record_path().read_text())

    def report(self):
        return json.loads((self.root / "entra-connect-import.json").read_text())

    def target(self, release_id, record=None):
        """The named release of the committed record, or of *record* when given."""
        return next(release for release in (record or self.record())["releases"]
                    if release["id"] == release_id)


class PublicationTests(CatalogHarness):
    def test_import_writes_the_expected_record_and_report(self):
        self.refresh(CHECKED)
        record = self.record()
        self.assertEqual(record["id"], "microsoft-entra-connect")
        self.assertEqual(record["provenance"]["verifier"], "deterministic-entra-connect")
        self.assertEqual(record["provenance"]["source_url"], entra_connect.LIFECYCLE_URL)
        self.assertEqual(record["labels"], {"ga": "Release date", "eol": "End of support date"})
        self.assertEqual(len(record["releases"]), 97)
        report = self.report()
        self.assertEqual(report["verifier"], record["provenance"]["verifier"])
        self.assertEqual(report["total_records"], 1)
        self.assertEqual(report["rows"]["seen"], report["rows"]["fresh"]
                         + report["rows"]["excluded"] + report["rows"]["duplicate_views"])

    def test_published_record_passes_the_real_catalog_validator(self):
        from engine.validation import validate_data
        self.refresh(CHECKED)
        records = validate_data(self.root)
        self.assertEqual([r["id"] for r in records if r["id"] == "microsoft-entra-connect"],
                         ["microsoft-entra-connect"])

    def test_quiet_refresh_preserves_product_and_report_bytes(self):
        self.refresh(CHECKED)
        published = self.snapshot()
        self.refresh("2026-09-23T02:00:00Z")
        self.assertEqual(self.snapshot(), published)

    def test_changing_only_the_excluded_row_advances_the_report(self):
        self.refresh(CHECKED)
        before = self.snapshot()
        archive = fixture(ARCHIVE).replace(
            "Changes in this build are included in version 1.1.561.0.",
            "Changes in this build were folded into version 1.1.561.0.")
        self.refresh("2026-09-23T03:00:00Z", archive=archive)
        after = self.snapshot()
        self.assertEqual(after["products/microsoft-entra-connect.json"],
                         before["products/microsoft-entra-connect.json"])
        self.assertNotEqual(after["entra-connect-import.json"],
                            before["entra-connect-import.json"])
        self.assertEqual(self.report()["excluded"][0]["cell"],
                         "Status: won't be released. Changes in this build were folded into "
                         "version 1.1.561.0.")

    def test_missing_build_is_retained_and_marked(self):
        self.refresh(CHECKED)
        history = fixture(HISTORY)
        start = history.index('<h2 id="2280">2.2.8.0</h2>')
        history = history[:start] + history[history.index('<h2 id="2210">'):]
        self.refresh("2026-09-23T04:00:00Z", history=history)
        kept = self.target("2.2.8.0")
        self.assertFalse(kept["upstream"]["in_source"])
        self.assertEqual(kept["milestones"]["ga"], "2023-10-11")
        report = self.report()
        self.assertEqual(report["rows"]["retained"], 1)
        self.assertEqual(report["retained"], [{"id": "2.2.8.0",
                                               "name": "Microsoft Entra Connect 2.2.8.0"}])

    def test_tampered_milestone_refuses_republication(self):
        self.refresh(CHECKED)
        record = self.record()
        self.target("2.5.79.0", record)["milestones"]["eol"] = "2099-01-01"
        dump(self.record_path(), record)
        before = self.snapshot()
        with self.assertRaises(ValueError):
            self.refresh("2026-09-23T05:00:00Z")
        self.assertEqual(self.snapshot(), before)

    def test_tampered_source_cell_refuses_republication(self):
        self.refresh(CHECKED)
        record = self.record()
        self.target("1.1.524.0", record)["upstream"]["cells"]["Status"] = "Released: April 2017"
        dump(self.record_path(), record)
        before = self.snapshot()
        with self.assertRaises(ValueError):
            self.refresh("2026-09-23T05:00:00Z")
        self.assertEqual(self.snapshot(), before)

    def test_foreign_record_refuses_import_before_any_network_call(self):
        sibling = json.loads((self.root / "products/sample.json").read_text())
        sibling["id"] = "microsoft-entra-connect"
        dump(self.record_path(), sibling)
        before = self.snapshot()
        with mock.patch.object(entra_connect.net, "get_text") as fetch:
            with self.assertRaises(ValueError) as caught:
                entra_connect.import_entra_connect(self.root)
        fetch.assert_not_called()
        self.assertIn("ownership collision", str(caught.exception))
        self.assertIn("deterministic-endoflife-date-v1", str(caught.exception))
        self.assertEqual(self.snapshot(), before)

    def test_parse_failure_leaves_the_committed_catalog_untouched(self):
        self.refresh(CHECKED)
        before = self.snapshot()
        with self.assertRaises(ValueError):
            self.refresh("2026-09-23T06:00:00Z",
                         history="<html><body><main><h1>Changed</h1></main></body></html>")
        self.assertEqual(self.snapshot(), before)

    def test_invalid_sibling_report_prevents_publication(self):
        dump(self.root / "vgpu-import.json", {"verifier": "deterministic-nvidia-vgpu",
                                              "total_records": 1})
        before = self.snapshot()
        with self.assertRaises(ValueError):
            self.refresh(CHECKED)
        self.assertEqual(self.snapshot(), before)


class DerivedDateTests(CatalogHarness):
    """A derived date this collector cannot re-derive is never republished."""

    def _derived(self, method):
        base = {"kind": "derived", "source_url": entra_connect.HISTORY_URL,
                "base_date": "2025-09-01", "base_label": "2.5.79.0 release date",
                "quote": ("Versions of Microsoft Entra Connect Sync 2.x retire 12 months from "
                          "the date that a newer version is released.")}
        if method == "release-plus-duration":
            return {**base, "method": method, "duration": {"value": 12, "unit": "month"}}
        return {**base, "method": method,
                "trigger": {"release_id": "2.6.91.0", "date": "2026-10-23",
                            "label": "2.6.91.0 release"}}

    def _publish_with(self, method):
        self.refresh(CHECKED)
        record = self.record()
        self.target("2.5.79.0", record)[derived.DERIVED_KEY] = {"eol": self._derived(method)}
        dump(self.record_path(), record)

    def test_derived_date_that_does_not_re_derive_is_refused(self):
        # 12 months from 2025-09-01 is 2026-09-01, not the vendor's 2026-10-23.
        self._publish_with("release-plus-duration")
        before = self.snapshot()
        with self.assertRaises(ValueError):
            self.refresh("2026-09-23T07:00:00Z")
        self.assertEqual(self.snapshot(), before)

    def test_coherent_derived_date_is_preserved_and_re_derived(self):
        self._publish_with("release-trigger")
        self.refresh("2026-09-23T08:00:00Z")
        kept = self.target("2.5.79.0")
        self.assertEqual(kept["milestones"]["eol"], "2026-10-23")
        self.assertEqual(kept[derived.DERIVED_KEY]["eol"]["method"], "release-trigger")

    def test_a_derived_entry_for_an_absent_milestone_is_refused(self):
        self._publish_with("release-trigger")
        record = self.record()
        self.target("2.5.79.0", record)["milestones"]["eol"] = None
        dump(self.record_path(), record)
        before = self.snapshot()
        with self.assertRaises(ValueError):
            self.refresh("2026-09-23T09:00:00Z")
        self.assertEqual(self.snapshot(), before)


if __name__ == "__main__":
    unittest.main()
