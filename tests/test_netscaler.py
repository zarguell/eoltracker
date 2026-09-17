"""NetScaler collector regression tests.

The fixtures are the vendor's pages saved verbatim on 2026-09-17:
``netscaler-matrix.html`` (current matrix: 3 releases, 17 exclusions) and
``netscaler-legacy.html`` (legacy matrix: 14 releases, 31 exclusions, 45 data
rows). Synthetic minimal pages exercise refusal paths without depending on
fixture byte offsets.
"""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from engine.importer import API, dump, normalize

from engine import netscaler

FIXTURES = Path(__file__).parent / "fixtures"
CURRENT = (FIXTURES / "netscaler-matrix.html").read_text()
LEGACY = (FIXTURES / "netscaler-legacy.html").read_text()


def parsed():
    return netscaler.parse_releases(CURRENT, LEGACY)


def matrix_page(tab_label, *rows):
    """A minimal matrix page: one tab, the vendor's header set, given rows."""
    header = ("<tr><th>Product/Component Name</th><th>Version / Model</th>"
              "<th>Language</th><th>NSC</th><th>EOS</th><th>EOM</th><th>EOL</th></tr>")
    return (f'<div class="ctx-tab"><span class="tab-text">{tab_label}</span>'
            f'<table>{header}{"".join(rows)}</table></div>')

def firmware_row(product, version, eol="08-Aug-30", eom="08-Aug-29"):
    return (f"<tr><td>{product}</td><td>{version}</td><td>EN</td><td>N/A</td>"
            f"<td>N/A</td><td>{eom}</td><td>{eol}</td></tr>")


class InventoryTests(unittest.TestCase):
    def test_both_matrices_yield_seventeen_firmware_lines(self):
        releases, _ = parsed()
        self.assertEqual(len(releases), 17)
        self.assertEqual(releases[0]["id"], "14.1")
        self.assertEqual(releases[-1]["id"], "5.x")

    def test_current_page_samples_match_the_vendor_cells(self):
        by_id = {r["id"]: r for r in parsed()[0]}
        self.assertEqual(by_id["14.1"]["milestones"],
                         {"ga": "2023-08-08", "eos": None, "eossec": None,
                          "eol": "2030-08-08"})
        # 13.1's EOL cell carries the vendor's footnote asterisk; the date is
        # 15-Sep-27 and the asterisk stays in the stored cell only.
        self.assertEqual(by_id["13.1"]["milestones"]["eol"], "2027-09-15")
        self.assertEqual(by_id["13.1"]["upstream"]["cells"]["EOL"], "15-Sep-27*")
        # 13.1 FIPS states no GA of its own.
        self.assertIsNone(by_id["13.1-fips"]["milestones"]["ga"])

    def test_releases_are_ordered_newest_major_first(self):
        releases, _ = parsed()
        majors = [int(r["id"].split(".")[0]) for r in releases]
        self.assertEqual(majors, sorted(majors, reverse=True))


class AccountingTests(unittest.TestCase):
    def test_every_source_row_is_accounted_per_page(self):
        # Independent fixture inventory: header rows are not source data.
        for html, page, source_rows in (
                (CURRENT, netscaler.SOURCE_URL, 20),
                (LEGACY, netscaler.LEGACY_URL, 45)):
            releases, excluded = netscaler.parse_page(html, page)
            report = netscaler.report_for(releases, excluded, [], "2026-09-17T00:00:00Z")
            self.assertEqual(report["rows"]["seen"], source_rows)
            self.assertEqual(len(releases) + len(excluded), source_rows)

    def test_legacy_tab_states_forty_five_data_rows(self):
        # 14 firmware releases (4 labelled + 10 in the blank group) + 31
        # appliance and other rows.
        releases, excluded = netscaler.parse_page(LEGACY, netscaler.LEGACY_URL)
        self.assertEqual(len(releases), 14)
        self.assertEqual(len(excluded), 31)

    def test_a_firmware_line_stated_twice_on_one_page_refuses(self):
        row = firmware_row("NetScaler ADC and Gateway Firmware", "14.1 (GA: 08-Aug-23)")
        page = matrix_page(netscaler.CURRENT_TAB, row + row)
        with self.assertRaisesRegex(ValueError, "stated twice"):
            netscaler.parse_page(page, netscaler.SOURCE_URL)


