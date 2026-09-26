"""The SolarWinds `ga` source, scoped (#119) — evidence, not a collector.

The per-version release notes state a "Release date:" line in prose. This test
pins the two pages the scope decision named, so the decision rests on saved
evidence rather than on a quotation, and so a future change to the vendor's
wording shows up as a failing assertion instead of a silent behaviour change.

It publishes nothing: `deterministic-solarwinds` records carry `ga: null`, and
`solarwinds-ga-scope.md` records why. The day is read here only to show what the
source states.
"""
import re
import unittest
from pathlib import Path

from engine import solarwinds, tables

FIXTURES = Path(__file__).parent / "fixtures"
PAGES = {
    "dpa 2026.2": ("progress-ga-scope-dpa-2026-2.htm", "June 30, 2026", "2026-06-30"),
    "SolarWinds Platform 2026.2": ("progress-ga-scope-solarwinds-platform-2026-2.htm",
                                   "June 9, 2026", "2026-06-09"),
}
RELEASE_DATE = re.compile(r"Release date:\s*(?P<date>[A-Z][a-z]+ \d{1,2}, \d{4})")


class ReleaseNoteDateTests(unittest.TestCase):
    def test_each_page_states_the_release_date_the_scope_decision_quotes(self):
        for product, (filename, stated, day) in PAGES.items():
            with self.subTest(product=product):
                html = (FIXTURES / filename).read_text(encoding="utf-8")
                found = RELEASE_DATE.search(tables.fold(html))
                self.assertIsNotNone(found, f"{product} states no 'Release date:' line")
                self.assertEqual(found.group("date"), stated)
                self.assertEqual(solarwinds.solarwinds_day(found.group("date"), product), day)

    def test_the_date_is_prose_and_not_a_lifecycle_table_column(self):
        # The date is vendor-stated prose on a release-notes page. It is not a
        # column of the release-history table, which is why a `ga` collector
        # would be a second source rather than a field of this one.
        for product, (filename, _stated, _day) in PAGES.items():
            html = (FIXTURES / filename).read_text(encoding="utf-8")
            doc = tables.parse_document(html)
            lifecycle = [block for block in doc.blocks
                         if solarwinds.TABLE_CLASS in (block.get("class") or "")]
            for block in lifecycle:
                labels = [tables.fold(cell["lead"]).lower() for row in block["rows"][:1]
                          for cell in row]
                self.assertNotIn("release date", labels, product)
            self.assertIn("Release date:", html, product)

    def test_no_published_record_carries_a_ga_it_cannot_derive(self):
        record = solarwinds._record("solarwinds-ncm", "SolarWinds NCM", [], "", "", "2026-09-26T00:00:00Z",
                                    {"eol": solarwinds.EOL_LABEL})
        self.assertEqual(record["releases"], [])
        self.assertEqual(record["labels"], {"eol": solarwinds.EOL_LABEL})


if __name__ == "__main__":
    unittest.main()
