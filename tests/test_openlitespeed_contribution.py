"""OpenLiteSpeed 1.7.x: a vendor-stated month, kept a month.

`contributions/openlitespeed.json` publishes OpenLiteSpeed 1.7.x as
`eossec 2025-09` / `eol 2025-09` — the month the vendor's own sentence states
("As of September 2025, OpenLiteSpeed version 1.7.x is archived and no longer
maintained"), never padded to a day and never carried by an exact-day surface.
The date is vendor-stated, not derived: a month-precision *statement* is a
different claim from arithmetic on a rule, so the record carries no
`milestone_provenance` and `validate_research` must accept it as it stands.

These tests pin the boundaries where a plausible mistake is silent: the month
padded to a day to satisfy a day-precision surface, the quote reworded in the
record, and the 1.7.x month leaking onto the `1.6.x & Older` line the same page
groups under "Archived". The vendor names only 1.7.x, so the older line is
published with no dates rather than inheriting them.
"""
import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

from engine import feeds, openeox, site_config, site_views
from engine.contribute import (
    build_record, check_file, date_in_quote, install_file, missing_backing,
    parse_contribution, research_object, research_view, validate_research)
from engine.importer import API, dump, normalize

CONTRIBUTION = Path(__file__).resolve().parents[1] / "contributions" / "openlitespeed.json"
# The vendor's own sentence, pinned verbatim: it is the only thing that states
# the month, so a reworded copy in the record is a review, not a silent edit.
QUOTE = ("As of September 2025, OpenLiteSpeed version 1.7.x is archived and no longer maintained. "
         "Please upgrade to version 1.8.x or 1.9.x.")
# The same page's current, undated classification. It is stored as evidence of
# the vendor's classification only; it states no end date for any branch.
CATEGORIES = "Version 1.9.x Latest Version 1.8.x Stable Version 1.7.x & Older Archived"
SOURCE = "https://openlitespeed.org/release-log/"
MONTH = "2025-09"
CHECKED = "2026-09-23T00:00:00Z"


def contribution():
    return json.loads(CONTRIBUTION.read_text(encoding="utf-8"))


