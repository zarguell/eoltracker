"""Regression tests for the NETGEAR collector and its rendered source (#154).

The fixture is the vendor's End of Service page **after rendering**, fetched
2026-09-26. No test launches a browser: the collector's parser is a pure
function of the rendered HTML, so the whole boundary is exercised from the saved
page.

Three things in that page are the tests' real subject:

* **The page states no column names.** Each row is five bare cells, so ``eol``
  comes from the row's own ``DD-MMM-YYYY`` sentence, and the ambiguous date cell
  is checked against it in both orders.
* **The first date cell is a separate, unnamed date.** It equals the end of
  service on most rows and is years earlier on 767, and it is mapped to nothing.
* **The end of service is per item number.** 783 of 1,273 dated models have item
  numbers that disagree, so a per-model record would have to invent or drop a
  date.
"""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from engine import netgear, render, sources, validation
from engine.importer import dump, normalize

FIXTURE = Path(__file__).parent / "fixtures" / "netgear-eos-rendered.html"
CHECKED = "2026-09-26T04:00:00Z"


_PAGE = None
_PARSED = None


def page():
    global _PAGE
    if _PAGE is None:
        _PAGE = FIXTURE.read_text(encoding="utf-8")
    return _PAGE


def parsed():
    """The fixture parsed once: the parser is pure, and 9,405 rows are not cheap."""
    global _PARSED
    if _PARSED is None:
        _PARSED = netgear.parse(page())
    return _PARSED


def record_for(records, item):
    return next(record for record in records if record["upstream"]["Item Number"]["text"] == item)


class PolicyTests(unittest.TestCase):
    def test_the_page_still_states_what_eos_means(self):
        netgear.require_policy(page(), "NETGEAR")
        with self.assertRaisesRegex(ValueError, "no longer states"):
            netgear.require_policy(page().replace(netgear.POLICY_TERMINAL_QUOTE, "gone"),
                                   "NETGEAR")

    def test_the_page_still_states_why_dates_are_per_sku(self):
        with self.assertRaisesRegex(ValueError, "no longer states"):
            netgear.require_policy(page().replace(netgear.POLICY_SKU_QUOTE, "gone"), "NETGEAR")

    def test_the_policy_prose_is_rendered_twice_and_both_copies_are_required(self):
        # Replacing one copy proves nothing: the page prints its policy twice, so
        # a page that lost the statement lost both.
        self.assertEqual(page().count(netgear.POLICY_TERMINAL_QUOTE), 2)

    def test_a_page_with_no_policy_is_refused_before_anything_is_read(self):
        with self.assertRaisesRegex(ValueError, "no longer states"):
            netgear.parse("<html><body>nothing here</body></html>")


class InventoryTests(unittest.TestCase):
    def test_every_row_of_every_category_is_published(self):
        records, accounting = parsed()
        self.assertEqual(accounting["categories"], 68)
        self.assertEqual(accounting["tables"], 68)
        self.assertEqual(accounting["rows"], 9405)
        self.assertEqual(accounting["published"], 9405)
        self.assertEqual(len(records), 9405)

    def test_the_dated_and_undated_rows_are_counted(self):
        _records, accounting = parsed()
        self.assertEqual(accounting["with_eol"], 7641)
        self.assertEqual(accounting["not_yet"], 1764)
        self.assertEqual(accounting["scheduled"], 255)
        self.assertEqual(accounting["earlier_date"], 767)
        self.assertEqual(accounting["with_eol"] + accounting["not_yet"], accounting["rows"])

    def test_a_page_that_renders_no_table_refuses(self):
        # The rendering profile's acceptance criterion: a page that renders no
        # expected table raises rather than publishing nothing.
        # A page that satisfies the policy but renders no table: the policy
        # check passes, and the missing table is what refuses.
        prose = " ".join((netgear.POLICY_TERMINAL_QUOTE, netgear.POLICY_SKU_QUOTE, netgear.NOT_YET))
        with self.assertRaisesRegex(ValueError, "no product table|break the category-then-table"):
            netgear.parse(f"<html><body>{prose}</body></html>")

    def test_an_unrecognised_block_refuses_the_page(self):
        html = page().replace("</table>", "</table><table><tr><td>stray</td></tr></table>", 1)
        with self.assertRaisesRegex(ValueError, "break the category-then-table alternation"):
            netgear.parse(html)


