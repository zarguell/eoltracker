"""Regression tests for the Palo Alto Networks hardware collector.

The page in ``tests/fixtures/paloalto-hardware-end-of-life-dates.html`` is Palo
Alto's own hardware end-of-life table, fetched 2026-09-26. No test reaches the
network, and none asserts a date the saved page does not state.

Two properties of the page shape these tests. It writes the same kind of day two
ways — "Mar 22, 2027" and "March 22nd, 2027" — so a reader that accepts only
one spelling loses half the table. And its ``Last Supported OS`` column can name
a window longer than the row's own end-of-life date, so a collector that quietly
used it to extend that date would be publishing a date the vendor never stated.
"""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from engine import paloalto, sources
from engine.importer import dump

FIXTURE = Path(__file__).parent / "fixtures" / "paloalto-hardware-end-of-life-dates.html"
PAGE = FIXTURE.read_text(encoding="utf-8")
CHECKED = "2026-09-26T01:00:00Z"


def parsed():
    return paloalto.parse(PAGE)


def product(line):
    for entry in parsed()[0]:
        if entry["line"] == line:
            return entry
    raise AssertionError(f"{line} is not a product row on the saved page")


class DateTests(unittest.TestCase):
    def test_both_spellings_the_page_uses_are_read_as_the_same_kind_of_day(self):
        self.assertEqual(paloalto.paloalto_day("Mar 22, 2027", "row"), "2027-03-22")
        self.assertEqual(paloalto.paloalto_day("March 22nd, 2027", "row"), "2027-03-22")
        self.assertEqual(paloalto.paloalto_day("August 1st, 2029", "row"), "2029-08-01")

    def test_the_past_marker_is_removed_to_read_the_day(self):
        self.assertEqual(paloalto.paloalto_day("January 31, 2024 (EOL)", "row"), "2024-01-31")

    def test_a_cell_that_states_no_date_is_absent(self):
        for cell in ("", "-", "TBD", "N/A"):
            with self.subTest(cell=cell):
                self.assertIsNone(paloalto.paloalto_day(cell, "row"))

    def test_a_day_the_calendar_does_not_have_is_refused(self):
        with self.assertRaisesRegex(paloalto.DateError, "not a real calendar day"):
            paloalto.paloalto_day("Feb 30, 2027", "row")

    def test_a_spelling_the_page_does_not_use_is_refused(self):
        with self.assertRaisesRegex(paloalto.DateError, "unrecognized Palo Alto date"):
            paloalto.paloalto_day("Q3 2027", "row")


class MappingTests(unittest.TestCase):
    def test_the_two_dated_columns_become_eos_and_eol_in_the_vendors_headings(self):
        entry = product("PAN-PA-410")
        self.assertEqual(entry["milestones"], {"ga": None, "eos": "2027-03-22",
                                               "eossec": None, "eol": "2032-03-21"})

    def test_nothing_is_derived_from_the_gap_between_the_two_dates(self):
        entry = product("PA-7000 Series")
        self.assertEqual(entry["milestones"]["eos"], "2025-12-31")
        self.assertEqual(entry["milestones"]["eol"], "2030-12-31")

    def test_the_last_supported_os_column_never_extends_the_end_of_life_date(self):
        # Ten rows name an OS window later than their own end-of-life date. The
        # vendor states both; the record publishes the vendor's date and flags
        # the row rather than recomputing one from the other.
        flagged = [entry for entry in parsed()[0] if entry["os_exceeds_eol"]]
        self.assertTrue(flagged)
        for entry in flagged:
            self.assertIsNotNone(entry["milestones"]["eol"])
        record = paloalto.record_for(flagged[0], CHECKED)
        self.assertIn("Last Supported OS note", record["upstream"])
        self.assertIn("neither is recomputed", record["upstream"]["Last Supported OS note"]["note"])

    def test_ga_and_eossec_are_null_because_the_table_states_neither(self):
        for entry in parsed()[0]:
            self.assertIsNone(entry["milestones"]["ga"], entry["line"])
            self.assertIsNone(entry["milestones"]["eossec"], entry["line"])

    def test_every_published_date_is_a_real_day(self):
        import re
        for entry in parsed()[0]:
            for value in entry["milestones"].values():
                if value:
                    self.assertRegex(value, r"^\d{4}-\d{2}-\d{2}$", entry["line"])


