"""Regression tests for the Cisco classic IOS and NX-OS lifecycle collector.

Fixtures are the vendor pages themselves, fetched live and stored byte-for-byte:
the end-of-sale/end-of-life hub, the IOS software releases catalog, one series
page per IOS train the hub files under ``IOS 15 Software``, the retirement
notices the catalog links for the trains Cisco has retired, the generic category
page a train without a lifecycle page redirects to, and the NX-OS lifecycle
support statement.

The rules these tests defend, in the order they matter:

* a vendor cell maps only to the milestone its own wording states, and nothing
  is derived from a cadence — ``EoSWM`` is a maintenance end the same page says
  is followed by PSIRT fixes, so it never becomes a terminal date, and the
  NX-OS table's missing general-availability date stays absent;
* a train the vendor inventories but publishes no page for is *excluded with
  that reason*, never published as undated and never silently dropped;
* hardware is not software: a hardware bulletin's ``Last Date of Support`` is
  not read as a train's end of life;
* this source writes only its own record and leaves a foreign one byte-identical,
  and a quiet refresh republishes byte-identical files.
"""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from engine import cisco_software, sources, validation
from engine.importer import API, dump, normalize

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "tests/fixtures"
HUB = (FIX / "cisco-eol-index.html").read_text(encoding="utf-8")
CATALOG = (FIX / "cisco-ios-releases-listing.html").read_text(encoding="utf-8")
NX_OS = (FIX / "cisco-nx-os-lifecycle.html").read_text(encoding="utf-8")
GENERIC = (FIX / "cisco-ios-category-redirect.html").read_text(encoding="utf-8")
CHECKED = "2026-09-17T12:00:00Z"
# The pages the vendor serves, keyed by the URL a listing states. A support
# series URL whose train Cisco has retired answers with that train's retirement
# notice from /obsolete/, so the entry carries the final URL the fetch lands on —
# the collector must see the redirect, because serving a train's notice from
# another path is exactly the case where a partial snapshot would publish an
# undated train.
SERIES = "https://www.cisco.com/c/en/us/support/ios-nx-os-software/"
OBSOLETE = "https://www.cisco.com/c/en/us/obsolete/ios-nx-os-software/"
PAGES = {
    SERIES + "ios-15-0se/series.html": ("cisco-ios-15-0se-series.html", None),
    SERIES + "ios-15-2e/series.html": ("cisco-ios-15-2e-series.html", None),
    SERIES + "ios-15-3m-t/series.html": ("cisco-ios-15-3m-t-series.html", None),
    SERIES + "ios-software-release-15-6m-t/series.html": ("cisco-ios-15-6m-t-series.html", None),
    SERIES + "ios-15-7m-t/series.html": ("cisco-ios-15-7m-t-series.html", None),
    SERIES + "ios-15-8m-t/series.html": ("cisco-ios-15-8m-t-series.html", None),
    SERIES + "ios-15-9m-t/series.html": ("cisco-ios-15-9m-t-series.html", None),
    OBSOLETE + "cisco-ios-15-0m.html": ("cisco-ios-15-0m-retirement.html", None),
    OBSOLETE + "cisco-ios-15-2m-t.html": ("cisco-ios-15-2m-t-retirement.html", None),
    # Cisco answers these with the retirement notice under /obsolete/.
    SERIES + "ios-15-4m-t/series.html":
        ("cisco-ios-15-4m-t-retirement.html", OBSOLETE + "cisco-ios-15-4m-t.html"),
}
GENERIC_URL = "https://www.cisco.com/c/en/us/support/ios-nx-os-software/index.html"
# The trains the catalog inventories but serves no lifecycle page for: each
# requested URL resolves to the generic IOS/NX-OS category page.
GENERIC_TRAINS = {
    "ios-software-release-15-0-1-s/model.html",
    "ios-software-release-15-0-1-sy/model.html",
    "ios-15-1s/series.html",
    "ios-software-release-15-1-1-sy/model.html",
    "ios-15-2s/series.html",
    "ios-15-3s/series.html",
    "ios-15-4s/series.html",
    "ios-15-5m-t/series.html",
}


class _Response:
    def __init__(self, url, text):
        self.url, self.text, self.status_code = url, text, 200
        self.content = text.encode()


