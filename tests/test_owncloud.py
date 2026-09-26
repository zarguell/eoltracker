"""Regression tests for the ownCloud Server collector (issue #135).

The fixture is the owncloud/core project's own Maintenance and Release
Schedule, fetched 2026-09-26. No test reaches the network.

The schedule is a small table with three traps, and each is pinned here:

* **The end-of-life column states a month** (``2027-01``) and no day, so it must
  publish a month and never be widened into one. A day in that column would mean
  the column changed.
* **``maintained, EOL TBA`` is the vendor's own trigger**, not an unknown date:
  line 11 is supported with no announced end, so ``eol`` is null and the cell is
  kept. A cell that is neither a month nor that trigger is a refusal.
* **The current-version column is a different fact from the line's own release
  date.** Line 10 was released 2017-04-27 and its current patch 10.16.4 was
  released 2026-07-29; publishing the patch's date as the line's ``ga`` would
  replace a stated date with a different stated date.
"""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from engine import net, owncloud, sources
from engine.importer import dump, normalize

FIXTURES = Path(__file__).parent / "fixtures"
SCHEDULE = FIXTURES / "owncloud-maintenance-schedule.html"
CHECKED = "2026-09-26T03:00:00Z"


def page_text():
    return SCHEDULE.read_text(encoding="utf-8")


def parsed():
    return owncloud.parse(page_text())


def line(releases, line_id):
    return next(release for release in releases if release["id"] == line_id)


class ScheduleShapeTests(unittest.TestCase):
    def test_the_page_states_every_major_line_it_lists(self):
        releases, accounting = parsed()
        self.assertEqual(accounting["rows"], 15)
        self.assertEqual(accounting["lines"], 15)
        self.assertEqual(len(accounting["triggers"]), 1)
        self.assertEqual([release["id"] for release in releases],
                         ["11", "10", "9.1", "9.0", "8.2", "8.1", "8.0", "7.0", "6.0", "5.0",
                          "4.5", "4.0", "3.0", "2.0", "1.0"])

    def test_a_line_publishes_its_own_release_date_as_ga(self):
        releases, _accounting = parsed()
        self.assertEqual(line(releases, "10")["milestones"],
                         {"ga": "2017-04-27", "eos": None, "eossec": None, "eol": "2027-01"})

    def test_a_changed_header_refuses_the_page(self):
        html = page_text().replace(">end of life<", ">end of support<", 1)
        with self.assertRaisesRegex(ValueError, "release tables, expected the one"):
            owncloud.parse(html)

    def test_a_page_that_is_no_longer_the_schedule_refuses(self):
        with self.assertRaisesRegex(ValueError, "no longer carries the"):
            owncloud.parse(page_text().replace(owncloud.PAGE_TITLE, "Old Notes"))

    def test_a_removed_release_table_refuses_the_page(self):
        html = page_text()
        start = html.rfind("<table")
        with self.assertRaisesRegex(ValueError, "release tables, expected the one"):
            owncloud.parse(html[:start])

    def test_a_version_the_page_states_twice_refuses(self):
        html = page_text()
        rows = page_text().split("<tr>")
        # Duplicate the first data row verbatim inside the table.
        index = next(i for i, row in enumerate(rows) if ">10<" in row)
        rows.insert(index + 1, rows[index])
        with self.assertRaisesRegex(ValueError, "more than once"):
            owncloud.parse("<table><tr><th>version</th><th>release date</th><th>end of life</th>"
                           "<th>current version</th><th>next version</th></tr>"
                           + "".join(f"<tr>{row}</tr>" for row in rows[1:] if "<td" in row)
                           + "</table>")

    def test_a_line_whose_release_date_is_gone_refuses(self):
        with self.assertRaisesRegex(ValueError, "not an ISO day"):
            owncloud._day("soon", "row")

    def test_a_cell_that_states_no_date_reads_as_none_rather_than_a_date(self):
        # "n/a" is the absence token; the refusal belongs to the row that has no
        # date where one is required, which ``parse`` raises.
        self.assertIsNone(owncloud._day("n/a", "row"))
        self.assertIsNone(owncloud._month("n/a", "row"))


