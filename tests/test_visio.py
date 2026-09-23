"""Regression tests for the Microsoft Visio collector, its registry entry and ownership.

The fixtures are the vendor's own Markdown renderings of its lifecycle pages
(``?accept=text/markdown``), plus the aggregate "Ending Support in <year>"
indexes, so these tests pin the parse against the real source rather than a
reconstruction of it. They pin the facts that matter for a Microsoft lifecycle
record: exactly the published lines are inventoried, Start Date never becomes
general availability, an end instant normalizes to the last fully supported
day, an unpublished deadline stays absent, a reshaped table or a repeated row
refuses instead of guessing, and the aggregate indexes corroborate the one-day
boundary. They also pin the shared-catalog rules — this source writes only its
own record, a foreign record is never overwritten, and a quiet refresh is
byte-identical.
"""
import json
import re
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest import mock

from engine import derived, importer, net, sources, validation, visio
from engine.importer import API, dump, normalize

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests/fixtures"
CHECKED = "2026-09-23T12:00:00Z"
DAY = re.compile(r"\d{4}-\d{2}-\d{2}$")
INDEX_DAY = re.compile(r"[A-Z][a-z]+ \d{1,2}, \d{4}")
MONTHS = {name: number for number, name in enumerate(
    ("January", "February", "March", "April", "May", "June", "July", "August",
     "September", "October", "November", "December"), start=1)}
VISIO_LINK = re.compile(r"\[([^\]]*)\]\([^)]*/lifecycle/products/(visio[^?)]*)")

PAGES = tuple((url, (FIXTURES / (url.rsplit("/", 1)[-1] + ".md")).read_text(encoding="utf-8"))
              for url in visio._page_urls())
INDEXES = {int(path.stem.rsplit("-", 1)[-1]): path.read_text(encoding="utf-8")
           for path in sorted(FIXTURES.glob("visio-end-of-support-*.md"))}


def parsed():
    return visio.parse_pages(PAGES)


def index_rows(markdown):
    """Every Visio entry of an aggregate index: ``(stated_day, link_text, slug)``.

    The index packs one calendar group per row as a run of product links
    followed by the date they share, so a row's links all carry that date.
    """
    found = []
    for line in markdown.splitlines():
        if not line.startswith("|") or "/lifecycle/products/visio" not in line:
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        stated = cells[-1]
        if not INDEX_DAY.fullmatch(stated):
            continue
        for text, slug in VISIO_LINK.findall(line):
            found.append((stated, text, slug))
    return found


def workbook_visio_rows():
    """The official export workbook's Visio rows, read with the standard library.

    The workbook is a checked reference for this collector rather than a refresh
    input, so the tests read it directly: nothing here is a dependency of
    ``engine.visio``. Returns ``{listing: [row]}``, each row keyed by its column
    letter, with a date serial converted to the ISO day it encodes.
    """
    import xml.etree.ElementTree as ET
    import zipfile

    ns = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
    with zipfile.ZipFile(FIXTURES / "visio-lifecycle-export.xlsx") as archive:
        strings = ["".join(node.text or "" for node in item.iter(ns + "t"))
                   for item in ET.fromstring(archive.read("xl/sharedStrings.xml"))]
        sheet = ET.fromstring(archive.read("xl/worksheets/sheet1.xml"))

    def cell_value(cell):
        node = cell.find(ns + "v")
        if node is None:
            return ""
        return strings[int(node.text)] if cell.get("t") == "s" else node.text

    rows = {}
    for row in sheet.iter(ns + "row"):
        cells = {re.sub(r"\d", "", cell.get("r")): cell_value(cell) for cell in row}
        if cells.get("A", "").startswith("Visio"):
            rows.setdefault(cells["A"], []).append(cells)
    return rows


def workbook_day(serial):
    """One workbook date serial as the ISO day it encodes."""
    return (date(1899, 12, 30) + timedelta(days=int(serial))).isoformat()


def scope_of_row(row):
    """The release scope a workbook row's own Release cell names, if any."""
    return visio.scope_of(row["C"]) if row.get("C") else None


def software_record(name="sample", verifier=None):
    record = normalize({"result": {"name": name, "label": name.title(), "category": "lang",
                                   "labels": {"eol": "Security Support"},
                                   "releases": [{"name": "1", "eolFrom": "2028-01-01"}]}}, CHECKED)
    record["provenance"]["verifier"] = verifier or sources.source("import-data").verifier
    return record


def catalog_root(directory, records):
    """A data directory holding ``records`` and the manifest the importer writes."""
    (directory / "products").mkdir(parents=True, exist_ok=True)
    for record in records:
        dump(directory / "products" / (record["id"] + ".json"), record)
    counted = [record for record in records
               if record["provenance"]["verifier"] == sources.source("import-data").verifier]
    dump(directory / "manifest.json", {
        "generated_at": CHECKED, "source_url": API, "product_count": len(counted),
        "release_count": sum(len(record["releases"]) for record in counted),
        "excluded_hardware": [], "source": "import-data"})


def report_of(releases=None, kept=(), detail=None):
    releases = parsed()[0] if releases is None else releases
    detail = parsed()[1] if detail is None else detail
    excluded = [{"url": url, "reason": reason} for url, reason in visio.EXCLUDED_OFFERINGS]
    return visio.report_for(releases, detail, list(kept), excluded, CHECKED)


