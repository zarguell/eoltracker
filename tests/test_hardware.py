"""Regression tests for the eosl.date hardware parser and merge.

The saved sample pages are real upstream documents: ``/tmp/eosl-cat.html`` is
Cisco's CATALYST family (the 5-column layout with a single terminal support
column) and ``/tmp/eosl-dell.html`` is the Dell EMC vendor overview (which
links families but publishes no model rows). Both are skipped when absent, so
the suite still runs on a checkout without the samples.
"""
import unittest
from pathlib import Path

from engine.hardware import (HARDWARE_SOURCE, cell_value, family_path, iter_family_urls,
                             merge_models, parse_family_page, parse_vendor_page, slugify)

CATALYST = Path("/tmp/eosl-cat.html")
DELL_VENDOR = Path("/tmp/eosl-dell.html")
CATALYST_URL = "https://eosl.date/network/ethernet-switches/vendor/cisco/catalyst/"
# The one model the contract names, and the 7600 EOL row's published dates.
KNOWN_MODEL = "7600 Catalyst 6500 IPSec VPN Services Module"
SUPPORTED_MODEL = "Catalyst 1000 Series"


def sample(path):
    return None if not path.is_file() else path.read_text(encoding="utf-8")


def model(models, product):
    found = [entry for entry in models if entry["product"] == product]
    if not found:
        raise AssertionError(f"Model not parsed: {product}")
    return found[0]


def hardware_model(product, model_number, product_line, milestones, status="eol", url=None):
    return {
        "vendor": "Cisco", "family": "CATALYST", "source_url": url or CATALYST_URL,
        "product": product, "model_number": model_number, "product_line": product_line,
        "milestones": milestones, "status": status, "upstream": {},
    }


def milestones(**values):
    return {field: values.get(field) for field in ("ga", "eos", "eossec", "eol")}


class CellValueTests(unittest.TestCase):
    def test_time_element_yields_its_datetime(self):
        self.assertEqual(
            cell_value({"time": "2019-10-01", "text": "Oct. 01, 2019", "links": []}),
            "2019-10-01")

    def test_bare_text_date_yields_itself(self):
        self.assertEqual(cell_value({"time": None, "text": "2011-05-31", "links": []}),
                         "2011-05-31")

    def test_unannounced_values_never_become_dates(self):
        for text in ("", "TBD", "Not Announced", "Not Available", "n/a", "unknown"):
            self.assertIsNone(cell_value({"time": None, "text": text, "links": []}), text)
        # An empty datetime attribute is the "Not Announced" encoding.
        self.assertIsNone(cell_value({"time": "", "text": "Not Announced", "links": []}))

    def test_an_impossible_day_is_not_a_date(self):
        self.assertIsNone(cell_value({"time": None, "text": "2026-02-30", "links": []}))

    def test_prose_and_urls_are_not_dates(self):
        self.assertIsNone(cell_value({
            "time": None, "text": "https://support.apple.com/en-us/111900", "links": []}))
        self.assertIsNone(cell_value({"time": None, "text": "Sep. 16, 2024", "links": []}))


class FamilyPageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = sample(CATALYST)
        if cls.html is None:
            raise unittest.SkipTest(f"Sample page missing: {CATALYST}")
        cls.page = parse_family_page(cls.html, CATALYST_URL)

    def test_page_identity_comes_from_the_url_and_breadcrumb(self):
        self.assertEqual(self.page["source_url"], CATALYST_URL)
        self.assertEqual(self.page["vendor"], "Cisco")
        self.assertEqual(self.page["family"], "CATALYST")

    def test_every_status_row_becomes_a_model(self):
        # 14 supported + 1 expiring + 163 end of life, and no advertisement row.
        self.assertEqual(len(self.page["models"]), 178)
        counts = {}
        for entry in self.page["models"]:
            counts[entry["status"]] = counts.get(entry["status"], 0) + 1
        self.assertEqual(counts, {"supported": 14, "expiring": 1, "eol": 163})

    def test_end_of_life_row_keeps_its_published_support_end(self):
        entry = model(self.page["models"], KNOWN_MODEL)
        self.assertEqual(entry["eol"], "2011-05-31")
        self.assertIsNone(entry["ga"])
        self.assertEqual(entry["status"], "eol")
        self.assertEqual(entry["model_number"], KNOWN_MODEL)
        self.assertEqual(entry["product_line"], "Cisco CATALYST")

    def test_supported_row_without_a_support_end_yet(self):
        entry = model(self.page["models"], SUPPORTED_MODEL)
        self.assertEqual(entry["ga"], "2019-10-01")
        self.assertIsNone(entry["eol"])
        self.assertEqual(entry["status"], "supported")

    def test_warning_row_is_expiring_with_its_date(self):
        entry = model(self.page["models"], "Catalyst 3650")
        self.assertEqual(entry["status"], "expiring")
        self.assertEqual(entry["eol"], "2026-10-31")
        self.assertIsNone(entry["ga"])

    def test_eossec_is_never_claimed_on_this_upstream(self):
        self.assertTrue(self.page["models"])
        for entry in self.page["models"]:
            self.assertIsNone(entry["eossec"])

    def test_no_sentinel_leaks_into_a_milestone(self):
        for entry in self.page["models"]:
            for field in ("ga", "eos", "eol"):
                value = entry[field]
                self.assertTrue(value is None or value[:2].isdigit(), (entry["product"], field))

    def test_unmapped_columns_are_retained_verbatim(self):
        entry = model(self.page["models"], SUPPORTED_MODEL)
        self.assertEqual(sorted(entry["upstream"]), sorted(
            ["Product", "Model Number", "Product Line", "Release Date", "End of Support"]))
        self.assertEqual(entry["upstream"]["Release Date"]["datetime"], "2019-10-01")
        self.assertEqual(entry["upstream"]["Release Date"]["role"], "ga")
        self.assertEqual(entry["upstream"]["End of Support"]["role"], "eol")
        self.assertEqual(entry["upstream"]["End of Support"]["text"], "")

    def test_a_non_family_url_is_rejected(self):
        with self.assertRaises(ValueError):
            parse_family_page(self.html, "https://eosl.date/vendor/cisco/")


