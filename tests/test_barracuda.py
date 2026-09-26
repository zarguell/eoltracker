"""Regression tests for the Barracuda firewall collector.

The page in ``tests/fixtures/barracuda-firewall-eos-eol.html`` is Barracuda's own
"NextGen and CloudGen Firewall Appliances - EoS / EoL Definitions" table,
fetched 2026-09-26. No test reaches the network, and none asserts a date the
saved page does not state.

Its rows are not uniform, and that is what these tests pin: a six-cell row opens
a model, a five-cell row is a *revision* of the model above it because the model
cell is row-spanned, a narrower row is a group label, `not set` is the vendor's
"no date" cell, and the EoFS cell ends with the last supporting firmware
version in parentheses.
"""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from engine import barracuda, sources
from engine.importer import dump

FIXTURE = Path(__file__).parent / "fixtures" / "barracuda-firewall-eos-eol.html"
PAGE = FIXTURE.read_text(encoding="utf-8")
CHECKED = "2026-09-26T01:00:00Z"


def parsed():
    return barracuda.parse(PAGE)


def product(label):
    for entry in parsed()[0]:
        if entry["label"] == label:
            return entry
    raise AssertionError(f"{label} is not a row on the saved page")


class DateTests(unittest.TestCase):
    def test_the_day_is_read_and_the_firmware_version_is_not_merged_into_it(self):
        self.assertEqual(barracuda.barracuda_day("2025-02-28 (2.0.10)", "row"), "2025-02-28")
        self.assertEqual(barracuda.barracuda_day("2021-05-31 (7.2.6 EoL)", "row"),
                         "2021-05-31")
        self.assertEqual(barracuda.barracuda_day("2022-02-28", "row"), "2022-02-28")

    def test_not_set_is_the_vendors_no_date_cell(self):
        for cell in ("not set", "not set ", "-", ""):
            with self.subTest(cell=cell):
                self.assertIsNone(barracuda.barracuda_day(cell, "row"))

    def test_a_day_the_calendar_does_not_have_is_refused(self):
        with self.assertRaisesRegex(barracuda.DateError, "not a real calendar day"):
            barracuda.barracuda_day("2021-02-30", "row")

    def test_a_wording_this_reader_does_not_know_is_refused(self):
        for cell in ("sometime in 2022", "31/03/2021", "2021 Q2"):
            with self.subTest(cell=cell):
                with self.assertRaises(barracuda.DateError):
                    barracuda.barracuda_day(cell, "row")


class RowModelTests(unittest.TestCase):
    def test_a_five_cell_row_is_a_revision_of_the_model_above_it(self):
        # The page row-spans the model cell, so a Rev. B row carries only the
        # revision, the part number and the dates.
        products = {entry["label"]: entry for entry in parsed()[0]}
        self.assertIn("F10 (EoL) Rev. A", products)
        self.assertIn("F10 (EoL) Rev. B", products)
        self.assertEqual(products["F10 (EoL) Rev. B"]["model"],
                         products["F10 (EoL) Rev. A"]["model"])
        self.assertEqual(products["F10 (EoL) Rev. B"]["revision"], "Rev. B")
        # The two revisions carry different dates, which is why they are two
        # records rather than one.
        self.assertNotEqual(products["F10 (EoL) Rev. A"]["milestones"]["eol"],
                            products["F10 (EoL) Rev. B"]["milestones"]["eol"])

    def test_a_multi_model_cell_stays_one_record_with_the_vendors_label(self):
        entry = product("SC22, SC23 (3G/UMTS) Rev. A")
        self.assertEqual(entry["milestones"], {"ga": None, "eos": "2022-02-28",
                                               "eossec": None, "eol": "2025-02-28"})

    def test_a_group_label_row_is_reported_not_read(self):
        products, excluded, _seen = parsed()
        self.assertTrue(excluded)
        for entry in excluded:
            self.assertIn("group label", entry["reason"])
        # A model with no dates still publishes a record, because the vendor
        # states the model and no date.
        undated = [entry for entry in products if entry["milestones"]["eol"] is None]
        self.assertTrue(undated)

    def test_the_two_columns_the_vendor_defines_become_eos_and_eol(self):
        entry = product("SC24, SC25 (4G/LTE, EMEA) Rev. A")
        self.assertEqual(entry["milestones"]["eos"], "2023-05-31")
        self.assertEqual(entry["milestones"]["eol"], "2026-05-31")
        self.assertIsNone(entry["milestones"]["ga"])
        self.assertIsNone(entry["milestones"]["eossec"])

    def test_no_two_rows_publish_as_one_record(self):
        products, _excluded, _seen = parsed()
        identities = [barracuda._identity(entry) for entry in products]
        self.assertEqual(len(set(identities)), len(identities))