class ParseTests(unittest.TestCase):

    def test_the_real_pages_yield_exactly_the_agreed_lines(self):
        releases, _ = parsed()
        # Independently counted from the vendor's tables: 11 Support Dates rows
        # (ten versioned desktop/LTSC lines plus Visio Plan 2) and 13 service-pack
        # / Original Release rows (2003 four, 2007 four, 2010 three, 2013 two).
        self.assertEqual(len(releases), 24)
        self.assertEqual([release["id"] for release in releases], [
            "visio-2024", "visio-ltsc-2024", "visio-2021", "visio-ltsc-2021", "visio-plan-2",
            "visio-2019", "visio-2016", "visio-2013", "visio-2013-sp1", "visio-2013-original",
            "visio-2010", "visio-2010-sp2", "visio-2010-sp1", "visio-2010-original",
            "visio-2007", "visio-2007-sp3", "visio-2007-sp2", "visio-2007-sp1",
            "visio-2007-original", "visio-2003", "visio-2003-sp3", "visio-2003-sp2",
            "visio-2003-sp1", "visio-2003-original"])

    def test_start_date_never_becomes_general_availability(self):
        releases, _ = parsed()
        # Microsoft's export guidance defines Start Date as "Date support started
        # for product", not as general availability, so no ga is published — and
        # the raw cell is still there to audit.
        self.assertTrue(all(release["milestones"]["ga"] is None for release in releases))
        by_id = {release["id"]: release for release in releases}
        self.assertEqual(by_id["visio-2024"]["upstream"]["cells"]["Start Date"],
                         "10/1/2024 8:00:00 AM")
        self.assertEqual(by_id["visio-2003-original"]["upstream"]["cells"]["Start Date"],
                         "11/17/2003 8:00:00 AM")

    def test_no_sale_or_security_only_milestone_is_invented(self):
        releases, _ = parsed()
        self.assertTrue(all(release["milestones"]["eos"] is None for release in releases))
        self.assertTrue(all(release["milestones"]["eossec"] is None for release in releases))
        # Mainstream End Date is a real cell on every fixed line and was never
        # allowed to fill a milestone.
        by_id = {release["id"]: release for release in releases}
        self.assertEqual(by_id["visio-2016"]["upstream"]["cells"]["Mainstream End Date"],
                         "10/14/2020 6:59:59 AM")
        self.assertEqual(by_id["visio-2016"]["milestones"]["eol"], "2025-10-14")

    def test_end_instants_normalize_to_the_last_fully_supported_day(self):
        by_id = {release["id"]: release for release in parsed()[0]}
        for release in by_id.values():
            if release["milestones"]["eol"] is not None:
                self.assertRegex(release["milestones"]["eol"], DAY, release["id"])
        expected = {
            "visio-2024": ("10/10/2029 6:59:59 AM", "2029-10-09"),
            "visio-ltsc-2024": ("10/10/2029 6:59:59 AM", "2029-10-09"),
            "visio-2021": ("10/14/2026 6:59:59 AM", "2026-10-13"),
            "visio-ltsc-2021": ("10/14/2026 6:59:59 AM", "2026-10-13"),
            "visio-2019": ("10/15/2025 6:59:59 AM", "2025-10-14"),
            "visio-2016": ("10/15/2025 6:59:59 AM", "2025-10-14"),
            "visio-2013": ("4/12/2023 6:59:59 AM", "2023-04-11"),
            "visio-2010": ("10/14/2020 6:59:59 AM", "2020-10-13"),
            "visio-2007": ("10/11/2017 6:59:59 AM", "2017-10-10"),
            "visio-2003": ("4/9/2014 6:59:59 AM", "2014-04-08"),
            "visio-2003-original": ("7/28/2005 6:59:59 AM", "2005-07-27"),
            "visio-2010-sp1": ("10/15/2014 6:59:59 AM", "2014-10-14"),
            "visio-2007-original": ("1/14/2009 6:59:59 AM", "2009-01-13"),
        }
        for release_id, (printed, normalized) in expected.items():
            release = by_id[release_id]
            self.assertEqual(release["milestones"]["eol"], normalized, release_id)
            # The printed instant survives verbatim, so the shift is auditable.
            self.assertIn(printed, release["upstream"]["cells"].values(), release_id)
        # The normalized day is never the printed day.
        for release in by_id.values():
            for value in release["upstream"]["cells"].values():
                self.assertNotEqual(value[:10], str(release["milestones"]["eol"]), release["id"])

    def test_a_deadline_the_page_does_not_state_stays_absent(self):
        # Visio Plan 2's Retirement Date cell reads "In Support": no date is
        # published for it, and none is inferred from the Modern cadence.
        plan2 = {release["id"]: release for release in parsed()[0]}["visio-plan-2"]
        self.assertEqual(plan2["upstream"]["cells"]["Retirement Date"], "In Support")
        self.assertEqual(plan2["milestones"],
                         {"ga": None, "eos": None, "eossec": None, "eol": None})

    def test_raw_headers_and_the_exact_page_url_are_retained(self):
        releases, detail = parsed()
        by_id = {release["id"]: release for release in releases}
        modern = by_id["visio-2024"]
        self.assertEqual(list(modern["upstream"]["cells"]), ["Listing", "Start Date",
                                                             "Retirement Date"])
        self.assertEqual(modern["upstream"]["table"], "Support Dates")
        self.assertEqual(modern["upstream"]["source_url"],
                         "https://learn.microsoft.com/en-us/lifecycle/products/visio-2024")
        fixed = by_id["visio-2010-sp1"]
        self.assertEqual(list(fixed["upstream"]["cells"]), ["Version", "Start Date", "End Date"])
        self.assertEqual(fixed["upstream"]["table"], "Releases")
        self.assertEqual(fixed["upstream"]["source_url"],
                         "https://learn.microsoft.com/en-us/lifecycle/products/visio-2010")
        self.assertEqual(by_id["visio-2010"]["upstream"]["editions"],
                         ["Premium", "Professional", "Standard"])
        self.assertEqual(len(detail), 11)

    def test_parsing_twice_is_identical(self):
        self.assertEqual(parsed(), parsed())

    def test_a_reshaped_support_table_refuses_the_parse(self):
        url, markdown = PAGES[0]
        reshaped = markdown.replace("| Listing | Start Date | Retirement Date |",
                                    "| Listing | Start Date | End of Life |", 1)
        with self.assertRaisesRegex(ValueError, "no Support Dates table declaring"):
            visio.parse_page(reshaped, url)

    def test_a_mixed_policy_and_table_refuses_the_parse(self):
        url, markdown = PAGES[0]
        mixed = markdown.replace("follows the [Modern]", "follows the [Fixed]", 1)
        with self.assertRaisesRegex(ValueError, "Fixed policy page has no Support Dates table"):
            visio.parse_page(mixed, url)

    def test_a_retitled_or_unregistered_page_refuses_the_parse(self):
        url, markdown = PAGES[0]
        with self.assertRaisesRegex(ValueError, "page title is"):
            visio.parse_page(markdown.replace("# Visio 2024", "# Visio 2025", 1), url)
        with self.assertRaisesRegex(ValueError, "No Visio listing is registered"):
            visio.parse_page(markdown, "https://learn.microsoft.com/en-us/lifecycle/products/visio")

    def test_a_support_table_with_two_rows_refuses_the_parse(self):
        url, markdown = PAGES[0]
        row = "| Visio 2024 | 10/1/2024 8:00:00 AM | 10/10/2029 6:59:59 AM |"
        with self.assertRaisesRegex(ValueError, "states 2 rows"):
            visio.parse_page(markdown.replace(row + "\n", row + "\n" + row + "\n", 1), url)

    def test_a_changed_end_instant_refuses_rather_than_being_shifted(self):
        url, markdown = PAGES[0]
        with self.assertRaisesRegex(ValueError, "not the published 6:59:59 AM instant"):
            visio.parse_page(markdown.replace("10/10/2029 6:59:59 AM",
                                              "10/10/2029 12:00:00 AM", 1), url)

    def test_a_reshaped_release_date_refuses_the_parse(self):
        url, markdown = PAGES[10]
        with self.assertRaisesRegex(ValueError, "unrecognized Microsoft lifecycle date"):
            visio.parse_page(markdown.replace("9/17/2007 8:00:00 AM", "September 2007", 1), url)

    def test_a_row_stated_twice_refuses_the_parse(self):
        # A page whose listing text produces a release id another page already
        # published is one line claimed twice: a review, never a silent
        # preference between the two. Microsoft does publish service-pack pages
        # for some products, so this is a reachable collision.
        extra = PAGES[0][1].replace("# Visio 2024", "# Visio 2013 SP1").replace(
            "| Visio 2024 |", "| Visio 2013 SP1 |")
        page = ("https://learn.microsoft.com/en-us/lifecycle/products/visio-2013-sp1", extra)
        with mock.patch.dict(visio.PAGE_NAMES, {"visio-2013-sp1": "Visio 2013 SP1"}):
            with self.assertRaisesRegex(ValueError, "is stated twice"):
                visio.parse_pages((PAGES[7], page))
        with self.assertRaisesRegex(ValueError, "is listed twice"):
            visio.parse_pages((PAGES[0], PAGES[0]))

    def test_editions_sentence_must_match_the_pages_own_list(self):
        url, markdown = PAGES[0]
        edited = markdown.replace("- Professional\n- Standard", "- Professional\n- Enterprise")
        with self.assertRaisesRegex(ValueError, "editions sentence"):
            visio.parse_page(edited, url)

    def test_an_unknown_service_pack_row_refuses_the_parse(self):
        url, markdown = PAGES[10]
        with self.assertRaisesRegex(ValueError, "unrecognized release row"):
            visio.parse_page(markdown.replace("| Service Pack 3 |", "| Update 3 |", 1), url)

    def test_a_service_pack_row_stated_twice_refuses_the_parse(self):
        url, markdown = PAGES[10]
        row = "| Service Pack 3 | 9/17/2007 8:00:00 AM | 4/9/2014 6:59:59 AM |"
        with self.assertRaisesRegex(ValueError, "stated twice in Releases"):
            visio.parse_page(markdown.replace(row + "\n", row + "\n" + row + "\n", 1), url)


