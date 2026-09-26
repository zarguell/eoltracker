"""Regression tests for the Barracuda collector.

The fixtures under ``tests/fixtures/barracuda-*.html`` are the four dated pages
Barracuda publishes across its product spaces, fetched 2026-09-26 from the
site's public content API. No test reaches the network.

The pages are not uniform, and that is what these tests pin. The firewall and
SecureEdge pages carry a part number and the long end-of-support labels; the load
balancer and WAF pages drop the part number and one of them spells the dates out
in full; the firewall page also holds a *licence* table that is not an appliance;
revision rows arrive in two shapes (a blank model cell, and a row the page renders
one cell short); absent dates are written `not set` and `Not Set`; the WAF page
writes slashes between the date parts; and one row states `2016-11-31`, a day
November does not have.
"""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from engine import barracuda, sources
from engine.importer import dump

FIXTURES = Path(__file__).parent / "fixtures"
CHECKED = "2026-09-26T01:00:00Z"
PAGES = {
    "NGFEOL": "barracuda-ngfeol-firewall-eos-eol.html",
    "LBADCv50": "barracuda-lbadcv50-load-balancer.html",
    "BWAFv76": "barracuda-bwafv76-web-application-firewall.html",
    "SEPPI": "barracuda-seppi-secureedge.html",
}
DISCOVERED = {"NGFEOL": "5505036", "LBADCv50": "7414557", "BWAFv76": "2721616",
              "SEPPI": "61374758"}
TITLES = {"NGFEOL": "Barracuda NextGen and CloudGen Firewall Appliances - EoS / EoL Definitions",
          "LBADCv50": "Hardware End of Sale/End of Life",
          "BWAFv76": "Hardware End of Sale/End of Life",
          "SEPPI": "Barracuda SecureEdge Appliances - EoS / EoL Definitions"}


def html(space):
    return (FIXTURES / PAGES[space]).read_text(encoding="utf-8")


def parsed(space):
    return barracuda.parse(html(space), space)


def _headed(markup):
    """The first headed table on a page, as ``(labels, rows)``."""
    from engine.tables import parse_document, th_header
    for block in parse_document(markup).blocks:
        found = th_header(block)
        if found:
            return found
    raise AssertionError("the saved page states no headed table")


def product(space, label):
    for entry in parsed(space)[0]:
        if entry["label"] == label:
            return entry
    raise AssertionError(f"{label} is not a row on the saved {space} page")


class DateTests(unittest.TestCase):
    def test_the_day_is_read_and_the_firmware_version_is_not_merged_into_it(self):
        self.assertEqual(barracuda.barracuda_day("2025-02-28 (2.0.10)", "row"), "2025-02-28")
        self.assertEqual(barracuda.barracuda_day("2021-05-31 (7.2.6 EoL)", "row"),
                         "2021-05-31")

    def test_both_separators_the_web_application_firewall_page_writes_are_read(self):
        self.assertEqual(barracuda.barracuda_day("2023/03/23", "row"), "2023-03-23")
        self.assertEqual(barracuda.barracuda_day("2020/11/15", "row"), "2020-11-15")

    def test_both_capitals_of_the_absent_date_are_absent(self):
        for cell in ("not set", "Not Set", "None", "—", "-", ""):
            with self.subTest(cell=cell):
                self.assertIsNone(barracuda.barracuda_day(cell, "row"))

    def test_a_day_the_calendar_does_not_have_is_refused(self):
        # The vendor's own F900 row states 2016-11-31; November has 30 days.
        with self.assertRaisesRegex(barracuda.DateError, "not a real calendar day"):
            barracuda.barracuda_day("2016-11-31", "row")

    def test_a_wording_this_reader_does_not_know_is_refused(self):
        for cell in ("sometime in 2022", "31/03/2021", "2021 Q2"):
            with self.subTest(cell=cell):
                with self.assertRaises(barracuda.DateError):
                    barracuda.barracuda_day(cell, "row")


