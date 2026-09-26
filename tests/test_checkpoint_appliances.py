"""Regression tests for the Check Point appliance collector.

The page in ``tests/fixtures/checkpoint-support-life-cycle-policy.html`` is
Check Point's own support-lifecycle policy page, fetched 2026-09-26. No test
reaches the network, and none asserts a date the saved page does not state.

Two things about this page shape the tests. It mixes day and month precision
inside one column, so a reader that widens or narrows either is wrong in a way
only a test catches. And it answers HTTP 202 with an empty body once a client
has fetched it repeatedly, so an empty document has to be distinguishable from a
page that changed shape.
"""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from engine import checkpoint, checkpoint_appliances as appliances, sources
from engine.importer import dump

FIXTURE = Path(__file__).parent / "fixtures" / "checkpoint-support-life-cycle-policy.html"
PAGE = FIXTURE.read_text(encoding="utf-8")
CHECKED = "2026-09-26T01:00:00Z"


def parsed():
    return appliances.parse(PAGE)


def model(name):
    for entry in parsed()[0]:
        if entry["product"] == name:
            return entry
    raise AssertionError(f"{name} is not an appliance row on the saved page")


class DateTests(unittest.TestCase):
    def test_the_pages_own_spellings_are_read_at_the_precision_they_state(self):
        cases = {
            "Oct-2011": ("2011-10", "month"),
            "Jan 2022": ("2022-01", "month"),
            "31-Oct-2014": ("2014-10-31", "day"),
            "19-Sep-2023": ("2023-09-19", "day"),
            "Feb-05-2022": ("2022-02-05", "day"),   # the page's US-order spelling
            "July 15 2026": ("2026-07-15", "day"),  # and its full-month spelling
            "Feb- 2019": ("2019-02", "month"),       # a stray space after the dash
        }
        for cell, expected in cases.items():
            with self.subTest(cell=cell):
                self.assertEqual(appliances.checkpoint_date(cell, "row"), expected)

    def test_an_absent_cell_states_no_date(self):
        for cell in ("", "-", "N/A", "NA"):
            with self.subTest(cell=cell):
                self.assertEqual(appliances.checkpoint_date(cell, "row"), (None, None))

    def test_a_two_digit_year_publishes_nothing_rather_than_a_century(self):
        # The schema holds a four-digit year and the vendor does not state the
        # century, so choosing one would invent half the date.
        for cell in ("May-06", "31-Dec-18", "31-Dec-08"):
            with self.subTest(cell=cell):
                with self.assertRaises(appliances.NotRepresentable):
                    appliances.checkpoint_date(cell, "row")

    def test_a_day_the_calendar_does_not_have_is_refused(self):
        with self.assertRaisesRegex(appliances.DateError, "not a real calendar day"):
            appliances.checkpoint_date("31-Feb-2020", "row")

    def test_a_spelling_the_page_does_not_use_is_refused(self):
        with self.assertRaisesRegex(appliances.DateError, "unrecognized Check Point date"):
            appliances.checkpoint_date("sometime in 2027", "row")

    def test_a_word_that_is_not_a_month_is_refused(self):
        with self.assertRaisesRegex(appliances.DateError, "not a month name"):
            appliances.checkpoint_date("Foo-2027", "row")


