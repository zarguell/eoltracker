import unittest
from pathlib import Path

from engine import netscaler

FIXTURES = Path(__file__).parent / "fixtures"


class LegacyFirmwareTests(unittest.TestCase):
    def test_blank_product_cells_preserve_all_ten_firmware_scopes(self):
        # Citrix legacy matrix: a blank rowspan=10 firmware group follows
        # blank appliance groups. Product text alone must not discard it.
        html = (FIXTURES / "netscaler-legacy.html").read_text()
        releases, excluded = netscaler.parse_page(html, netscaler.LEGACY_URL)
        blank_group = {r["id"]: r for r in releases
                       if not r["upstream"]["cells"]["Product/Component Name"]}
        expected = {
            "12.0", "11.1", "11.0", "10.5",
            "10.0.x-10.1.x-10.5.e-admin-partition-and-10.5.e-10.5.x.e-admin-partition",
            "9.x", "8.x", "7.x", "6.x", "5.x",
        }
        self.assertEqual(set(blank_group), expected)
        self.assertEqual(blank_group["12.0"]["milestones"]["ga"], "2017-04-25")
        self.assertEqual(blank_group["5.x"]["milestones"]["eol"], "2008-03-01")
        self.assertTrue(any("MPX 5500" in row["row"] for row in excluded))
        self.assertFalse(any("MPX" in r["upstream"]["name"] for r in releases))
