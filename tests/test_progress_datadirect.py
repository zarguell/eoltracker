"""Regression tests for the DataDirect driver collector (issue #130).

The three fixtures are the vendor's own documents, fetched 2026-09-26: the
life cycle page, the Product Life Cycle Policy Guide and the discontinued
products notice. No test reaches the network.

The page is awkward in three specific ways, and each is pinned here:

* **One date column, six shapes.** ``03-Jun-26``, ``01-July-25``, ``1-May-23``,
  ``10-Jun-2025``, ``6-Apr-2023`` and the month-only ``May-23`` all appear in the
  same column. The month-only cell is the one that matters: it must publish a
  month and never be widened into a day.
* **Two streams per row.** A driver states an Active and a Sunset release
  stream, and the Sunset group spans three columns of its own. A driver with no
  Active stream states a retirement date, a version and a date.
* **A stream retirement target that is not a support end.** The policy puts the
  stream's most recent release in the Sunset phase and its prior releases in the
  Retired phase, so the stream's target retirement date fills no milestone. That
  is the mistake this collector is most able to make, so it is tested directly.
"""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from engine import progress, sources
from engine.importer import dump, normalize
from engine.sources import ENDOFLIFE_DATE_API

FIXTURES = Path(__file__).parent / "fixtures"
PAGE = FIXTURES / "datadirect-life-cycle.html"
POLICY = FIXTURES / "datadirect-life-cycle-policy.pdf"
NOTICE = FIXTURES / "datadirect-dis-eol.pdf"
CHECKED = "2026-09-26T02:00:00Z"


def page_text():
    return PAGE.read_text(encoding="utf-8")


def parsed():
    return progress.parse_datadirect(page_text(),
                                     progress.pdf_text(POLICY.read_bytes(), "policy"),
                                     progress.pdf_text(NOTICE.read_bytes(), "notice"))


def driver(key):
    drivers, _excluded, _accounting = parsed()
    return drivers[key]


class DateGrammarTests(unittest.TestCase):
    """Every shape the page states, and the one that must stay a month."""

    def test_a_two_digit_year_day_is_read_at_the_precision_the_vendor_writes(self):
        self.assertEqual(progress.datadirect_date("03-Jun-26", "c"), "2026-06-03")
        self.assertEqual(progress.datadirect_date("02-Sep-26", "c"), "2026-09-02")

    def test_a_spelled_month_and_an_unpadded_day_are_the_same_grammar(self):
        self.assertEqual(progress.datadirect_date("01-July-25", "c"), "2025-07-01")
        self.assertEqual(progress.datadirect_date("1-May-23", "c"), "2023-05-01")
        self.assertEqual(progress.datadirect_date("6-Apr-2023", "c"), "2023-04-06")

    def test_a_four_digit_year_is_read_as_stated(self):
        self.assertEqual(progress.datadirect_date("10-Jun-2025", "c"), "2025-06-10")
        self.assertEqual(progress.datadirect_date("26-Jan-2027", "c"), "2027-01-26")

    def test_a_month_with_no_day_publishes_a_month_and_is_never_widened(self):
        # MongoDB ODBC states "May-23" as its stream retirement date. A day would
        # be a date the vendor never wrote (AGENTS.md rule 4).
        self.assertEqual(progress.datadirect_date("May-23", "c"), "2023-05")
        record = progress.datadirect_record(
            "mongodb-odbc", driver("MongoDB ODBC"),
            progress._datadirect_releases(driver("MongoDB ODBC"), None, "c"), None, CHECKED)
        sunset = next(r for r in record["releases"] if r["upstream"]["stream"].startswith("SUNSET"))
        self.assertEqual(sunset["upstream"]["cells"]["Stream Retirement Date"], "May-23")
        self.assertIsNone(sunset["milestones"]["eol"])
        for milestone in sunset["milestones"].values():
            self.assertNotEqual(milestone, "2023-05-31")

    def test_an_unknown_shape_refuses_rather_than_passing_as_unknown(self):
        for value in ("soon", "2026-06-03", "Jun 2026", "31-02-26", "2026"):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    progress.datadirect_date(value, "c")

    def test_a_no_date_token_publishes_nothing(self):
        for value in ("n/a", "N/A", "-", ""):
            with self.subTest(value=value):
                self.assertIsNone(progress.datadirect_date(value, "c"))