class WorkbookTests(unittest.TestCase):
    """The official export workbook as a checked reference, never as a source.

    The refresh reads the product pages, so the workbook cannot drop or invent a
    line here. These tests measure the workbook against the pages and pin what
    the report discloses about it: every Visio row is present (edition rows
    included), the two sources agree on every published deadline, product-level
    and release-level ends stay distinct where the workbook separates them, and
    Microsoft's own export stores the same last-supported day this collector
    computes from the printed instant.
    """

    @classmethod
    def setUpClass(cls):
        cls.workbook = workbook_visio_rows()
        cls.releases = {release["id"]: release for release in parsed()[0]}
        cls.scoped = {page["listing"] for page in parsed()[1] if page["release_rows"]}

    def release_of(self, listing, row):
        """The published release a workbook row describes.

        A listing whose page carries a ``Releases`` table has one row per
        edition *and* one per release scope; a listing whose page does not has
        only its edition rows, which all describe the same release line.
        """
        scope = scope_of_row(row) if listing in self.scoped else None
        return self.releases[visio.release_id(listing, scope)]

    def stated_end(self, listing, row):
        """The workbook's own terminal day for one row.

        Modern lines retire (column I); Fixed lines end their extended phase
        where one exists (H) and otherwise their mainstream phase (G); a
        service-pack row states its own end (K). A line with none of them —
        Visio Plan 2's ``In Support`` — states no day at all.
        """
        for column in ("K", "I", "H", "G"):
            if row.get(column):
                return workbook_day(row[column])
        return None

    def test_the_workbook_carries_all_forty_three_visio_rows(self):
        self.assertEqual(len(self.workbook), 12)
        self.assertEqual(sum(len(rows) for rows in self.workbook.values()),
                         visio.WORKBOOK_VISIO_ROWS)
        self.assertEqual(visio.WORKBOOK_VISIO_ROWS, 43)
        # The current lines the implementation brief warned might be missing are
        # present at this revision, one row per edition.
        for listing in visio.WORKBOOK_CURRENT_LINES:
            self.assertIn(listing, self.workbook)
            self.assertEqual({row["B"] for row in self.workbook[listing]},
                             {"Professional", "Standard"})

    def test_every_workbook_row_agrees_with_the_page_it_describes(self):
        checked = 0
        for listing, rows in self.workbook.items():
            if listing == "Visio Services in SharePoint (in Microsoft 365)":
                continue    # an excluded offering, not a published line
            for row in rows:
                release = self.release_of(listing, row)
                self.assertEqual(release["milestones"]["eol"],
                                 self.stated_end(listing, row),
                                 f"{listing} {row.get('C', '')}")
                checked += 1
        # 43 rows less the single excluded offering's row.
        self.assertEqual(checked, 42)

    def test_the_workbook_keeps_product_and_release_ends_distinct(self):
        # Visio 2003 proves the two levels are not one date: the product's
        # extended end is 2014-04-08 while its Original Release ends
        # 2005-07-27. Publishing either for the other would fabricate a
        # deadline, and the committed rows keep them apart.
        for release_id, expected in (("visio-2003", "2014-04-08"),
                                     ("visio-2003-original", "2005-07-27")):
            self.assertEqual(self.releases[release_id]["milestones"]["eol"], expected)
        self.assertEqual(self.releases["visio-2003"]["upstream"]["cells"]
                         ["Extended End Date"], "4/9/2014 6:59:59 AM")
        self.assertEqual(self.releases["visio-2003-original"]["upstream"]["cells"]["End Date"],
                         "7/28/2005 6:59:59 AM")

    def test_the_workbook_states_start_dates_no_release_publishes_as_ga(self):
        for listing, rows in self.workbook.items():
            if listing == "Visio Services in SharePoint (in Microsoft 365)":
                continue
            for row in rows:
                release = self.release_of(listing, row)
                if row.get("F"):
                    # The workbook's Start Date (F) is the product's start; a
                    # release row states its own in Release Start Date (J).
                    column = "J" if scope_of_row(row) and row.get("J") else "F"
                    self.assertEqual(workbook_day(row[column]),
                                     visio.day(release["upstream"]["cells"]["Start Date"],
                                               f"{listing} Start Date"), listing)
                self.assertIsNone(release["milestones"]["ga"], listing)

    def test_the_workbook_stores_the_last_supported_day_not_the_printed_instant(self):
        # Microsoft's own export stores the day this collector computes, not the
        # printed day: Visio 2024's workbook end is 2029-10-09 while its page
        # prints 10/10/2029 6:59:59 AM. The boundary is visible in the vendor's
        # export as well as in the vendor's aggregate index, so it is the
        # vendor's own convention rather than an invention here.
        self.assertEqual(self.releases["visio-2024"]["upstream"]["cells"]
                         ["Retirement Date"], "10/10/2029 6:59:59 AM")
        self.assertEqual(self.releases["visio-2024"]["milestones"]["eol"], "2029-10-09")
        for listing, rows in self.workbook.items():
            if listing == "Visio Services in SharePoint (in Microsoft 365)":
                continue
            for row in rows:
                release = self.release_of(listing, row)
                self.assertEqual(release["milestones"]["eol"], self.stated_end(listing, row),
                                 f"{listing} {row.get('C', '')}")

    def test_the_report_records_the_reconciliation_it_discloses(self):
        report = report_of()
        used = [line for line in report["disclosures"] if visio.WORKBOOK_URL in line]
        self.assertEqual(len(used), 1)
        self.assertIn("43 Visio rows", used[0])
        for listing in visio.WORKBOOK_CURRENT_LINES:
            self.assertIn(listing, used[0])
        self.assertIn("product pages are the source", used[0])
        # The disclosure has to be honest about the artifact rather than repeat
        # the expectation: the workbook does carry the current lines, and the
        # earlier "missing" reading was a truncated conversion of it.
        self.assertIn("not what the artifact contains", used[0])
        self.assertIn("truncated text conversion", used[0])

    def test_the_rejected_omission_claim_was_a_truncation_not_the_workbook(self):
        # The 35-row reading the brief described is reproducible from a lossy
        # text conversion of the sheet, and it is what a naive pipe-table
        # reading drops: the converted form carries 1,000-odd fewer rows and
        # loses exactly the four current Visio lines. This is why the disclosure
        # corrects the expectation instead of repeating it.
        rows = workbook_visio_rows()
        self.assertEqual(sum(len(r) for r in rows.values()), visio.WORKBOOK_VISIO_ROWS)
        # A conversion that stops partway through the sheet loses the tail rows,
        # where the 2021 and 2024 Visio lines live (Excel rows 2725-2785 of
        # 2,943) purely because of their position, not their content.
        published_without_current = sum(
            len(r) for listing, r in rows.items()
            if listing not in visio.WORKBOOK_CURRENT_LINES)
        self.assertEqual(published_without_current, 35)
        self.assertEqual(visio.WORKBOOK_VISIO_ROWS - published_without_current, 8)