def fetch(url, page=None):
    """Serve the fixture the vendor serves for ``url``, following its redirects."""
    if page is not None:
        return _Response(url, page)
    if url == cisco_software.IOS_HUB_URL:
        return _Response(url, HUB)
    if url == cisco_software.IOS_CATALOG_URL:
        return _Response(url, CATALOG)
    if url == cisco_software.NX_OS_URL:
        return _Response(url, NX_OS)
    if url in PAGES:
        name, final = PAGES[url]
        return _Response(final or url, (FIX / name).read_text(encoding="utf-8"))
    if any(url.endswith(slug) for slug in GENERIC_TRAINS):
        return _Response(GENERIC_URL, GENERIC)
    raise AssertionError(f"Unexpected fixture URL: {url}")


def parsed():
    """The fixture snapshot as the collector parses it (trains, releases, excluded)."""
    trains, hub_rows, catalog_rows, excluded, duplicates = cisco_software.ios_inventory(
        HUB, CATALOG)
    releases = []
    for train in trains:
        response = fetch(train["url"])
        if "birth-cert-table" not in response.text and "Retirement Notification" not in response.text:
            excluded.append({"id": train["id"], "name": train["name"], "url": train["url"],
                             "reason": "no lifecycle page"})
            continue
        title, cells, statement, _ = cisco_software.parse_series(
            response.text, f"Cisco IOS {train['id']}")
        releases.append(cisco_software.page_release(train, title, cells, statement, response.url))
    return trains, releases, excluded, hub_rows, catalog_rows, duplicates


class InventoryTests(unittest.TestCase):
    def test_both_listings_reconcile_to_the_same_trains(self):
        trains, hub_rows, catalog_rows, excluded, duplicates = cisco_software.ios_inventory(
            HUB, CATALOG)
        ids = [train["id"] for train in trains]
        # The hub's seven "IOS 15 Software" trains plus the catalog-only trains.
        self.assertEqual(ids[:7], ["15.0se", "15.2e", "15.3mt", "15.6mt", "15.7mt", "15.8mt",
                                   "15.9mt"])
        self.assertEqual(len(ids), len(set(ids)))
        # 15.3M&T appears in both listings under different spellings and is one train.
        self.assertEqual(ids.count("15.3mt"), 1)
        self.assertEqual(duplicates, 1)
        self.assertEqual({train["listing"] for train in trains}, {"hub", "catalog"})

    def test_a_catalog_row_disagreeing_with_the_hub_about_the_train_page_refuses(self):
        # The catalog names a different page for 15.3M&T than the hub does: the
        # two vendor listings contradict each other about the train's identity,
        # and the first-wins path would have published the hub's link silently.
        catalog = CATALOG.replace(
            'href="/c/en/us/support/ios-nx-os-software/ios-15-3m-t/series.html"',
            'href="/c/en/us/support/ios-nx-os-software/ios-15-3m-t-eol/series.html"', 1)
        with self.assertRaisesRegex(ValueError, "disagree about the train's page"):
            cisco_software.ios_inventory(HUB, catalog)

    def test_an_identical_restatement_across_the_listings_stays_a_duplicate(self):
        # Control: the real fixtures name one page for the shared train, so the
        # check above fires on a real contradiction, not on every duplicate.
        trains, _, _, _, duplicates = cisco_software.ios_inventory(HUB, CATALOG)
        self.assertEqual(duplicates, 1)
        shared = next(train for train in trains if train["id"] == "15.3mt")
        self.assertEqual(shared["url"],
                         "https://www.cisco.com/c/en/us/support/ios-nx-os-software/"
                         "ios-15-3m-t/series.html")

    def test_vendor_spellings_of_one_train_share_an_identity(self):
        self.assertEqual(cisco_software.train_id("15.3 M & T"),
                         cisco_software.train_id("Cisco IOS Software Releases 15.3M&T"))
        # Distinct trains stay distinct: M&T, S and E are different trains.
        self.assertEqual(cisco_software.train_id("15.2 E"), "15.2e")
        self.assertEqual(cisco_software.train_id("15.2S"), "15.2s")
        self.assertNotEqual(cisco_software.train_id("15.2 M & T"), "15.2s")

    def test_every_row_of_both_listings_is_accounted(self):
        trains, hub_rows, catalog_rows, excluded, duplicates = cisco_software.ios_inventory(
            HUB, CATALOG)
        self.assertEqual(len(hub_rows) + len(catalog_rows), 321 + 12)
        # Every row is a distinct train, a duplicate row of one, or an exclusion
        # carrying the reason it states no classic IOS train lifecycle.
        self.assertEqual(len(trains) + len(excluded) + duplicates,
                         len(hub_rows) + len(catalog_rows))

    def test_rows_outside_the_ios_group_are_excluded_with_their_reason(self):
        _, _, _, excluded, _ = cisco_software.ios_inventory(HUB, CATALOG)
        by_row = {(entry.get("section"), entry.get("row")): entry for entry in excluded
                  if "id" not in entry}
        # IOS XE and IOS XR share the section but are other software families.
        xe = by_row[("IOS-NX-OS", "XE 17")]
        self.assertIn("IOS XE Software", xe["group"])
        self.assertIn("not classic IOS software", xe["reason"])
        self.assertIn("IOS XR Software", by_row[("IOS-NX-OS", "XR (End-of-Sale Releases)")]["group"])
        # A row in another section names that section.
        other = next(entry for key, entry in by_row.items() if key[0] == "Switches")
        self.assertIn("'Switches'", other["reason"])


