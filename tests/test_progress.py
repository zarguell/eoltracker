"""Regression tests for the Progress Software collectors (#127, #128, #129, #131).

The saved pages under ``tests/fixtures/progress-*.html`` are Progress's own
Zoomin and Sitefinity output, fetched 2026-09-26. They are the evidence every
assertion below reads: no test reaches the network, and none asserts a date the
saved page does not state.
"""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from engine import progress, sources
from engine.importer import dump, normalize

FIXTURES = Path(__file__).parent / "fixtures"
CHECKED = "2026-09-26T01:00:00Z"
PAGES = {
    progress.OPENEDGE_URL: "progress-openedge-life-cycle.html",
    progress.CORTICON_URL: "progress-corticon-life-cycle.html",
    progress.CORTICON_JS_URL: "progress-corticon-js-life-cycle.html",
    progress.WHATSUP_URL: "progress-whatsup-gold-life-cycle.html",
    progress.WHATSUP_POLICY_URL: "progress-whatsup-gold-eos-policy.html",
    progress.SITEFINITY_URL: "progress-sitefinity-lifecycle.html",
}


def page(url):
    return (FIXTURES / PAGES[url]).read_text(encoding="utf-8")


def release(records, release_id):
    return next(record for record in records if record["id"] == release_id)


class DateGrammarTests(unittest.TestCase):
    def test_a_day_a_month_and_the_named_form_are_three_widths_the_vendor_states(self):
        self.assertEqual(progress.progress_date("2028-Jan-01", "row"), "2028-01-01")
        self.assertEqual(progress.progress_date("2024-Jan", "row"), "2024-01")
        self.assertEqual(progress.progress_date("January 2024", "row", named=True), "2024-01")
        # Both month spellings the sibling pages use are the same month.
        self.assertEqual(progress.progress_date("2025-Nov", "row"), "2025-11")
        self.assertEqual(progress.progress_date("2025-April", "row"), "2025-04")

    def test_a_month_is_never_widened_into_a_day_or_narrowed_into_one(self):
        self.assertEqual(len(progress.progress_date("2024-Jan", "row")), 7)
        self.assertEqual(len(progress.progress_date("2028-Jan-01", "row")), 10)

    def test_a_day_the_calendar_does_not_have_is_refused(self):
        with self.assertRaisesRegex(ValueError, "not a real calendar day"):
            progress.progress_date("2028-Feb-31", "row")

    def test_a_month_word_the_vendor_does_not_use_is_refused(self):
        with self.assertRaisesRegex(ValueError, "not a month name"):
            progress.progress_date("2024-Smae", "row")

    def test_a_bare_year_is_not_a_date_this_schema_holds(self):
        with self.assertRaisesRegex(ValueError, "unrecognized Progress date"):
            progress.progress_date("2020", "row", named=True)


