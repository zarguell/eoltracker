"""XenServer collector regression tests.

The fixtures are the vendor's pages saved verbatim on 2026-09-23:
``xenserver-support.html`` (the current xenserver.com product matrix: 2 lines)
and ``xenserver-ctx692513.html`` (Citrix support article CTX692513, stating the
Citrix Hypervisor 8.2 Cumulative Update 1 end of life). The legacy Citrix
matrix is the already-committed ``netscaler-legacy.html``, whose XenServer,
XenSource XenServer and Citrix Hypervisor tabs this collector reads.

Synthetic minimal pages exercise refusal paths without depending on fixture
byte offsets.
"""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from engine.importer import API, dump, normalize

from engine import xenserver

FIXTURES = Path(__file__).parent / "fixtures"
CURRENT = (FIXTURES / "xenserver-support.html").read_text()
LEGACY = (FIXTURES / "netscaler-legacy.html").read_text()
STATEMENT = (FIXTURES / "xenserver-ctx692513.html").read_text()


def parsed():
    return xenserver.parse_releases(CURRENT, LEGACY, STATEMENT)


def current_page(*rows, header=None):
    """A minimal xenserver.com matrix: the vendor's header set and given rows."""
    head = header or ("Product", "Version", "Language", "NSC", "EOS", "EOM & EOL", "Notes")
    cells = "".join(f"<th>{name}</th>" for name in head)
    return f"<div class='ctx-table-container'><table><tr>{cells}</tr>{''.join(rows)}</table></div>"


def current_row(version, eol="07-31-2031", eos="NA", nsc="02-07-2026", product="XenServer"):
    return (f"<tr><td>{product}</td><td>{version}</td><td>EN</td><td>{nsc}</td>"
            f"<td>{eos}</td><td>{eol}</td><td>XenServer specific licence required</td></tr>")


def legacy_page(tab, *rows, header=None):
    """A minimal Citrix legacy matrix: one labelled tab and its given rows."""
    if header is None:
        header = ("Product/Component Name", "Version/Model", "Language", "NSC",
                  "EOS", "EOM", "EOL", "EOES")
    head = "".join(f"<th>{name}</th>" for name in header)
    return (f'<div class="ctx-tab"><span class="tab-text " >{tab}</span>'
            f"<table><tr>{head}</tr>{''.join(rows)}</table></div>")


class InventoryTests(unittest.TestCase):
    def test_the_three_pages_yield_twenty_nine_lines(self):
        releases, excluded, statement = parsed()
        self.assertEqual(len(releases), 29)
        self.assertEqual(excluded, [])
        self.assertEqual(statement["article"], "CTX692513")

    def test_current_lines_match_the_vendor_cells(self):
        by_id = {r["id"]: r for r in parsed()[0]}
        # The current matrix writes MM-DD-YYYY; 07-31-2031 establishes the
        # order, so 02-07-2026 is 2026-07-02, not February 7.
        self.assertEqual(by_id["9"]["milestones"],
                         {"ga": None, "eos": None, "eossec": None, "eol": "2031-07-31"})
        self.assertEqual(by_id["9"]["upstream"]["cells"]["NSC"], "02-07-2026")
        self.assertEqual(by_id["8.4"]["milestones"],
                         {"ga": None, "eos": "2024-06-03", "eossec": None,
                          "eol": "2028-11-30"})
        self.assertEqual(by_id["8.4"]["upstream"]["cells"]["EOM & EOL"], "11-30-2028")

    def test_xenserver_8_and_8_4_are_one_line(self):
        # The vendor states XenServer 8 is XenServer 8.4 under the hood, so the
        # catalog publishes one 8.4 line and never a separate "8".
        ids = {r["id"] for r in parsed()[0]}
        self.assertIn("8.4", ids)
        self.assertNotIn("8", ids)

    def test_historical_lines_keep_their_explicit_dates(self):
        by_id = {r["id"]: r for r in parsed()[0]}
        self.assertEqual(by_id["8.2-ltsr"]["milestones"]["eol"], "2025-06-25")
        self.assertEqual(by_id["8.1-cr"]["milestones"]["eol"], "2020-12-17")
        self.assertEqual(by_id["8.0-cr"]["milestones"]["eol"], "2020-08-31")
        self.assertEqual(by_id["7.6-cr"]["milestones"]["eol"], "2020-01-10")
        self.assertEqual(by_id["7.1-ltsr"]["milestones"]["eol"], "2022-08-15")

    def test_releases_are_ordered_newest_line_first(self):
        releases, _, _ = parsed()
        majors = [int(r["id"].split(".")[0].split("-")[0]) for r in releases]
        self.assertEqual(majors, sorted(majors, reverse=True))
        self.assertEqual(releases[0]["id"], "9")


