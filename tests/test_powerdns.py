"""Regression tests for the PowerDNS Authoritative lifecycle collector."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from engine import powerdns
from engine.importer import API, dump, normalize

FIXTURE = Path(__file__).parent / "fixtures/powerdns-authoritative.html"


def fixture_text():
    return FIXTURE.read_text(encoding="utf-8")


class ParseTests(unittest.TestCase):
    def test_real_page_yields_eleven_scopes(self):
        releases = powerdns.parse_releases(fixture_text())
        self.assertEqual([r["name"] for r in releases],
                         ["5.1", "5.0", "4.9", "4.8", "4.7", "4.6", "4.5", "4.4",
                          "4.3", "4.2", "4.1 and older"])

    def test_day_month_and_approximate_dates_map_at_stated_precision(self):
        releases = {r["id"]: r for r in powerdns.parse_releases(fixture_text())}
        self.assertEqual(releases["5.1"]["milestones"]["ga"], "2026-06-03")
        self.assertEqual(releases["5.0"]["milestones"]["ga"], "2025-08-22")
        self.assertEqual(releases["4.6"]["milestones"]["ga"], "2022-01")
        # 5.1's EOL is "~ January 2028": approximate is not a deadline.
        self.assertIsNone(releases["5.1"]["milestones"]["eol"])
        # 4.8's EOL cell is "EOL June 2026": definite month precision.
        self.assertEqual(releases["4.8"]["milestones"]["eol"], "2026-06")
        # "4.1 and older" is EOL everywhere: one grouped scope, no invented dates.
        self.assertEqual(releases["4.1-and-older"]["milestones"],
                         {"ga": None, "eos": None, "eossec": None, "eol": None})
        self.assertEqual(releases["4.1-and-older"]["upstream"]["cells"]["End of Life"], "EOL")

    def test_critical_only_column_is_validated_but_never_mapped(self):
        releases = {r["id"]: r for r in powerdns.parse_releases(fixture_text())}
        self.assertEqual(releases["5.0"]["upstream"]["cells"]["Critical-Only updates"],
                         "3rd of June 2026")
        for release in releases.values():
            self.assertIsNone(release["milestones"]["eos"])
            self.assertIsNone(release["milestones"]["eossec"])

    def test_reshaped_headers_refuse_the_parse(self):
        html = fixture_text().replace("Critical-Only updates", "Critical updates only")
        with self.assertRaises(ValueError):
            powerdns.parse_releases(html)

    def test_duplicate_row_refuses_the_parse(self):
        html = fixture_text().replace(
            "</table>",
            "<tr><td><p>5.1</p></td><td><p>3rd of June 2026</td>"
            "<td><p>~ January 2027</p></td><td><p>~ January 2028</p></td></tr></table>", 1)
        with self.assertRaises(ValueError):
            powerdns.parse_releases(html)

    def test_unrecognized_date_cell_refuses_the_parse(self):
        html = fixture_text().replace("15th of March 2024", "15th of March, 2024")
        with self.assertRaises(ValueError):
            powerdns.parse_releases(html)

    def test_missing_caption_or_table_refuses_the_parse(self):
        with self.assertRaises(ValueError):
            powerdns.parse_releases("<html><body><p>No tables</p></body></html>")


class PublicationTests(unittest.TestCase):
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

    def snapshot(self):
        return {str(p.relative_to(self.root)): p.read_bytes()
                for p in self.root.rglob("*.json")}

    def refresh(self, checked, html=None):
        with mock.patch.object(powerdns.net, "get_text",
                               return_value=html or fixture_text()), \
                mock.patch.object(powerdns, "datetime") as clock:
            clock.now.return_value.isoformat.return_value = checked
            powerdns.import_authoritative(self.root)

    def test_quiet_refresh_preserves_product_and_report_bytes(self):
        self.refresh("2026-09-17T01:00:00Z")
        published = self.snapshot()
        self.assertIn("products/powerdns-authoritative.json", published)
        self.assertIn("powerdns-authoritative-import.json", published)
        self.refresh("2026-09-17T02:00:00Z")
        self.assertEqual(self.snapshot(), published)

    def test_import_writes_the_expected_record_and_report(self):
        self.refresh("2026-09-17T01:00:00Z")
        record = json.loads(
            (self.root / "products/powerdns-authoritative.json").read_text())
        self.assertEqual(record["id"], "powerdns-authoritative")
        self.assertEqual(record["provenance"]["verifier"],
                         "deterministic-powerdns-authoritative")
        self.assertEqual(len(record["releases"]), 11)
        report = json.loads((self.root / "powerdns-authoritative-import.json").read_text())
        self.assertEqual(report["rows"],
                         {"seen": 11, "published": 11, "retained": 0, "excluded": 0})

    def test_missing_line_is_retained_and_marked(self):
        self.refresh("2026-09-17T01:00:00Z")
        before = json.loads((self.root / "products/powerdns-authoritative.json").read_text())
        # Remove the whole 4.9 row cleanly: match through its row end.
        html = fixture_text()
        start = html.index("<td><p>4.9</p></td>")
        end = html.index("</tr>", start) + len("</tr>")
        row_start = html.rindex("<tr", 0, start)
        html = html[:row_start] + html[end:]
        self.refresh("2026-09-17T02:00:00Z", html=html)
        record = json.loads((self.root / "products/powerdns-authoritative.json").read_text())
        self.assertEqual(len(record["releases"]), 11)
        retained = next(r for r in record["releases"] if r["id"] == "4.9")
        self.assertFalse(retained["upstream"]["in_source"])
        self.assertEqual(retained["milestones"],
                         next(r for r in before["releases"] if r["id"] == "4.9")["milestones"])
        report = json.loads((self.root / "powerdns-authoritative-import.json").read_text())
        self.assertEqual(report["rows"],
                         {"seen": 10, "published": 11, "retained": 1, "excluded": 0})

    def test_tampered_milestone_refuses_republication(self):
        self.refresh("2026-09-17T01:00:00Z")
        path = self.root / "products/powerdns-authoritative.json"
        record = json.loads(path.read_text())
        record["releases"][0]["milestones"]["eol"] = "2028-01"
        dump(path, record)
        before = self.snapshot()
        with self.assertRaises(ValueError):
            self.refresh("2026-09-17T02:00:00Z")
        self.assertEqual(self.snapshot(), before)

    def test_foreign_record_refuses_import_before_network(self):
        record = json.loads((self.root / "products/sample.json").read_text())
        record["id"] = "powerdns-authoritative"
        dump(self.root / "products/powerdns-authoritative.json", record)
        before = self.snapshot()
        with mock.patch.object(powerdns.net, "get_text") as fetch:
            with self.assertRaises(ValueError):
                powerdns.import_authoritative(self.root)
        fetch.assert_not_called()
        self.assertEqual(self.snapshot(), before)

    def test_parse_failure_leaves_existing_catalog_untouched(self):
        self.refresh("2026-09-17T01:00:00Z")
        before = self.snapshot()
        with self.assertRaises(ValueError):
            self.refresh("2026-09-17T02:00:00Z", html="<html>Changed layout</html>")
        self.assertEqual(self.snapshot(), before)

    def test_invalid_sibling_report_prevents_publication(self):
        dump(self.root / "ceph-import.json", {"verifier": "deterministic-ceph",
                                              "total_records": 1})
        before = self.snapshot()
        with self.assertRaises(ValueError):
            self.refresh("2026-09-17T01:00:00Z")
        self.assertEqual(self.snapshot(), before)


if __name__ == "__main__":
    unittest.main()