class TrainUrlTests(unittest.TestCase):
    """A discovered href is vendor data: it is policy-checked before any fetch."""

    def test_root_relative_and_vendor_https_links_resolve_to_cisco(self):
        self.assertEqual(cisco_software.train_url("/c/en/us/support/x/series.html", "probe"),
                         "https://www.cisco.com/c/en/us/support/x/series.html")
        self.assertEqual(
            cisco_software.train_url("https://www.cisco.com/c/en/us/support/x/series.html", "probe"),
            "https://www.cisco.com/c/en/us/support/x/series.html")
        # A bare cisco.com host is the vendor's too.
        self.assertEqual(cisco_software.train_url("https://cisco.com/a.html", "probe"),
                         "https://cisco.com/a.html")
        # A protocol-relative link resolves to HTTPS against the vendor host.
        self.assertEqual(cisco_software.train_url("//www.cisco.com/a.html", "probe"),
                         "https://www.cisco.com/a.html")

    def test_an_unsafe_or_foreign_destination_is_refused_before_the_fetch(self):
        for href in ("http://www.cisco.com/c/en/us/support/x/series.html",
                     "//evil.example.com/series.html",
                     "https://evil.example.com/series.html",
                     "https://cisco.com.evil.example.com/series.html",
                     "https://user:secret@www.cisco.com/series.html",
                     "https://www.cisco.com.evil.example/x.html",
                     "ftp://www.cisco.com/x.html",
                     "file:///etc/passwd",
                     "https://www.cisco.com./x.html",
                     "javascript:alert(1)",
                     "https://127.0.0.1/series.html",
                     "https://169.254.169.254/latest/meta-data/",
                     "https://[::1]/series.html",
                     "https://10.0.0.1/series.html",
                     "https://www.cisco.com/series.html\nHost: evil.example.com",
                     ""):
            with self.subTest(href=href):
                with self.assertRaises(ValueError):
                    cisco_software.train_url(href, "probe")

    def test_an_unsafe_row_link_is_excluded_and_never_fetched(self):
        # The hub's own markup is mutated to carry a foreign link that still
        # looks like a train page: the row is accounted with the reason, and no
        # train is created for it, so import_ios never issues a request there.
        hostile = ("https://evil.example.com/c/en/us/support/ios-nx-os-software/"
                   "ios-15-7m-t/series.html")
        hub = HUB.replace('href="/c/en/us/support/ios-nx-os-software/ios-15-7m-t/series.html"',
                          f'href="{hostile}"', 1)
        trains, _, _, excluded, _ = cisco_software.ios_inventory(hub, CATALOG)
        self.assertNotIn("15.7mt", [train["id"] for train in trains])
        entry = next(entry for entry in excluded if entry.get("id") == "15.7mt")
        self.assertIn("not a page this source fetches", entry["reason"])
        self.assertIn("evil.example.com", entry["reason"])
        self.assertEqual(entry["href"], hostile)
        self.assertFalse(any(hostile in train["url"] for train in trains))

    def test_a_catalog_row_with_a_foreign_link_is_excluded_too(self):
        hostile = "https://169.254.169.254/c/en/us/support/ios-nx-os-software/x/series.html"
        catalog = CATALOG.replace('href="/c/en/us/support/ios-nx-os-software/ios-15-5m-t/series.html"',
                                  f'href="{hostile}"', 1)
        trains, _, _, excluded, _ = cisco_software.ios_inventory(HUB, catalog)
        self.assertNotIn("15.5mt", [train["id"] for train in trains])
        entry = next(entry for entry in excluded if entry.get("href") == hostile)
        self.assertEqual(entry["listing"], "catalog")
        self.assertIn("not a page this source fetches", entry["reason"])

    def test_a_refused_row_link_keeps_the_report_arithmetic(self):
        # The refused row is an inventoried train excluded with its reason, so
        # the report's own sums still add up: a refused link is accounted for
        # like any other train the source could not publish.
        hostile = ("https://evil.example.com/c/en/us/support/ios-nx-os-software/"
                   "ios-15-7m-t/series.html")
        hub = HUB.replace('href="/c/en/us/support/ios-nx-os-software/ios-15-7m-t/series.html"',
                          f'href="{hostile}"', 1)
        trains, hub_rows, catalog_rows, excluded, duplicates = cisco_software.ios_inventory(
            hub, CATALOG)
        self.assertEqual(len(trains) + len(excluded) + duplicates,
                         len(hub_rows) + len(catalog_rows))
        self.assertIn("15.7mt", [entry.get("id") for entry in excluded])

    def test_a_redirect_that_leaves_the_vendor_host_refuses_the_fetch(self):
        with mock.patch.object(cisco_software.net, "get") as get:
            get.return_value = _Response("https://169.254.169.254/secret", "<html></html>")
            with self.assertRaises(ValueError):
                cisco_software._page("https://www.cisco.com/c/en/us/support/x/series.html")
        get.assert_called_once()

    def test_a_same_host_redirect_is_followed_and_returned(self):
        with mock.patch.object(cisco_software.net, "get") as get:
            get.return_value = _Response(
                "https://www.cisco.com/c/en/us/obsolete/ios-nx-os-software/x.html",
                "<html>notice</html>")
            final, text = cisco_software._page(
                "https://www.cisco.com/c/en/us/support/x/series.html")
        self.assertEqual(final, "https://www.cisco.com/c/en/us/obsolete/ios-nx-os-software/x.html")
        self.assertEqual(text, "<html>notice</html>")

    def test_the_shared_url_policy_applies_to_the_resolved_href(self):
        # The vendor host is not the whole story: the shared policy also refuses
        # a credential-shaped query, so a link that would carry a token into a
        # fetched URL — or a citation this project could not publish — is refused.
        for href in ("https://www.cisco.com/x.html?token=abc",
                     "https://www.cisco.com/x.html?X-Amz-Signature=deadbeef",
                     "https://www.cisco.com/x.html?access_key=abc"):
            with self.subTest(href=href):
                with self.assertRaisesRegex(ValueError, "not a safe HTTP URL"):
                    cisco_software.train_url(href, "probe")
        self.assertEqual(cisco_software.train_url("https://www.cisco.com/x.html?a=b", "probe"),
                         "https://www.cisco.com/x.html?a=b")

    def test_the_shared_url_rule_is_actually_installed_here(self):
        # A silent fallback would make the test above vacuous, so the module the
        # collector imported is pinned: engine/urls.py supplies the rule and the
        # collector must be using it rather than its own copy.
        from engine import urls

        self.assertIs(cisco_software._safe_http_url, urls.safe_http_url)


