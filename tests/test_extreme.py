"""Regression tests for the Extreme Networks collector.

The fixtures under ``tests/fixtures/extreme-*.xlsx`` are the two spreadsheet
extracts the vendor publishes from its end-of-sale index page, fetched
2026-09-26. No test reaches the network, and none asserts a date the saved
extract does not state.

Three properties of these files drive the reader. The dates are Excel serials,
an encoding the vendor documents nowhere, so the decoder is pinned on what it
accepts and what it refuses. The three identifier columns have no data
dictionary, so they are carried verbatim and never used to invent an identity.
And two part numbers differ only in punctuation — `RPS9DC-I` and `RPS9DC+I` are
different hardware — so the collector must never fuse them.
"""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from engine import extreme, sources
from engine.importer import dump

FIXTURES = Path(__file__).parent / "fixtures"
CHECKED = "2026-09-26T01:00:00Z"
SHEETS = {"EOS": "extreme-eos.xlsx", "EOSL": "extreme-eosl.xlsx"}


def payload(sheet):
    return (FIXTURES / SHEETS[sheet]).read_bytes()


def parsed(sheet):
    return extreme.parse(payload(sheet), sheet)


class SerialTests(unittest.TestCase):
    def test_a_serial_is_read_as_the_day_the_vendor_printed(self):
        # The vendor's own PDF renders the same row as 2/28/2012, 7/31/2025 and
        # 7/31/2027; the XLSX stores 40967, 45869 and 46599.
        self.assertEqual(extreme.excel_day("40967", "row"), "2012-02-28")
        self.assertEqual(extreme.excel_day("45869", "row"), "2025-07-31")
        self.assertEqual(extreme.excel_day("46599", "row"), "2027-07-31")

    def test_an_empty_or_zero_cell_states_no_date(self):
        for cell in ("", "0"):
            with self.subTest(cell=cell):
                self.assertIsNone(extreme.excel_day(cell, "row"))

    def test_the_ambiguous_1900_range_is_refused_rather_than_guessed(self):
        # Excel counts a day that never happened, so a serial at or below 59
        # cannot be resolved to one calendar day.
        for serial in ("1", "59"):
            with self.subTest(serial=serial):
                with self.assertRaisesRegex(extreme.SheetError, "ambiguous"):
                    extreme.excel_day(serial, "row")

    def test_a_serial_outside_the_range_this_catalog_publishes_is_refused(self):
        for serial in ("1", "500000"):
            with self.subTest(serial=serial):
                with self.assertRaisesRegex(extreme.SheetError, "ambiguous|outside"):
                    extreme.excel_day(serial, "row")

    def test_a_value_that_is_not_a_serial_is_refused(self):
        with self.assertRaisesRegex(extreme.SheetError, "not an Excel date serial"):
            extreme.excel_day("soon", "row")


class SheetTests(unittest.TestCase):
    def test_each_extract_states_its_own_run_date_and_columns(self):
        for sheet, columns in extreme.FILES.items():
            with self.subTest(sheet=sheet):
                run_date, products, seen = parsed(sheet)
                self.assertEqual(run_date, "December 16, 2025")
                self.assertEqual(seen, 1)
                self.assertTrue(products)
                self.assertEqual(len(columns[1]), 6 if sheet == "EOS" else 5)

    def test_the_software_maintenance_column_exists_only_on_the_eos_sheet(self):
        _run, products, _seen = parsed("EOS")
        self.assertIn(extreme.EOSM, products[0]["cells"])
        _run, retired, _seen = parsed("EOSL")
        self.assertNotIn(extreme.EOSM, retired[0]["cells"])

    def test_a_renamed_column_refuses_the_sheet(self):
        original = extreme.FILES["EOS"]
        try:
            extreme.FILES["EOS"] = (original[0], ("Marketing Part Number", "Product",
                                                   "Product Short Description", "EOS date",
                                                   "EOSM date", "End of life"))
            with self.assertRaisesRegex(extreme.SheetError, "columns changed"):
                parsed("EOS")
        finally:
            extreme.FILES["EOS"] = original

    def test_a_sheet_without_a_run_date_refuses(self):
        original = extreme.FILES["EOS"]
        try:
            # A payload that is a valid zip but not a lifecycle sheet.
            import io
            import zipfile
            buffer = io.BytesIO()
            with zipfile.ZipFile(buffer, "w") as archive:
                archive.writestr("xl/worksheets/sheet1.xml", "<worksheet><sheetData>"
                                 '<row r="1"><c r="A1">nothing</c></row>'
                                 '<row r="2"><c r="A1">Marketing Part Number</c></row>'
                                 '<row r="3"><c r="A1">X-1</c></row>'
                                 "</sheetData></worksheet>")
            with self.assertRaisesRegex(extreme.SheetError, "no run date"):
                extreme.parse(buffer.getvalue(), "EOS")
        finally:
            extreme.FILES["EOS"] = original

    def test_a_body_that_is_not_a_spreadsheet_is_refused(self):
        with self.assertRaisesRegex(extreme.SheetError, "not a readable spreadsheet"):
            extreme.parse(b"<html>not a spreadsheet</html>", "EOS")


