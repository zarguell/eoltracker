"""The IIS collector must publish Microsoft's own rows and nothing invented.

These tests pin the boundaries where a plausible mistake stays silent: a support
*start* mapped into ``ga``, a blank End Date filled from the wrong platform, a
numeric IIS version invented for Windows Server 2025, a Semi-Annual Channel row
given a date Microsoft never states, an inherited date recorded as if Microsoft
had stated it, a parent page's printed Pacific instant copied without the
last-full-day reading, and a row that silently disappears from the accounting.

The saved pages in ``tests/fixtures/microsoft-*.html`` are Microsoft Learn's own
rendering of the pages this source reads, so the parser is exercised offline
against the real table shapes rather than a synthesized approximation.
"""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from engine import derived, iis
from engine.importer import API, dump, normalize

FIXTURES = Path(__file__).parent / "fixtures"
# Each registered page and the saved page it is read from. Keyed by the URL the
# collector registered, so a fixture that no longer matches its page fails here.
PAGES = {
    iis.IIS_URL: "microsoft-iis-lifecycle.html",
    iis.FIXED_POLICY_URL: "microsoft-fixed-policy.html",
    iis.TUNING_URL: "microsoft-tuning-iis-10.html",
    iis.WINDOWS_SERVER_2022_URL: "microsoft-windows-server-2022.html",
    iis.IIS_ROLE_2025_URL: "microsoft-windows-server-2025-iis-role.html",
    iis.WINDOWS_SERVER_2025_URL: "microsoft-windows-server-2025.html",
    iis.WINDOWS_10_HOME_PRO_URL: "microsoft-windows-10-home-and-pro.html",
    iis.WINDOWS_10_ENTERPRISE_EDUCATION_URL:
        "microsoft-windows-10-enterprise-and-education.html",
}
CHECKED = "2026-09-23T00:00:00Z"


def html(url):
    return (FIXTURES / PAGES[url]).read_text(encoding="utf-8")


def pages():
    return {url: iis.Page(url, html(url)) for url in iis.PAGES}


def snapshot():
    """The complete published snapshot, from the saved pages."""
    parsed = pages()
    direct, excluded = iis.parse_page(parsed[iis.IIS_URL])
    releases, changes, parents = iis.complete(direct, parsed)
    return {"record": iis.record_for(releases, CHECKED),
            "report": iis.report_for(releases, excluded, changes, parents, CHECKED),
            "releases": releases, "excluded": excluded, "changes": changes, "parents": parents}


def rows():
    return {release["id"]: release for release in snapshot()["record"]["releases"]}