class OpenEdgeTests(unittest.TestCase):
    def parsed(self):
        return progress.parse_openedge(page(progress.OPENEDGE_URL))

    def test_all_four_tables_are_read_and_split_by_product_line(self):
        releases, _excluded, accounting = self.parsed()
        self.assertEqual(len(releases), 38)
        self.assertEqual({release["upstream"]["family"] for release in releases},
                         {"openedge", "openedge-pro2"})
        self.assertEqual(sum(table["rows"] for table in accounting["tables"]), 38)
        self.assertEqual([table["table"] for table in accounting["tables"]],
                         ["OpenEdge Product Life Cycle", "OpenEdge Pro2 Life Cycle",
                          "Retired OpenEdge Releases", "Retired OpenEdge Pro2 Releases"])

    def test_the_active_column_is_ga_and_the_retired_column_is_eol(self):
        releases, _excluded, _accounting = self.parsed()
        twelve_eight = release(releases, "OpenEdge 12.8 (LTS)")
        self.assertEqual(twelve_eight["milestones"],
                         {"ga": "2024-01", "eos": None, "eossec": None, "eol": "2030-01-31"})

    def test_month_and_day_precision_share_one_column_without_padding_either_way(self):
        releases, _excluded, _accounting = self.parsed()
        self.assertEqual(release(releases, "OpenEdge 12.8 (LTS)")["milestones"]["ga"],
                         "2024-01")
        self.assertEqual(release(releases, "OpenEdge 12.2 (LTS)")["milestones"]["eol"],
                         "2028-10-31")

    def test_an_unannounced_retirement_publishes_nothing_and_no_date_is_derived(self):
        releases, _excluded, _accounting = self.parsed()
        thirteen = release(releases, "OpenEdge 13.0")
        self.assertIsNone(thirteen["milestones"]["eol"])
        self.assertIn("TBD", thirteen["upstream"]["cells"]["Retired"])
        self.assertNotIn("milestone_provenance", thirteen)

    def test_the_sunset_phase_never_becomes_a_security_support_end(self):
        releases, _excluded, _accounting = self.parsed()
        for release_ in releases:
            self.assertIsNone(release_["milestones"]["eossec"])
        # The phase is still published as the vendor's own cell.
        self.assertEqual(release(releases, "OpenEdge 12.8 (LTS)")["upstream"]["cells"]["Sunset"],
                         "2028-Jan-01")

    def test_a_contingent_sunset_stays_a_cell_and_is_never_a_settled_date(self):
        releases, _excluded, _accounting = self.parsed()
        # The Pro2 page footnotes the Sunset column as contingent on the next
        # LTS release GA and "subject to revision", so the cell is carried and
        # no milestone is read from it.
        current = [release_ for release_ in releases
                   if release_["upstream"]["table"] == "OpenEdge Pro2 Life Cycle"]
        self.assertTrue(current)
        self.assertIn("2027-Jun-30", {release_["upstream"]["cells"]["Sunset*"]
                                      for release_ in current})
        for release_ in current:
            self.assertIsNone(release_["milestones"]["eossec"])
            self.assertIsNone(release_["milestones"]["eos"])

    def test_the_third_party_section_is_excluded_with_the_vendors_own_sentence(self):
        _releases, excluded, _accounting = self.parsed()
        third = [entry for entry in excluded if entry.get("context") == "third-party"]
        self.assertEqual(len(third), 1)
        self.assertIn("Progress resells third-party products", third[0]["quote"])

    def test_a_renamed_column_refuses_the_page(self):
        tampered = page(progress.OPENEDGE_URL).replace(">Retired<", ">End of life<", 1)
        with self.assertRaisesRegex(ValueError, "columns changed"):
            progress.parse_openedge(tampered)

    def test_a_footnote_the_vendor_dropped_refuses_the_page(self):
        anchor = "OpenEdge 13.0 will retire when the next OpenEdge release becomes"
        # The page states the trigger twice (a release note and the footnote);
        # the collector's guarantee is that it cannot read a TBD cell without
        # the sentence, so both statements have to go.
        tampered = page(progress.OPENEDGE_URL).replace(anchor, "OpenEdge 13.0 retires soon")
        with self.assertRaisesRegex(ValueError, "no longer states"):
            progress.parse_openedge(tampered)