class StreamIdentityTests(unittest.TestCase):
    """A driver's two streams are two releases of one product, not two products."""

    def test_a_driver_with_both_streams_states_both_releases(self):
        releases = progress._datadirect_releases(driver("Apache Impala JDBC"), None, "c")
        self.assertEqual([r["id"] for r in releases], ["6.0.0.001491", "5.1.4.000130"])
        self.assertEqual([r["milestones"]["ga"] for r in releases],
                         ["2026-08-13", "2023-10-06"])
        self.assertEqual([r["upstream"]["stream"] for r in releases],
                         [progress.DATADIRECT_ACTIVE_HEADING, progress.DATADIRECT_SUNSET_HEADING])

    def test_a_driver_with_no_active_stream_states_only_its_sunset_release(self):
        releases = progress._datadirect_releases(driver("Btrieve ODBC"), None, "c")
        self.assertEqual([r["id"] for r in releases], ["07.12.0013"])
        self.assertEqual(releases[0]["milestones"]["ga"], "2025-09-30")

    def test_a_version_the_vendor_dates_not_at_all_publishes_no_ga(self):
        # XQuery states a version (5.0) and "n/a" for its date.
        releases = progress._datadirect_releases(driver("XQuery"), None, "c")
        self.assertEqual(releases[0]["id"], "5.0")
        self.assertIsNone(releases[0]["milestones"]["ga"])

    def test_the_two_product_tables_cover_disjoint_drivers(self):
        drivers, _excluded, accounting = parsed()
        tables = [entry for entry in accounting if entry["table"] != "platform footnote"]
        self.assertEqual([entry["drivers"] for entry in tables], [69, 24])
        self.assertEqual(len(drivers), 93)

    def test_a_driver_stated_in_both_tables_would_refuse(self):
        html = page_text()
        # Copy a whole data row out of the current-stream table and into the
        # end-of-support table: the same driver stated twice must refuse rather
        # than be published twice.
        import re
        rows = [m.group(0) for m in re.finditer(r"<tr>.*?</tr>", html, re.S)]
        stolen = next(row for row in rows if "Amazon Redshift JDBC" in row)
        index = html.rfind("<tr>")
        broken = html[:index] + stolen + html[index:]
        with self.assertRaisesRegex(ValueError, "stated in both product tables"):
            progress.parse_datadirect(
                broken, progress.pdf_text(POLICY.read_bytes(), "policy"),
                progress.pdf_text(NOTICE.read_bytes(), "notice"))


class RetirementMappingTests(unittest.TestCase):
    """The stream retirement target is a stream date, never a support end."""

    def test_a_stream_retirement_date_fills_no_milestone(self):
        releases = progress._datadirect_releases(driver("Apache Impala JDBC"), None, "c")
        sunset = releases[1]
        self.assertEqual(sunset["upstream"]["cells"]["Stream Retirement Date"], "20-Mar-25")
        self.assertEqual(sunset["milestones"],
                         {"ga": "2023-10-06", "eos": None, "eossec": None, "eol": None})
        self.assertIn("not this release's terminal support end",
                      sunset["upstream"]["retirement_note"])

    def test_a_record_that_fills_eol_from_the_retirement_target_is_rejected(self):
        record = progress.datadirect_record(
            "apache-impala-jdbc", driver("Apache Impala JDBC"),
            progress._datadirect_releases(driver("Apache Impala JDBC"), None, "c"), None, CHECKED)
        progress.validate_datadirect(record)
        sunset = record["releases"][1]
        sunset["milestones"]["eol"] = "2025-03-20"
        with self.assertRaisesRegex(ValueError, "claims an eol its own cells do not state"):
            progress.validate_datadirect(record)

    def test_a_sunset_release_may_not_claim_an_eossec(self):
        record = progress.datadirect_record(
            "apache-impala-jdbc", driver("Apache Impala JDBC"),
            progress._datadirect_releases(driver("Apache Impala JDBC"), None, "c"), None, CHECKED)
        record["releases"][1]["milestones"]["eossec"] = "2024-01-01"
        with self.assertRaisesRegex(ValueError, "eos or eossec this source never states"):
            progress.validate_datadirect(record)

    def test_a_hand_edited_release_date_is_re_derived_and_rejected(self):
        record = progress.datadirect_record(
            "apache-impala-jdbc", driver("Apache Impala JDBC"),
            progress._datadirect_releases(driver("Apache Impala JDBC"), None, "c"), None, CHECKED)
        progress.validate_datadirect(record)
        record["releases"][0]["milestones"]["ga"] = "2020-01-01"
        with self.assertRaisesRegex(ValueError, "claims a ga its own cell does not state"):
            progress.validate_datadirect(record)