class DirectRowTests(unittest.TestCase):
    def test_every_direct_row_keeps_the_date_its_own_cell_states(self):
        # The twelve version rows of the IIS lifecycle table, with the End Date
        # each one states. A support Start Date is never published as `ga`.
        expected = {
            "iis-10-windows-server-2019": "2029-01-09",
            "iis-10-windows-server-semi-annual-channel": None,
            "iis-10-windows-server-2016": "2027-01-12",
            "iis-8-5-windows-server-2012-r2": "2023-10-10",
            "iis-8-5-windows-8-1": "2023-01-10",
            "iis-8-windows-server-2012": "2023-10-10",
            "iis-7-5-windows-server-2008-r2": "2020-01-14",
            "iis-7-5-windows-7": "2020-01-14",
            "iis-7-0-windows-server-2008": "2020-01-14",
            "iis-6-0-windows-server-2003": "2015-07-14",
        }
        published = rows()
        for release_id, eol in expected.items():
            release = published[release_id]
            self.assertEqual(release["milestones"]["eol"], eol, release_id)
            self.assertNotIn(derived.DERIVED_KEY, release, release_id)
        # A stated date is never described as derived, and the two undated rows
        # do not appear as stated dates.
        self.assertIsNone(published["iis-10-windows-server-semi-annual-channel"]["milestones"]["eol"])

    def test_no_row_publishes_a_release_sale_or_security_date(self):
        # The IIS table states a support Start Date and an End Date only: `ga`,
        # `eos` and `eossec` are unsupported by the source and stay absent.
        for release in snapshot()["record"]["releases"]:
            self.assertIsNone(release["milestones"]["ga"], release["id"])
            self.assertIsNone(release["milestones"]["eos"], release["id"])
            self.assertIsNone(release["milestones"]["eossec"], release["id"])

    def test_support_start_stays_a_raw_cell_and_never_becomes_ga(self):
        # The page's Start Date column is the start of support, so it stays the
        # vendor's own cell: mapping it into `ga` would publish a release date
        # Microsoft never states.
        release = rows()["iis-10-windows-server-2019"]
        self.assertEqual(release["upstream"]["cells"]["Start Date"], "11/13/2018 8:00:00 AM")
        self.assertIsNone(release["milestones"]["ga"])

    def test_end_instant_is_read_as_the_last_full_day_of_support(self):
        # Microsoft prints the instant support stops; the stored day is the one
        # before it, and the raw cell is retained verbatim beside the date.
        self.assertEqual(iis.end_day("1/10/2029 6:59:59 AM", "test"), "2029-01-09")
        self.assertEqual(iis.start_day("11/13/2018 8:00:00 AM", "test"), "2018-11-13")
        # A time that is not the reviewed end instant would move the last
        # supported day, so it refuses rather than becoming the printed day.
        with self.assertRaisesRegex(ValueError, "unreviewed end-of-support clock"):
            iis.end_day("1/10/2029 12:00:00 AM", "test")
        with self.assertRaisesRegex(ValueError, "unreviewed end-of-support clock"):
            iis.end_day("1/10/2029 7:00:00 AM", "test")
        self.assertIsNone(iis.end_day("", "test"))
        self.assertIsNone(iis.end_day("N/A", "test"))
        with self.assertRaises(ValueError):
            iis.end_day("31/02/2029 6:59:59 AM", "test")

    def test_an_impossible_clock_refuses_rather_than_becoming_a_day(self):
        # Every clock component is bounded. Before #107 the time was never
        # validated, so `99:99:99 AM` was read as the printed calendar day and
        # an impossible source value could move a support boundary silently.
        for cell in ("1/10/2029 99:99:99 AM", "1/10/2029 13:00:00 PM",
                     "1/10/2029 6:60:00 AM", "1/10/2029 6:59:60 AM",
                     "1/10/2029 0:00:00 AM", "1/10/2029 12:60:00 AM"):
            with self.assertRaisesRegex(ValueError, "impossible support clock"):
                iis.instant(cell, "test")
            with self.assertRaisesRegex(ValueError, "impossible support clock"):
                iis.end_day(cell, "test")

    def test_a_13_oclock_pm_cell_is_refused_at_the_hour_component(self):
        # 13:00 is declared PM, which is no 12-hour clock value: it refuses by
        # name rather than wrapping to 13:00 or reading as 1:00.
        with self.assertRaisesRegex(ValueError, "impossible support clock"):
            iis.instant("1/10/2029 13:00:00 PM", "test")

    def test_a_seven_am_end_cell_is_an_unreviewed_convention(self):
        # 7:00 AM is a real clock, so it passes the component bounds, but it is
        # not the reviewed end instant: accepting it as the printed day would
        # shift the last supported day by one.
        with self.assertRaisesRegex(ValueError, "unreviewed end-of-support clock"):
            iis.end_day("1/10/2029 7:00:00 AM", "test")
        with self.assertRaisesRegex(ValueError, "unreviewed end-of-support clock"):
            iis.end_day("1/10/2029 6:59:59 PM", "test")

    def test_a_start_cell_still_accepts_its_reviewed_clock(self):
        # The start convention (8:00:00 AM) is unchanged: the end convention is
        # the one that was reviewed, and the start's own bound is the clock's.
        self.assertEqual(iis.start_day("11/13/2018 8:00:00 AM", "test"), "2018-11-13")
        with self.assertRaisesRegex(ValueError, "impossible support clock"):
            iis.start_day("11/13/2018 8:00:99 AM", "test")

    def test_the_footnote_marker_is_not_part_of_a_version_name(self):
        # Three rows carry the page's ESU footnote asterisk; the marker belongs
        # to the page's tip, so the published name and id drop it while the raw
        # cell keeps it verbatim.
        release = rows()["iis-7-5-windows-7"]
        self.assertEqual(release["name"], "IIS 7.5 on Windows 7")
        self.assertEqual(release["upstream"]["name"], "IIS 7.5 on Windows 7*")