class OpenLiteSpeedCase(unittest.TestCase):
    """The real contribution file, admitted into a throwaway catalog."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "products").mkdir()
        # One deterministic record plus the manifest, so the install path runs
        # the same catalog gate a real admission does rather than a laxer one.
        deterministic = normalize(
            {"result": {"name": "sample", "label": "Sample", "category": "lang",
                        "labels": {"eol": "Security Support"},
                        "releases": [{"name": "1", "eolFrom": "2028-01-01"}]}},
            CHECKED)
        dump(self.root / "products" / "sample.json", deterministic)
        dump(self.root / "manifest.json",
             {"generated_at": CHECKED, "source_url": API, "product_count": 1,
              "release_count": 1, "excluded_hardware": []})

    def offline(self, url):
        raise AssertionError(f"the focused test must not touch the network: {url}")

    def build(self):
        payload = contribution()
        parsed = parse_contribution(payload, path=str(CONTRIBUTION))
        research = research_object(parsed, parsed["evidence"], None)
        return build_record(parsed, research, CHECKED)

    def lines(self, record):
        return {release["id"]: release for release in record["releases"]}


class AdmissionTests(OpenLiteSpeedCase):
    """The contribution file passes the admission gate the CLI runs."""

    def test_the_contribution_check_passes(self):
        report = check_file(CONTRIBUTION, root=self.root, fetch=self.offline, allow_stale=True)
        self.assertEqual(report["action"], "check")
        self.assertEqual(report["id"], "researched-openlitespeed")
        self.assertEqual(report["verifier"], "researched-eoltracker-agent")
        self.assertFalse(report["written"])
        # The stored evidence was not refetched, and the report says so: the
        # dated sentence is preserved, not re-read from the live page.
        self.assertFalse(report["verified"])
        # Every branch the notice covers is named, the undated one included.
        self.assertEqual([line["id"] for line in report["releases"]], ["1.7", "1.6-and-older"])

    def test_the_live_page_no_longer_states_the_dated_sentence(self):
        # The dated sentence cannot be refetched, which is why the record is
        # admitted from stored evidence. A fetch that returns the page's current
        # text must be refused rather than silently accepted as verification.
        def current_page(url):
            return f"<html><body><p>{CATEGORIES}</p></body></html>"

        with self.assertRaisesRegex(ValueError, "Quote not found"):
            check_file(CONTRIBUTION, root=self.root, fetch=current_page)

    def test_the_install_lands_the_record(self):
        report = install_file(CONTRIBUTION, root=self.root, fetch=self.offline, allow_stale=True)
        self.assertEqual(report["action"], "install")
        stored = json.loads((self.root / "products" / "researched-openlitespeed.json").read_text())
        validate_research(stored, "software")
        self.assertEqual(self.lines(stored)["1.7"]["milestones"],
                         {"ga": None, "eos": None, "eossec": None, "eol": MONTH})

    def test_the_unrefetchable_quote_is_admitted_as_a_reading_not_a_live_check(self):
        # The live page no longer carries the dated sentence, so the record is
        # admitted from the stored evidence: verified_at stays null and the
        # record says so instead of claiming a check that never happened.
        record = self.build()
        self.assertIsNone(record["provenance"]["research"]["verified_at"])
        view = research_view(record, today=date(2026, 9, 23))
        self.assertFalse(view["verified"])
        self.assertEqual(view["source_url"], SOURCE)
        self.assertEqual(view["retrieved_at"], "2026-09-23")


class MonthPrecisionTests(OpenLiteSpeedCase):
    """The vendor states a month, so the stored deadline is a month."""

    def test_only_eol_is_the_stated_month(self):
        milestones = self.lines(self.build())["1.7"]["milestones"]
        self.assertEqual(milestones["eol"], MONTH)
        self.assertIsNone(milestones["eossec"])

    def test_the_month_is_never_padded_to_a_day(self):
        milestones = self.lines(self.build())["1.7"]["milestones"]
        self.assertTrue(site_config.is_month(milestones["eol"]))
        self.assertNotRegex(milestones["eol"], r"\d{4}-\d{2}-\d{2}")
        self.assertEqual(site_config.human_date(milestones["eol"]), "September 2025")
        self.assertEqual(site_config.month_end(milestones["eol"]), date(2025, 9, 30))

    def test_no_general_availability_or_end_of_sale_is_invented(self):
        # The vendor dates individual patch releases, never a branch's first
        # availability, and announces no end of sale: both stay absent.
        milestones = self.lines(self.build())["1.7"]["milestones"]
        self.assertIsNone(milestones["ga"])
        self.assertIsNone(milestones["eos"])

    def test_the_stated_month_is_not_a_derived_date(self):
        # A month the vendor states is not arithmetic on a rule, so the record
        # carries no milestone_provenance and re-derives the date literally.
        line = self.lines(self.build())["1.7"]
        self.assertNotIn("milestone_provenance", line)
        self.assertEqual(missing_backing(line["milestones"], contribution()["evidence"]), [])


class QuoteTests(OpenLiteSpeedCase):
    """The month is backed by the vendor's own sentence, stored verbatim."""

    def test_the_dated_sentence_is_stored_exactly(self):
        entry = next(item for item in contribution()["evidence"] if item["source_url"] == SOURCE
                     and "September 2025" in item["quote"])
        self.assertEqual(entry["milestones"], ["eol"])
        # Its own reading date, not the day the page was last re-read: the
        # sentence cannot be refetched, and the citation dates the reading.
        self.assertEqual(entry["retrieved_at"], "2026-09-17")

    def test_the_quote_states_the_month_and_no_day(self):
        self.assertTrue(date_in_quote(MONTH, QUOTE))
        # The sentence names September 2025, so no day may be stored as backed.
        for day in ("2025-09-01", "2025-09-30", "2025-09-17"):
            self.assertFalse(date_in_quote(day, QUOTE))

    def test_the_undated_category_backs_no_date(self):
        # The page's current "Version 1.7.x & Older Archived" classification is
        # recorded as the vendor's classification, not as evidence of a deadline.
        quotes = [item["quote"] for item in contribution()["evidence"]]
        self.assertIn(CATEGORIES, quotes)
        self.assertFalse(date_in_quote(MONTH, CATEGORIES))


