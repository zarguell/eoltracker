"""Samba's planning table must publish realized dates and keep forecasts raw."""
import unittest
from pathlib import Path

from engine import samba


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

if __name__ == "__main__":
    unittest.main()