class InheritedScopeTests(unittest.TestCase):
    def test_omitted_platforms_inherit_the_parent_platform_terminal_date(self):
        published = rows()
        # Windows Server 2022 is absent from the IIS table entirely; the IIS 10.0
        # tuning page names the scope and its parent page states the date.
        self.assertEqual(published["iis-10-windows-server-2022"]["milestones"]["eol"], "2031-10-14")
        self.assertEqual(published["web-server-iis-windows-server-2025"]["milestones"]["eol"],
                         "2034-11-14")
        for release_id in ("iis-10-windows-server-2022", "web-server-iis-windows-server-2025"):
            entry = published[release_id][derived.DERIVED_KEY]["eol"]
            self.assertEqual(entry["method"], "support-inheritance")
            self.assertEqual(entry["kind"], "derived")
            self.assertEqual(entry["parent"]["date"], published[release_id]["milestones"]["eol"])

    def test_undated_rows_inherit_from_the_windows_10_lifecycle_the_note_links(self):
        published = rows()
        for release_id in ("iis-10-windows-10-pro",
                           "iis-10-windows-10-enterprise-and-education"):
            release = published[release_id]
            self.assertEqual(release["milestones"]["eol"], "2025-10-14")
            # The vendor's own row still states no End Date: the blank cell is
            # kept verbatim rather than overwritten with the derived date.
            self.assertEqual(release["upstream"]["cells"]["End Date"], "")
            self.assertEqual(release["upstream"]["table"], iis.RELEASES_TABLE)
        self.assertEqual(
            published["iis-10-windows-10-pro"][derived.DERIVED_KEY]["eol"]["parent"]["source_url"],
            iis.WINDOWS_10_HOME_PRO_URL)
        self.assertEqual(
            published["iis-10-windows-10-enterprise-and-education"][derived.DERIVED_KEY]["eol"]
            ["parent"]["source_url"], iis.WINDOWS_10_ENTERPRISE_EDUCATION_URL)

    def test_windows_server_2025_carries_no_invented_iis_version(self):
        # Microsoft states the role, never a numeric IIS version, for Windows
        # Server 2025: neither the release's name, nor its id, nor any stored
        # text may assert one.
        release = rows()["web-server-iis-windows-server-2025"]
        self.assertEqual(release["name"], "Web Server (IIS) on Windows Server 2025")
        blob = json.dumps(release)
        for invented in ("IIS 10 on Windows Server 2025", "IIS 10.0 on Windows Server 2025",
                         "iis-10-windows-server-2025"):
            self.assertNotIn(invented, blob)

    def test_a_fixed_policy_parent_is_covered_by_the_fixed_policy_rule(self):
        # The Fixed Policy's component rule is what licenses inheriting from a
        # Fixed-policy platform; a Modern-policy parent is not covered by it, so
        # the IIS component sentence is stored instead.
        published = rows()
        fixed = published["iis-10-windows-server-2022"][derived.DERIVED_KEY]["eol"]
        self.assertEqual(fixed["source_url"], iis.FIXED_POLICY_URL)
        self.assertEqual(fixed["quote"], iis.FIXED_POLICY_QUOTE)
        modern = published["iis-10-windows-10-pro"][derived.DERIVED_KEY]["eol"]
        self.assertEqual(modern["source_url"], iis.IIS_URL)
        self.assertEqual(modern["quote"], iis.COMPONENT_QUOTE)

    def test_the_inherited_parent_dates_match_the_committed_catalog(self):
        # The last-full-day reading is what makes the inherited dates agree with
        # the committed Windows Server records; a reader comparing the two sees
        # one date, not a silent off-by-one.
        import json

        committed = json.loads((Path(__file__).resolve().parents[1]
                                / "data/products/windows-server.json").read_text())
        by_id = {release["id"]: release for release in committed["releases"]}
        for release_id, parent in (("iis-10-windows-server-2022", "2022"),
                                   ("web-server-iis-windows-server-2025", "2025")):
            entry = rows()[release_id][derived.DERIVED_KEY]["eol"]
            self.assertEqual(entry["parent"]["date"], by_id[parent]["upstream"]["eolFrom"])
            self.assertEqual(entry["parent"]["product_id"], "windows-server")
            self.assertEqual(entry["parent"]["release_id"], parent)

    def test_an_omitted_platform_row_the_table_gains_is_published_as_stated(self):
        # Microsoft adding the Windows Server 2022 row to its own table is the
        # expected fix on their side: the vendor's row then wins and the derived
        # row is gone, not duplicated.
        row = ("<tr>\n\t\t\t\t\t\t\t<td>IIS 10 on Windows Server 2022</td>\n"
               "\t\t\t\t\t\t\t<td align=\"right\">\n"
               "\t\t\t\t\t\t\t\t<local-time timezone=\"America/Los_Angeles\" format=\"date\" "
               "datetime=\"8/18/2021 8:00:00 AM\">8/18/2021 8:00:00 AM</local-time>\n"
               "\t\t\t\t\t\t\t</td>\n\t\t\t\t\t\t\t<td align=\"right\">\n"
               "\t\t\t\t\t\t\t\t<local-time timezone=\"America/Los_Angeles\" format=\"date\" "
               "datetime=\"10/15/2031 6:59:59 AM\">10/15/2031 6:59:59 AM</local-time>\n"
               "\t\t\t\t\t\t\t</td>\n\t\t\t\t\t\t</tr>")
        anchor = "<tbody>\n\t\t\t\t\t\t<tr>"
        self.assertEqual(html(iis.IIS_URL).count(anchor), 1)
        amended = html(iis.IIS_URL).replace(anchor, anchor + row, 1)
        self.assertIn(row, amended)
        parsed = pages()
        parsed[iis.IIS_URL] = iis.Page(iis.IIS_URL, amended)
        direct, excluded = iis.parse_page(parsed[iis.IIS_URL])
        releases, changes, parents = iis.complete(direct, parsed)
        published = {release["id"]: release for release in releases}
        stated = published["iis-10-windows-server-2022"]
        self.assertEqual(stated["milestones"]["eol"], "2031-10-14")
        self.assertNotIn(derived.DERIVED_KEY, stated)
        self.assertEqual(stated["upstream"]["table"], iis.RELEASES_TABLE)
        self.assertEqual([change["state"] for change in changes
                          if change["id"] == "iis-10-windows-server-2022"], ["stated-by-source"])
        # No duplicate row was published for the same platform.
        self.assertEqual(sum(1 for release in releases
                             if release["name"] == "IIS 10 on Windows Server 2022"), 1)

    def test_an_undated_row_that_gains_its_own_date_is_published_as_stated(self):
        # The vendor's own date always wins over a derivation: when the table
        # starts stating an End Date, the row is published as stated and nothing
        # is derived beside it.
        amended = html(iis.IIS_URL).replace(
            '<td>IIS 10 on Windows 10 Pro</td>',
            '<td>IIS 10 on Windows 10 Pro</td>').replace(
            'datetime="7/29/2015 8:00:00 AM">7/29/2015 8:00:00 AM</local-time>\n'
            '\t\t\t\t\t\t\t</td>\n\t\t\t\t\t\t\t<td align="right">\n'
            '\t\t\t\t\t\t\t\t<local-time timezone="America/Los_Angeles" format="date" '
            'datetime=""></local-time>\n\t\t\t\t\t\t\t</td>',
            'datetime="7/29/2015 8:00:00 AM">7/29/2015 8:00:00 AM</local-time>\n'
            '\t\t\t\t\t\t\t</td>\n\t\t\t\t\t\t\t<td align="right">\n'
            '\t\t\t\t\t\t\t\t<local-time timezone="America/Los_Angeles" format="date" '
            'datetime="10/14/2032 6:59:59 AM">10/14/2032 6:59:59 AM</local-time>\n'
            '\t\t\t\t\t\t\t</td>')
        self.assertNotEqual(amended, html(iis.IIS_URL))
        parsed = pages()
        parsed[iis.IIS_URL] = iis.Page(iis.IIS_URL, amended)
        direct, excluded = iis.parse_page(parsed[iis.IIS_URL])
        releases, changes, parents = iis.complete(direct, parsed)
        published = {release["id"]: release for release in releases}
        release = published["iis-10-windows-10-pro"]
        self.assertEqual(release["milestones"]["eol"], "2032-10-13")
        self.assertNotIn(derived.DERIVED_KEY, release)
        states = [change["state"] for change in changes
                  if change["id"] == "iis-10-windows-10-pro"]
        self.assertEqual(states, ["stated-by-source"])