class OlderBranchTests(OpenLiteSpeedCase):
    """The 1.7.x month does not transfer to the branches under "& Older"."""

    def test_the_older_line_is_published_with_no_dates(self):
        line = self.lines(self.build())["1.6-and-older"]
        self.assertEqual(line["milestones"],
                         {"ga": None, "eos": None, "eossec": None, "eol": None})
        self.assertNotIn("milestone_provenance", line)

    def test_the_vendor_sentence_names_1_7_x_only(self):
        # The only sentence that carries a date names 1.7.x, so it cannot back
        # a milestone on any other line.
        self.assertIn("1.7.x", QUOTE)
        self.assertNotIn("1.6", QUOTE)

    def test_only_the_named_branch_publishes_events(self):
        events = feeds.software_events([self.build()])
        self.assertEqual({event["release_id"] for event in events}, {"1.7"})
        self.assertEqual({event["date"] for event in events}, {MONTH})


class ExactSurfaceTests(OpenLiteSpeedCase):
    """A month-precision deadline is disclosed, never carried by an exact day."""

    def test_the_page_shows_the_stated_month(self):
        row = next(item for item in site_views.release_rows(self.build()) if item["id"] == "1.7")
        self.assertEqual(row["cells"]["eol"]["value"], MONTH)
        self.assertEqual(row["cells"]["eol"]["human"], "September 2025")
        self.assertTrue(row["cells"]["eol"]["month"])
        self.assertIsNone(row["cells"]["eol"]["derived"])
        self.assertIsNone(row["cells"]["eossec"]["value"])

    def test_the_feeds_exclude_the_month_from_the_day_documents(self):
        products = [self.build()]
        # Inside the month's own window the deadline is upcoming, so it is the
        # exclusion document — never a padded day — that carries it.
        events = feeds.upcoming_events(products, today=date(2025, 9, 1))
        days, excluded = feeds.representable(events)
        self.assertEqual(days, [])
        self.assertEqual({entry["date"] for entry in excluded}, {MONTH})
        document = feeds.exclusions_document(excluded, len(days),
                                             feeds.generated_at({"generated_at": CHECKED}))
        self.assertEqual(document["counts"]["upcoming_events"], 1)
        self.assertEqual(document["counts"]["feeds"], 0)
        self.assertEqual(document["counts"]["by_code"], {feeds.MONTH_EXCLUSION_CODE: 1,
                                                         feeds.DERIVED_EXCLUSION_CODE: 0})
        for entry in document["excluded"]:
            self.assertEqual(entry["code"], feeds.MONTH_EXCLUSION_CODE)
            self.assertEqual(entry["month"], MONTH)
            self.assertEqual(entry["human"], "September 2025")
            self.assertEqual(entry["product"], "researched-openlitespeed")
            self.assertNotIn("derived", entry)
        out = Path(self.temp.name) / "site"
        result = feeds.build(products, None, out_dir=out,
                             manifest={"generated_at": CHECKED})
        # The month is past by the build's own clock, so nothing is syndicated.
        self.assertEqual(result["events"], 0)
        for path in feeds.FEED_PATHS.values():
            self.assertNotIn(MONTH, (out / path).read_text(encoding="utf-8"))

    def test_openeox_excludes_the_month_and_writes_no_day(self):
        out = Path(self.temp.name) / "openeox"
        index = openeox.build([self.build()], site=out)
        codes = {row["code"] for row in index["excluded"]}
        self.assertEqual(codes, {"end_of_life_month_precision",
                                 "end_of_security_support_unknown"})
        month = next(row for row in index["excluded"]
                     if row["code"] == "end_of_life_month_precision")
        self.assertEqual((month["product"], month["release"]),
                         ("researched-openlitespeed", "1.7"))
        self.assertIn(MONTH, month["reason"])
        written = sorted(path.name for path in (out / "v1" / "openeox").rglob("*.json"))
        self.assertEqual(written, ["index.json"])


if __name__ == "__main__":
    unittest.main()