class BoundaryTests(unittest.TestCase):
    """The one-day end boundary, corroborated by Microsoft's own aggregate pages."""

    def test_every_visio_entry_on_every_aggregate_index_is_one_day_before_its_cell(self):
        # Every printed end instant a Visio page states, keyed by its ISO day.
        printed = {}
        for release in parsed()[0]:
            for value in release["upstream"]["cells"].values():
                if isinstance(value, str) and value.endswith("6:59:59 AM"):
                    month, day_of_month, year = value.split(" ")[0].split("/")
                    printed.setdefault(f"{year}-{int(month):02d}-{int(day_of_month):02d}",
                                       []).append(release["id"])
        self.assertEqual(len(INDEXES), 13)
        checked = 0
        for year, markdown in sorted(INDEXES.items()):
            for stated, text, slug in index_rows(markdown):
                if slug == "visio-services-in-sharepoint-in-microsoft-365":
                    # The excluded offering, asserted here so the index reading
                    # is complete and asserted again by the exclusion test.
                    self.assertEqual(stated, "February 10, 2023")
                    continue
                month, day_of_month, stated_year = re.search(
                    r"([A-Z][a-z]+) (\d{1,2}), (\d{4})", stated).groups()
                stated_day = f"{stated_year}-{MONTHS[month]:02d}-{int(day_of_month):02d}"
                # Every day an aggregate index states for a Visio line is the
                # day before a product page's printed end instant: that is the
                # normalization this collector applies, derived from Microsoft's
                # own two statements of the same deadline.
                following = (date.fromisoformat(stated_day) + timedelta(days=1)).isoformat()
                self.assertIn(following, printed,
                              f"{year} {text} {slug} -> {stated} matches no product-page cell")
                checked += 1
        # 13 index pages, 22 Visio entries, 21 of them published lines.
        self.assertEqual(checked, 21)

    def test_the_disclosed_index_counts_match_the_measured_indexes(self):
        # The disclosure states how much corroboration exists, so the number is
        # recomputed here from the saved index pages rather than trusted: every
        # Visio entry on every index page, less the one excluded offering.
        entries = sum(len(index_rows(markdown)) for markdown in INDEXES.values())
        self.assertEqual(entries - 1, visio.BOUNDARY_INDEX_ENTRIES)
        self.assertEqual(len(INDEXES), visio.BOUNDARY_INDEX_PAGES)
        joined = " ".join(report_of()["disclosures"])
        self.assertIn(f"({entries - 1} entries across {len(INDEXES)} index pages", joined)
        self.assertIn("all one calendar day before", joined)

    def test_the_module_states_the_boundary_and_the_workbook_independence(self):
        text = (visio.__doc__ + visio.report_for.__doc__).lower()
        self.assertIn("last fully supported calendar day", text)
        self.assertIn("is *not* read here", visio.__doc__)
        report = report_of()
        joined = " ".join(report["disclosures"])
        self.assertIn("last fully supported calendar day (2029-10-09)", joined)
        self.assertIn("does not depend on that artifact", joined)
        self.assertIn("43 Visio rows", joined)