class CorticonTests(unittest.TestCase):
    def test_both_pages_publish_and_the_layout_row_is_counted_not_parsed(self):
        for url, expected in ((progress.CORTICON_URL, 18), (progress.CORTICON_JS_URL, 10)):
            releases, accounting = progress.parse_corticon(page(url), url)
            self.assertEqual(len(releases), expected, url)
            self.assertEqual(accounting["layout"], 1, url)
            self.assertNotIn(progress.LAYOUT_LABELS[url],
                             {release["id"] for release in releases}, url)

    def test_the_js_page_prefixes_retired_rows_and_the_prefix_is_normalized(self):
        releases, _accounting = progress.parse_corticon(page(progress.CORTICON_JS_URL),
                                                        progress.CORTICON_JS_URL)
        self.assertIn("Corticon.js 2.3", {release["id"] for release in releases})
        raw = next(release_["upstream"]["cells"]["Product Release"] for release_ in releases
                   if release_["id"] == "Corticon.js 2.3")
        self.assertTrue(raw.strip().startswith("- "), raw)

    def test_both_month_spellings_read_and_an_unannounced_date_stays_null(self):
        current, _ = progress.parse_corticon(page(progress.CORTICON_JS_URL),
                                             progress.CORTICON_JS_URL)
        newest = release(current, "Corticon.js 2.4")
        self.assertEqual(newest["milestones"],
                         {"ga": "2025-11", "eos": None, "eossec": None, "eol": None})
        self.assertEqual(newest["upstream"]["cells"]["Retired"], "TBD")

    def test_a_page_that_loses_its_layout_row_refuses(self):
        tampered = page(progress.CORTICON_URL).replace(">RETIRED<", ">Current<", 1)
        with self.assertRaisesRegex(ValueError, "layout row"):
            progress.parse_corticon(tampered, progress.CORTICON_URL)


class WhatsUpTests(unittest.TestCase):
    def parsed(self):
        return progress.parse_whatsup(page(progress.WHATSUP_URL))

    def test_the_deprecated_tables_reversed_headers_are_read_by_label(self):
        releases, _excluded, _accounting = self.parsed()
        twenty_four = release(releases, "24.0")
        # The deprecated table prints 'Retired | Deprecated'; 24.0 is Retired
        # 2025-Jun and Deprecated 2026-Apr, and only Retired becomes eol.
        self.assertEqual(twenty_four["upstream"]["cells"]["Retired"], "2025-Jun")
        self.assertEqual(twenty_four["upstream"]["cells"]["Deprecated"], "2026-Apr")
        self.assertEqual(twenty_four["milestones"]["eol"], "2025-06")
        self.assertIsNone(twenty_four["milestones"]["ga"])

    def test_the_unannounced_next_release_publishes_no_retirement(self):
        releases, _excluded, _accounting = self.parsed()
        newest = release(releases, "26.0")
        self.assertEqual(newest["upstream"]["cells"]["Retired"], "Next-GA")
        self.assertIsNone(newest["milestones"]["eol"])

    def test_every_end_of_sale_offering_is_excluded_with_its_month_and_replacement(self):
        releases, excluded, accounting = self.parsed()
        offerings = [entry for entry in excluded if entry.get("context") == "offering"]
        self.assertEqual(len(offerings), 6)
        self.assertEqual(accounting["offerings"], 6)
        self.assertTrue(offerings)
        for entry in offerings:
            self.assertRegex(entry["eos"], r"^\d{4}-\d{2}$")
            self.assertIn("not a release", entry["reason"])
            self.assertTrue(entry["suggested_replacement"])

    def test_no_offering_date_ever_becomes_a_release_milestone(self):
        releases, _excluded, _accounting = self.parsed()
        for release_ in releases:
            self.assertIsNone(release_["milestones"]["eos"])