class AmbiguousScopeTests(unittest.TestCase):
    def test_semi_annual_channel_stays_unknown(self):
        release = rows()["iis-10-windows-server-semi-annual-channel"]
        self.assertIsNone(release["milestones"]["eol"])
        self.assertNotIn(derived.DERIVED_KEY, release)
        self.assertEqual(release["upstream"]["cells"]["End Date"], "")

    def test_no_supported_scope_is_silently_dropped(self):
        # The current branches, checked by the platform each names rather than by
        # an id, so a renamed id cannot hide a missing platform.
        platforms = {release["name"] for release in snapshot()["record"]["releases"]}
        for required in ("IIS 10 on Windows Server 2022", "Web Server (IIS) on Windows Server 2025",
                         "IIS 10 on Windows Server (Semi-Annual Channel)",
                         "IIS 10 on Windows 10 Pro",
                         "IIS 10 on Windows 10, Enterprise and Education"):
            self.assertIn(required, platforms)

    def test_out_of_scope_products_are_absent(self):
        # IIS Express, the add-on modules, Web Deploy and WebPI are separate
        # products with their own lifecycle; none is a row of this table.
        blob = json.dumps(snapshot()["record"]).lower()
        for out_of_scope in ("express", "arr", "url rewrite", "web deploy", "webpi",
                             "web platform installer", "administration api"):
            self.assertNotIn(out_of_scope, blob)