class ShapeTests(unittest.TestCase):
    def test_each_space_publishes_its_own_column_shape(self):
        for space in PAGES:
            with self.subTest(space=space):
                products, _excluded, _seen = parsed(space)
                self.assertTrue(products, space)

    def test_the_three_date_label_spellings_are_each_read(self):
        # The firewall and SecureEdge pages use the long pair, the load balancer
        # page the abbreviation, and the WAF page spells both words out. Each is
        # read by the labels the table itself declares.
        expected = {
            "NGFEOL": ("EoS & EoHS", "EoFS (EoL: last supporting release)"),
            "SEPPI": ("EoS & EoHS", "EoFS (EoL: last supporting release)"),
            "LBADCv50": ("EoS", "EoL"),
            "BWAFv76": ("End of Sale", "End of Life"),
        }
        for space, pair in expected.items():
            with self.subTest(space=space):
                labels = _headed(html(space))[0]
                self.assertEqual(barracuda._shape_of(labels, space)[1][-3:-1], pair)

    def test_a_page_with_no_heeded_table_refuses(self):
        with self.assertRaisesRegex(ValueError, "no headed table"):
            barracuda.parse("<html><body><p>nothing here</p></body></html>", "NGFEOL")

    def test_an_empty_document_is_a_fetch_refusal_not_an_empty_table(self):
        with self.assertRaisesRegex(ValueError, "empty document"):
            barracuda.parse("", "NGFEOL")

    def test_a_model_table_with_an_unknown_date_pair_refuses(self):
        tampered = html("LBADCv50").replace(">EoS<", ">End of ordering<", 1)
        with self.assertRaisesRegex(ValueError, "not one of the published pairs"):
            barracuda.parse(tampered, "LBADCv50")

    def test_a_table_that_heads_neither_a_revision_nor_a_part_is_reported_not_read(self):
        # The firewall page's licence table: a subscription lifecycle, not an
        # appliance, so it is named in the report and nothing is read from it.
        _products, excluded, _seen = parsed("NGFEOL")
        licences = [entry for entry in excluded
                    if entry.get("table", "").startswith("Barracuda License")]
        self.assertEqual(len(licences), 1)
        self.assertIn("licence or subscription", licences[0]["reason"])


class RowModelTests(unittest.TestCase):
    def test_a_revision_row_with_a_blank_model_cell_carries_the_model_forward(self):
        products, _excluded, _seen = parsed("LBADCv50")
        labels = [entry["label"] for entry in products]
        self.assertIn("840 Rev A", labels)
        self.assertIn("840 Rev B", labels)
        both = [entry for entry in products if entry["label"].startswith("840")]
        self.assertEqual({entry["model"] for entry in both}, {"840"})

    def test_a_revision_row_the_page_renders_one_cell_short_is_read_too(self):
        # The firewall page omits the row-spanned model cell entirely rather
        # than blanking it.
        products, _excluded, _seen = parsed("NGFEOL")
        self.assertIn("F18 Rev. B", [entry["label"] for entry in products])

    def test_the_two_dated_columns_become_eos_and_eol_at_day_precision(self):
        entry = product("LBADCv50", "840 Rev A")
        self.assertEqual(entry["milestones"], {"ga": None, "eos": "2021-06-30",
                                               "eossec": None, "eol": "2024-06-30"})
        self.assertIsNone(entry["milestones"]["ga"])
        self.assertIsNone(entry["milestones"]["eossec"])

    def test_a_multi_model_cell_stays_one_record_with_the_vendors_label(self):
        entry = product("NGFEOL", "SC22, SC23 (3G/UMTS) Rev. A")
        self.assertEqual(entry["milestones"]["eol"], "2025-02-28")

    def test_the_products_own_line_comes_from_the_table_heading(self):
        # The firewall page carries an appliance table, a control-center table
        # and a modem table, and each names its own product.
        lines = {entry["product_line"] for entry in parsed("NGFEOL")[0]}
        self.assertIn("Barracuda CloudGen Firewall", lines)
        self.assertIn("Barracuda Modem", lines)

    def test_no_two_rows_publish_as_one_record(self):
        for space in PAGES:
            with self.subTest(space=space):
                products, _excluded, _seen = parsed(space)
                labels = [barracuda._identity(entry) for entry in products]
                self.assertEqual(len(set(labels)), len(labels))

    def test_the_firewall_permalinks_that_are_already_published_do_not_move(self):
        # These identities are live on the site; a reader's bookmark must keep
        # working across this collector's change in scope.
        for label, identity in (("SC20, SC21 Rev. A", "barracuda-sc20-sc21-rev-a"),
                                ("F18 Rev. B", "barracuda-f18-rev-b"),
                                ("F10 (EoL) Rev. A", "barracuda-f10-eol-rev-a")):
            with self.subTest(label=label):
                self.assertEqual(barracuda._identity(product("NGFEOL", label)), identity)