class ClassificationTests(unittest.TestCase):
    def test_blank_product_cells_preserve_all_ten_firmware_scopes(self):
        # The legacy matrix's blank rowspan=10 firmware group follows blank
        # appliance groups: product text alone must not discard it, and the
        # appliance part lists sharing the blank group must not leak in.
        releases, _ = netscaler.parse_page(LEGACY, netscaler.LEGACY_URL)
        blank_group = {r["id"] for r in releases
                       if not r["upstream"]["cells"]["Product/Component Name"]}
        self.assertEqual(blank_group, {
            "12.0", "11.1", "11.0", "10.5",
            "10.0.x-10.1.x-10.5.e-admin-partition-and-10.5.e-10.5.x.e-admin-partition",
            "9.x", "8.x", "7.x", "6.x", "5.x",
        })
        self.assertFalse(any("MPX" in r["id"] or "SDX" in r["id"] for r in releases))

    def test_appliance_platform_rows_are_excluded_with_reason(self):
        # MPX/SDX rows carry appliance dates: a hardware scope, never releases.
        releases, excluded = parsed()
        self.assertTrue(any("MPX/SDX" in row["row"] for row in excluded))
        self.assertTrue(any("MPX 5500" in row["row"] for row in excluded))
        self.assertFalse(any("MPX" in r["upstream"]["name"] for r in releases))

    def test_unknown_eol_preserves_firmware_inventory(self):
        page = matrix_page(netscaler.CURRENT_TAB,
            firmware_row("NetScaler ADC and Gateway Firmware", "15.1", eol="N/A"),
            firmware_row("NetScaler ADC and Gateway Firmware", "15.2", eol=""))
        releases, excluded = netscaler.parse_page(page, netscaler.SOURCE_URL)
        self.assertEqual({r["id"]: r["milestones"]["eol"] for r in releases},
                         {"15.1": None, "15.2": None})
        self.assertEqual(excluded, [])


class DriftTests(unittest.TestCase):
    def test_renamed_tab_refuses_the_parse(self):
        with self.assertRaisesRegex(ValueError, "no 'NetScaler ADC"):
            netscaler.parse_page(
                CURRENT.replace("NetScaler ADC (formerly Citrix ADC)", "Renamed"),
                netscaler.SOURCE_URL)

    def test_renamed_column_refuses_the_parse(self):
        with self.assertRaisesRegex(ValueError, "unexpected NetScaler table headers"):
            netscaler.parse_page(CURRENT.replace("EOM</th>", "Maintenance</th>"),
                                 netscaler.SOURCE_URL)

    def test_a_firmware_line_on_both_pages_is_a_contradiction(self):
        current = matrix_page(netscaler.CURRENT_TAB,
                              firmware_row("NetScaler ADC and Gateway Firmware",
                                           "14.1 (GA: 08-Aug-23)"))
        legacy = matrix_page(netscaler.LEGACY_TAB,
                             firmware_row("NetScaler ADC and Gateway Firmware",
                                          "14.1 (GA: 08-Aug-23)"))
        with self.assertRaisesRegex(ValueError, "stated on both matrix pages"):
            netscaler.parse_releases(current, legacy)

    def test_an_impossible_day_refuses_the_parse(self):
        # date_value rejects calendar-impossible days instead of normalizing.
        with self.assertRaises(ValueError):
            netscaler.date_value("31-Feb-30", "test")
        self.assertEqual(netscaler.date_value("08-Aug-30", "test"), "2030-08-08")
        self.assertEqual(netscaler.date_value("01-April-23", "test"), "2023-04-01")
        self.assertIsNone(netscaler.date_value("N/A", "test"))
        self.assertIsNone(netscaler.date_value("", "test"))


class ReDerivationTests(unittest.TestCase):
    def record(self):
        return netscaler.record_for(parsed()[0], "2026-09-17T00:00:00Z")

    def test_tampered_milestone_is_refused(self):
        record = self.record()
        record["releases"][0]["milestones"]["eol"] = "2099-01-01"
        with self.assertRaisesRegex(ValueError, "eol contradicts its stored cells"):
            netscaler.validate_record(record)

    def test_invented_eossec_is_refused(self):
        record = self.record()
        record["releases"][0]["milestones"]["eossec"] = "2031-01-01"
        with self.assertRaisesRegex(ValueError, "security-support end the source"):
            netscaler.validate_record(record)

    def test_wrong_id_for_version_cell_is_refused(self):
        record = self.record()
        record["releases"][0]["id"] = "14.2"
        with self.assertRaisesRegex(ValueError, "does not name its own version cell"):
            netscaler.validate_record(record)

    def test_eom_after_eol_in_cells_is_refused(self):
        # The EOM ordering check re-derives both from the stored cells, so the
        # tamper target is the cell, not the normalized milestone.
        record = self.record()
        record["releases"][0]["upstream"]["cells"]["EOM"] = "08-Aug-31"
        with self.assertRaisesRegex(ValueError, "before its own"):
            netscaler.validate_record(record)

    def test_foreign_verifier_is_refused(self):
        record = self.record()
        record["provenance"]["verifier"] = "deterministic-something-else"
        with self.assertRaisesRegex(ValueError, "source identity"):
            netscaler.validate_record(record)