class AccountingTests(unittest.TestCase):
    def test_every_source_row_is_accounted_for(self):
        # Independently counted from the saved page: one product-level Support
        # Dates row plus twelve version rows.
        data = snapshot()
        self.assertEqual(len(data["excluded"]), 1)
        self.assertEqual(len(data["record"]["releases"]) - 2, 12)
        self.assertEqual(data["report"]["rows"]["seen"],
                         data["report"]["rows"]["direct"] + data["report"]["rows"]["excluded"])
        self.assertEqual(data["report"]["rows"]["seen"], 13)
        self.assertEqual(data["report"]["rows"]["published"],
                         data["report"]["rows"]["direct"] + data["report"]["rows"]["derived"]
                         + data["report"]["rows"]["retained"])
        self.assertTrue(data["excluded"][0]["reason"])
        self.assertIn("See Note", data["excluded"][0]["row"])

    def test_the_report_names_every_page_it_read(self):
        report = snapshot()["report"]
        self.assertEqual([page["url"] for page in report["pages"]], list(iis.PAGES))
        for page in report["pages"]:
            self.assertTrue(page["label"])

    def test_every_inherited_row_names_its_scope_and_its_parent(self):
        report = snapshot()["report"]
        kinds = {entry["kind"] for entry in report["derived"]}
        self.assertEqual(kinds, {"undated-row", "omitted-platform"})
        for entry in report["derived"]:
            self.assertEqual(entry["state"], "inherited")
            self.assertIn("IIS", entry["scope"]["quote"])
            self.assertEqual(entry["parent"]["date"], entry["date"])
            self.assertTrue(entry["parent"]["cells"])
            self.assertTrue(entry["parent"]["policy"])
        self.assertEqual(report["total_records"], 1)