class ColumnVariationTests(unittest.TestCase):
    """The 6-column layout adds an end of sales column the 5-column one lacks."""

    def test_end_of_life_date_column_maps_to_end_of_sale(self):
        html = """
        <table><thead><tr><th>Product</th><th>Model Number</th><th>Product Line</th>
        <th>End of Life Date</th><th>Release Date</th><th>End of Support Date</th></tr></thead>
        <tbody><tr class="release-row-supported">
        <td data-label="Product">DS-6520F-8GB</td>
        <td data-label="Model Number">DS-6520F-8GB</td>
        <td data-label="Product Line">Dell EMC Connectrix - Brocade</td>
        <td data-label="End of Life Date">2022-08-31</td>
        <td data-label="Release Date"><time datetime="2013-04-08">Apr. 08, 2013</time></td>
        <td data-label="End of Support Date">2027-08-31</td>
        </tr></tbody></table>
        """
        page = parse_family_page(
            html, "https://eosl.date/storage/vendor/dell-emc/connectrix-brocade/")
        entry = page["models"][0]
        self.assertEqual(entry["eos"], "2022-08-31")
        self.assertEqual(entry["eol"], "2027-08-31")
        self.assertEqual(entry["ga"], "2013-04-08")
        self.assertEqual(entry["upstream"]["End of Life Date"]["role"], "eos")

    def test_end_of_service_column_is_the_terminal_one(self):
        html = """
        <table><thead><tr><th>Product</th><th>Product Line</th><th>End of Sale Date</th>
        <th>End of Service Date</th></tr></thead>
        <tbody><tr class="table-eol-row release-row-eol">
        <td data-label="Product">Isilon IQ 6000i</td>
        <td data-label="Product Line">Dell EMC PowerScale / Isilon</td>
        <td data-label="End of Sale Date">2008-05-30</td>
        <td data-label="End of Service Date">2013-06-30</td>
        </tr></tbody></table>
        """
        page = parse_family_page(html, "https://eosl.date/storage/vendor/dell-emc/powerscale-isilon/")
        entry = page["models"][0]
        self.assertEqual(entry["eos"], "2008-05-30")
        self.assertEqual(entry["eol"], "2013-06-30")

    def test_relative_support_prose_is_stripped_from_the_date(self):
        html = """
        <table><thead><tr><th>Product</th><th>Product Name</th><th>End of Support</th></tr></thead>
        <tbody><tr class="table-eol-row release-row-eol">
        <td data-label="Product"></td><td data-label="Product Name">Recovery Manager Central</td>
        <td data-label="End of Support"><a href="https://support.hpe.com/x">
        <time datetime="2026-04-30">Apr. 30, 2026<br><small>Support ended 4 months ago</small></time>
        </a></td></tr></tbody></table>
        """
        page = parse_family_page(html, "https://eosl.date/backup/vendor/hpe/backup-and-recovery/")
        entry = page["models"][0]
        # The product-less identity falls back to the product name column.
        self.assertEqual(entry["product"], "Recovery Manager Central")
        self.assertEqual(entry["eol"], "2026-04-30")

    def test_one_product_released_as_versions_keeps_the_versions_apart(self):
        """A single product name covers one row per version, each with its own dates."""
        def row(version, release, support, status):
            return (f'<tr class="{status}">'
                    f'<td data-label="Product"></td>'
                    f'<td data-label="Product Name">Recovery Manager Central (RMC)</td>'
                    f'<td data-label="Version">6.3.{version}</td>'
                    f'<td data-label="Release Date"><time datetime="{release}">{release}</time></td>'
                    f'<td data-label="End of Support">{support}</td></tr>')
        html = ('<table><thead><tr><th>Product</th><th>Product Name</th><th>Version</th>'
                '<th>Release Date</th><th>End of Support</th></tr></thead><tbody>'
                + row("13", "2024-11-14", "2027-11-14", "release-row-supported")
                + row("12", "2024-03-11", "2027-03-11",
                      "table-warning-row release-row-warning")
                + '</tbody></table>')
        page = parse_family_page(
            html, "https://eosl.date/backup/vendor/hpe/hpe-recovery-manager-central/")
        self.assertEqual([entry["model_number"] for entry in page["models"]], ["6.3.13", "6.3.12"])
        # Both rows survive merging: distinct versions, not a date conflict.
        merged = merge_models([{
            "vendor": page["vendor"], "family": page["family"], "source_url": page["source_url"],
            "product": entry["product"], "model_number": entry["model_number"],
            "product_line": entry["product_line"],
            "milestones": {field: entry[field] for field in
                           ("ga", "eos", "eossec", "eol")},
            "status": entry["status"], "upstream": entry["upstream"],
        } for entry in page["models"]])
        self.assertEqual(len(merged), 2)

    def test_unknown_headers_are_retained_in_upstream(self):
        html = """
        <table><thead><tr><th>Product</th><th>Model Number</th><th>Product Line</th>
        <th>EOL Announced</th><th>End of Support</th><th>Last Date to Convert Warranty</th>
        </tr></thead><tbody><tr class="table-eol-row release-row-eol">
        <td data-label="Product">EX4200</td><td data-label="Model Number">EX4200</td>
        <td data-label="Product Line">Juniper Networks EX Series</td>
        <td data-label="EOL Announced">2021-05-31</td>
        <td data-label="End of Support">2026-05-31</td>
        <td data-label="Last Date to Convert Warranty">2027-05-31</td>
        </tr></tbody></table>
        """
        page = parse_family_page(html, "https://eosl.date/network/vendor/juniper-networks/ex/")
        entry = page["models"][0]
        self.assertEqual(entry["eol"], "2026-05-31")
        self.assertIsNone(entry["eos"])
        self.assertEqual(entry["upstream"]["EOL Announced"]["value"], "2021-05-31")
        self.assertIsNone(entry["upstream"]["EOL Announced"]["role"])

    def test_a_prose_only_terminal_cell_publishes_no_date(self):
        html = """
        <table><thead><tr><th>Product</th><th>Model Name</th><th>End of Support (EOSL)</th>
        </tr></thead><tbody><tr class="release-row-supported">
        <td data-label="Product">Mac Pro</td><td data-label="Model Name">Mac Pro</td>
        <td data-label="End of Support (EOSL)"><a href="https://support.apple.com/en-us/111900">
        https://support.apple.com/en-us/111900</a></td></tr></tbody></table>
        """
        page = parse_family_page(html, "https://eosl.date/mac/vendor/apple/mac-pro/")
        entry = page["models"][0]
        self.assertIsNone(entry["eol"])
        self.assertEqual(entry["status"], "supported")
        self.assertIn("support.apple.com", entry["upstream"]["End of Support (EOSL)"]["text"])

    def test_blank_separator_rows_are_skipped(self):
        html = """
        <table><thead><tr><th>Product</th><th>Model Number</th><th>End of Support</th></tr></thead>
        <tbody><tr class="release-row-supported"><td data-label="Product"></td>
        <td data-label="Model Number"></td><td data-label="End of Support"></td></tr>
        <tr class="ad-row"><td>(adsbygoogle = window.adsbygoogle || []).push({});</td></tr>
        <tr class="release-row-supported"><td data-label="Product">C9300</td>
        <td data-label="Model Number">C9300</td>
        <td data-label="End of Support">2030-01-31</td></tr></tbody></table>
        """
        page = parse_family_page(html, "https://eosl.date/network/vendor/cisco/catalyst-9000/")
        self.assertEqual([entry["product"] for entry in page["models"]], ["C9300"])

    def test_a_table_without_a_support_column_fails_loudly(self):
        html = """
        <table><thead><tr><th>Product</th><th>Model Number</th><th>Warranty</th></tr></thead>
        <tbody><tr class="release-row-supported"><td data-label="Product">X</td>
        <td data-label="Model Number">X</td>
        <td data-label="Warranty">2030-01-31</td></tr></tbody></table>
        """
        with self.assertRaises(ValueError):
            parse_family_page(html, "https://eosl.date/network/vendor/cisco/x/")


class VendorPageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = sample(DELL_VENDOR)
        if cls.html is None:
            raise unittest.SkipTest(f"Sample page missing: {DELL_VENDOR}")

    def test_families_are_discovered_from_their_real_paths(self):
        slugs = parse_vendor_page(self.html)
        self.assertIn("connectrix-brocade", slugs)
        self.assertIn("vxrail", slugs)
        self.assertEqual(len(slugs), len(set(slugs)))
        # The overview's own `/vendor/dell-emc/` link is not a family.
        self.assertNotIn("dell-emc", slugs)

    def test_a_page_without_families_yields_nothing(self):
        self.assertEqual(parse_vendor_page("<html><a href=\"/vendor/cisco/\">Cisco</a></html>"), [])


class SitemapTests(unittest.TestCase):
    SITEMAP = """<?xml version="1.0" encoding="UTF-8"?>
    <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
    <url><loc>https://eosl.date/storage/vendor/hpe/nimble-storage/</loc></url>
    <url><loc>https://eosl.date/storage/san-switches/vendor/dell-emc/connectrix-cisco/</loc></url>
    <url><loc>https://eosl.date/mac/vendor/apple/macbook-pro/</loc></url>
    </urlset>"""

    def test_family_urls_keep_their_nested_categories(self):
        self.assertEqual(list(iter_family_urls(self.SITEMAP)), [
            "https://eosl.date/storage/vendor/hpe/nimble-storage/",
            "https://eosl.date/storage/san-switches/vendor/dell-emc/connectrix-cisco/",
            "https://eosl.date/mac/vendor/apple/macbook-pro/",
        ])

    def test_foreign_and_non_family_urls_are_ignored(self):
        self.assertIsNone(family_path("https://endoflife.date/api/v1/products/"))
        self.assertIsNone(family_path("/vendor/cisco/"))
        self.assertIsNone(family_path("https://zarguell.github.io/eoltracker/vendor/hpe/x/"))
        self.assertEqual(family_path("/mac/vendor/apple/macbook-pro/").group("vendor"), "apple")

    def test_hardware_source_is_the_publisher_root(self):
        self.assertEqual(HARDWARE_SOURCE, "https://eosl.date/")