class OwnershipTests(unittest.TestCase):
    def test_foreign_record_is_refused(self):
        record = ReDerivationTests().record()
        record["provenance"]["verifier"] = "deterministic-foreign"
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "products").mkdir()
            (root / "products" / "netscaler-adc.json").write_text(
                json.dumps(record), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "ownership collision"):
                netscaler.committed_record(root)

    def test_absent_record_is_none(self):
        with tempfile.TemporaryDirectory() as temp:
            self.assertIsNone(netscaler.committed_record(Path(temp)))


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

    def refresh(self, checked, current=CURRENT, legacy=LEGACY):
        with mock.patch.object(netscaler.net, "get_text", side_effect=[current, legacy]), \
                mock.patch.object(netscaler, "_now", return_value=checked):
            netscaler.import_netscaler(self.root)

    def test_quiet_refresh_and_report_only_change_have_independent_revisions(self):
        before = self.snapshot()
        self.refresh("2026-09-17T01:00:00Z")
        published = self.snapshot()
        self.assertEqual({k: published[k] for k in before}, before)
        self.refresh("2026-09-17T02:00:00Z")
        self.assertEqual(self.snapshot(), published)
        # Change an excluded hardware model, leaving all firmware rows alone.
        self.assertIn("MPX 5500", LEGACY)
        self.refresh("2026-09-17T03:00:00Z", legacy=LEGACY.replace("MPX 5500", "MPX 5501"))
        self.assertEqual((self.root / "products/netscaler-adc.json").read_bytes(),
                         published["products/netscaler-adc.json"])
        report = json.loads((self.root / netscaler.REPORT).read_text())
        self.assertEqual(report["checked_at"], "2026-09-17T03:00:00Z")
        self.assertTrue(any("MPX 5501" in r["row"] for r in report["excluded"]))

    def test_foreign_record_refuses_import_before_network_and_writes_nothing(self):
        record = json.loads((self.root / "products/sample.json").read_text())
        record["id"] = "netscaler-adc"
        dump(self.root / "products/netscaler-adc.json", record)
        before = self.snapshot()
        with mock.patch.object(netscaler.net, "get_text") as fetch:
            with self.assertRaises(ValueError):
                netscaler.import_netscaler(self.root)
        fetch.assert_not_called()
        self.assertEqual(self.snapshot(), before)

    def test_parse_failure_leaves_existing_catalog_untouched(self):
        self.refresh("2026-09-17T01:00:00Z")
        before = self.snapshot()
        with self.assertRaises(ValueError):
            self.refresh("2026-09-17T02:00:00Z", current="<html>Changed layout</html>")
        self.assertEqual(self.snapshot(), before)

    def test_missing_line_retains_dates_and_accounts_only_fetched_rows(self):
        self.refresh("2026-09-17T01:00:00Z")
        before = json.loads((self.root / "products/netscaler-adc.json").read_text())
        current = matrix_page(netscaler.CURRENT_TAB,
            firmware_row("NetScaler ADC and Gateway Firmware", "14.1 (GA: 08-Aug-23)"))
        self.refresh("2026-09-17T02:00:00Z", current=current)
        record = json.loads((self.root / "products/netscaler-adc.json").read_text())
        self.assertEqual({r["id"]: r["milestones"] for r in record["releases"]},
                         {r["id"]: r["milestones"] for r in before["releases"]})
        report = json.loads((self.root / netscaler.REPORT).read_text())
        self.assertEqual(report["rows"],
                         {"seen": 46, "published": 15, "retained": 2, "excluded": 31})

    def test_invalid_sibling_report_prevents_publication(self):
        dump(self.root / "ceph-import.json", {"verifier": "deterministic-ceph",
                                             "total_records": 1})
        before = self.snapshot()
        with self.assertRaises(ValueError):
            self.refresh("2026-09-17T01:00:00Z")
        self.assertEqual(self.snapshot(), before)