class RecordTests(unittest.TestCase):

    def test_record_names_its_registered_source_and_publishes_no_identifier(self):
        record = visio.record_for(parsed()[0], CHECKED)
        self.assertEqual(record["id"], "visio")
        self.assertEqual(record["category"], "software")
        self.assertEqual(record["upstream_category"], "app")
        self.assertEqual(record["provenance"]["verifier"],
                         sources.source("import-visio").verifier)
        self.assertEqual(record["provenance"]["source_url"], visio.SOURCE_URL)
        self.assertEqual(record["links"]["html"], visio.SOURCE_URL)
        # Microsoft publishes no CPE for a Visio lifecycle line; none is invented.
        self.assertEqual(record["identifiers"], [])

    def test_the_record_validates_offline_against_its_own_cells(self):
        record = visio.record_for(parsed()[0], CHECKED)
        visio.validate_record(record)
        validation.check_derived(record)

    def test_a_tampered_milestone_is_refused_offline(self):
        record = visio.record_for(parsed()[0], CHECKED)
        record["releases"][0]["milestones"]["eol"] = "2030-10-09"
        with self.assertRaisesRegex(ValueError, "contradicts its stored cells"):
            visio.validate_record(record)

    def test_a_tampered_ga_is_refused_offline(self):
        record = visio.record_for(parsed()[0], CHECKED)
        record["releases"][0]["milestones"]["ga"] = "2024-10-01"
        with self.assertRaisesRegex(ValueError, "contradicts its stored cells"):
            visio.validate_record(record)

    def test_a_tampered_cell_is_refused_offline(self):
        record = visio.record_for(parsed()[0], CHECKED)
        release = next(entry for entry in record["releases"] if entry["id"] == "visio-2016")
        release["upstream"]["cells"]["Extended End Date"] = "10/15/2026 6:59:59 AM"
        with self.assertRaisesRegex(ValueError, "contradicts its stored cells"):
            visio.validate_record(record)

    def test_a_release_renamed_away_from_its_cells_is_refused(self):
        record = visio.record_for(parsed()[0], CHECKED)
        record["releases"][0]["id"] = "visio-2030"
        with self.assertRaisesRegex(ValueError, "does not name its own release line"):
            visio.validate_record(record)

    def test_a_tampered_derivation_is_refused_offline(self):
        # Visio publishes every date itself, so no release carries a derivation;
        # a hand-added one must still be re-checked rather than trusted.
        record = visio.record_for(parsed()[0], CHECKED)
        release = next(entry for entry in record["releases"] if entry["id"] == "visio-2024")
        release[derived.DERIVED_KEY] = {"eol": {
            "kind": "derived", "method": "release-plus-duration",
            "source_url": visio.SOURCE_URL,
            "quote": "Visio 2024 follows the Modern Lifecycle Policy and retires after five years.",
            "base_date": "2024-10-01", "base_label": "support start",
            "duration": {"value": 5, "unit": "year"}}}
        with self.assertRaisesRegex(ValueError, "is 2029-10-01, but the stored eol milestone"):
            visio.validate_record(record)

    def test_a_derivation_can_never_override_a_vendor_stated_date(self):
        # Visio states every date itself, so a derived entry beside a stated one
        # could only be an attempt to replace the vendor's own cell. This
        # collector refuses that outright, whichever milestone it targets.
        record = visio.record_for(parsed()[0], CHECKED)
        release = next(entry for entry in record["releases"] if entry["id"] == "visio-2016")
        release[derived.DERIVED_KEY] = {"eol": {
            "kind": "derived", "method": "release-trigger", "source_url": visio.SOURCE_URL,
            "quote": "Visio 2016 and Visio 2019 share the Fixed Lifecycle Policy end date.",
            "base_date": "2015-09-22", "base_label": "support start",
            "trigger": {"release_id": "visio-2019", "date": "2025-10-14",
                        "label": "Visio 2019 extended end date"}}}
        # The entry re-derives coherently to the stored date, yet the record is
        # still refused only when the date itself stops following the cell.
        visio.validate_record(record)
        release["milestones"]["eol"] = "2025-10-13"
        with self.assertRaisesRegex(ValueError, "contradicts its stored cells"):
            visio.validate_record(record)
        release["milestones"]["eol"] = "2025-10-14"
        visio.validate_record(record)
        # With the cell honoured again, an incoherent rule is caught by the
        # shared gate: the two checks agree rather than one accepting what the
        # other rejects.
        release[derived.DERIVED_KEY]["eol"]["trigger"]["date"] = "2025-10-13"
        with self.assertRaisesRegex(ValueError, "is not the eol milestone"):
            validation.check_derived(record)

    def test_a_derivation_keyed_by_an_absent_milestone_is_refused(self):
        record = visio.record_for(parsed()[0], CHECKED)
        release = next(entry for entry in record["releases"] if entry["id"] == "visio-plan-2")
        release[derived.DERIVED_KEY] = {"eol": {
            "kind": "derived", "method": "release-trigger", "source_url": visio.SOURCE_URL,
            "quote": "Visio Plan 2 follows the Modern Lifecycle Policy and retires later.",
            "base_date": "2017-10-18", "base_label": "support start",
            "trigger": {"release_id": "visio-2024", "date": "2029-10-09",
                        "label": "Visio 2024 retirement"}}}
        with self.assertRaisesRegex(ValueError, "milestone is absent"):
            visio.validate_record(record)

    def test_another_sources_verifier_is_refused(self):
        record = visio.record_for(parsed()[0], CHECKED)
        record["provenance"]["verifier"] = sources.source("import-data").verifier
        with self.assertRaisesRegex(ValueError, "Invalid Microsoft Visio source identity"):
            visio.validate_record(record)

    def test_a_line_the_pages_no_longer_state_is_retained_not_deleted(self):
        releases, _ = parsed()
        committed = visio.record_for(releases, CHECKED)
        fresh = [release for release in releases if release["id"] != "visio-2010-sp1"]
        combined, kept = visio.combine_releases(fresh, committed)
        self.assertEqual([entry["id"] for entry in kept], ["visio-2010-sp1"])
        retained = {release["id"]: release for release in combined}["visio-2010-sp1"]
        self.assertIs(retained["upstream"]["in_source"], False)
        self.assertEqual(retained["milestones"]["eol"], "2014-10-14")
        # A retained row is still publishable: a dropped page is not an end of life.
        visio.validate_record(visio.record_for(combined, CHECKED))

    def test_freshly_parsed_releases_carry_no_retention_marker(self):
        combined, kept = visio.combine_releases(parsed()[0], None)
        self.assertEqual(kept, [])
        self.assertTrue(all("in_source" not in release["upstream"] for release in combined))