class NoticeTests(unittest.TestCase):
    """The discontinued notice is the only terminal date this source publishes."""

    def test_the_notice_states_one_date_for_three_products(self):
        notice, eol = progress._datadirect_dis(
            progress.pdf_text(NOTICE.read_bytes(), "notice"), "DataDirect")
        self.assertEqual(eol, "2024-11-30")
        self.assertEqual(notice["products"], ["DataDirect XML Converters", "DataDirect XQuery",
                                              "Stylus Studio XML"])
        self.assertEqual(notice["definition"], progress.DATADIRECT_DIS_MEANING)

    def test_a_driver_in_both_documents_keeps_both_dates(self):
        releases = progress._datadirect_releases(driver("XML Converters"), "2024-11-30", "c")
        self.assertEqual(releases[0]["milestones"]["eol"], "2024-11-30")
        # The table's stream retirement target stays, and is not the eol.
        self.assertEqual(releases[0]["upstream"]["cells"]["Stream Retirement Date"], "20-Feb-24")
        self.assertIn("different milestones", releases[0]["upstream"]["eol_source"])

    def test_a_notice_that_no_longer_names_its_products_refuses(self):
        # A PDF stores text in positioned runs, so the notice's own spelling is
        # "Stylus StudioXML"; that is what the collector reads and what a changed
        # notice would alter.
        broken = progress.pdf_text(NOTICE.read_bytes(), "notice")
        self.assertIn("Stylus StudioXML", broken)
        broken = broken.replace("Stylus StudioXML", "Some Other Product")
        with self.assertRaisesRegex(ValueError, "no longer states"):
            progress._datadirect_dis(broken, "DataDirect")

    def test_a_notice_without_its_date_refuses(self):
        broken = progress.pdf_text(NOTICE.read_bytes(), "notice").replace(
            "November 30, 2024", "an unannounced time")
        with self.assertRaisesRegex(ValueError, "states no effective date"):
            progress._datadirect_dis(broken, "DataDirect")

    def test_a_document_that_is_not_a_pdf_refuses(self):
        with self.assertRaisesRegex(ValueError, "served through the documentation viewer"):
            progress.pdf_text(b"<html>a viewer page</html>", "policy")

    def test_a_pdf_with_no_text_layer_refuses(self):
        import zlib
        payload = b"%PDF-1.4\n" + b"1 0 obj<</Length 0>>stream\n\nendstream endobj\n"
        with self.assertRaisesRegex(ValueError, "no readable text layer"):
            progress.pdf_text(payload, "policy")