class MonthPrecisionTests(unittest.TestCase):
    """The schedule publishes no day in the end-of-life column, so none is made."""

    def test_a_month_is_published_as_a_month(self):
        self.assertEqual(owncloud._month("2027-01", "row"), "2027-01")

    def test_a_day_in_the_month_column_refuses_rather_than_being_narrowed(self):
        with self.assertRaisesRegex(ValueError, "a day in a column"):
            owncloud._month("2027-01-15", "row")

    def test_an_impossible_month_refuses(self):
        for value in ("2027-13", "2027-00", "soon", "2027"):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    owncloud._month(value, "row")

    def test_fourteen_of_the_fifteen_lines_publish_a_month(self):
        releases, _accounting = parsed()
        months = [release for release in releases if release["milestones"]["eol"]]
        self.assertEqual(len(months), 14)
        for release in months:
            self.assertRegex(release["milestones"]["eol"], r"^\d{4}-\d{2}$")
            self.assertIn("month precision", release["upstream"]["eol_note"])

    def test_a_record_that_widens_a_month_into_a_day_is_rejected(self):
        record = owncloud.record_for(parsed()[0], CHECKED)
        owncloud.validate_record(record)
        release = line(record["releases"], "10")
        release["milestones"]["eol"] = "2027-01-31"
        with self.assertRaisesRegex(ValueError, "claims an eol its own cell does not state"):
            owncloud.validate_record(record)


class TriggerTests(unittest.TestCase):
    def test_the_maintained_line_publishes_no_eol_and_keeps_the_vendors_cell(self):
        releases, accounting = parsed()
        current = line(releases, "11")
        self.assertEqual(current["milestones"],
                         {"ga": "2026-07-30", "eos": None, "eossec": None, "eol": None})
        self.assertEqual(current["upstream"]["cells"]["end of life"], "maintained, EOL TBA")
        self.assertIn("no announced end of life", current["upstream"]["eol_note"])
        self.assertEqual([entry["line"] for entry in accounting["triggers"]], ["11"])

    def test_a_cell_that_is_neither_a_month_nor_the_trigger_refuses(self):
        # The refusal may come from the month grammar or from the row check; what
        # matters is that an unrecognised cell never publishes as an absent date.
        with self.assertRaisesRegex(ValueError, "not a month this schedule states|"
                                               "does not state the vendor's"):
            owncloud.parse(page_text().replace("maintained, EOL TBA", "sometime soon", 1))

    def test_a_null_eol_without_the_vendors_note_is_rejected(self):
        record = owncloud.record_for(parsed()[0], CHECKED)
        owncloud.validate_record(record)
        del line(record["releases"], "11")["upstream"]["eol_note"]
        with self.assertRaisesRegex(ValueError, "without the vendor's own trigger note"):
            owncloud.validate_record(record)


class CurrentVersionTests(unittest.TestCase):
    """The patch release is a different fact from the line's own release date."""

    def test_the_patch_and_its_date_are_kept_but_never_become_the_line_ga(self):
        releases, _accounting = parsed()
        current = line(releases, "10")
        self.assertEqual(current["upstream"]["cells"]["current version"], "10.16.4 (2026-07-29)")
        self.assertEqual(current["upstream"]["current version release"], "2026-07-29")
        self.assertEqual(current["milestones"]["ga"], "2017-04-27")

    def test_a_line_with_no_current_version_states_none_rather_than_failing(self):
        releases, _accounting = parsed()
        oldest = line(releases, "1.0")
        self.assertEqual(oldest["upstream"]["cells"]["current version"], "-")
        self.assertNotIn("current version release", oldest["upstream"])
        self.assertEqual(oldest["upstream"]["cells"]["next version"], "End of Life")
        self.assertNotIn("next version release", oldest["upstream"])

    def test_a_next_version_with_no_stated_date_publishes_none(self):
        releases, _accounting = parsed()
        self.assertIsNone(line(releases, "10")["upstream"]["next version release"])

    def test_a_current_version_of_another_line_refuses(self):
        with self.assertRaisesRegex(ValueError, "is not a release of line"):
            owncloud._patch("12.0.0 (2026-01-01)", "row", "11")

    def test_a_patch_without_a_date_refuses(self):
        with self.assertRaisesRegex(ValueError, "not a patch and date"):
            owncloud._patch("11.0.0", "row", "11")

    def test_a_hand_edited_ga_is_re_derived_and_rejected(self):
        record = owncloud.record_for(parsed()[0], CHECKED)
        owncloud.validate_record(record)
        line(record["releases"], "10")["milestones"]["ga"] = "2020-01-01"
        with self.assertRaisesRegex(ValueError, "claims a ga its own cell does not state"):
            owncloud.validate_record(record)