class SlugTests(unittest.TestCase):
    def test_slugs_are_ascii_lower_case_and_hyphenated(self):
        self.assertEqual(slugify("Cisco Catalyst 1000 Series"), "cisco-catalyst-1000-series")
        self.assertEqual(slugify("MA-MOD-4×10"), "ma-mod-4-10")
        self.assertEqual(slugify(""), "")


class MergeTests(unittest.TestCase):
    def test_a_model_seen_in_two_families_keeps_both_sources(self):
        first = hardware_model("UCS C210 M2", "UCS C210 M2", "Cisco UCS",
                               milestones(ga="2010-01-01", eol="2018-01-01"),
                               url="https://eosl.date/hyper-converged/vendor/cisco/ucs/")
        second = hardware_model("UCS C210 M2", "UCS C210 M2", "Cisco UCS",
                                milestones(eol="2018-01-01"),
                                url="https://eosl.date/uncategorized/vendor/ibm/xseries/")
        merged = merge_models([first, second])
        self.assertEqual(list(merged), ["cisco-ucs-c210-m2"])
        self.assertEqual(merged["cisco-ucs-c210-m2"]["source_urls"],
                         [first["source_url"], second["source_url"]])
        self.assertEqual(merged["cisco-ucs-c210-m2"]["milestones"]["ga"], "2010-01-01")

    def test_a_missing_milestone_is_filled_but_never_overwritten(self):
        first = hardware_model("Switch", "Switch", "Line", milestones(eol=None, ga="2010-01-01"))
        second = hardware_model("Switch", "Switch", "Line",
                                milestones(eol="2020-01-01", ga="2010-01-01"))
        merged = merge_models([first, second])
        self.assertEqual(merged["cisco-switch"]["milestones"], {
            "ga": "2010-01-01", "eos": None, "eossec": None, "eol": "2020-01-01"})

    def test_conflicting_milestones_raise(self):
        first = hardware_model("Switch", "Switch", "Line", milestones(eol="2020-01-01"))
        second = hardware_model("Switch", "Switch", "Line", milestones(eol="2021-01-01"))
        with self.assertRaises(ValueError):
            merge_models([first, second])

    def test_a_status_advance_is_kept(self):
        first = hardware_model("Switch", "Switch", "Line", milestones(eol="2020-01-01"),
                               status="supported")
        second = hardware_model("Switch", "Switch", "Line", milestones(eol="2020-01-01"),
                                status="eol")
        self.assertEqual(merge_models([first, second])["cisco-switch"]["status"], "eol")

    def test_distinct_models_sharing_a_slug_stay_distinct(self):
        models = [
            hardware_model("Mac Mini Unibody (Mid 2010)", "Mac Mini Unibody (Mid 2011)",
                           "", milestones(eol="2012-10-23")),
            hardware_model("Mac Mini Unibody (Mid 2011)", "Mac Mini Unibody (Mid 2011)",
                           "", milestones(eol="2012-10-23")),
        ]
        merged = merge_models(models)
        self.assertEqual(len(merged), 2)
        self.assertEqual({record["identity"][1] for record in merged.values()},
                         {"Mac Mini Unibody (Mid 2010)", "Mac Mini Unibody (Mid 2011)"})

    def test_a_model_without_a_name_is_rejected(self):
        with self.assertRaises(ValueError):
            merge_models([hardware_model("", "", "Line", milestones(eol="2020-01-01"))])


if __name__ == "__main__":
    unittest.main()