class StatementTests(unittest.TestCase):
    def test_the_article_states_the_8_2_terminal_date(self):
        _, _, statement = parsed()
        self.assertEqual(statement["quote"],
                         "Citrix Hypervisor 8.2 Cumulative Update 1 becomes End of "
                         "Life on June 25, 2025.")
        self.assertEqual(xenserver._statement_date(statement["quote"]), "2025-06-25")

    def test_the_statement_is_retained_beside_the_legacy_row(self):
        releases, _, statement = parsed()
        line = next(r for r in releases if r["id"] == "8.2-ltsr")
        self.assertEqual(line["upstream"]["table"], "Citrix Hypervisor tab")
        self.assertEqual(line["upstream"]["statement"], statement)

    def test_a_disagreeing_statement_refuses_the_parse(self):
        # The legacy row states 25-Jun-25; an article stating another day is a
        # source contradiction, not a value to silently prefer.
        article = STATEMENT.replace("June 25, 2025", "June 26, 2025")
        with self.assertRaisesRegex(ValueError, "the two sources disagree"):
            xenserver.parse_releases(CURRENT, LEGACY, article)

    def test_a_missing_statement_refuses_the_parse(self):
        with self.assertRaisesRegex(ValueError, "no recognized Citrix Hypervisor 8.2"):
            xenserver.parse_releases(CURRENT, LEGACY, "<html>Article moved</html>")

    def test_a_line_absent_from_the_legacy_matrix_is_published_from_the_statement(self):
        legacy = LEGACY.replace("8.2 LTSR", "8.9 LTSR")
        releases, excluded, statement = xenserver.parse_releases(CURRENT, legacy, STATEMENT)
        line = next(r for r in releases if r["id"] == "8.2-ltsr")
        self.assertEqual(line["milestones"]["eol"], "2025-06-25")
        self.assertEqual(line["upstream"]["table"], xenserver.STATEMENT_TABLE)
        # The statement-only line is still accounted: the per-table counts sum
        # to every source row this fetch saw.
        report = xenserver.report_for(releases, excluded, [], statement,
                                      "2026-09-23T00:00:00Z")
        self.assertEqual(sum(t["rows"] for t in report["tables"]), report["rows"]["seen"])
        self.assertEqual([t["table"] for t in report["tables"]][-1],
                         xenserver.STATEMENT_TABLE)