class SitefinityTests(unittest.TestCase):
    def parsed(self):
        return progress.parse_sitefinity(page(progress.SITEFINITY_URL))

    def test_a_grouped_row_expands_into_one_release_per_version_it_names(self):
        releases, _excluded, accounting = self.parsed()
        self.assertEqual(accounting["grouped_rows"], 2)
        ids = {release["id"] for release in releases}
        for version in ("14.1", "14.2", "14.3", "13.0", "13.1", "13.2"):
            self.assertIn(version, ids)
        grouped = next(release_ for release_ in releases if release_["id"] == "14.2")
        self.assertEqual(grouped["upstream"]["group"],
                         progress._fold(grouped["upstream"]["cells"]["Version"]))
        self.assertIn("14.3", grouped["upstream"]["group"])

    def test_a_floor_is_not_a_deadline(self):
        releases, _excluded, _accounting = self.parsed()
        newest = release(releases, "15.4")
        self.assertIsNone(newest["milestones"]["eol"])
        self.assertIn("No earlier than Jan 2030", newest["upstream"]["cells"]["Retired"])

    def test_a_stated_month_is_published_at_month_precision(self):
        releases, _excluded, _accounting = self.parsed()
        self.assertEqual(release(releases, "15.3")["milestones"],
                         {"ga": "2025-04", "eos": None, "eossec": None, "eol": "2026-11"})

    def test_a_year_or_a_month_window_states_a_date_the_schema_cannot_hold(self):
        releases, _excluded, accounting = self.parsed()
        shapes = {entry["shape"] for entry in accounting["not_representable"]}
        self.assertEqual(shapes, {"year", "month window"})
        for entry in accounting["not_representable"]:
            self.assertTrue(entry["reason"])
        # The grouped row whose Active is a window publishes no ga.
        self.assertIsNone(release(releases, "14.1")["milestones"]["ga"])

    def test_the_show_all_versions_control_row_is_accounted_for_not_published(self):
        releases, excluded, accounting = self.parsed()
        self.assertEqual(accounting["control"], 1)
        self.assertEqual([entry["context"] for entry in excluded], ["control"])
        self.assertNotIn("Show all versions", {release["id"] for release in releases})

    def test_the_derivation_helper_never_runs_as_part_of_the_refresh(self):
        # The vendor states a first-of-month rule; the collector publishes the
        # stated months, and the helper that would derive days is separate.
        releases, _excluded, _accounting = self.parsed()
        newest = release(releases, "15.3")
        page_text = progress.tables.parse_document(page(progress.SITEFINITY_URL)).page_text
        derived = progress.sitefinity_first_of_month(newest, page_text, phases=True)
        self.assertEqual(derived["derived"]["eol"], "2026-11-01")
        self.assertEqual(newest["milestones"]["eol"], "2026-11")
        self.assertNotIn("milestone_provenance", newest)

    def test_the_derivation_helper_refuses_without_the_vendors_rule(self):
        releases, _excluded, _accounting = self.parsed()
        with self.assertRaisesRegex(ValueError, "no longer states"):
            progress.sitefinity_first_of_month(release(releases, "15.3"), "the page text",
                                               phases=True)


class RecordTests(unittest.TestCase):
    def records(self, product_id, releases=None, checked=CHECKED, url=None, verifier=None,
                labels=None):
        builders = {
            "openedge": progress.openedge_record,
            "openedge-pro2": progress.openedge_pro2_record,
            "whatsup-gold": progress.whatsup_record,
        }
        if product_id == "sitefinity":
            return progress.sitefinity_record(releases or [], checked)
        if product_id in builders:
            return builders[product_id](releases or [], checked)
        return progress.corticon_records(releases or [], url or progress.CORTICON_URL, checked)

    def test_every_published_record_names_its_source_and_its_column(self):
        parsed, _excluded, _accounting = progress.parse_openedge(page(progress.OPENEDGE_URL))
        record = progress.openedge_record(
            [release_ for release_ in parsed if release_["upstream"]["family"] == "openedge"],
            CHECKED)
        progress.validate_openedge(record)
        self.assertEqual(record["labels"], {"ga": "Active", "eol": "Retired"})
        self.assertEqual(record["provenance"]["verifier"], progress.OPENEDGE_VERIFIER)
        self.assertEqual(record["provenance"]["source_url"], progress.OPENEDGE_URL)

    def test_a_record_whose_date_contradicts_its_cells_is_refused(self):
        parsed, _excluded, _accounting = progress.parse_openedge(page(progress.OPENEDGE_URL))
        record = progress.openedge_record(
            [release_ for release_ in parsed if release_["upstream"]["family"] == "openedge"],
            CHECKED)
        record["releases"][0]["milestones"]["eol"] = "2099-01-01"
        with self.assertRaisesRegex(ValueError, "contradict its stored"):
            progress.validate_openedge(record)

    def test_a_row_of_the_other_product_line_is_refused_in_this_record(self):
        parsed, _excluded, _accounting = progress.parse_openedge(page(progress.OPENEDGE_URL))
        record = progress.openedge_record(
            [release_ for release_ in parsed if release_["upstream"]["family"] == "openedge"],
            CHECKED)
        pro2 = next(release_ for release_ in parsed
                    if release_["upstream"]["family"] == "openedge-pro2")
        record["releases"].append(pro2)
        with self.assertRaisesRegex(ValueError, "belongs to openedge-pro2"):
            progress.validate_openedge(record)

    def test_every_source_publishes_the_records_its_registry_entry_names(self):
        for spec in progress.SPECS:
            source = sources.source(spec["id"])
            self.assertEqual(source.verifier, spec["verifier"])
            self.assertEqual(source.report, spec["report"])
            self.assertEqual(source.category, "software")
            self.assertTrue(hasattr(progress, spec["entry"]))