class MappingTests(unittest.TestCase):
    def test_the_three_columns_the_vendor_publishes_separately_stay_separate(self):
        # 2200 states all three at month precision, so the parsed row shows the
        # three values and the milestones withhold them; a day-precision row
        # below is the one that publishes.
        entry = model("2200 Appliance")
        self.assertEqual(entry["milestones"], {"ga": None, "eos": None,
                                               "eossec": None, "eol": None})
        self.assertEqual([entry["precisions"][c] for c in
                          ("General Availability", "End of Sale", "End of Support")],
                         ["month", "month", "month"])
        day_row = next(entry for entry in parsed()[0]
                       if entry["precisions"].get("End of Support") == "day")
        self.assertRegex(day_row["milestones"]["eol"], r"^\d{4}-\d{2}-\d{2}$")

    def test_end_of_engineering_support_is_never_mapped(self):
        # Check Point defines it as maintenance releases three years after end of
        # sale: a maintenance window, not a security-support end.
        for entry in parsed()[0]:
            self.assertIsNone(entry["milestones"]["eossec"], entry["product"])
        # The cell is the vendor's own text; the parsed value is never a milestone.
        self.assertEqual(model("2200 Appliance")["engineering"], "Jun-2020")

    def test_no_day_is_invented_from_a_month_cell(self):
        # The hardware schema holds a calendar day, so a month-precision cell is
        # withheld from the milestone rather than padded to a day the vendor never
        # printed. Every published milestone is therefore a full day.
        import re
        for entry in parsed()[0]:
            for column, value in entry["milestones"].items():
                if value:
                    self.assertRegex(value, r"\d{4}-\d{2}-\d{2}", f"{entry['product']} {column}")
        withheld_months = [entry for entry in parsed()[0]
                           if any("month precision" in item["reason"] for item in entry["withheld"])]
        self.assertTrue(withheld_months)

    def test_no_date_is_derived_from_the_vendors_four_year_rule(self):
        # The policy states a minimum support duration; nothing is computed from
        # it, so a month-precision cell is withheld rather than turned into the
        # date the rule would imply.
        entry = model("3100 Appliance")
        self.assertIsNone(entry["milestones"]["eol"])
        self.assertEqual(entry["precisions"]["End of Support"], "month")

    def test_the_vendor_status_column_is_kept_and_never_mapped(self):
        entry = model("1120 Appliance")
        self.assertEqual(entry["cells"]["Status"]["text"], "Successor Product Available")

    def test_every_family_on_the_page_is_collected(self):
        families = {entry["family"] for entry in parsed()[0]}
        for family in ("Enterprise Appliances", "High End Data Center Appliances",
                       "Scalable Platforms (Chassis & Maestro)", "Ruggedized Appliances",
                       "DDoS Protector"):
            self.assertIn(family, families)


class ShapeTests(unittest.TestCase):
    def test_nineteen_appliance_tables_are_read_and_the_rest_are_named(self):
        models, excluded, seen = parsed()
        self.assertEqual(seen, 36)
        self.assertEqual(len(models), 298)
        self.assertEqual(len(excluded), 17)
        for entry in excluded:
            self.assertIn("engine.checkpoint", entry["reason"])

    def test_the_sibling_software_source_reads_its_own_table_from_the_same_page(self):
        # Two sources, one page: the software trains and the appliance rows must
        # not collide, and each must still read what it owns.
        releases, _excluded = checkpoint.parse_trains(PAGE)
        self.assertTrue(releases)
        models, _other, _seen = parsed()
        self.assertEqual(len({entry["product"] for entry in models}), len(models))

    def test_an_empty_document_is_a_fetch_refusal_not_a_page_change(self):
        with self.assertRaisesRegex(ValueError, "empty document"):
            appliances.parse("")

    def test_a_page_with_no_appliance_table_refuses_rather_than_publishing_nothing(self):
        with self.assertRaisesRegex(ValueError, "none is an appliance schedule"):
            appliances.parse("<html><body><table><tr><th>Service</th><th>End of Sale</th>"
                             "</tr></table></body></html>")

    def test_a_renamed_appliance_column_refuses_the_page(self):
        # Rename the column wherever the page heads it, not in the prose that
        # defines it: the header text is what a reader of the table actually sees.
        self.assertIn(">End of Engineering Support<", PAGE)
        tampered = PAGE.replace(">End of Engineering Support<", ">End of Engineering<")
        with self.assertRaisesRegex(ValueError, "none is an appliance schedule"):
            appliances.parse(tampered)

    def test_an_unrecognized_status_refuses_the_row(self):
        tampered = PAGE.replace(">Active<", ">Nearly Gone<", 1)
        with self.assertRaisesRegex(ValueError, "unrecognized Status"):
            appliances.parse(tampered)

    def test_two_digit_year_cells_are_published_as_withheld_not_as_dates(self):
        withheld = [entry for entry in parsed()[0] if entry["withheld"]]
        self.assertTrue(withheld)
        for entry in withheld:
            reasons = " ".join(item["reason"] for item in entry["withheld"])
            if "two-digit year" in reasons:
                for column in ("General Availability", "End of Sale",
                               "End of Engineering Support", "End of Support"):
                    if any(item["column"] == column for item in entry["withheld"]):
                        self.assertIsNone(entry["milestones"].get(
                            "eol" if column == "End of Support" else "ga"
                            if column == "General Availability" else "eos"))