class RecordTests(unittest.TestCase):
    def test_a_record_states_the_vendors_eof_nuance_rather_than_a_total_eol(self):
        record = barracuda.record_for(product("SC22, SC23 (3G/UMTS) Rev. A"), CHECKED)
        note = record["upstream"]["End of Firmware Support note"]["note"]
        self.assertIn("end of firmware support", note)
        self.assertIn("not completely End-of-Life", note)
        self.assertEqual(record["milestones"]["eol"], "2025-02-28")
        # The firmware version stays in the cell it was printed in.
        self.assertIn("2.0.10", record["upstream"]["EoFS (EoL: last supporting release)"]["text"])

    def test_status_comes_from_the_vendors_own_date(self):
        past = next(entry for entry in parsed()[0]
                    if entry["milestones"]["eol"] and entry["milestones"]["eol"] < "2026-09-26")
        self.assertEqual(barracuda.record_for(past, CHECKED)["status"], "eol")
        undated = barracuda.record_for(product("SC20, SC21 Rev. A"), CHECKED)
        self.assertEqual(undated["status"], "unknown")

    def test_the_report_accounts_for_the_page_and_names_the_unread_spaces(self):
        products, excluded, seen = parsed()
        report = barracuda.report_for(products, excluded, seen, CHECKED)
        rows = report["rows"]
        self.assertEqual(rows["seen"], len(products) + len(excluded))
        self.assertEqual(report["total_records"], len(products))
        self.assertEqual(rows["with_eol"],
                         sum(1 for p in products if p["milestones"]["eol"]))
        # The spaces this source does not read are named, not claimed.
        self.assertEqual({entry["space"] for entry in report["other_spaces"]},
                         set(barracuda.OTHER_SPACES))
        self.assertTrue(any("client-side" in line for line in report["limitations"]))


class ShapeTests(unittest.TestCase):
    def test_an_empty_document_is_a_fetch_refusal_not_an_empty_table(self):
        with self.assertRaisesRegex(ValueError, "empty document"):
            barracuda.parse("")

    def test_a_renamed_column_refuses_the_page(self):
        # The header text sits inside a paragraph and is printed with an
        # escaped ampersand; the reader sees the decoded label.
        self.assertIn(">EoS &amp; EoHS", PAGE)
        tampered = PAGE.replace(">EoS &amp; EoHS", ">End of sale", 1)
        with self.assertRaisesRegex(ValueError, "columns changed"):
            barracuda.parse(tampered)

    def test_a_date_the_reader_does_not_know_excludes_that_row_and_names_it(self):
        # One unreadable date cell on a fifty-row page should not discard the
        # other forty-nine: the row is reported with the cell and the wording
        # that could not be read, and nothing is published from it.
        marker = "><strong data-renderer-mark=\"true\">2022-02-28</strong>"
        self.assertIn(marker, PAGE)
        tampered = PAGE.replace(marker,
                                "><strong data-renderer-mark=\"true\">sometime in 2022</strong>", 1)
        products, excluded, _seen = barracuda.parse(tampered)
        self.assertEqual(len(products), 49)
        refused = [entry for entry in excluded if "unrecognized Barracuda date" in entry["reason"]]
        self.assertEqual(len(refused), 1)
        self.assertIn("EoS & EoHS", refused[0]["reason"])
        self.assertIn("sometime in 2022", refused[0]["reason"])


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
        with mock.patch.object(barracuda, "net") as net, \
                mock.patch.object(barracuda, "_now", return_value=checked):
            net.get_text.return_value = page
            return sources.source("import-barracuda").run(self.root)

    def test_the_registered_source_publishes_its_records_and_one_report(self):
        detail = self.refresh()
        self.assertIn("Barracuda firewall models", detail)
        published = sorted(path.stem for path in (self.root / "hardware").glob("barracuda-*.json"))
        self.assertEqual(len(published), 50)
        report = json.loads((self.root / barracuda.REPORT).read_text())
        self.assertEqual(report["total_records"], 50)
        self.assertEqual(report["verifier"], barracuda.VERIFIER)
        record = json.loads((self.root / "hardware" / (published[0] + ".json")).read_text())
        self.assertEqual(record["vendor"], "Barracuda")

    def test_a_quiet_refresh_republishes_byte_identical_files(self):
        self.refresh()
        published = self.snapshot()
        self.refresh("2026-09-27T01:00:00Z")
        self.assertEqual(self.snapshot(), published)
        first = sorted(path for path in published if path.startswith("hardware/barracuda-"))[0]
        self.assertEqual(json.loads(published[first])["provenance"]["last_checked"], CHECKED)

    def test_a_refused_page_writes_nothing(self):
        for page in ("", "<html><body>gone</body></html>"):
            with self.subTest(page=page[:12]):
                with self.assertRaises(ValueError):
                    self.refresh("2026-09-27T02:00:00Z", page)
                self.assertEqual(set(self.snapshot()), {"manifest.json"})


if __name__ == "__main__":
    unittest.main()