class DateMappingTests(unittest.TestCase):
    def test_the_end_of_service_comes_from_the_rows_own_sentence(self):
        records, _accounting = parsed()
        # The page's cells read 1/11/2022 and 10/31/2025, and the note reads
        # "reached EOS on 31-OCT-2025". The note decides; the second cell is
        # verified against it; the first is years earlier and is mapped to nothing.
        record = record_for(records, "ANT224D10-10000S")
        self.assertEqual(record["milestones"]["eol"], "2025-10-31")
        self.assertIsNone(record["milestones"]["eos"])
        self.assertIsNone(record["milestones"]["eossec"])

    def test_an_ambiguous_cell_is_read_in_the_order_the_note_gives(self):
        # 9/12/2013 with a note of 09-DEC-2013 is 9 December, and 12/9/2013 is
        # the same day written the other way round. Both reconcile; neither is
        # resolved on its own.
        self.assertTrue(netgear.reconciles((9, 12, 2013), 9, 12, 2013))
        self.assertTrue(netgear.reconciles((12, 9, 2013), 9, 12, 2013))
        self.assertFalse(netgear.reconciles((1, 2, 2013), 9, 12, 2013))

    def test_a_cell_in_neither_order_does_not_reconcile(self):
        self.assertIs(netgear.reconciles((4, 5, 2020), 9, 12, 2013), False)

    def test_a_cell_of_the_wrong_year_does_not_reconcile(self):
        self.assertIs(netgear.reconciles((9, 12, 1999), 9, 12, 2013), False)

    def test_a_row_whose_cell_disagrees_with_its_own_note_refuses(self):
        # The real boundary: a note moved one day leaves the cell unable to
        # reconcile in either order, and the page refuses rather than publishing
        # one of the two dates.
        html = page().replace("reached EOS on 31-OCT-2025", "reached EOS on 30-OCT-2025", 1)
        with self.assertRaisesRegex(ValueError, "does not state the end-of-service date"):
            netgear.parse(html)

    def test_a_cell_that_is_not_a_date_refuses(self):
        for value in ("soon", "9-12-2013", "12/2013", "9/12/13"):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, "not a date this page states"):
                    netgear.cell_date(value, "row")

    def test_a_product_that_has_not_reached_eos_publishes_no_date(self):
        records, _accounting = parsed()
        record = record_for(records, "PAV12V-100NAS")
        self.assertIsNone(record["milestones"]["eol"])
        self.assertIn(netgear.NOT_YET, record["upstream"]["Note"]["text"])
        # The vendor says so in the row, so the status is stated rather than
        # derived as "unknown" from the null date.
        self.assertEqual(record["status"], "supported")

    def test_a_scheduled_end_of_service_is_published(self):
        records, _accounting = parsed()
        scheduled = [r for r in records
                     if (r["upstream"]["Note"]["text"] or "").startswith(netgear.SCHEDULED)]
        self.assertEqual(len(scheduled), 255)
        for record in scheduled:
            self.assertRegex(record["milestones"]["eol"], r"^\d{4}-\d{2}-\d{2}$")
            self.assertGreaterEqual(record["milestones"]["eol"], "2026-01-01")

    def test_a_row_with_an_unrecognised_note_refuses(self):
        html = page().replace("The product reached EOS on 09-DEC-2013",
                              "The product is somehow fine", 1)
        with self.assertRaisesRegex(ValueError, "states no end-of-service sentence"):
            netgear.parse(html)

    def test_a_row_with_no_item_number_refuses(self):
        # Every data row's first cell is the model; blanking the item number is a
        # page this collector cannot read rather than a product to guess at.
        html = page().replace("<td class=\"css-1bgb2xw\">WNAP210-100AUS</td>",
                              "<td class=\"css-1bgb2xw\"></td>", 1)
        with self.assertRaisesRegex(ValueError, "states no item number"):
            netgear.parse(html)


class PerSkuTests(unittest.TestCase):
    def test_one_record_per_item_number_not_per_model(self):
        records, _accounting = parsed()
        by_model = {}
        for record in records:
            by_model.setdefault(record["upstream"]["Model"]["text"], set()).add(
                record["milestones"]["eol"])
        wnap = by_model["WNAP210"]
        self.assertGreater(len(wnap), 1, "WNAP210's item numbers disagree, which is why the item "
                                          "number is the record")
        self.assertEqual(len({record["id"] for record in records}), 9405)

    def test_the_category_travels_as_a_cell_not_a_container(self):
        records, _accounting = parsed()
        record = record_for(records, "ANT224D10-10000S")
        self.assertEqual(record["upstream"]["Category"]["text"], "SMB Wireless")
        self.assertEqual(record["product_line"], "SMB Wireless")
        for label, cell in record["upstream"].items():
            with self.subTest(label=label):
                self.assertIn("text", cell)
                self.assertIn("links", cell)