class TableShapeTests(unittest.TestCase):
    """Both header rows, and the third-party table the page also states."""

    def test_the_sunset_group_spans_three_columns(self):
        self.assertEqual(progress.DATADIRECT_GROUP_LEAVES,
                         {progress.DATADIRECT_ACTIVE_HEADING: 2,
                          progress.DATADIRECT_SUNSET_HEADING: 3})
        doc = progress.parse_document(page_text())
        block = next(b for b in doc.blocks
                     if tuple(progress._fold(c["text"]) for c in b["rows"][0])
                     == progress.DATADIRECT_TABLE_LABELS)
        labels, _start, _flat = progress._datadirect_labels(block, "c")
        self.assertEqual(labels, tuple(name for name, _role in progress.DATADIRECT_COLUMNS))
        self.assertEqual(labels[4], "Stream Retirement Date")

    def test_a_renamed_leaf_refuses_the_table(self):
        html = page_text().replace("<th class=\"tg-red\">Stream Retirement Date</th>",
                                   "<th class=\"tg-red\">End of Life</th>", 1)
        with self.assertRaisesRegex(ValueError, "stream columns changed"):
            progress.parse_datadirect(
                html, progress.pdf_text(POLICY.read_bytes(), "policy"),
                progress.pdf_text(NOTICE.read_bytes(), "notice"))

    def test_a_removed_product_table_refuses_the_page(self):
        html = page_text()
        start = html.rfind("<table")
        end = html.find("</table>", start)
        with self.assertRaisesRegex(ValueError, "driver tables, expected the two"):
            progress.parse_datadirect(
                html[:start] + html[end:], progress.pdf_text(POLICY.read_bytes(), "policy"),
                progress.pdf_text(NOTICE.read_bytes(), "notice"))

    def test_the_third_party_rows_are_excluded_with_the_vendors_own_reason(self):
        _drivers, excluded, _accounting = parsed()
        self.assertEqual([row["component"] for row in excluded],
                         ["ICU All Platforms", "ICU Linux IA 64 and Linux PPC 32",
                          "ICU Windows, Linux, AIX, Solaris, Linux Z/OS 64, Linux PPC 64 and "
                          "Power 8 64 (Linux PPC Little Endian)", "Libcurl", "OpenLDAP",
                          "OpenSSL 3.5"])
        for row in excluded:
            self.assertIn("third-party components", row["reason"])

    def test_a_page_that_keeps_the_footnote_but_drops_every_mark_refuses(self):
        # The ``**`` mark is the vendor's only link between a driver row and its
        # platform limitation, so a page that keeps the footnote text and drops
        # every mark states a limitation nothing refers to.
        html = page_text().replace("**", "")
        with self.assertRaisesRegex(ValueError, "footnote mark"):
            progress.parse_datadirect(
                html, progress.pdf_text(POLICY.read_bytes(), "policy"),
                progress.pdf_text(NOTICE.read_bytes(), "notice"))

    def test_the_marked_drivers_are_named_so_the_limitation_is_visible(self):
        _drivers, _excluded, accounting = parsed()
        footnote = next(entry for entry in accounting if entry["table"] == "platform footnote")
        self.assertEqual(len(footnote["marked"]), 4)
        for name in footnote["marked"]:
            self.assertIn("OpenAccess SDK", name)
        self.assertEqual(footnote["quote"], progress.DATADIRECT_FOOTNOTE_QUOTE)

    def test_a_page_whose_vendor_sentence_is_gone_refuses(self):
        html = page_text().replace("General Availability (GA) to retirement",
                                   "its first release to its last")
        with self.assertRaisesRegex(ValueError, "no longer states"):
            progress.parse_datadirect(
                html, progress.pdf_text(POLICY.read_bytes(), "policy"),
                progress.pdf_text(NOTICE.read_bytes(), "notice"))

    def test_a_policy_that_no_longer_defines_the_streams_refuses(self):
        stored = progress.pdf_text(POLICY.read_bytes(), "policy")
        self.assertIn("Atany giventime", stored)
        policy = stored.replace("Atany giventime", "At some later point", 1)
        with self.assertRaisesRegex(ValueError, "no longer states"):
            progress.parse_datadirect(page_text(), policy,
                                     progress.pdf_text(NOTICE.read_bytes(), "notice"))


