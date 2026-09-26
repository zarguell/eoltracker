"""Regression tests for the WatchGuard lifecycle collector.

The page under ``tests/fixtures/watchguard-end-of-life-policy.html`` is
WatchGuard's own end-of-life policy page, fetched 2026-09-26. It is the evidence
every assertion reads: no test reaches the network, and none asserts a date the
saved page does not state.

The page has one property that shapes this collector: it renders each table's
column names as a line of page text above the table rather than as ``<th>``
cells, so the shape is declared in prose and read positionally. The tests below
pin that contract — the declaration is required, and a row width that disagrees
with it refuses rather than shifting a date.
"""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from engine import sources, watchguard
from engine.importer import dump

FIXTURE = Path(__file__).parent / "fixtures" / "watchguard-end-of-life-policy.html"
PAGE = FIXTURE.read_text(encoding="utf-8")
CHECKED = "2026-09-26T01:00:00Z"


def parsed():
    return watchguard.parse(PAGE)


def model(product):
    for entry in parsed()[0]:
        if entry["product"] == product:
            return entry
    raise AssertionError(f"{product} is not a product row on the saved page")


class DateTests(unittest.TestCase):
    def test_the_pages_own_day_spelling_is_read(self):
        self.assertEqual(watchguard.watchguard_day("01 Mar 2022", "row"), "2022-03-01")
        self.assertEqual(watchguard.watchguard_day("31 Dec 2018", "row"), "2018-12-31")

    def test_the_one_table_using_a_full_month_name_is_read_too(self):
        # The access-point table writes "01 July 2022" where the firewall tables
        # write "01 Jul 2022"; both are the vendor's own spelling of one day.
        self.assertEqual(watchguard.watchguard_day("01 July 2022", "row"), "2022-07-01")

    def test_a_footnote_marker_on_a_date_is_not_part_of_it(self):
        self.assertEqual(watchguard.watchguard_day("10 Jul 2020*", "row"), "2020-07-10")

    def test_an_empty_cell_states_no_date(self):
        self.assertIsNone(watchguard.watchguard_day("", "row"))
        self.assertIsNone(watchguard.watchguard_day("   ", "row"))

    def test_a_day_the_calendar_does_not_have_is_refused(self):
        with self.assertRaisesRegex(ValueError, "not a real calendar day"):
            watchguard.watchguard_day("31 Feb 2021", "row")

    def test_prose_in_a_date_cell_is_refused_rather_than_guessed(self):
        with self.assertRaisesRegex(ValueError, "unrecognized WatchGuard date"):
            watchguard.watchguard_day("Two years after the release date", "row")


class MappingTests(unittest.TestCase):
    def test_end_of_sale_is_orderability_and_end_of_life_is_terminal_support(self):
        entry = model("Firebox T15")
        self.assertEqual(entry["milestones"], {"ga": None, "eos": "2022-03-01",
                                               "eossec": None, "eol": "2027-03-01"})
        # Both vendor columns stay verbatim, so a reader can check the row.
        self.assertEqual(entry["upstream"]["End of Sale (EOS)"]["text"], "01 Mar 2022")
        self.assertEqual(entry["upstream"]["End of Life (EOL)"]["text"], "01 Mar 2027")

    def test_the_migration_path_is_never_a_milestone(self):
        self.assertIsNone(model("Firebox T15")["milestones"]["eossec"])
        self.assertIn("Firebox T115-W", model("Firebox T15")["upstream"]["Migration Path"]["text"])

    def test_no_date_is_derived_from_the_gap_between_the_two_columns(self):
        # WatchGuard says end-of-sale dates are "up to five years prior to product
        # EOL". Firebox T25-W is five years and three months apart, so a derived
        # end-of-sale date would be wrong; the page's own value is published.
        entry = model("Firebox T25-W")
        self.assertEqual(entry["milestones"]["eos"], "2026-04-01")
        self.assertEqual(entry["milestones"]["eol"], "2031-07-01")

    def test_ga_is_null_because_the_page_states_no_release_date(self):
        self.assertIsNone(model("Firebox T15")["milestones"]["ga"])

    def test_a_regional_qualifier_is_not_part_of_the_published_name(self):
        # The page writes "Firebox III - Outside Japan FB 4500, ..."; the model
        # name keeps the qualifier because the vendor put it there, and the
        # record is still one product row as WatchGuard states it.
        self.assertIn("Outside Japan", model("Firebox III - Outside Japan FB 4500, 2500, 1000, 700, 500")["product"])

    def test_two_products_that_slugify_alike_stay_two_records(self):
        identities = {watchguard._identity(entry) for entry in parsed()[0]}
        self.assertEqual(len(identities), len(parsed()[0]))
        plus = watchguard._identity(model("Firebox II+"))
        plain = watchguard._identity(model("Firebox II"))
        self.assertNotEqual(plus, plain)
        self.assertRegex(plus, r"^watchguard-firebox-ii-[0-9a-f]{8}$")