class MilestoneSemanticsTests(unittest.TestCase):
    def test_nsc_is_never_general_availability(self):
        releases, _, _ = parsed()
        self.assertTrue(all(r["milestones"]["ga"] is None for r in releases))

    def test_eom_and_eoes_never_fill_a_normalized_milestone(self):
        releases, _, _ = parsed()
        self.assertTrue(all(r["milestones"]["eossec"] is None for r in releases))
        # The 8.2 LTSR row states an EOM (03-Jun-24) and an EOES, but neither
        # fills eol: eol is the row's own EOL cell, and eossec stays null.
        line = next(r for r in releases if r["id"] == "8.2-ltsr")
        self.assertEqual(line["upstream"]["cells"]["EOM"], "03-Jun-24")
        self.assertEqual(line["upstream"]["cells"]["EOES"], "N/A")
        self.assertEqual(line["milestones"]["eol"], "2025-06-25")
        # 7.0 CR states both an EOM and an EOL, and eol keeps the EOL cell.
        line = next(r for r in releases if r["id"] == "7.0-cr")
        self.assertEqual(line["upstream"]["cells"]["EOM"], "19-May-19")
        self.assertEqual(line["upstream"]["cells"]["EOL"], "19-May-21")
        self.assertEqual(line["milestones"]["eol"], "2021-05-19")

    def test_a_table_without_an_eos_column_publishes_no_sales_end(self):
        # The Citrix Hypervisor tab declares no EOS column, so its lines keep
        # eos null even though the 8.2 line's terminal date is known.
        by_id = {r["id"]: r for r in parsed()[0]}
        self.assertEqual(by_id["8.2-ltsr"]["upstream"]["cells"].get("EOS"), None)
        self.assertIsNone(by_id["8.2-ltsr"]["milestones"]["eos"])
        self.assertIsNone(by_id["8.0-cr"]["milestones"]["eos"])

    def test_na_and_blank_cells_state_no_date(self):
        self.assertIsNone(xenserver.date_value("N/A", "legacy", "test"))
        self.assertIsNone(xenserver.date_value("NA", "current", "test"))
        self.assertIsNone(xenserver.date_value("", "legacy", "test"))

    def test_edition_language_splits_are_kept_apart(self):
        # 6.0.0 EN/SC and JA state different end-of-sales dates; merging them
        # would lose one edition's date.
        by_id = {r["id"]: r for r in parsed()[0]}
        self.assertEqual(by_id["6.0.0"]["milestones"]["eos"], "2013-07-25")
        self.assertEqual(by_id["6.0.0-ja"]["milestones"]["eos"], "2013-09-23")
        self.assertEqual(by_id["6.0.0-ja"]["upstream"]["cells"]["Language"], "JA")

    def test_edition_ids_do_not_depend_on_the_vendors_row_order(self):
        # The same two rows in the opposite order must mint the same ids, so a
        # permalink survives the vendor reordering a table.
        first = ("XenServer tab / Current Release (CR) Lifecycle Dates",
                 "9.9", "EN, SC")
        second = ("XenServer tab / Current Release (CR) Lifecycle Dates", "9.9", "JA")
        self.assertEqual(xenserver._edition_ids([first, second]), ["9.9", "9.9-ja"])
        self.assertEqual(xenserver._edition_ids([second, first]), ["9.9-ja", "9.9"])

    def test_a_line_repeated_with_one_language_refuses(self):
        page = legacy_page(
            "XenServer",
            "<tr><td>XenServer</td><td>9.9</td><td>EN</td><td>N/A</td><td>N/A</td>"
            "<td>N/A</td><td>31-Dec-30</td><td>N/A</td></tr>"
            "<tr><td>XenServer</td><td>9.9</td><td>EN</td><td>N/A</td><td>N/A</td>"
            "<td>N/A</td><td>31-Dec-30</td><td>N/A</td></tr>")
        releases, _ = xenserver.parse_table(page, xenserver.BY_KEY[
            "XenServer tab / Current Release (CR) Lifecycle Dates"])
        with self.assertRaisesRegex(ValueError, "stated twice"):
            xenserver._id_lines(releases)

    def test_a_repeated_line_with_no_language_refuses(self):
        # A version stated twice with blank language cells cannot be told apart
        # as two editions, so it is a duplicate rather than two release rows.
        table = "XenServer tab / Current Release (CR) Lifecycle Dates"
        with self.assertRaisesRegex(ValueError, "no distinguishing language edition"):
            xenserver._edition_ids([(table, "9.9", ""), (table, "9.9", "")])