class SeriesPageTests(unittest.TestCase):
    def test_stated_labels_map_to_their_own_milestones(self):
        releases = {r["id"]: r for r in parsed()[1]}
        fifteen_two = releases["15.2e"]
        self.assertEqual(fifteen_two["milestones"],
                         {"ga": "2013-08-28", "eos": "2020-08-14", "eossec": None,
                          "eol": "2025-08-31"})
        self.assertEqual(fifteen_two["upstream"]["cells"]["End-of-Support Date"], "31-AUG-2025")
        self.assertEqual(fifteen_two["upstream"]["lifecycle_statement"],
                         "This product is no longer Supported by Cisco.")
        for release in releases.values():
            self.assertIsNone(release["milestones"]["eossec"])

    def test_available_train_publishes_no_invented_deadline(self):
        releases = {r["id"]: r for r in parsed()[1]}
        # 15.8M&T states Status: Available and a series date only.
        self.assertEqual(releases["15.8mt"]["milestones"],
                         {"ga": "2017-07-30", "eos": None, "eossec": None, "eol": None})
        self.assertEqual(releases["15.8mt"]["upstream"]["cells"]["Status"], "Available")

    def test_end_of_support_date_is_the_terminal_date_not_the_sale_date(self):
        releases = {r["id"]: r for r in parsed()[1]}
        fifteen_nine = releases["15.9mt"]
        # 15.9M&T: EoS 28-JUL-2026, EoS(upport) 31-JUL-2031. The later value is eol.
        self.assertEqual(fifteen_nine["milestones"]["eos"], "2026-07-28")
        self.assertEqual(fifteen_nine["milestones"]["eol"], "2031-07-31")
        # The same two values the vendor's own announcement states for 15.9(3)M.
        announcement = (FIX / "cisco-ios-15-9-3m-announcement.html").read_text(encoding="utf-8")
        self.assertIn("July 28, 2026", announcement)
        self.assertIn("July 31, 2031", announcement)

    def test_retirement_notice_keeps_the_recorded_dates(self):
        releases = {r["id"]: r for r in parsed()[1]}
        self.assertEqual(releases["15.2mt"]["milestones"],
                         {"ga": None, "eos": "2015-01-27", "eossec": None, "eol": "2020-01-31"})
        # 15.4M&T's series URL answers with its retirement notice from /obsolete/.
        self.assertEqual(releases["15.4mt"]["milestones"],
                         {"ga": None, "eos": "2017-03-01", "eossec": None, "eol": "2022-02-28"})
        self.assertEqual(releases["15.4mt"]["upstream"]["page"],
                         OBSOLETE + "cisco-ios-15-4m-t.html")
        self.assertEqual(releases["15.0m"]["milestones"]["eos"], "2012-04-01")

    def test_retirement_notice_copyright_row_is_not_a_milestone(self):
        # The notice lists "Cisco's End-of-Life Policy" in the same <li> list; the
        # parse must read only the three lifecycle labels, not that link's text.
        title, cells, statement, retirement = cisco_software.parse_series(
            (FIX / "cisco-ios-15-2m-t-retirement.html").read_text(encoding="utf-8"), "probe")
        self.assertTrue(retirement)
        self.assertEqual(set(cells), {"End-of-Sale Date", "End-of-Support Date"})
        self.assertEqual(statement, "The Cisco IOS 15.2M&T has been retired and is no longer "
                                    "supported.")

    def test_unexpected_label_refuses_the_parse(self):
        html = (FIX / "cisco-ios-15-2e-series.html").read_text(encoding="utf-8")
        html = html.replace("<th>End-of-Support Date</th>", "<th>End-of-Service Date</th>")
        with self.assertRaises(ValueError):
            cisco_software.parse_series(html, "probe")

    def test_unrecognized_date_cell_refuses_the_parse(self):
        html = (FIX / "cisco-ios-15-2e-series.html").read_text(encoding="utf-8")
        html = html.replace("31-AUG-2025", "31-AUG-25")
        title, cells, statement, _ = cisco_software.parse_series(html, "probe")
        train = {"id": "probe", "name": title, "url": "probe", "hub_status": ""}
        with self.assertRaises(ValueError):
            cisco_software.page_release(train, title, cells, statement)

    def test_page_without_lifecycle_labels_refuses_the_parse(self):
        with self.assertRaises(ValueError):
            cisco_software.parse_series(GENERIC, "probe")