class MappingTests(unittest.TestCase):
    def test_eos_becomes_eos_and_eosl_becomes_eol(self):
        _run, products, _seen = parsed("EOS")
        product = next(entry for entry in products if entry["part"] == "BR-MLXE-8-AC")
        self.assertEqual(product["milestones"], {"ga": None, "eos": "2012-02-28",
                                                 "eossec": None, "eol": "2027-07-31"})

    def test_the_software_maintenance_date_is_never_mapped(self):
        _run, products, _seen = parsed("EOS")
        for product in products[:200]:
            self.assertIsNone(product["milestones"]["eossec"])
        record = extreme.record_for(products[0], CHECKED, "extreme-example")
        note = record["upstream"]["End of Software Maintenance"]
        self.assertIn("maintenance window", note["note"])
        self.assertIn("not a stated security-support end", note["note"])

    def test_the_raw_serial_is_published_beside_the_day_read(self):
        _run, products, _seen = parsed("EOS")
        product = next(entry for entry in products if entry["part"] == "BR-MLXE-8-AC")
        record = extreme.record_for(product, CHECKED, "extreme-example")
        self.assertEqual(record["upstream"]["EOS date"]["raw"], "40967")
        self.assertEqual(record["upstream"]["EOS date"]["text"], "40967")

    def test_the_run_date_is_published_as_the_only_version_signal(self):
        _run, products, _seen = parsed("EOS")
        record = extreme.record_for(products[0], CHECKED, "extreme-example")
        self.assertEqual(record["upstream"]["Run date"]["text"], "December 16, 2025")
        self.assertIn("version signal", record["upstream"]["Run date"]["note"])


class IdentityTests(unittest.TestCase):
    def test_two_skus_differing_only_in_punctuation_are_never_fused(self):
        # The vendor's own file states RPS9DC-I and RPS9DC+I: different
        # hardware that slugifies identically.
        products = [{"part": "RPS9DC-I"}, {"part": "RPS9DC+I"}]
        ids, collisions = extreme.identities(products)
        self.assertEqual(len(set(ids.values())), 2)
        self.assertEqual(len(collisions), 1)
        self.assertEqual(collisions[0][1], ["RPS9DC+I", "RPS9DC-I"])

    def test_a_product_stated_twice_with_two_spellings_stays_two_records(self):
        # SALSA-Ent-edition-XL and SALSA-Ent-edition XL are one product written
        # two ways; fusing them is a judgement this collector does not make, so
        # both are published and the pair is named for a human.
        products = [{"part": "SALSA-Ent-edition-XL"}, {"part": "SALSA-Ent-edition XL"}]
        ids, collisions = extreme.identities(products)
        self.assertEqual(len(set(ids.values())), 2)
        self.assertEqual(len(collisions), 1)

    def test_an_ordinary_part_number_keeps_a_clean_slug(self):
        ids, collisions = extreme.identities([{"part": "BR-MLXE-8-AC"}])
        self.assertEqual(list(ids.values()), ["extreme-br-mlxe-8-ac"])
        self.assertEqual(collisions, [])