class RecordTests(unittest.TestCase):
    def test_a_record_states_the_vendors_eof_nuance_rather_than_a_total_eol(self):
        record = barracuda.record_for({**product("NGFEOL", "SC22, SC23 (3G/UMTS) Rev. A"),
                                       "id": "example"}, CHECKED)
        note = record["upstream"]["End of Firmware Support note"]["note"]
        self.assertIn("end of firmware support", note)
        self.assertIn("not completely End-of-Life", note)
        self.assertIn("2.0.10", record["upstream"]["EoFS (EoL: last supporting release)"]["text"])

    def test_status_comes_from_the_vendors_own_date(self):
        past = next(entry for entry in parsed("NGFEOL")[0]
                    if entry["milestones"]["eol"] and entry["milestones"]["eol"] < "2026-09-26")
        self.assertEqual(barracuda.record_for({**past, "id": "x"}, CHECKED)["status"], "eol")

    def test_the_report_accounts_for_every_space_and_row(self):
        products, excluded, pages = [], [], {}
        for space in PAGES:
            rows, refusals, _seen = parsed(space)
            products.extend(rows)
            excluded.extend(refusals)
            pages[space] = {"page_id": DISCOVERED[space]}
        report = barracuda.report_for(products, excluded, pages, CHECKED)
        self.assertEqual(report["rows"]["seen"], len(products) + len(excluded))
        self.assertEqual(report["total_records"], len(products))
        self.assertEqual(report["rows"]["spaces"], len(PAGES))
        self.assertEqual(report["rows"]["with_eol"],
                         sum(1 for p in products if p["milestones"]["eol"]))
        self.assertTrue(report["limitations"])


class DiscoveryTests(unittest.TestCase):
    def _space_pages(self, space, page_id, title, dated=True):
        body = {"body": {"view": {"value": f"<table><tr><th>Model</th></tr>"
                                          f"<tr><td>{'2020-01-01' if dated else 'x'}</td></tr>"
                                          f"</table>"}}}
        return {"results": [{"id": page_id, "title": title, **body},
                            {"id": "999", "title": "Deployment", **body}],
                "size": 2}

    def test_a_dated_page_is_found_by_walking_the_space(self):
        for space, title in (("LBADCv50", "Hardware End of Sale/End of Life"),
                             ("NGFEOL", "Barracuda NextGen and CloudGen Firewall Appliances - "
                                         "EoS / EoL Definitions")):
            with self.subTest(space=space):
                with mock.patch.object(barracuda, "_api",
                                       return_value=self._space_pages(space, "12345", title)):
                    self.assertEqual(barracuda.discover(space), ("12345", title))

    def test_a_page_without_dated_rows_is_not_taken_for_the_lifecycle_page(self):
        with mock.patch.object(barracuda, "_api",
                               return_value=self._space_pages("NGFEOL", "12345",
                                                              "EoS / EoL Definitions",
                                                              dated=False)):
            self.assertIsNone(barracuda.discover("NGFEOL"))

    def test_a_space_with_no_lifecycle_page_reports_nothing_found(self):
        with mock.patch.object(barracuda, "_api", return_value={"results": [], "size": 0}):
            self.assertIsNone(barracuda.discover("SEPPI"))

    def test_an_api_error_is_named_as_a_refusal(self):
        import urllib.error
        error = urllib.error.HTTPError("u", 503, "Unavailable", {}, None)
        with mock.patch.object(barracuda.net, "get_json", side_effect=error):
            with self.assertRaisesRegex(ValueError, "HTTP 503"):
                barracuda.discover("NGFEOL")


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
        def fake_api(url):
            for space, page_id in DISCOVERED.items():
                if f"spaceKey={space}" in url:
                    return {"results": [{"id": page_id, "title": TITLES[space],
                                         "body": {"view": {"value": html(space)}}}], "size": 1}
                if url.endswith(f"/{page_id}?expand=body.view"):
                    return {"body": {"view": {"value": html(space)}}}
            return {"results": [], "size": 0}

        with mock.patch.object(barracuda, "_api", side_effect=fake_api), \
                mock.patch.object(barracuda, "_now", return_value=checked):
            return sources.source("import-barracuda").run(self.root)

    def test_the_registered_source_publishes_every_space_and_one_report(self):
        detail = self.refresh()
        self.assertIn("Barracuda appliances across 4 product spaces", detail)
        published = sorted(path.stem for path in (self.root / "hardware").glob("barracuda-*.json"))
        self.assertGreater(len(published), 100)
        report = json.loads((self.root / barracuda.REPORT).read_text())
        self.assertEqual(report["total_records"], len(published))
        self.assertEqual(report["verifier"], barracuda.VERIFIER)
        self.assertEqual(sorted(report["spaces"]), sorted(PAGES))
        record = json.loads((self.root / "hardware" / (published[0] + ".json")).read_text())
        self.assertEqual(record["vendor"], "Barracuda")

    def test_a_quiet_refresh_republishes_byte_identical_files(self):
        self.refresh()
        published = self.snapshot()
        self.refresh("2026-09-27T01:00:00Z")
        self.assertEqual(self.snapshot(), published)

    def test_a_space_whose_dated_page_is_missing_refuses_the_run(self):
        with mock.patch.object(barracuda, "_api", return_value={"results": [], "size": 0}):
            with self.assertRaisesRegex(ValueError, "no dated end-of-support page"):
                barracuda.import_barracuda(self.root)
        self.assertEqual(set(self.snapshot()), {"manifest.json"})


if __name__ == "__main__":
    unittest.main()