class NxOsPageTests(unittest.TestCase):
    def test_major_release_table_maps_eovss_to_both_ends(self):
        releases, excluded = cisco_software.parse_lifecycle_page(NX_OS)
        by_id = {r["id"]: r for r in releases}
        self.assertEqual(sorted(by_id), ["10.2", "10.3", "10.4", "10.5", "10.6", "10.7"])
        # 10.2(x) states both ends separately: Feb 28 2025 (EoVSS) / Aug 31 2025 (LDoS).
        self.assertEqual(by_id["10.2"]["milestones"],
                         {"ga": None, "eos": None, "eossec": "2025-02-28", "eol": "2025-08-31"})
        # 10.3(x) states one date the page says aligns both milestones.
        self.assertEqual(by_id["10.3"]["milestones"],
                         {"ga": None, "eos": None, "eossec": "2027-02-28", "eol": "2027-02-28"})

    def test_eoswm_is_retained_verbatim_and_never_mapped(self):
        releases, _ = cisco_software.parse_lifecycle_page(NX_OS)
        by_id = {r["id"]: r for r in releases}
        # 10.4(x): EoSWM Feb 28 2026 precedes the LDoS Feb 29 2028 by two years.
        self.assertEqual(by_id["10.4"]["upstream"]["cells"]["EoSWM Date"], "Feb 28 2026")
        self.assertEqual(by_id["10.4"]["milestones"]["eol"], "2028-02-29")
        for release in releases:
            self.assertNotEqual(release["milestones"]["eol"],
                                release["upstream"]["cells"]["EoSWM Date"])

    def test_no_general_availability_date_is_invented(self):
        releases, _ = cisco_software.parse_lifecycle_page(NX_OS)
        for release in releases:
            self.assertIsNone(release["milestones"]["ga"])
            self.assertIsNone(release["milestones"]["eos"])

    def test_footnote_marker_is_kept_verbatim_and_not_a_date(self):
        releases, _ = cisco_software.parse_lifecycle_page(NX_OS)
        by_id = {r["id"]: r for r in releases}
        self.assertEqual(by_id["10.3"]["upstream"]["cells"]["EoVSS/LDoS"], "Feb 28 2027 *")
        self.assertEqual(by_id["10.3"]["milestones"]["eol"], "2027-02-28")

    def test_the_release_taxonomy_table_is_excluded_not_parsed(self):
        releases, excluded = cisco_software.parse_lifecycle_page(NX_OS)
        self.assertEqual(len(excluded), 4)
        self.assertTrue(all("release taxonomy" in entry["reason"] for entry in excluded))
        self.assertTrue(all(entry["table"] == "Cisco NX-OS Software release types"
                            for entry in excluded))
        self.assertFalse(any(release["milestones"]["eol"] for release in releases
                             if release["id"] == "major"))

    def test_reshaped_headers_refuse_the_parse(self):
        html = NX_OS.replace("EoSWM Date", "End of SW Maintenance")
        with self.assertRaises(ValueError):
            cisco_software.parse_lifecycle_page(html)

    def test_unrecognized_release_cell_refuses_the_parse(self):
        html = NX_OS.replace(">10.7(x)<", ">NX-OS 10.7<")
        with self.assertRaises(ValueError):
            cisco_software.parse_lifecycle_page(html)

    def test_undated_security_cell_refuses_the_parse(self):
        html = NX_OS.replace("Feb 28 2031", "TBD")
        with self.assertRaises(ValueError):
            cisco_software.parse_lifecycle_page(html)

    def test_missing_milestones_table_refuses_the_parse(self):
        with self.assertRaises(ValueError):
            cisco_software.parse_lifecycle_page("<html><body><p>No tables</p></body></html>")

    def nx_row(self, release, eoswm, security):
        return (f'<tr><td><p>{release}</p></td><td><p>{eoswm}</p></td>'
                f'<td><p>{security}</p></td></tr>')

    def duplicate_row(self, page, row):
        """``page`` with ``row`` appended to the milestones table's tbody."""
        marker = "NX-OS EoL Milestones</a></p>"
        start = page.index(marker)
        end = page.index("</tbody>", start)
        return page[:end] + row + page[end:]

    def test_an_identical_duplicate_major_release_row_is_reconciled(self):
        row = self.nx_row("10.2(x)", "Nov 30 2023", "Feb 28 2025/Aug 31 2025")
        releases, excluded = cisco_software.parse_lifecycle_page(self.duplicate_row(NX_OS, row))
        self.assertEqual([release["id"] for release in releases].count("10.2"), 1)
        self.assertIn("duplicate train row for release '10.2'",
                      [entry["reason"] for entry in excluded])

    def test_a_duplicate_row_contradicting_a_lifecycle_cell_refuses_the_parse(self):
        # The old path dropped the second row without reading its cells: a
        # changed EoSWM or EoVSS/LDoS value is a vendor contradiction, not a
        # duplicate, so the refresh must refuse rather than publish the first.
        for eoswm, security in (("Nov 30 2024", "Feb 28 2025/Aug 31 2025"),
                                ("Nov 30 2023", "Mar 28 2025/Aug 31 2025"),
                                ("Nov 30 2023", "Feb 28 2025/Sep 30 2025")):
            with self.subTest(eoswm=eoswm, security=security):
                row = self.nx_row("10.2(x)", eoswm, security)
                with self.assertRaisesRegex(ValueError, "stated twice with contradicting values"):
                    cisco_software.parse_lifecycle_page(self.duplicate_row(NX_OS, row))


class PublicationTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        dump(self.root / "products/sample.json",
             normalize({"result": {"name": "sample", "label": "Sample", "category": "lang",
                                   "labels": {},
                                   "releases": [{"name": "1", "releaseDate": "2026-01-01"}]}},
                       "2026-09-17T00:00:00Z"))
        dump(self.root / "manifest.json", {
            "generated_at": "2026-09-17T00:00:00Z", "source_url": API, "source": "import-data",
            "product_count": 1, "release_count": 1, "excluded_hardware": []})

    def snapshot(self):
        return {str(p.relative_to(self.root)): p.read_bytes()
                for p in self.root.rglob("*.json")}

    def refresh_ios(self, checked, hub=None, catalog=None):
        with mock.patch.object(cisco_software.net, "get",
                               side_effect=lambda url: fetch(url)), \
                mock.patch.object(cisco_software, "datetime") as clock:
            clock.now.return_value.isoformat.return_value = checked
            cisco_software.import_ios(self.root)

    def refresh_nx_os(self, checked, page=None):
        with mock.patch.object(cisco_software.net, "get",
                               side_effect=lambda url: fetch(url, page)), \
                mock.patch.object(cisco_software, "datetime") as clock:
            clock.now.return_value.isoformat.return_value = checked
            cisco_software.import_nx_os(self.root)

    def test_ios_import_writes_the_expected_record_and_report(self):
        self.refresh_ios("2026-09-17T01:00:00Z")
        record = json.loads((self.root / "products/cisco-ios.json").read_text())
        self.assertEqual(record["id"], "cisco-ios")
        self.assertEqual(record["provenance"]["verifier"], "deterministic-cisco-ios")
        self.assertEqual(record["category"], "software")
        self.assertEqual(record["labels"],
                         {"ga": "Series Release Date", "eos": "End-of-Sale Date",
                          "eol": "End-of-Support Date"})
        report = json.loads((self.root / "cisco-ios-import.json").read_text())
        self.assertEqual(report["verifier"], "deterministic-cisco-ios")
        self.assertEqual(report["total_records"], 1)
        # The report's own arithmetic adds up: source rows, trains and outcomes.
        rows = report["rows"]
        self.assertEqual(rows["seen"], rows["hub_page_rows"] + rows["catalog_rows"])
        self.assertEqual(rows["trains"],
                         rows["published_fresh"] + rows["excluded_trains"])
        self.assertEqual(rows["excluded"],
                         rows["excluded_trains"] + rows["excluded_listing_rows"])

    def test_nx_os_import_writes_the_expected_record_and_report(self):
        self.refresh_nx_os("2026-09-17T01:00:00Z")
        record = json.loads((self.root / "products/cisco-nx-os.json").read_text())
        self.assertEqual(record["id"], "cisco-nx-os")
        self.assertEqual(record["provenance"]["verifier"], "deterministic-cisco-nx-os")
        self.assertEqual(len(record["releases"]), 6)
        report = json.loads((self.root / "cisco-nx-os-import.json").read_text())
        rows = report["rows"]
        self.assertEqual(rows["seen"], rows["published"] + rows["excluded"])
        self.assertEqual(rows["milestones"]["eossec"], 6)
        self.assertEqual(rows["milestones"]["ga"], 0)

    def test_quiet_refresh_preserves_both_records_and_reports(self):
        self.refresh_ios("2026-09-17T01:00:00Z")
        self.refresh_nx_os("2026-09-17T01:00:00Z")
        published = self.snapshot()
        self.refresh_ios("2026-09-17T02:00:00Z")
        self.refresh_nx_os("2026-09-17T02:00:00Z")
        self.assertEqual(self.snapshot(), published)

    def test_missing_train_page_is_retained_and_marked(self):
        self.refresh_ios("2026-09-17T01:00:00Z")
        before = json.loads((self.root / "products/cisco-ios.json").read_text())
        # Drop 15.9M&T's page: it is served as the generic category page instead.
        def without(url):
            if url.endswith("ios-15-9m-t/series.html"):
                return _Response(GENERIC_URL, GENERIC)
            return fetch(url)

        with mock.patch.object(cisco_software.net, "get", side_effect=without), \
                mock.patch.object(cisco_software, "datetime") as clock:
            clock.now.return_value.isoformat.return_value = "2026-09-17T02:00:00Z"
            cisco_software.import_ios(self.root)
        record = json.loads((self.root / "products/cisco-ios.json").read_text())
        retained = next(r for r in record["releases"] if r["id"] == "15.9mt")
        self.assertFalse(retained["upstream"]["in_source"])
        self.assertEqual(retained["milestones"],
                         next(r for r in before["releases"]
                              if r["id"] == "15.9mt")["milestones"])
        report = json.loads((self.root / "cisco-ios-import.json").read_text())
        self.assertEqual(report["rows"]["retained"], 1)
        self.assertTrue(any(entry["id"] == "15.9mt" for entry in report["retained"]))

    def test_tampered_milestone_refuses_republication(self):
        self.refresh_ios("2026-09-17T01:00:00Z")
        path = self.root / "products/cisco-ios.json"
        record = json.loads(path.read_text())
        record["releases"][0]["milestones"]["eol"] = "2099-01-01"
        dump(path, record)
        before = self.snapshot()
        with self.assertRaises(ValueError):
            self.refresh_ios("2026-09-17T02:00:00Z")
        self.assertEqual(self.snapshot(), before)

    def test_foreign_record_refuses_import_before_network(self):
        dump(self.root / "products/cisco-ios.json",
             normalize({"result": {"name": "cisco-ios", "label": "Cisco IOS", "category": "os",
                                   "labels": {},
                                   "releases": [{"name": "1", "releaseDate": "2026-01-01"}]}},
                       "2026-09-17T00:00:00Z"))
        before = self.snapshot()
        with mock.patch.object(cisco_software.net, "get") as get:
            with self.assertRaises(ValueError):
                cisco_software.import_ios(self.root)
        get.assert_not_called()
        self.assertEqual(self.snapshot(), before)

    def test_parse_failure_leaves_the_catalog_untouched(self):
        self.refresh_nx_os("2026-09-17T01:00:00Z")
        before = self.snapshot()
        with self.assertRaises(ValueError):
            self.refresh_nx_os("2026-09-17T02:00:00Z", page="<html>Changed layout</html>")
        self.assertEqual(self.snapshot(), before)

    def test_invalid_sibling_report_prevents_publication(self):
        dump(self.root / "ceph-import.json", {"verifier": "deterministic-ceph",
                                              "total_records": 1})
        before = self.snapshot()
        with self.assertRaises(ValueError):
            self.refresh_ios("2026-09-17T01:00:00Z")
        self.assertEqual(self.snapshot(), before)

    def test_published_records_validate_against_the_registry(self):
        self.refresh_ios("2026-09-17T01:00:00Z")
        self.refresh_nx_os("2026-09-17T01:00:00Z")
        records = validation.validate_data(self.root)
        self.assertEqual(sorted(record["id"] for record in records),
                         ["cisco-ios", "cisco-nx-os", "sample"])

    def test_registry_owns_the_ids_and_pages_the_collector_reads(self):
        self.assertEqual(cisco_software.VERIFIER_IOS,
                         sources.source("import-cisco-ios").verifier)
        self.assertEqual(cisco_software.VERIFIER_NX_OS,
                         sources.source("import-cisco-nx-os").verifier)
        self.assertEqual(cisco_software.IOS_HUB_URL,
                         sources.source("import-cisco-ios").pages[0].url)
        self.assertEqual(cisco_software.NX_OS_URL,
                         sources.source("import-cisco-nx-os").pages[0].url)
        self.assertIs(sources.record_validator(sources.source("import-cisco-ios")),
                      cisco_software.validate_ios_record)
        self.assertIs(sources.record_validator(sources.source("import-cisco-nx-os")),
                      cisco_software.validate_nx_os_record)


if __name__ == "__main__":
    unittest.main()