class ReDerivationTests(unittest.TestCase):
    def record(self):
        return iis.record_for(snapshot()["releases"], CHECKED)

    def test_every_stored_row_re_derives_from_its_own_cells(self):
        iis.validate_record(self.record())

    def test_foreign_verifier_is_refused(self):
        record = self.record()
        record["provenance"]["verifier"] = "deterministic-something-else"
        with self.assertRaisesRegex(ValueError, "source identity"):
            iis.validate_record(record)

    def test_tampered_direct_date_is_refused(self):
        record = self.record()
        direct = next(r for r in record["releases"]
                      if derived.DERIVED_KEY not in r and r["milestones"]["eol"])
        direct["milestones"]["eol"] = "2099-01-01"
        with self.assertRaisesRegex(ValueError, "contradicts its stored cells"):
            iis.validate_record(record)

    def test_tampered_inherited_date_is_refused(self):
        # The inherited date is re-derived from the parent list's own stored
        # cells, so a tampered result fails rather than being read back.
        record = self.record()
        inherited = next(r for r in record["releases"] if derived.DERIVED_KEY in r)
        inherited["milestones"]["eol"] = "2099-01-01"
        with self.assertRaises(ValueError):
            iis.validate_record(record)

    def test_tampered_parent_cell_is_refused(self):
        # The parent's own row is what the date is read from: editing it without
        # editing the derived date (or the reverse) fails the re-derivation.
        record = self.record()
        inherited = next(r for r in record["releases"] if derived.DERIVED_KEY in r)
        column = inherited["upstream"]["parent"]["end_column"]
        inherited["upstream"]["parent"]["cells"][column] = "11/15/2099 6:59:59 AM"
        with self.assertRaises(ValueError):
            iis.validate_record(record)

    def test_invented_release_or_security_date_is_refused(self):
        record = self.record()
        record["releases"][0]["milestones"]["ga"] = "2018-11-13"
        with self.assertRaisesRegex(ValueError, "claims a release, sale or security-support date"):
            iis.validate_record(record)

    def test_removing_the_inheritance_from_an_undated_row_is_refused(self):
        # A row the IIS table states with no End Date may not carry a date that
        # no inheritance licenses.
        record = self.record()
        release = next(r for r in record["releases"] if r["upstream"]["table"] == iis.RELEASES_TABLE
                       and r["upstream"]["cells"]["End Date"] == ""
                       and derived.DERIVED_KEY in r)
        del release[derived.DERIVED_KEY]
        with self.assertRaisesRegex(ValueError, "contradicts its stored cells"):
            iis.validate_record(record)

    def test_a_scope_without_its_evidence_is_refused(self):
        record = self.record()
        inherited = next(r for r in record["releases"] if derived.DERIVED_KEY in r)
        del inherited["upstream"]["scope"]
        with self.assertRaisesRegex(ValueError, "scope evidence"):
            iis.validate_record(record)

    def test_a_derived_date_the_vendor_already_states_is_refused(self):
        # A direct row that also carries a derivation is refused: the vendor's
        # own cell is the statement, and a derivation beside it is unearned.
        record = self.record()
        release = next(r for r in record["releases"]
                       if derived.DERIVED_KEY not in r and r["milestones"]["eol"])
        release[derived.DERIVED_KEY] = iis.provenance(
            {"date": release["milestones"]["eol"], "release_name": "x", "end_column": "End Date",
             "end_cell": "x", "source_url": iis.IIS_URL, "milestone": "eol",
             "product_id": "x", "release_id": "x", "policy": iis.FIXED_POLICY_STATEMENT},
            {"page": iis.FIXED_POLICY_URL, "quote": iis.FIXED_POLICY_QUOTE})
        with self.assertRaisesRegex(ValueError, "already states"):
            iis.validate_record(record)