class ReportTests(unittest.TestCase):

    def test_report_accounts_for_every_row_and_page_it_read(self):
        report = report_of()
        self.assertEqual(report["rows"]["seen"], 24)
        self.assertEqual(report["rows"]["published"], 24)
        self.assertEqual(report["rows"]["support_dates"], 11)
        self.assertEqual(report["rows"]["releases"], 13)
        self.assertEqual(report["rows"]["seen"],
                         report["rows"]["support_dates"] + report["rows"]["releases"])
        self.assertEqual(report["rows"]["excluded"], 0)
        self.assertEqual(report["rows"]["retained"], 0)
        self.assertEqual(report["pages"]["read"], 11)
        self.assertEqual(report["pages"]["listed"], 11)
        self.assertEqual(report["pages"]["with_release_rows"], 4)
        self.assertEqual(report["offerings"], {"excluded": 3, "published": 11})
        self.assertEqual(len(report["page_detail"]), 11)
        self.assertEqual(report["milestones"],
                         {"ga": 0, "eos": 0, "eossec": 0, "eol": 23})
        self.assertEqual(report["total_records"], 1)

    def test_every_page_detail_states_its_own_columns_and_end_column(self):
        detail = {entry["listing"]: entry for entry in report_of()["page_detail"]}
        self.assertEqual(detail["Visio 2024"]["columns"],
                         ["Listing", "Start Date", "Retirement Date"])
        self.assertEqual(detail["Visio 2024"]["end_column"], "Retirement Date")
        self.assertEqual(detail["Visio 2010"]["end_column"], "Extended End Date")
        self.assertEqual(detail["Visio LTSC 2021"]["end_column"], "Mainstream End Date")
        self.assertEqual(detail["Visio 2010"]["columns"],
                         ["Listing", "Start Date", "Mainstream End Date", "Extended End Date"])

    def test_the_report_lists_every_excluded_visio_offering_with_a_reason(self):
        report = report_of()
        excluded = {entry["url"]: entry["reason"] for entry in report["excluded"]}
        self.assertEqual(len(excluded), 3)
        self.assertIn(visio.SERVICES_URL, excluded)
        self.assertTrue(any("visio-plan-1" in url for url in excluded))
        self.assertTrue(any("deployment-guide-for-visio" in url for url in excluded))
        for reason in excluded.values():
            self.assertGreater(len(reason), 60)
        self.assertTrue(any("does not include the Visio desktop app" in reason
                            for reason in excluded.values()))

    def test_limitations_disclose_scope_and_precision_choices(self):
        report = report_of()
        joined = " ".join(report["limitations"])
        self.assertIn("Visio Services in SharePoint", joined)
        self.assertIn("Visio Plan 1", joined)
        self.assertIn("in_source false", joined)
        self.assertIn("updated_at", joined)