class MergeTests(unittest.TestCase):
    def test_the_two_extracts_as_published_share_no_part_number(self):
        collected = []
        for sheet in sorted(SHEETS):
            _run, products, _seen = parsed(sheet)
            collected.extend(products)
        products, restated, _excluded = extreme.merge(collected)
        self.assertEqual(restated, [])
        self.assertEqual(len(products), len(collected))

    def test_a_part_stated_twice_with_different_dates_refuses(self):
        one = {"part": "X-1", "sheet": "EOS", "milestones": {"ga": None, "eos": "2020-01-01",
                                                              "eossec": None, "eol": "2024-01-01"},
               "software_maintenance": None, "cells": {}}
        two = dict(one, sheet="EOSL", milestones=dict(one["milestones"], eol="2025-01-01"))
        with self.assertRaisesRegex(extreme.SheetError, "different"):
            extreme.merge([one, two])

    def test_a_part_stated_twice_with_the_same_dates_is_one_product(self):
        one = {"part": "X-1", "sheet": "EOS", "milestones": {"ga": None, "eos": "2020-01-01",
                                                              "eossec": None, "eol": "2024-01-01"},
               "software_maintenance": None, "cells": {"EOS date": {"text": "2020-01-01"}}}
        two = dict(one, sheet="EOSL")
        products, restated, _excluded = extreme.merge([one, two])
        self.assertEqual(len(products), 1)
        self.assertEqual(len(restated), 1)
        self.assertIn("also stated", restated[0]["reason"])


class ReportTests(unittest.TestCase):
    def test_the_report_accounts_for_the_page_and_carries_the_run_dates(self):
        collected, sheets = [], {}
        for sheet in sorted(SHEETS):
            run_date, products, _seen = parsed(sheet)
            sheets[sheet] = {"run_date": run_date, "rows": len(products)}
            collected.extend(products)
        products, restated, _excluded = extreme.merge(collected)
        ids, collisions = extreme.identities(products)
        report = extreme.report_for(products, restated, sheets, CHECKED, collisions)
        rows = report["rows"]
        self.assertEqual(rows["seen"], len(products) + len(restated))
        self.assertEqual(report["total_records"], len(products))
        self.assertEqual(rows["sheets"], 2)
        self.assertTrue(all(entry["run_date"] for entry in report["sheets"].values()))
        self.assertTrue(report["collisions"])
        # The vendor states a five-year support rule on its index page; the
        # report must say so and say it is applied nowhere.
        rule = [line for line in report["limitations"] if "five-year" in line]
        self.assertEqual(len(rule), 1)
        self.assertIn("applies it nowhere", rule[0])


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
        class Response:
            def __init__(self, content):
                self.content = content

            def json(self):
                return {}

        def fake_get(url):
            for sheet, name in SHEETS.items():
                if extreme.FILES[sheet][0] in url:
                    return Response((FIXTURES / name).read_bytes())
            raise AssertionError(f"unexpected fetch: {url}")

        with mock.patch.object(extreme.net, "get", side_effect=fake_get), \
                mock.patch.object(extreme, "_now", return_value=checked):
            return sources.source("import-extreme").run(self.root)

    def test_the_registered_source_publishes_its_records_and_one_report(self):
        detail = self.refresh()
        self.assertIn("Extreme Networks products", detail)
        published = [path for path in (self.root / "hardware").glob("extreme-*.json")]
        self.assertGreater(len(published), 100)
        report = json.loads((self.root / extreme.REPORT).read_text())
        self.assertEqual(report["total_records"], len(published))
        self.assertEqual(report["verifier"], extreme.VERIFIER)
        # Both extracts are cut from the same run, so they state the same date.
        self.assertEqual(sorted({entry["run_date"] for entry in report["sheets"].values()}),
                         ["December 16, 2025"])
        record = json.loads(published[0].read_text())
        self.assertEqual(record["vendor"], "Extreme Networks")
        self.assertIn(extreme.INDEX_URL, record["provenance"]["source_urls"])

    def test_a_quiet_refresh_republishes_byte_identical_files(self):
        self.refresh()
        published = self.snapshot()
        self.refresh("2026-09-27T01:00:00Z")
        self.assertEqual(self.snapshot(), published)

    def test_a_sheet_that_is_not_a_spreadsheet_writes_nothing(self):
        with mock.patch.object(extreme.net, "get") as get:
            get.return_value.content = b"<html>gone</html>"
            with self.assertRaises(extreme.SheetError):
                extreme.import_extreme(self.root)
        self.assertEqual(set(self.snapshot()), {"manifest.json"})


if __name__ == "__main__":
    unittest.main()