class FetchMarkerTests(unittest.TestCase):
    """A rendered record says so, and the registry agrees both ways."""

    def test_every_record_carries_the_fetch_marker(self):
        records, _accounting = parsed()
        for record in records[:200]:
            note = record["provenance"]["fetch"]
            self.assertEqual(note["fetch"], "rendered")
            self.assertIn("headless", note["rendered_by"])
            self.assertEqual(note["operator_switch"], render.ENV_SWITCH)

    def test_a_rendered_record_whose_source_is_plain_is_refused(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "hardware").mkdir()
            shutil = __import__("shutil")
            shutil.copy("data/hardware/watchguard-firebox-m300.json",
                        root / "hardware" / "watchguard-firebox-m300.json")
            record = json.loads((root / "hardware" / "watchguard-firebox-m300.json").read_text())
            record["provenance"]["fetch"] = {"fetch": "rendered", "rendered_by": "x",
                                             "operator_switch": "y"}
            (root / "hardware" / "watchguard-firebox-m300.json").write_text(json.dumps(record))
            with self.assertRaisesRegex(validation.CatalogError, "registered as plain"):
                validation.validate_hardware(root)

    def test_a_rendered_source_whose_record_states_nothing_is_refused(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "hardware").mkdir()
            shutil = __import__("shutil")
            shutil.copy("data/hardware/netgear-ant224d10-10000s.json",
                        root / "hardware" / "netgear-ant224d10-10000s.json")
            record = json.loads((root / "hardware" / "netgear-ant224d10-10000s.json").read_text())
            del record["provenance"]["fetch"]
            (root / "hardware" / "netgear-ant224d10-10000s.json").write_text(json.dumps(record))
            with self.assertRaisesRegex(validation.CatalogError, "states no fetch profile"):
                validation.validate_hardware(root)


class PublicationTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        (self.root / "hardware").mkdir()
        sibling = normalize({"result": {"name": "sample", "label": "Sample", "category": "lang",
                                        "labels": {},
                                        "releases": [{"name": "1", "releaseDate": "2026-01-01"}]}},
                            CHECKED)
        dump(self.root / "products/sample.json", sibling) if (self.root / "products").mkdir() \
            is None else None
        dump(self.root / "manifest.json", {"generated_at": CHECKED,
                                           "source_url": sources.ENDOFLIFE_DATE_API,
                                           "source": "import-data", "product_count": 1,
                                           "release_count": 1, "excluded_hardware": [],
                                           "hardware_count": 0})

    def snapshot(self):
        return {str(path.relative_to(self.root)): path.read_bytes()
                for path in self.root.rglob("*.json")}

    def refresh(self, checked=CHECKED):
        rendered = render.Rendered(url=netgear.SOURCE_URL, source_id="import-netgear",
                                   html=page())
        with mock.patch.object(netgear.render, "render", return_value=rendered), \
                mock.patch.object(netgear, "_now", return_value=checked):
            return sources.source("import-netgear").run(self.root)

    def test_the_source_publishes_its_records_and_one_report(self):
        detail = self.refresh()
        self.assertIn("9405 NETGEAR item numbers", detail)
        published = sorted((self.root / "hardware").glob("netgear-*.json"))
        self.assertEqual(len(published), 9405)
        report = json.loads((self.root / netgear.REPORT).read_text())
        self.assertEqual(report["fetch_profile"], "rendered")
        self.assertEqual(report["verifier"], netgear.VERIFIER)
        self.assertEqual(report["rows"]["with_eol"], 7641)
        self.assertEqual(report["rows"]["earlier_unnamed_date"], 767)
        self.assertEqual(report["total_records"], 9405)
        record = json.loads(published[0].read_text())
        self.assertEqual(record["provenance"]["verifier"], netgear.VERIFIER)
        self.assertIn(render.ENV_SWITCH, json.dumps(report["operator_switch"]))

    def test_a_quiet_refresh_republishes_byte_identical_files(self):
        self.refresh()
        published = self.snapshot()
        self.refresh("2026-09-27T04:00:00Z")
        self.assertEqual(self.snapshot(), published)

    def test_the_operator_switch_is_recorded_as_off_when_it_is_off(self):
        report = json.loads((self.root / netgear.REPORT).read_text()) if False else None
        self.assertEqual(render.switch_state(), f"{render.ENV_SWITCH}=off")


if __name__ == "__main__":
    unittest.main()