class AccountingTests(unittest.TestCase):
    def test_every_source_row_is_accounted_per_table(self):
        # Independent fixture inventory: header rows are not source data.
        releases, excluded, _ = parsed()
        expected = {
            "XenServer product matrix": 2,
            "Citrix Hypervisor tab": 3,
            "XenServer tab / Current Release (CR) Lifecycle Dates": 19,
            "XenServer tab / Long Term Service Release (LTSR) Lifecycle Dates": 1,
            "XenSource XenServer tab": 4,
        }
        seen = {key: 0 for key in expected}
        for release in releases:
            seen[release["upstream"]["table"]] += 1
        self.assertEqual(seen, expected)
        self.assertEqual(sum(seen.values()) + len(excluded), 29)

    def test_report_counts_agree_with_the_parsed_rows(self):
        releases, excluded, statement = parsed()
        report = xenserver.report_for(releases, excluded, [], statement,
                                      "2026-09-23T00:00:00Z")
        self.assertEqual(report["rows"],
                         {"seen": 29, "published": 29, "retained": 0, "excluded": 0})
        self.assertEqual(sum(t["rows"] for t in report["tables"]), 29)
        self.assertEqual(report["total_records"], 1)

    def test_a_row_outside_the_product_scope_is_excluded_with_its_reason(self):
        page = legacy_page(
            "XenServer",
            f"<tr><td>XenCenter</td><td>8.2</td><td>EN</td><td>N/A</td><td>N/A</td>"
            f"<td>N/A</td><td>15-Aug-22</td><td>N/A</td></tr>")
        releases, excluded = xenserver.parse_table(page, xenserver.BY_KEY[
            "XenServer tab / Current Release (CR) Lifecycle Dates"])
        self.assertEqual(releases, [])
        self.assertEqual(len(excluded), 1)
        self.assertIn("outside the XenServer hypervisor scope", excluded[0]["reason"])

    def test_a_grouping_row_without_a_version_is_excluded(self):
        page = current_page("<tr><td>XenServer</td><td></td><td>EN</td><td>N/A</td>"
                            "<td>NA</td><td>NA</td><td></td></tr>")
        releases, excluded = xenserver.parse_table(page, xenserver.TABLES[0])
        self.assertEqual(releases, [])
        self.assertIn("states no version", excluded[0]["reason"])


class DriftTests(unittest.TestCase):
    def test_a_renamed_current_column_refuses_the_parse(self):
        page = CURRENT.replace("<th scope=\"col\" style=\"text-align: center;\">EOS</th>",
                               "<th>Sales end</th>")
        with self.assertRaisesRegex(ValueError, "XenServer product matrix"):
            xenserver.parse_releases(page, LEGACY, STATEMENT)

    def test_a_renamed_legacy_tab_refuses_the_parse(self):
        with self.assertRaisesRegex(ValueError, "Citrix Hypervisor tab"):
            xenserver.parse_releases(CURRENT,
                                     LEGACY.replace(">Citrix Hypervisor<sup>", ">Renamed<sup>"),
                                     STATEMENT)

    def test_the_two_tables_of_the_xenserver_tab_are_not_interchangeable(self):
        # The CR table declares EOS; the LTSR table declares Notes. Reading both
        # with one header set would silently mis-model one of them.
        cr = xenserver.BY_KEY["XenServer tab / Current Release (CR) Lifecycle Dates"]
        ltsr = xenserver.BY_KEY["XenServer tab / Long Term Service Release (LTSR) Lifecycle Dates"]
        self.assertNotEqual(cr.headers, ltsr.headers)

    def test_an_impossible_day_refuses_the_parse(self):
        self.assertEqual(xenserver.date_value("08-Aug-30", "legacy", "test"), "2030-08-08")
        self.assertEqual(xenserver.date_value("07-31-2031", "current", "test"), "2031-07-31")
        with self.assertRaises(ValueError):
            xenserver.date_value("31-Feb-30", "legacy", "test")
        with self.assertRaises(ValueError):
            xenserver.date_value("13-31-2031", "current", "test")

    def test_the_wrong_page_for_a_table_refuses_the_parse(self):
        with self.assertRaisesRegex(ValueError, "matched"):
            xenserver.parse_releases(LEGACY, LEGACY, STATEMENT)