class RecordTests(unittest.TestCase):
    def test_a_published_record_names_its_source_its_family_and_its_column(self):
        record = appliances.record_for(model("2200 Appliance"), CHECKED)
        self.assertEqual(record["vendor"], "Check Point")
        self.assertEqual(record["category"], "hardware")
        self.assertEqual(record["family"], "Enterprise Appliances")
        self.assertEqual(record["provenance"]["verifier"], appliances.VERIFIER)
        self.assertEqual(record["id"], "checkpoint-enterprise-appliances-2200-appliance")
        # A row the vendor dates to the day is the one that publishes a
        # milestone; the DDoS Protector schedule is the day-precise one.
        dated = next(entry for entry in parsed()[0]
                     if entry["family"] == "DDoS Protector" and entry["product"] == "X100")
        published = appliances.record_for(dated, CHECKED)["milestones"]
        self.assertEqual(published, {"ga": None, "eos": "2026-02-15",
                                     "eossec": None, "eol": "2029-02-15"})

    def test_the_engineering_cell_is_published_with_the_reason_it_is_not_a_milestone(self):
        record = appliances.record_for(model("2200 Appliance"), CHECKED)
        cell = record["upstream"]["End of Engineering Support"]
        # The cell is the vendor's own text, never a normalised value.
        self.assertEqual(cell["text"], "Jun-2020")
        self.assertIn("not a security-support end", cell["note"])

    def test_status_comes_from_the_vendors_own_end_of_support_date(self):
        past = next(entry for entry in parsed()[0]
                    if entry["precisions"].get("End of Support") == "day"
                    and entry["milestones"]["eol"] < "2026-09-26")
        self.assertEqual(appliances.record_for(past, CHECKED)["status"], "eol")
        future = next(entry for entry in parsed()[0]
                      if entry["precisions"].get("End of Support") == "day"
                      and entry["milestones"]["eol"] > "2026-09-26")
        self.assertEqual(appliances.record_for(future, CHECKED)["status"], "expiring")
        undated = appliances.record_for(model("1595R Appliance"), CHECKED)
        self.assertIsNone(undated["milestones"]["eol"])
        self.assertEqual(undated["status"], "unknown")

    def test_the_report_accounts_for_the_whole_page(self):
        models, excluded, seen = parsed()
        report = appliances.report_for(models, excluded, seen, CHECKED)
        rows = report["rows"]
        self.assertEqual(rows["seen"], len(models) + len(excluded))
        self.assertEqual(rows["published"], len(models))
        self.assertEqual(rows["tables"], seen)
        self.assertEqual(report["total_records"], len(models))
        self.assertEqual(report["verifier"], appliances.VERIFIER)
        # The precision split is part of what a reader is owed: every row is
        # either a day the vendor dated, a month it withheld, or no date at all.
        column = "End of Support"
        absent = len(models) - rows["day_precision"][column] - rows["month_precision"][column]
        self.assertEqual(rows["day_precision"][column] + rows["month_precision"][column] + absent,
                         len(models))
        self.assertEqual(rows["with_eol"], rows["day_precision"][column])
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

    def refresh(self, checked=CHECKED, page=PAGE):
        with mock.patch.object(appliances, "net") as net, \
                mock.patch.object(appliances, "_now", return_value=checked):
            net.get_text.return_value = page
            return sources.source("import-checkpoint-appliances").run(self.root)

    def test_the_registered_source_publishes_its_records_and_one_report(self):
        detail = self.refresh()
        self.assertIn("Check Point appliances", detail)
        published = sorted(path.stem for path in (self.root / "hardware").glob("checkpoint-*.json"))
        self.assertEqual(len(published), 298)
        report = json.loads((self.root / appliances.REPORT).read_text())
        self.assertEqual(report["total_records"], 298)
        record = json.loads((self.root / "hardware" / (published[0] + ".json")).read_text())
        self.assertEqual(record["provenance"]["verifier"], appliances.VERIFIER)

    def test_a_quiet_refresh_republishes_byte_identical_files(self):
        self.refresh()
        published = self.snapshot()
        self.refresh("2026-09-27T01:00:00Z")
        self.assertEqual(self.snapshot(), published)
        first = sorted(path for path in published if path.startswith("hardware/checkpoint-"))[0]
        self.assertEqual(json.loads(published[first])["provenance"]["last_checked"], CHECKED)

    def test_a_refused_page_writes_nothing(self):
        for page in ("", "<html><body>gone</body></html>"):
            with self.subTest(page=page[:12]):
                with self.assertRaises(ValueError):
                    self.refresh("2026-09-27T02:00:00Z", page)
                self.assertEqual(set(self.snapshot()), {"manifest.json"})


if __name__ == "__main__":
    unittest.main()