class RowModelTests(unittest.TestCase):
    def test_one_record_is_one_product_line_and_lists_its_skus(self):
        entry = product("PA-7000 Series")
        # The line, then the parenthesised SKU list the vendor wraps under it.
        self.assertEqual(entry["members"][0], "PA-7000 Series")
        self.assertTrue(any(line.startswith("(PAN-PA-7000-100G-NPC-A") for line in entry["members"]))
        record = paloalto.record_for(entry, CHECKED)
        self.assertEqual(record["name"], "PA-7000 Series")
        self.assertIn("PAN-PA-7050-AC-SYS", record["model_number"])
        self.assertEqual(record["id"], "paloalto-pa-7000-series")

    def test_a_row_of_accessory_parts_is_still_one_line(self):
        entry = product("PAN-QSFP-40GBASE-LM4")
        self.assertEqual(entry["members"], ["PAN-QSFP-40GBASE-LM4"])

    def test_the_whole_table_is_published_with_nothing_dropped(self):
        products, excluded, seen = parsed()
        self.assertEqual(len(products), 34)
        self.assertEqual(excluded, [])
        self.assertEqual(seen, 1)
        self.assertEqual(len({paloalto._identity(entry["line"]) for entry in products}), 34)

    def test_the_past_marker_survives_in_the_published_cell(self):
        # A row whose dates have already passed carries the vendor's (EOL)
        # marker. It is removed to read the day and kept in the cell verbatim.
        past = next(entry for entry in parsed()[0]
                    if "(EOL)" in entry["cells"]["End-of-Life Date"]["text"])
        record = paloalto.record_for(past, CHECKED)
        self.assertIn("(EOL)", record["upstream"]["End-of-Life Date"]["text"])
        self.assertNotIn("(EOL)", record["milestones"]["eol"])


class ShapeTests(unittest.TestCase):
    def test_an_empty_document_is_a_fetch_refusal_not_an_empty_table(self):
        with self.assertRaisesRegex(ValueError, "empty document"):
            paloalto.parse("")

    def test_a_renamed_column_refuses_the_page(self):
        tampered = PAGE.replace(">End-of-Life Date<", ">End-of-Life<", 1)
        with self.assertRaisesRegex(ValueError, "columns changed"):
            paloalto.parse(tampered)

    def test_an_unexpected_second_table_refuses_the_page(self):
        extra = PAGE.replace("</body>", "<table><tr><th>Other</th></tr>"
                                          "<tr><td>row</td></tr></table></body>")
        with self.assertRaisesRegex(ValueError, "headed tables where the page publishes one"):
            paloalto.parse(extra)

    def test_a_date_the_reader_does_not_know_refuses_the_row(self):
        tampered = PAGE.replace("Mar 22, 2027", "Sometime in 2027", 1)
        with self.assertRaisesRegex(paloalto.DateError, "unrecognized Palo Alto date"):
            paloalto.parse(tampered)


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

    def refresh(self, checked=CHECKED, page=PAGE):
        with mock.patch.object(paloalto, "net") as net, \
                mock.patch.object(paloalto, "_now", return_value=checked):
            net.get_text.return_value = page
            return sources.source("import-paloalto").run(self.root)

    def test_the_registered_source_publishes_its_records_and_one_report(self):
        detail = self.refresh()
        self.assertIn("Palo Alto hardware product lines", detail)
        published = sorted(path.stem for path in (self.root / "hardware").glob("paloalto-*.json"))
        self.assertEqual(len(published), 34)
        report = json.loads((self.root / paloalto.REPORT).read_text())
        self.assertEqual(report["total_records"], 34)
        self.assertEqual(report["rows"]["skus"], 80)
        record = json.loads((self.root / "hardware" / (published[0] + ".json")).read_text())
        self.assertEqual(record["provenance"]["verifier"], paloalto.VERIFIER)
        self.assertEqual(record["vendor"], "Palo Alto Networks")

    def test_a_quiet_refresh_republishes_byte_identical_files(self):
        self.refresh()
        published = self.snapshot()
        self.refresh("2026-09-27T01:00:00Z")
        self.assertEqual(self.snapshot(), published)
        first = sorted(path for path in published if path.startswith("hardware/paloalto-"))[0]
        self.assertEqual(json.loads(published[first])["provenance"]["last_checked"], CHECKED)

    def test_a_refused_page_writes_nothing(self):
        for page in ("", "<html><body>gone</body></html>"):
            with self.subTest(page=page[:12]):
                with self.assertRaises(ValueError):
                    self.refresh("2026-09-27T02:00:00Z", page)
                self.assertEqual(set(self.snapshot()), {"manifest.json"})


if __name__ == "__main__":
    unittest.main()