class ShapeTests(unittest.TestCase):
    def test_every_family_on_the_page_publishes_its_product_rows(self):
        _models, _excluded, seen = parsed()
        self.assertGreaterEqual(seen, 5)
        families = {entry["family"] for entry in parsed()[0]}
        for family in ("WatchGuard Firebox", "WatchGuard Access Points", "WatchGuard XCS",
                       "Datablink", "WatchGuard AuthPoint"):
            self.assertIn(family, families)

    def test_an_older_products_continuation_keeps_its_own_family(self):
        # The page reuses the heading "Older Products" under several families;
        # those rows belong to the family they continue, not to a family of
        # their own.
        families = {entry["family"] for entry in parsed()[0]}
        self.assertNotIn("Older Products", families)
        self.assertIn("WatchGuard Firebox", families)

    def test_a_table_of_a_different_width_is_reported_and_nothing_is_read(self):
        _models, excluded, _seen = parsed()
        widths = [entry for entry in excluded if "cells wide" in entry["reason"]]
        self.assertTrue(widths)
        for entry in widths:
            self.assertTrue(entry["reason"])

    def test_a_row_stating_availability_prose_publishes_no_milestone(self):
        models, excluded, _seen = parsed()
        # The prose rows live in the endpoint-security tables, whose five-column
        # shape this source reports whole rather than reading, and every table
        # entry carries the reason it was not read.
        self.assertTrue(excluded)
        for entry in excluded:
            self.assertTrue(entry["reason"])
            self.assertIn("cells wide", entry["reason"])
        for entry in models:
            for column in ("End of Sale (EOS)", "End of Life (EOL)"):
                self.assertRegex(entry["upstream"][column]["text"],
                                 r"^(\d{1,2} [A-Za-z]+ \d{4}\*?)?$")

    def test_the_definition_tables_are_not_product_rows(self):
        models, _excluded, _seen = parsed()
        self.assertNotIn("End-of-Sale Date", {entry["product"] for entry in models})

    def test_a_page_that_drops_its_column_declaration_refuses(self):
        # The page declares the columns above every product table, so removing
        # every declaration leaves a page whose shape is no longer stated.
        # The declaration is checked against the page's folded text, so the
        # tamper is made in the markup the same way the vendor prints it.
        tampered = PAGE.replace("Migration Path", "Replacement Path")
        self.assertNotIn("Migration Path", tampered)
        with self.assertRaisesRegex(ValueError, "no longer states its product columns"):
            watchguard.parse(tampered)

    def test_a_table_whose_rows_change_width_refuses_to_be_read(self):
        # A column dropped from the firewall table would otherwise shift every
        # date one cell left; the width check refuses instead.
        tampered = PAGE.replace(
            "<td class=\"table-cell\">01 Mar 2027</td>", "<td class=\"table-cell\"></td>", 1)
        _models, excluded, _seen = watchguard.parse(tampered)
        self.assertTrue(any("cells wide" in entry["reason"] for entry in excluded))