class PageShapeTests(unittest.TestCase):
    def test_a_renamed_column_refuses_the_parse(self):
        with self.assertRaisesRegex(ValueError, "expected one 'Releases' table"):
            iis.parse_page(iis.Page(iis.IIS_URL, html(iis.IIS_URL).replace(
                "<th>Version</th>", "<th>Release</th>")))

    def test_a_missing_current_scope_refuses_the_parse(self):
        # Dropping the Windows 10 row the collector completes leaves a declared
        # scope unaccounted for, which is a review rather than a silent drop.
        amended = html(iis.IIS_URL).replace(
            "<td>IIS 10 on Windows 10 Pro</td>", "<td>IIS 10 on Windows 10 Pro (renamed)</td>")
        parsed = pages()
        parsed[iis.IIS_URL] = iis.Page(iis.IIS_URL, amended)
        direct, _ = iis.parse_page(parsed[iis.IIS_URL])
        with self.assertRaisesRegex(ValueError, "no longer states"):
            iis.complete(direct, parsed)

    def test_a_page_that_no_longer_states_the_component_rule_refuses(self):
        parsed = pages()
        parsed[iis.IIS_URL] = iis.Page(iis.IIS_URL, html(iis.IIS_URL).replace(
            iis.COMPONENT_QUOTE, "IIS is a thing."))
        direct, _ = iis.parse_page(parsed[iis.IIS_URL])
        with self.assertRaisesRegex(ValueError, "no longer states"):
            iis.complete(direct, parsed)

    def test_a_reworded_fixed_policy_rule_refuses_the_parse(self):
        parsed = pages()
        parsed[iis.FIXED_POLICY_URL] = iis.Page(iis.FIXED_POLICY_URL, html(iis.FIXED_POLICY_URL).replace(
            iis.FIXED_POLICY_QUOTE.split(".")[0], "A component follows its parent"))
        direct, _ = iis.parse_page(parsed[iis.IIS_URL])
        with self.assertRaisesRegex(ValueError, "component-support answer"):
            iis.complete(direct, parsed)

    def test_a_document_that_is_not_the_registered_page_refuses(self):
        with self.assertRaisesRegex(ValueError, "canonical URL"):
            iis.Page(iis.IIS_URL, html(iis.WINDOWS_SERVER_2022_URL))


class PublicationTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        sibling = normalize({"result": {"name": "sample", "label": "Sample", "category": "lang",
                                        "labels": {},
                                        "releases": [{"name": "1", "releaseDate": "2026-01-01"}]}},
                            CHECKED)
        dump(self.root / "products/sample.json", sibling)
        dump(self.root / "manifest.json", {
            "generated_at": CHECKED, "source_url": API, "source": "import-data",
            "product_count": 1, "release_count": 1, "excluded_hardware": []})

    def snapshot(self):
        return {str(path.relative_to(self.root)): path.read_bytes()
                for path in self.root.rglob("*.json")}

    def refresh(self, checked, overrides=None):
        pages_html = {url: html(url) for url in iis.PAGES}
        pages_html.update(overrides or {})
        with mock.patch.object(iis.net, "get_text",
                               side_effect=lambda url: pages_html[url]), \
                mock.patch.object(iis, "_now", return_value=checked):
            iis.import_iis(self.root)

    def test_quiet_refresh_and_report_only_change_have_independent_revisions(self):
        before = self.snapshot()
        self.refresh("2026-09-23T01:00:00Z")
        published = self.snapshot()
        self.assertEqual({key: published[key] for key in before}, before)
        # A refresh at a later time with identical content republishes the same
        # bytes: the revision marks content, not the fetch attempt.
        self.refresh("2026-09-23T02:00:00Z")
        self.assertEqual(self.snapshot(), published)
        # Changing only the excluded product-level row's cell advances the report
        # while the record keeps its own revision timestamp.
        amended = html(iis.IIS_URL).replace("See Note", "See the note")
        self.refresh("2026-09-23T03:00:00Z", {iis.IIS_URL: amended})
        self.assertEqual((self.root / "products/iis.json").read_bytes(),
                         published["products/iis.json"])
        report = json.loads((self.root / iis.REPORT).read_text())
        self.assertEqual(report["checked_at"], "2026-09-23T03:00:00Z")
        self.assertEqual(report["excluded"][0]["row"].split(" | ")[-1], "See the note")

    def test_foreign_record_refuses_the_import_before_any_fetch(self):
        record = json.loads((self.root / "products/sample.json").read_text())
        record["id"] = "iis"
        dump(self.root / "products/iis.json", record)
        before = self.snapshot()
        with mock.patch.object(iis.net, "get_text") as fetch:
            with self.assertRaisesRegex(ValueError, "ownership collision"):
                iis.import_iis(self.root)
        fetch.assert_not_called()
        self.assertEqual(self.snapshot(), before)

    def test_a_parse_failure_leaves_the_committed_catalog_untouched(self):
        self.refresh("2026-09-23T01:00:00Z")
        before = self.snapshot()
        with self.assertRaises(ValueError):
            self.refresh("2026-09-23T02:00:00Z",
                         {iis.IIS_URL: "<html>Changed layout</html>"})
        self.assertEqual(self.snapshot(), before)

    def test_a_row_the_current_table_drops_is_retained_and_accounted(self):
        self.refresh("2026-09-23T01:00:00Z")
        before = json.loads((self.root / "products/iis.json").read_text())
        row = ("<tr>\n\t\t\t\t\t\t\t<td>IIS 6.0 on Windows Server 2003</td>\n"
               "\t\t\t\t\t\t\t<td align=\"right\">\n"
               "\t\t\t\t\t\t\t\t<local-time timezone=\"America/Los_Angeles\" format=\"date\" "
               "datetime=\"5/28/2003 8:00:00 AM\">5/28/2003 8:00:00 AM</local-time>\n"
               "\t\t\t\t\t\t\t</td>\n\t\t\t\t\t\t\t<td align=\"right\">\n"
               "\t\t\t\t\t\t\t\t<local-time timezone=\"America/Los_Angeles\" format=\"date\" "
               "datetime=\"7/15/2015 6:59:59 AM\">7/15/2015 6:59:59 AM</local-time>\n"
               "\t\t\t\t\t\t\t</td>\n\t\t\t\t\t\t</tr>")
        self.assertIn(row, html(iis.IIS_URL))
        self.refresh("2026-09-23T02:00:00Z",
                     {iis.IIS_URL: html(iis.IIS_URL).replace(row, "")})
        record = json.loads((self.root / "products/iis.json").read_text())
        kept = {r["id"]: r for r in record["releases"]}
        self.assertEqual(kept["iis-6-0-windows-server-2003"]["milestones"],
                         {"ga": None, "eos": None, "eossec": None, "eol": "2015-07-14"})
        self.assertIs(kept["iis-6-0-windows-server-2003"]["upstream"]["in_source"], False)
        report = json.loads((self.root / iis.REPORT).read_text())
        self.assertEqual(report["rows"]["retained"], 1)
        self.assertEqual(len(record["releases"]), len(before["releases"]))
        self.assertEqual([entry["id"] for entry in report["retained"]],
                         ["iis-6-0-windows-server-2003"])

    def test_an_inconsistent_sibling_report_prevents_publication(self):
        dump(self.root / "ceph-import.json",
             {"verifier": "deterministic-ceph", "total_records": 1})
        before = self.snapshot()
        with self.assertRaises(ValueError):
            self.refresh("2026-09-23T01:00:00Z")
        self.assertEqual(self.snapshot(), before)


class ContractTests(unittest.TestCase):
    def test_the_registry_entry_matches_this_collector(self):
        from engine import sources

        source = sources.source("import-iis")
        self.assertEqual(source.verifier, iis.VERIFIER)
        self.assertEqual(source.report, iis.REPORT)
        self.assertEqual(source.category, "software")
        self.assertEqual(source.validator, "engine.iis.validate_record")
        self.assertEqual([page.url for page in source.pages], list(iis.PAGES))

    def test_the_record_satisfies_the_published_schema(self):
        from jsonschema import Draft202012Validator

        schema = json.loads((Path(__file__).resolve().parents[1]
                             / "schema/product.json").read_text())
        record = snapshot()["record"]
        Draft202012Validator(schema).validate(record)
        # Only the recording of a derivation may appear; every other row states
        # its own dates, and no row states a date the source does not publish.
        for release in record["releases"]:
            if derived.DERIVED_KEY in release:
                self.assertEqual(set(release[derived.DERIVED_KEY]), {"eol"})


if __name__ == "__main__":
    unittest.main()