class RetentionTests(unittest.TestCase):
    def test_a_line_the_page_drops_is_retained_with_its_dates(self):
        releases, _accounting = parsed()
        dropped = line(releases, "8.0")
        kept, reasons = owncloud.combine([release for release in releases
                                          if release["id"] != "8.0"],
                                         {"releases": [dropped]})
        self.assertEqual([release["id"] for release in kept if release["id"] == "8.0"], ["8.0"])
        retained = next(r for r in kept if r["id"] == "8.0")
        self.assertFalse(retained["upstream"]["in_source"])
        self.assertEqual(retained["milestones"]["eol"], "2016-10")
        self.assertIn("no longer states this release line", reasons[0]["reason"])

    def test_nothing_is_retained_when_the_page_states_every_line(self):
        releases, _accounting = parsed()
        rows, reasons = owncloud.combine(releases, {"releases": releases})
        self.assertEqual(len(rows), len(releases))
        self.assertEqual(reasons, [])


class AttributionTests(unittest.TestCase):
    def test_the_vendor_is_owncloud_and_never_kiteworks(self):
        # Issue #126 settled the attribution: ownCloud publishes this under its
        # own project identity.
        record = owncloud.record_for(parsed()[0], CHECKED)
        self.assertEqual(record["id"], "owncloud-server")
        self.assertEqual(record["name"], "ownCloud Server")
        self.assertIn(owncloud.SOURCE_URL, record["links"].values())
        blob = json.dumps(record) + owncloud.ATTRIBUTION
        self.assertNotIn("Kiteworks\"", blob)
        self.assertIn("not Kiteworks", owncloud.ATTRIBUTION)

    def test_the_schedule_is_recorded_with_the_page_that_designates_it(self):
        record = owncloud.record_for(parsed()[0], CHECKED)
        self.assertEqual(record["provenance"]["source_url"], owncloud.SOURCE_URL)
        self.assertEqual(record["links"]["support"], owncloud.SUPPORT_URL)


class PublicationTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        (self.root / "products").mkdir()
        (self.root / "hardware").mkdir()
        sibling = normalize({"result": {"name": "sample", "label": "Sample", "category": "lang",
                                        "labels": {},
                                        "releases": [{"name": "1", "releaseDate": "2026-01-01"}]}},
                            CHECKED)
        dump(self.root / "products/sample.json", sibling)
        dump(self.root / "manifest.json", {"generated_at": CHECKED,
                                           "source_url": sources.ENDOFLIFE_DATE_API,
                                           "source": "import-data", "product_count": 1,
                                           "release_count": 1, "excluded_hardware": [],
                                           "hardware_count": 0})

    def snapshot(self):
        return {str(path.relative_to(self.root)): path.read_bytes()
                for path in self.root.rglob("*.json")}

    def refresh(self, checked=CHECKED):
        with mock.patch.object(owncloud.net, "get_text", return_value=page_text()), \
                mock.patch.object(owncloud, "_now", return_value=checked):
            return sources.source("import-owncloud").run(self.root)

    def test_the_registered_source_publishes_the_record_and_its_report(self):
        detail = self.refresh()
        self.assertIn("15 ownCloud Server release lines", detail)
        record = json.loads((self.root / "products/owncloud-server.json").read_text())
        owncloud.validate_record(record)
        self.assertEqual(len(record["releases"]), 15)
        report = json.loads((self.root / owncloud.REPORT).read_text())
        self.assertEqual(report["rows"], {"seen": 15, "published": 15, "retained": 0,
                                          "triggers": 1})
        self.assertEqual(report["verifier"], owncloud.VERIFIER)
        self.assertEqual(report["total_records"], 1)

    def test_a_quiet_refresh_republishes_byte_identical_files(self):
        self.refresh()
        published = self.snapshot()
        self.refresh("2026-09-27T03:00:00Z")
        self.assertEqual(self.snapshot(), published)

    def test_a_page_that_is_not_the_schedule_writes_nothing(self):
        with mock.patch.object(owncloud.net, "get_text", return_value="<html>gone</html>"):
            with self.assertRaises(ValueError):
                owncloud.import_owncloud(self.root)
        self.assertEqual(set(self.snapshot()),
                         {"manifest.json", "products/sample.json"})


if __name__ == "__main__":
    unittest.main()