class CatalogRootCase(unittest.TestCase):
    """A data directory holding an import-data product, as the committed one does."""

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.sibling = software_record()
        catalog_root(self.root, [self.sibling])
        self.sibling_bytes = (self.root / "products/sample.json").read_bytes()

    def publish(self, pages=PAGES):
        releases, detail = visio.parse_pages(pages)
        record = visio.record_for(releases, CHECKED)
        report = report_of(releases, (), detail)
        return visio.publish_record(record, report, self.root)

    def import_with(self, overrides=None):
        """Run the real import, with the registered pages served from fixtures."""
        by_url = dict(PAGES)
        by_url.update(overrides or {})
        with mock.patch.object(
                net, "get_text",
                side_effect=lambda url: by_url[url.rsplit("?", 1)[0]]) as fetch:
            detail = visio.import_visio(self.root)
        return detail, fetch


class PublicationTests(CatalogRootCase):

    def test_publish_writes_only_its_own_record_and_report(self):
        self.publish()
        record = json.loads((self.root / "products/visio.json").read_text())
        self.assertEqual(record["id"], "visio")
        self.assertEqual(len(record["releases"]), 24)
        self.assertEqual((self.root / "products/sample.json").read_bytes(), self.sibling_bytes)
        report = json.loads((self.root / visio.REPORT).read_text())
        self.assertEqual(report["verifier"], visio.VERIFIER)
        self.assertEqual(report["total_records"], 1)
        self.assertEqual(len(validation.validate_data(self.root)), 2)

    def test_republishing_an_unchanged_source_is_byte_identical(self):
        published = self.publish()
        before = (self.root / "products/visio.json").read_bytes()
        report_before = (self.root / visio.REPORT).read_bytes()
        again = self.publish()
        self.assertEqual((self.root / "products/visio.json").read_bytes(), before)
        self.assertEqual((self.root / visio.REPORT).read_bytes(), report_before)
        self.assertEqual(published["provenance"]["last_checked"],
                         again["provenance"]["last_checked"])
        self.assertEqual(again["provenance"]["last_checked"], CHECKED)

    def test_a_quiet_refresh_at_a_later_timestamp_keeps_the_revision_time(self):
        self.publish()
        later = self.publish()
        self.assertEqual(later["provenance"]["last_checked"], CHECKED)

    def test_a_record_another_source_owns_is_never_overwritten(self):
        self.sibling["id"] = "visio"
        dump(self.root / "products/visio.json", self.sibling)
        with mock.patch.object(net, "get_text") as fetch:
            with self.assertRaisesRegex(ValueError, "ownership collision"):
                visio.import_visio(self.root)
        fetch.assert_not_called()
        self.assertEqual(json.loads((self.root / "products/visio.json").read_text()),
                         self.sibling)

    def test_a_parse_failure_writes_nothing(self):
        broken = [(PAGES[0][0], PAGES[0][1].replace("# Visio 2024", "# Visio 2025", 1))]
        with mock.patch.object(net, "get_text", return_value=broken[0][1]):
            with self.assertRaisesRegex(ValueError, "page title is"):
                visio.import_visio(self.root)
        self.assertEqual(sorted(path.name for path in (self.root / "products").glob("*.json")),
                         ["sample.json"])
        self.assertFalse((self.root / visio.REPORT).exists())

    def test_import_fetches_the_registered_pages_as_markdown(self):
        detail, fetch = self.import_with()
        self.assertEqual([call.args[0] for call in fetch.call_args_list],
                         [url + visio.ACCEPT for url in visio._page_urls()])
        # The registry's own URLs are the reader-facing pages, and the sources
        # page names them so the site attributes the right page.
        self.assertEqual([page.url for page in sources.source("import-visio").pages],
                         list(visio._page_urls()))
        self.assertIn("24 Microsoft Visio lifecycle lines", detail)
        self.assertIn(visio.REPORT, detail)
        self.assertEqual((self.root / "products/sample.json").read_bytes(), self.sibling_bytes)
        self.assertEqual(json.loads((self.root / visio.REPORT).read_text())["verifier"],
                         visio.VERIFIER)
        validation.validate_data(self.root)

    def test_import_retains_a_service_pack_row_the_page_dropped(self):
        # Microsoft drops a service-pack row from a Releases table. The
        # committed line is retained from its own cells rather than deleted: a
        # dropped row is not an end of life and introduces no date.
        self.import_with()
        dropped = {PAGES[8][0]: PAGES[8][1].replace(
            "| Service Pack 1 | 6/28/2011 8:00:00 AM | 10/15/2014 6:59:59 AM |\n", "")}
        detail, _ = self.import_with(dropped)
        self.assertIn("retained 1", detail)
        record = json.loads((self.root / "products/visio.json").read_text())
        retained = {release["id"]: release for release in record["releases"]}["visio-2010-sp1"]
        self.assertIs(retained["upstream"]["in_source"], False)
        self.assertEqual(retained["milestones"]["eol"], "2014-10-14")
        report = json.loads((self.root / visio.REPORT).read_text())
        self.assertEqual(report["retained"][0]["id"], "visio-2010-sp1")
        self.assertEqual(report["rows"]["retained"], 1)
        self.assertEqual(report["rows"]["seen"], 23)
        validation.validate_data(self.root)


