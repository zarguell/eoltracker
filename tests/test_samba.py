"""Samba's planning table must publish realized dates and keep forecasts raw."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from engine import samba
from engine.importer import API, dump, normalize


class SambaPlanningTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixture = Path(__file__).parent / "fixtures" / "samba-release-planning.html"
        cls.html = fixture.read_text(encoding="utf-8")

    def test_realized_dates_publish_and_forecasts_stay_raw(self):
        releases = {row["id"]: row for row in samba.parse_releases(self.html)}
        # Independently counted from the vendor table: 30 series rows
        # (4.25 upcoming … 3.0) plus the template-rendered 4.24 current row.
        self.assertEqual(len(releases), 32)
        # Realized ga and terminal eol publish at day precision.
        self.assertEqual(releases["samba-4.20"]["milestones"],
                         {"ga": "2024-03-27", "eos": None, "eossec": None,
                          "eol": "2025-09-12"})
        # Current series: realized start, forecast end stays raw.
        self.assertEqual(releases["samba-4.23"]["milestones"]["ga"], "2025-09-12")
        self.assertIsNone(releases["samba-4.23"]["milestones"]["eol"])
        self.assertEqual(releases["samba-4.23"]["upstream"]["cells"]["discontinued (EOL)"],
                         "~2027-03")
        # Upcoming series: everything is a forecast, no milestone at all.
        self.assertEqual(releases["samba-4.25"]["milestones"],
                         dict.fromkeys(("ga", "eos", "eossec", "eol")))
        # The security-mode column is a mode entry, never an end of security
        # support: it must not appear in any milestone, only in raw cells.
        self.assertEqual(releases["samba-4.21"]["milestones"]["eossec"], None)
        self.assertEqual(releases["samba-4.21"]["upstream"]["cells"]["security"],
                         "2025-09-12")
        # Oldest realized row survives intact.
        self.assertEqual(releases["samba-3.0"]["milestones"],
                         {"ga": "2003-09-24", "eos": None, "eossec": None,
                          "eol": "2009-08-05"})
    def test_month_form_cell_refuses_parse(self):
        # A tilde stripped from a forecast leaves a bare month. The vendor
        # states no day, so padding one would invent precision (rule 4): the
        # cell must fail the parse, never become a milestone.
        html = self.html.replace("~2027-03", "2027-03")
        with self.assertRaises(ValueError):
            samba.parse_releases(html)

    def test_record_contradicting_own_cells_refuses(self):
        releases = samba.parse_releases(self.html)
        checked = "2026-09-17T00:00:00Z"
        record = samba.record_for(releases, checked)
        samba.validate_record(record)
        # A hand-edited milestone that no longer follows the stored cells is
        # refused offline: validate re-derives every date from the cells.
        record["releases"][0]["milestones"]["eol"] = "2027-03-01"
        with self.assertRaises(ValueError):
            samba.validate_record(record)

    def test_a_series_the_planning_table_drops_is_retained_not_deleted(self):
        releases = samba.parse_releases(self.html)
        committed = samba.record_for(releases, "2026-09-17T00:00:00Z")
        fresh = [release for release in releases if release["id"] != "samba-4.20"]
        combined, kept = samba.combine_releases(fresh, committed)
        self.assertEqual([entry["id"] for entry in kept], ["samba-4.20"])
        retained = {release["id"]: release for release in combined}["samba-4.20"]
        self.assertIs(retained["upstream"]["in_source"], False)
        # The retained row keeps the cells and dates the vendor published.
        self.assertEqual(retained["milestones"], {"ga": "2024-03-27", "eos": None,
                                                  "eossec": None, "eol": "2025-09-12"})
        self.assertEqual(retained["upstream"]["cells"],
                         {release["id"]: release for release in releases}["samba-4.20"]
                         ["upstream"]["cells"])
        # Retention is publishable: absence from the table is not a discontinued
        # series, and the record still re-derives from its own stored cells.
        samba.validate_record(samba.record_for(combined, "2026-09-17T00:00:00Z"))

    def test_a_retention_marker_outside_the_allowed_values_refuses(self):
        releases = samba.parse_releases(self.html)
        record = samba.record_for(releases, "2026-09-17T00:00:00Z")
        record["releases"][0]["upstream"]["in_source"] = True
        with self.assertRaisesRegex(ValueError, "retention marker"):
            samba.validate_record(record)

    def test_freshly_parsed_releases_carry_no_retention_marker(self):
        combined, kept = samba.combine_releases(samba.parse_releases(self.html), None)
        self.assertEqual(kept, [])
        self.assertTrue(all("in_source" not in release["upstream"] for release in combined))


class PublicationTests(unittest.TestCase):
    """The refresh publishes the merged snapshot, not only the current rows."""

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        sibling = normalize({"result": {"name": "sample", "label": "Sample",
                            "category": "lang", "labels": {},
                            "releases": [{"name": "1", "releaseDate": "2026-01-01"}]}},
                            "2026-09-17T00:00:00Z")
        dump(self.root / "products/sample.json", sibling)
        dump(self.root / "manifest.json", {
            "generated_at": "2026-09-17T00:00:00Z", "source_url": API,
            "source": "import-data", "product_count": 1, "release_count": 1,
            "excluded_hardware": []})
        self.html = (Path(__file__).parent / "fixtures"
                     / "samba-release-planning.html").read_text(encoding="utf-8")

    def snapshot(self):
        return {str(path.relative_to(self.root)): path.read_bytes()
                for path in self.root.rglob("*.json")}

    def refresh(self, checked, html=None):
        with mock.patch.object(samba.net, "get_text", return_value=html or self.html), \
                mock.patch.object(samba, "_now", return_value=checked):
            return samba.import_samba(self.root)

    def removed_row(self):
        """The fixture with one whole planning row removed, as a source cleanup."""
        start = self.html.index("<td>4.20")
        row_start = self.html.rindex("<tr", 0, start)
        row_end = self.html.index("</tr>", start) + len("</tr>")
        return self.html[:row_start] + self.html[row_end:]

    def test_quiet_refresh_publishes_byte_identical_files(self):
        self.refresh("2026-09-17T01:00:00Z")
        published = self.snapshot()
        self.assertIn("products/samba.json", published)
        self.assertIn("samba-import.json", published)
        self.refresh("2026-09-17T02:00:00Z")
        self.assertEqual(self.snapshot(), published)

    def test_a_removed_row_is_retained_with_its_url_and_cells(self):
        self.refresh("2026-09-17T01:00:00Z")
        before = json.loads((self.root / "products/samba.json").read_text())
        self.refresh("2026-09-17T02:00:00Z", html=self.removed_row())
        record = json.loads((self.root / "products/samba.json").read_text())
        # The dropped series keeps its permalink, cells and dates.
        self.assertEqual(len(record["releases"]), len(before["releases"]))
        retained = {release["id"]: release for release in record["releases"]}["samba-4.20"]
        self.assertFalse(retained["upstream"]["in_source"])
        self.assertEqual(retained["upstream"]["cells"],
                         next(r for r in before["releases"]
                              if r["id"] == "samba-4.20")["upstream"]["cells"])
        self.assertEqual(retained["milestones"],
                         next(r for r in before["releases"]
                              if r["id"] == "samba-4.20")["milestones"])
        report = json.loads((self.root / "samba-import.json").read_text())
        # Fresh rows and retained history are accounted separately, and the
        # report's own arithmetic adds up.
        self.assertEqual(report["rows"], {"seen": 31, "published": 32,
                                          "retained": 1, "excluded": 0})
        self.assertEqual([entry["id"] for entry in report["retained"]], ["samba-4.20"])
        self.assertEqual(report["total_records"], 1)

    def test_a_second_refresh_of_the_dropped_row_page_is_byte_identical(self):
        self.refresh("2026-09-17T01:00:00Z")
        dropped = self.removed_row()
        self.refresh("2026-09-17T02:00:00Z", html=dropped)
        settled = self.snapshot()
        # The retained row is republished from the committed record, so a second
        # fetch of the same page changes nothing: retention is idempotent.
        self.refresh("2026-09-17T03:00:00Z", html=dropped)
        self.assertEqual(self.snapshot(), settled)

    def test_the_retained_report_does_not_count_history_as_fresh_rows(self):
        self.refresh("2026-09-17T01:00:00Z")
        self.refresh("2026-09-17T02:00:00Z", html=self.removed_row())
        report = json.loads((self.root / "samba-import.json").read_text())
        # The forecast lists describe this fetch only: no retained row appears,
        # and the milestone counts cover the 31 rows the page actually stated.
        retained_ids = {entry["id"] for entry in report["retained"]}
        self.assertFalse(retained_ids & {entry["id"] for entry in report["forecast_ga"]})
        self.assertFalse(retained_ids & {entry["id"] for entry in report["forecast_eol"]})
        self.assertEqual(report["milestones"]["ga_forecast"] + report["milestones"]["ga_stated"],
                         31)
        self.assertEqual(report["rows"]["seen"], 31)
        self.assertEqual(report["rows"]["published"] - report["rows"]["retained"],
                         report["rows"]["seen"])

if __name__ == "__main__":
    unittest.main()
