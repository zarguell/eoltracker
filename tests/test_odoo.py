"""Odoo's published support calendar must not invent retirement deadlines."""
import unittest
from pathlib import Path

from engine import odoo


class OdooCalendarTests(unittest.TestCase):
    def test_vendor_months_and_qualified_support_dates(self):
        html = (Path(__file__).parent / "fixtures" / "odoo-support.html").read_text(encoding="utf-8")
        releases = {row["name"]: row for row in odoo.parse_releases(html)}
        # Independently counted: seven SaaS rows, six majors, one older group.
        self.assertEqual(set(releases), {
            "Odoo SaaS 19.4", "Odoo SaaS 19.3", "Odoo SaaS 19.2", "Odoo SaaS 19.1",
            "Odoo SaaS 18.4", "Odoo SaaS 18.3", "Odoo SaaS 18.2",
            "Odoo 19.0", "Odoo 18.0", "Odoo 17.0", "Odoo 16.0", "Odoo 15.0", "Odoo 14.0",
            "Older versions",
        })
        current = releases["Odoo 19.0"]
        self.assertEqual(current["milestones"], {"ga": "2025-09", "eos": None, "eossec": None, "eol": None})
        self.assertEqual(current["upstream"]["cells"]["End of standard support"], "September 2028 (planned)")
        # Realized standard-support expiry still is not terminal or security EOL:
        # extended support continues, with different security terms by platform.
        old = releases["Odoo 16.0"]
        self.assertEqual(old["milestones"], {"ga": "2022-10", "eos": None, "eossec": None, "eol": None})
        self.assertEqual(old["upstream"]["cells"]["End of standard support"], "September 2025")
        self.assertEqual(releases["Odoo 14.0"]["milestones"], dict.fromkeys(("ga", "eos", "eossec", "eol")))
        self.assertEqual(releases["Odoo SaaS 19.4"]["milestones"]["ga"], "2026-07")


if __name__ == "__main__":
    unittest.main()