class RegistryIntegrationTests(CatalogRootCase):

    def save_visio(self, verifier=None):
        record = visio.record_for(parsed()[0], CHECKED)
        if verifier:
            record["provenance"]["verifier"] = verifier
        dump(self.root / "products/visio.json", record)
        return record

    def test_validate_data_dispatches_to_the_owning_sources_validator(self):
        self.save_visio()
        records = validation.validate_data(self.root)
        self.assertEqual(sorted(record["id"] for record in records), ["sample", "visio"])

    def test_validate_data_refuses_a_visio_date_that_drifted(self):
        record = self.save_visio()
        record["releases"][0]["milestones"]["eol"] = "2030-10-09"
        dump(self.root / "products/visio.json", record)
        with self.assertRaisesRegex(ValueError, "contradicts its stored cells"):
            validation.validate_data(self.root)

    def test_validate_data_dispatches_only_records_the_owning_source_claims(self):
        # A record carrying another source's verifier is refused before that
        # source's own validator could be handed a row it does not understand.
        self.save_visio(verifier=sources.source("import-vgpu").verifier)
        with self.assertRaisesRegex(ValueError, "vGPU row without the"):
            validation.validate_data(self.root)

    def test_the_report_sidecar_is_checked_against_the_records_it_describes(self):
        record = self.save_visio()
        report = report_of()
        dump(self.root / visio.REPORT, report)
        self.assertEqual(len(validation.validate_data(self.root)), 2)
        report["total_records"] = 2
        dump(self.root / visio.REPORT, report)
        with self.assertRaisesRegex(ValueError, "reports 2 records but 1 carry"):
            validation.validate_data(self.root)
        del record
        report["total_records"] = 1
        report["verifier"] = sources.source("import-vgpu").verifier
        dump(self.root / visio.REPORT, report)
        with self.assertRaisesRegex(ValueError, "does not name the source"):
            validation.validate_data(self.root)


if __name__ == "__main__":
    unittest.main()