# The page each source reads first: breaking it has to stop that source before
# it writes anything.
LEADING_PAGE = {
    "import-progress-openedge": progress.OPENEDGE_URL,
    "import-progress-corticon": progress.CORTICON_URL,
    "import-progress-whatsup-gold": progress.WHATSUP_URL,
    "import-progress-sitefinity": progress.SITEFINITY_URL,
}


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

    def refresh(self, spec, checked=CHECKED, pages=None):
        pages = pages or {url: page(url) for url in PAGES}
        with mock.patch.object(progress, "net") as net, \
                mock.patch.object(progress, "_now", return_value=checked):
            net.get_text.side_effect = lambda url: pages[url]
            return sources.source(spec["id"]).run(self.root)

    def test_each_source_publishes_every_record_it_owns_and_one_report(self):
        for spec in progress.SPECS:
            with self.subTest(source=spec["id"]):
                self.setUp()
                detail = self.refresh(spec)
                self.assertTrue(detail)
                for product_id in spec["records"]:
                    self.assertTrue((self.root / "products" / f"{product_id}.json").is_file(),
                                    product_id)
                report = json.loads((self.root / spec["report"]).read_text())
                self.assertEqual(report["verifier"], spec["verifier"])
                self.assertEqual(report["total_records"], len(spec["records"]))
                self.assertTrue(report["limitations"])

    def test_a_quiet_refresh_republishes_byte_identical_files(self):
        for spec in progress.SPECS:
            with self.subTest(source=spec["id"]):
                self.setUp()
                self.refresh(spec)
                published = self.snapshot()
                self.refresh(spec, "2026-09-27T01:00:00Z")
                self.assertEqual(self.snapshot(), published)
                record = json.loads(published[f"products/{spec['records'][0]}.json"])
                self.assertEqual(record["provenance"]["last_checked"], CHECKED)

    def test_a_refused_page_leaves_every_committed_file_untouched(self):
        for spec in progress.SPECS:
            with self.subTest(source=spec["id"]):
                self.setUp()
                self.refresh(spec)
                before = self.snapshot()
                pages = {url: page(url) for url in PAGES}
                pages[LEADING_PAGE[spec["id"]]] = "<html><body>gone</body></html>"
                with self.assertRaises(ValueError):
                    self.refresh(spec, "2026-09-27T02:00:00Z", pages)
                self.assertEqual(self.snapshot(), before)

    def test_the_report_accounts_for_every_row_the_page_states(self):
        self.refresh(progress.SPECS[0])
        report = json.loads((self.root / progress.SPECS[0]["report"]).read_text())
        rows = report["rows"]
        self.assertEqual(rows["seen"], rows["published"] + rows["excluded"])
        self.assertEqual(sum(table["rows"] for table in report["tables"]), rows["published"])


if __name__ == "__main__":
    unittest.main()