class ReDerivationTests(unittest.TestCase):
    def record(self):
        return xenserver.record_for(parsed()[0], "2026-09-23T00:00:00Z")

    def release(self, record, line_id):
        return next(r for r in record["releases"] if r["id"] == line_id)

    def test_tampered_eol_is_refused(self):
        record = self.record()
        self.release(record, "8.1-cr")["milestones"]["eol"] = "2099-01-01"
        with self.assertRaisesRegex(ValueError, "eol contradicts its stored cells"):
            xenserver.validate_record(record)

    def test_tampered_eos_is_refused(self):
        record = self.record()
        self.release(record, "8.4")["milestones"]["eos"] = "2099-01-01"
        with self.assertRaisesRegex(ValueError, "eos contradicts its stored cells"):
            xenserver.validate_record(record)

    def test_invented_ga_is_refused(self):
        record = self.record()
        self.release(record, "9")["milestones"]["ga"] = "2024-03-26"
        with self.assertRaisesRegex(ValueError, "general-availability date the vendor"):
            xenserver.validate_record(record)

    def test_invented_eossec_is_refused(self):
        record = self.record()
        self.release(record, "9")["milestones"]["eossec"] = "2031-01-01"
        with self.assertRaisesRegex(ValueError, "security-support end the source"):
            xenserver.validate_record(record)

    def test_a_tampered_statement_quote_is_refused(self):
        record = self.record()
        line = self.release(record, "8.2-ltsr")
        line["upstream"]["statement"]["quote"] = line["upstream"]["statement"]["quote"].replace(
            "June 25, 2025", "June 24, 2025")
        with self.assertRaisesRegex(ValueError, "contradicts the CTX692513 statement"):
            xenserver.validate_record(record)

    def test_a_release_naming_an_unknown_table_is_refused(self):
        record = self.record()
        self.release(record, "7.6-cr")["upstream"]["table"] = "Invented table"
        with self.assertRaisesRegex(ValueError, "does not name the vendor table"):
            xenserver.validate_record(record)

    def test_a_release_missing_a_column_is_refused(self):
        record = self.record()
        del self.release(record, "7.6-cr")["upstream"]["cells"]["EOES"]
        with self.assertRaisesRegex(ValueError, "does not carry its vendor table's columns"):
            xenserver.validate_record(record)

    def test_foreign_verifier_is_refused(self):
        record = self.record()
        record["provenance"]["verifier"] = "deterministic-something-else"
        with self.assertRaisesRegex(ValueError, "source identity"):
            xenserver.validate_record(record)


class OwnershipTests(unittest.TestCase):
    def test_foreign_record_is_refused(self):
        record = xenserver.record_for(parsed()[0], "2026-09-23T00:00:00Z")
        record["provenance"]["verifier"] = "deterministic-foreign"
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "products").mkdir()
            (root / "products" / "xenserver.json").write_text(
                json.dumps(record), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "ownership collision"):
                xenserver.committed_record(root)

    def test_absent_record_is_none(self):
        with tempfile.TemporaryDirectory() as temp:
            self.assertIsNone(xenserver.committed_record(Path(temp)))


class PublicationTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        sibling = normalize({"result": {"name": "sample", "label": "Sample",
                            "category": "lang", "labels": {},
                            "releases": [{"name": "1", "releaseDate": "2026-01-01"}]}},
                            "2026-09-23T00:00:00Z")
        dump(self.root / "products/sample.json", sibling)
        dump(self.root / "manifest.json", {
            "generated_at": "2026-09-23T00:00:00Z", "source_url": API,
            "source": "import-data", "product_count": 1, "release_count": 1,
            "excluded_hardware": []})

    def snapshot(self):
        return {str(p.relative_to(self.root)): p.read_bytes()
                for p in self.root.rglob("*.json")}

    def refresh(self, checked, current=CURRENT, legacy=LEGACY, statement=STATEMENT):
        with mock.patch.object(xenserver.net, "get_text",
                               side_effect=[current, legacy, statement]), \
                mock.patch.object(xenserver, "_now", return_value=checked):
            xenserver.import_xenserver(self.root)

    def test_published_record_is_valid_and_accounts_for_every_row(self):
        self.refresh("2026-09-23T01:00:00Z")
        record = json.loads((self.root / "products/xenserver.json").read_text())
        self.assertEqual(record["id"], "xenserver")
        self.assertEqual(record["provenance"]["verifier"], "deterministic-xenserver")
        self.assertEqual(len(record["releases"]), 29)
        report = json.loads((self.root / xenserver.REPORT).read_text())
        self.assertEqual(report["verifier"], "deterministic-xenserver")
        self.assertEqual(report["total_records"], 1)
        self.assertEqual(report["rows"]["seen"],
                         report["rows"]["published"] + report["rows"]["excluded"])

    def test_quiet_refresh_and_report_only_change_have_independent_revisions(self):
        self.refresh("2026-09-23T01:00:00Z")
        published = self.snapshot()
        self.refresh("2026-09-23T02:00:00Z")
        self.assertEqual(self.snapshot(), published)
        # The statement is the only row this source can exclude-free reword;
        # change the retention accounting instead by dropping a legacy line.
        legacy = LEGACY.replace("7.5 CR", "7.55 CR")
        self.refresh("2026-09-23T03:00:00Z", legacy=legacy)
        record = json.loads((self.root / "products/xenserver.json").read_text())
        self.assertIn("7.5-cr", {r["id"] for r in record["releases"]})
        report = json.loads((self.root / xenserver.REPORT).read_text())
        self.assertEqual(report["checked_at"], "2026-09-23T03:00:00Z")
        self.assertEqual([r["id"] for r in report["retained"]], ["7.5-cr"])

    def test_a_missing_line_is_retained_with_its_dates(self):
        self.refresh("2026-09-23T01:00:00Z")
        before = json.loads((self.root / "products/xenserver.json").read_text())
        # The current matrix stops stating 8.4 while keeping 9: the line keeps
        # its committed row and dates rather than disappearing from the catalog.
        current = current_page(current_row("9"))
        self.refresh("2026-09-23T02:00:00Z", current=current)
        record = json.loads((self.root / "products/xenserver.json").read_text())
        after = {r["id"]: r["milestones"] for r in record["releases"]}
        self.assertEqual(after["8.4"], {"ga": None, "eos": "2024-06-03", "eossec": None,
                                        "eol": "2028-11-30"})
        self.assertEqual(len(after), len(before["releases"]))
        report = json.loads((self.root / xenserver.REPORT).read_text())
        self.assertEqual(report["rows"]["retained"], 1)
        self.assertEqual([r["id"] for r in report["retained"]], ["8.4"])
        # A retained line is not a source row this fetch saw.
        self.assertEqual(report["rows"]["seen"], 28)
        self.assertEqual(report["rows"]["seen"],
                         report["rows"]["published"] + report["rows"]["excluded"])

    def test_foreign_record_refuses_import_before_network_and_writes_nothing(self):
        record = json.loads((self.root / "products/sample.json").read_text())
        record["id"] = "xenserver"
        dump(self.root / "products/xenserver.json", record)
        before = self.snapshot()
        with mock.patch.object(xenserver.net, "get_text") as fetch:
            with self.assertRaises(ValueError):
                xenserver.import_xenserver(self.root)
        fetch.assert_not_called()
        self.assertEqual(self.snapshot(), before)

    def test_parse_failure_leaves_existing_catalog_untouched(self):
        self.refresh("2026-09-23T01:00:00Z")
        before = self.snapshot()
        with self.assertRaises(ValueError):
            self.refresh("2026-09-23T02:00:00Z", current="<html>Changed layout</html>")
        self.assertEqual(self.snapshot(), before)

    def test_statement_disagreement_leaves_existing_catalog_untouched(self):
        self.refresh("2026-09-23T01:00:00Z")
        before = self.snapshot()
        with self.assertRaises(ValueError):
            self.refresh("2026-09-23T02:00:00Z",
                         statement=STATEMENT.replace("June 25, 2025", "July 25, 2025"))
        self.assertEqual(self.snapshot(), before)

    def test_invalid_sibling_report_prevents_publication(self):
        dump(self.root / "ceph-import.json", {"verifier": "deterministic-ceph",
                                              "total_records": 1})
        before = self.snapshot()
        with self.assertRaises(ValueError):
            self.refresh("2026-09-23T01:00:00Z")
        self.assertEqual(self.snapshot(), before)


if __name__ == "__main__":
    unittest.main()