class RecordTests(unittest.TestCase):
    def test_a_published_record_names_its_source_and_its_columns(self):
        record = watchguard.record_for(model("Firebox T15"), CHECKED)
        self.assertEqual(record["vendor"], "WatchGuard")
        self.assertEqual(record["category"], "hardware")
        self.assertEqual(record["provenance"]["verifier"], watchguard.VERIFIER)
        self.assertEqual(record["provenance"]["source_urls"], [watchguard.SOURCE_URL])
        self.assertEqual(record["milestones"]["eol"], "2027-03-01")

    def test_a_past_deadline_reads_as_end_of_life_and_a_future_one_as_expiring(self):
        # Firebox T10-D reached its end of life on 01 Nov 2024; Firebox T15 reaches
        # its own on 01 Mar 2027. Both dates are the page's, and the status is
        # the catalog's vocabulary applied to them rather than a vendor claim.
        past = watchguard.record_for(model("Firebox T10-D"), CHECKED)
        self.assertEqual(past["milestones"]["eol"], "2024-11-01")
        self.assertEqual(past["status"], "eol")
        future = watchguard.record_for(model("Firebox T15"), CHECKED)
        self.assertEqual(future["milestones"]["eol"], "2027-03-01")
        self.assertEqual(future["status"], "expiring")

    def test_the_report_accounts_for_every_row_the_page_states(self):
        models, excluded, seen = watchguard.parse(PAGE)
        report = watchguard.report_for(models, excluded, seen, CHECKED)
        self.assertEqual(report["rows"]["seen"], len(models) + len(excluded))
        self.assertEqual(report["rows"]["published"], len(models))
        self.assertEqual(report["rows"]["tables"], seen)
        self.assertEqual(report["total_records"], len(models))
        self.assertEqual(report["verifier"], watchguard.VERIFIER)
        self.assertTrue(report["limitations"])


class PublicationTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        (self.root / "hardware").mkdir()
        dump(self.root / "manifest.json", {"generated_at": CHECKED, "source_url": "x",
                                           "source": "import-data", "product_count": 1,
                                           "release_count": 1, "excluded_hardware": [],
                                           "hardware_count": 0})

    def snapshot(self):
        return {str(path.relative_to(self.root)): path.read_bytes()
                for path in self.root.rglob("*.json")}

    def refresh(self, checked=CHECKED):
        with mock.patch.object(watchguard, "net") as net, \
                mock.patch.object(watchguard, "_now", return_value=checked):
            net.get_text.return_value = PAGE
            return sources.source("import-watchguard").run(self.root)

    def test_the_registered_source_publishes_its_records_and_one_report(self):
        detail = self.refresh()
        self.assertIn("WatchGuard products", detail)
        published = sorted(path.stem for path in (self.root / "hardware").glob("watchguard-*.json"))
        self.assertEqual(len(published), 170)
        report = json.loads((self.root / watchguard.REPORT).read_text())
        self.assertEqual(report["total_records"], len(published))
        record = json.loads((self.root / "hardware" / (published[0] + ".json")).read_text())
        self.assertEqual(record["provenance"]["verifier"], watchguard.VERIFIER)

    def test_a_quiet_refresh_republishes_byte_identical_files(self):
        self.refresh()
        published = self.snapshot()
        self.refresh("2026-09-27T01:00:00Z")
        self.assertEqual(self.snapshot(), published)
        first = sorted(path for path in published if path.startswith("hardware/watchguard-"))[0]
        record = json.loads(published[first])
        self.assertEqual(record["provenance"]["last_checked"], CHECKED)

    def test_a_refused_page_writes_nothing(self):
        with mock.patch.object(watchguard, "net") as net, \
                mock.patch.object(watchguard, "_now", return_value=CHECKED):
            net.get_text.return_value = "<html><body>gone</body></html>"
            with self.assertRaises(ValueError):
                watchguard.import_watchguard(self.root)
        self.assertEqual(self.snapshot(), {"manifest.json": self.snapshot()["manifest.json"]})


if __name__ == "__main__":
    unittest.main()