class IdentityTests(unittest.TestCase):
    def test_the_vendors_marked_name_and_the_notices_name_are_one_product(self):
        # The page writes "Progress® DataDirect® XML Converters®"; the notice
        # writes "DataDirect XML Converters". They must be the same driver.
        self.assertEqual(progress._datadirect_identity("Progress® DataDirect® XML Converters®",
                                                       "x"), "XML Converters")
        self.assertEqual(progress._datadirect_identity("DataDirect XML Converters", "x"),
                         "XML Converters")
        self.assertEqual(progress._datadirect_identity("Stylus Studio XML", "x"),
                         "Stylus Studio XML")

    def test_a_punctuated_name_still_yields_a_catalog_id(self):
        self.assertEqual(progress._datadirect_id("Aha! JDBC"), "datadirect-aha-jdbc")
        self.assertEqual(progress._datadirect_id("SequeLink 6.0 ODBC Socket 64-bit"),
                         "datadirect-sequelink-6-0-odbc-socket-64-bit")


class PublicationTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        (self.root / "products").mkdir()
        (self.root / "hardware").mkdir()
        # The manifest describes the endoflife.date snapshot and requires at
        # least one record; a DataDirect record is an additive shard owned by
        # this source and is never counted into the importer's totals. The staged
        # sibling record stands in for the importer's own catalog.
        sibling = normalize({"result": {"name": "sample", "label": "Sample", "category": "lang",
                                        "labels": {},
                                        "releases": [{"name": "1", "releaseDate": "2026-01-01"}]}},
                            CHECKED)
        dump(self.root / "products/sample.json", sibling)
        dump(self.root / "manifest.json", {"generated_at": CHECKED,
                                           "source_url": ENDOFLIFE_DATE_API,
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

        def fake_get(url):
            if url == progress.DATADIRECT_URL:
                return Response(PAGE.read_bytes())
            if url == progress.DATADIRECT_POLICY_URL:
                return Response(POLICY.read_bytes())
            if url == progress.DATADIRECT_DIS_URL:
                return Response(NOTICE.read_bytes())
            raise AssertionError(f"unexpected fetch: {url}")

        def fake_get_text(url, encoding=None):
            return page_text()

        with mock.patch.object(progress.net, "get", side_effect=fake_get), \
                mock.patch.object(progress.net, "get_text", side_effect=fake_get_text), \
                mock.patch.object(progress, "_now", return_value=checked):
            return sources.source("import-progress-datadirect").run(self.root)

    def test_the_registered_source_publishes_one_record_per_driver(self):
        detail = self.refresh()
        self.assertIn("94 DataDirect drivers", detail)
        published = sorted((self.root / "products").glob("datadirect-*.json"))
        self.assertEqual(len(published), 94)
        report = json.loads((self.root / progress.DATADIRECT_REPORT).read_text())
        self.assertEqual(report["rows"], {"seen": 99, "published": 93, "retained": 0,
                                          "excluded": 6, "notice_only": 1})
        self.assertEqual(report["notice_only"], ["Stylus Studio XML"])
        footnote = next(entry for entry in report["tables"]
                        if entry["table"] == "platform footnote")
        self.assertEqual(len(footnote["marked"]), 4)
        self.assertEqual(report["end_of_life_notice"]["eol"], "2024-11-30")
        self.assertEqual(report["verifier"], progress.DATADIRECT_VERIFIER)
        for record in published:
            progress.validate_datadirect(json.loads(record.read_text()))

    def test_a_quiet_refresh_republishes_byte_identical_files(self):
        self.refresh()
        published = self.snapshot()
        self.refresh("2026-09-27T02:00:00Z")
        self.assertEqual(self.snapshot(), published)

    def test_a_page_that_is_not_the_lifecycle_page_writes_nothing(self):
        with mock.patch.object(progress.net, "get_text", return_value="<html>gone</html>"), \
                mock.patch.object(progress.net, "get") as get:
            get.return_value = type("R", (), {"content": b"<html>viewer</html>"})()
            with self.assertRaises(ValueError):
                progress.import_datadirect(self.root)
        self.assertEqual(set(self.snapshot()),
                         {"manifest.json", "products/sample.json"})


if __name__ == "__main__":
    unittest.main()
