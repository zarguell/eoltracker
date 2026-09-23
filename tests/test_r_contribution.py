"""R's successor-release retirement rule: six derived deadlines and one current line.

`contributions/r.json` publishes R 4.0 through 4.6, one row per x.y line. GA is
each line's own x.y.0 release day read from the Foundation's own CRAN base
archive row. The terminal `eol` of 4.0 through 4.5 is DERIVED: the Foundation's
own Software Development Life Cycle document states that "At a new x.y.0 version
of R, the prior version is retired from formal support", so each line ends on the
day its successor x.y.0 release is published. 4.6 is the current line and has no
announced end, so its dates stay unknown.

These tests pin the boundaries where a plausible mistake is silent: a trigger
naming an unpublished release, a derived deadline edited into a day its rule does
not produce, a derived date leaking into the exact-day feeds or the OpenEoX
export, the current line acquiring an invented end, and a generic "support"
sentence being collapsed into end-of-security-support.
"""
import json
import tempfile
import unittest
from datetime import date, datetime, timezone
from pathlib import Path

from engine import derived, feeds, openeox, site_config, site_views
from engine.contribute import (
    build_record, check_file, date_in_quote, install_file, missing_backing,
    parse_contribution, research_object, validate_research)
from engine.importer import API, dump, normalize

CONTRIBUTION = Path(__file__).resolve().parents[1] / "contributions" / "r.json"
# The Foundation's rule, pinned verbatim as the PDF states it: this sentence is
# what licenses every derived deadline, so a reworded copy in the record is a
# review of the derivation, not a silent edit. Only the apostrophe in "R Core’s"
# is typographic; the PDF publishes the sentence in prose, not as a heading.
RULE_QUOTE = ("At a new x.y.0 version of R, the prior version is retired from formal support. "
              "R Core\u2019s efforts are then focused on the new Release (and the ongoing "
              "Development) version. No further development, bug fixes or patches are made "
              "available for the retired versions.")
SDLC_PDF = "https://www.r-project.org/doc/R-SDLC.pdf"
ARCHIVE = "https://cran.r-project.org/src/base/R-4/"
# The successor relation the rule produces, and the archive row that dates each
# successor's own x.y.0 release.
LINES = {
    "4.0": ("2020-04-24", "4.1", "2021-05-18"),
    "4.1": ("2021-05-18", "4.2", "2022-04-22"),
    "4.2": ("2022-04-22", "4.3", "2023-04-21"),
    "4.3": ("2023-04-21", "4.4", "2024-04-24"),
    "4.4": ("2024-04-24", "4.5", "2025-04-11"),
    "4.5": ("2025-04-11", "4.6", "2026-04-24"),
}
CURRENT = "4.6"
CURRENT_GA = "2026-04-24"
GA_QUOTES = {
    "4.0": "R-4.0.0.tar.gz 2020-04-24 09:05 32M",
    "4.1": "R-4.1.0.tar.gz 2021-05-18 09:05 32M",
    "4.2": "R-4.2.0.tar.gz 2022-04-22 09:05 36M",
    "4.3": "R-4.3.0.tar.gz 2023-04-21 09:06 33M",
    "4.4": "R-4.4.0.tar.gz 2024-04-24 06:07 36M",
    "4.5": "R-4.5.0.tar.gz 2025-04-11 10:51 39M",
    "4.6": "R-4.6.0.tar.gz 2026-04-24 09:17 39M",
}
NO_END_YET = "The date for the next release is not yet set."
CHECKED = "2026-09-23T00:00:00Z"


def contribution():
    return json.loads(CONTRIBUTION.read_text(encoding="utf-8"))


class RCase(unittest.TestCase):
    """The real contribution file, admitted into a throwaway catalog."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "products").mkdir()
        # One deterministic record plus the manifest, so admission runs the same
        # catalog gate a real install does rather than a laxer one.
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


class AdmissionTests(RCase):
    """The contribution file passes the admission gate the CLI runs."""

    def test_the_contribution_check_passes(self):
        report = check_file(CONTRIBUTION, root=self.root, fetch=self.offline, allow_stale=True)
        self.assertEqual(report["action"], "check")
        self.assertEqual(report["id"], "researched-r")
        self.assertEqual(report["verifier"], "researched-eoltracker-agent")
        self.assertFalse(report["written"])

    def test_the_install_lands_every_line_the_notice_covers(self):
        report = install_file(CONTRIBUTION, root=self.root, fetch=self.offline, allow_stale=True)
        self.assertEqual(report["action"], "install")
        stored = json.loads((self.root / "products" / "researched-r.json").read_text())
        validate_research(stored, "software")
        self.assertEqual([line["id"] for line in stored["releases"]],
                         list(LINES) + [CURRENT])

    def test_the_ga_day_is_quoted_from_the_foundation_own_archive_row(self):
        # Every stated GA is backed by the archive row the checker can refetch,
        # so an admission with no offline flag re-verifies it live.
        record = self.build()
        quoted = [item["quote"] for item in contribution()["evidence"]
                  if item["source_url"] == ARCHIVE]
        for line_id, (ga, _, _) in LINES.items():
            self.assertEqual(GA_QUOTES[line_id], next(q for q in quoted if q.startswith(
                f"R-{line_id}.0.tar.gz")))
            self.assertTrue(date_in_quote(ga, GA_QUOTES[line_id]))
        self.assertEqual(self.lines(record)[CURRENT]["milestones"]["ga"], CURRENT_GA)
        self.assertTrue(date_in_quote(CURRENT_GA, GA_QUOTES[CURRENT]))


class SuccessorTriggerTests(RCase):
    """Each line ends on its own successor's published x.y.0 release day."""

    def test_every_derived_deadline_is_the_successor_release_day(self):
        lines = self.lines(self.build())
        for line_id, (ga, successor, successor_ga) in LINES.items():
            milestones = lines[line_id]["milestones"]
            self.assertEqual(milestones["ga"], ga, line_id)
            self.assertEqual(milestones["eol"], successor_ga, line_id)
            # The trigger names a release this record publishes, and the date it
            # names is that release's own stated GA day, not a computed one.
            self.assertEqual(lines[successor]["milestones"]["ga"], successor_ga, line_id)

    def test_every_entry_carries_the_rule_the_base_and_the_trigger(self):
        lines = self.lines(self.build())
        for line_id, (ga, successor, successor_ga) in LINES.items():
            entry = lines[line_id]["milestone_provenance"]["eol"]
            self.assertEqual(entry["kind"], "derived")
            self.assertEqual(entry["method"], "release-trigger")
            self.assertEqual(entry["source_url"], SDLC_PDF)
            self.assertEqual(entry["quote"], RULE_QUOTE)
            self.assertEqual(entry["base_date"], ga)
            self.assertTrue(date_in_quote(ga, GA_QUOTES[line_id]))
            self.assertEqual(entry["trigger"]["release_id"], successor)
            self.assertEqual(entry["trigger"]["date"], successor_ga)
            self.assertEqual(set(entry), {"kind", "method", "source_url", "quote",
                                          "base_date", "base_label", "trigger"})

    def test_the_rule_re_derives_every_stored_deadline(self):
        lines = self.lines(self.build())
        ids = set(lines)
        for line_id, (_, _, successor_ga) in LINES.items():
            self.assertEqual(
                derived.derive(lines[line_id]["milestones"],
                               lines[line_id]["milestone_provenance"], line_id, ids),
                {"eol": successor_ga})

    def test_a_trigger_naming_an_unpublished_release_is_refused(self):
        # The rule's successor must be a release this record publishes, so the
        # trigger's own day is quotable evidence rather than an outside claim.
        payload = contribution()
        for line in payload["releases"]:
            if line["id"] == "4.2":
                line["milestone_provenance"]["eol"]["trigger"]["release_id"] = "9.9"
        with self.assertRaisesRegex(ValueError, "names no release in this record"):
            parse_contribution(payload)

    def test_no_line_ends_on_its_own_release_day(self):
        # A line pointing at itself would claim the rule says something it does
        # not: every derived deadline is a *later* line's GA day, never its own.
        lines = self.lines(self.build())
        for line_id, (ga, successor, successor_ga) in LINES.items():
            self.assertNotEqual(successor, line_id)
            self.assertNotEqual(lines[line_id]["milestones"]["eol"], ga)
            self.assertEqual(lines[line_id]["milestones"]["eol"], successor_ga)
            self.assertLess(ga, successor_ga)

    def test_a_tampered_deadline_or_base_fails_the_catalog_gate(self):
        record = self.build()
        line = self.lines(record)["4.4"]
        line["milestones"]["eol"] = "2025-04-12"
        with self.assertRaisesRegex(ValueError, "is not the eol milestone"):
            validate_research(record, "software")
        record = self.build()
        line = self.lines(record)["4.4"]
        line["milestone_provenance"]["eol"]["trigger"]["date"] = "2025-04-12"
        with self.assertRaisesRegex(ValueError, "is not the eol milestone"):
            validate_research(record, "software")
        # A base moved past the successor's release day would make the rule end
        # the line before it began: the engine refuses that ordering.
        record = self.build()
        line = self.lines(record)["4.4"]
        line["milestone_provenance"]["eol"]["base_date"] = "2026-01-01"
        with self.assertRaisesRegex(ValueError, "precedes base_date"):
            validate_research(record, "software")

    def test_the_derived_deadline_is_exempt_from_the_literal_quote_rule(self):
        # The vendor states a rule, never the resulting day, so no stored quote
        # contains it: the entry's own rule quote is the evidence for that key.
        record = self.build()
        for line_id in LINES:
            line = self.lines(record)[line_id]
            self.assertEqual(
                missing_backing(line["milestones"],
                                record["provenance"]["research"]["evidence"],
                                line["milestone_provenance"]), [], line_id)


class CurrentLineTests(RCase):
    """4.6 is the current line: its end is unknown and stays absent."""

    def test_the_current_line_states_a_ga_and_no_end(self):
        line = self.lines(self.build())[CURRENT]
        self.assertEqual(line["milestones"],
                         {"ga": CURRENT_GA, "eos": None, "eossec": None, "eol": None})
        self.assertNotIn("milestone_provenance", line)

    def test_the_unknown_end_is_quoted_as_the_vendor_stating_it(self):
        developer = [item["quote"] for item in contribution()["evidence"]
                     if item["source_url"] == "https://developer.r-project.org/"]
        self.assertIn(NO_END_YET, developer)
        # The current release page dates the line's own patches; those are patch
        # releases of the current line and never a terminal date for it.
        self.assertTrue(any("Happy Hop" in quote for quote in developer))

    def test_no_upcoming_event_or_end_exists_for_the_current_line(self):
        record = self.build()
        rows = site_views.release_rows(record)
        summary = site_views.summarize(record, rows, date(2026, 9, 23))
        self.assertIsNone(summary["next"])
        self.assertTrue(summary["derived"])
        self.assertIsNone(rows[0]["cells"]["eol"]["value"])
        self.assertIsNone(rows[0]["cells"]["eol"]["derived"])


class PrecisionTests(RCase):
    """Every value here is a day, and no generic sentence fills eossec."""

    def test_no_stored_milestone_is_a_month(self):
        for line in self.build()["releases"]:
            for key, value in line["milestones"].items():
                if value:
                    self.assertFalse(site_config.is_month(value), f"{line['id']}.{key}")

    def test_eos_and_eossec_stay_null_on_every_line(self):
        # The Foundation states one combined retirement; a generic "retired from
        # formal support" never fills end-of-security-support, and no end of
        # sale is announced. Only the terminal milestone is ever derived.
        for line in self.build()["releases"]:
            self.assertIsNone(line["milestones"]["eos"], line["id"])
            self.assertIsNone(line["milestones"]["eossec"], line["id"])
            expected = {"eol"} if line["id"] in LINES else set()
            self.assertEqual(set(line.get("milestone_provenance") or {}), expected, line["id"])


class ExactSurfaceTests(RCase):
    """A derived deadline is disclosed everywhere and carried by no exact surface."""

    def test_the_page_shows_the_deadline_as_a_derived_cell(self):
        rows = site_views.release_rows(self.build())
        row = next(item for item in rows if item["id"] == "4.5")
        cell = row["cells"]["eol"]
        self.assertEqual(cell["value"], "2026-04-24")
        self.assertEqual(cell["derived"]["label"], "derived")
        self.assertEqual(cell["derived"]["method"], "release-trigger")
        self.assertEqual(cell["derived"]["quote"], RULE_QUOTE)
        self.assertEqual(row["cells"]["ga"]["derived"], None)

    def test_the_feeds_carry_only_the_successor_stated_day(self):
        # Today is moved before the last transition so exactly one derived
        # deadline is upcoming: 4.5's end, which coincides with 4.6's stated GA.
        products = [self.build()]
        events = feeds.upcoming_events(products, today=date(2026, 1, 1))
        days, excluded = feeds.representable(events)
        self.assertEqual([event["product_id"] for event in days], ["researched-r"])
        self.assertEqual([(event["release_id"], event["milestone"]) for event in days],
                         [(CURRENT, "ga")])
        self.assertEqual([(event["release_id"], event["milestone"]) for event in excluded],
                         [("4.5", "eol")])
        self.assertTrue(excluded[0]["derived"])
        self.assertEqual(excluded[0]["date"], "2026-04-24")
        # The documents are built from `days`, so the derived event's identity is
        # in none of them while the stated one is.
        stamp = datetime(2026, 9, 23, tzinfo=timezone.utc)
        documents = {"atom": feeds.atom_feed(days, stamp),
                     "rss": feeds.rss_feed(days, stamp),
                     "ics": feeds.calendar_feed(days, stamp)}
        for name, text in documents.items():
            self.assertNotIn(excluded[0]["id"], text, name)
            self.assertIn(days[0]["id"], text, name)

    def test_the_exclusion_document_publishes_the_rule_that_produced_it(self):
        products = [self.build()]
        events = feeds.upcoming_events(products, today=date(2026, 1, 1))
        days, excluded = feeds.representable(events)
        document = feeds.exclusions_document(excluded, len(days),
                                             datetime(2026, 9, 23, tzinfo=timezone.utc))
        self.assertEqual(document["counts"]["upcoming_events"], len(days) + len(excluded))
        self.assertEqual(document["counts"]["by_code"][feeds.DERIVED_EXCLUSION_CODE], 1)
        entry = document["excluded"][0]
        self.assertEqual(entry["code"], feeds.DERIVED_EXCLUSION_CODE)
        self.assertEqual((entry["product"], entry["release"]), ("researched-r", "4.5"))
        self.assertEqual(entry["date"], "2026-04-24")
        self.assertEqual(entry["derived"]["method"], "release-trigger")
        self.assertEqual(entry["derived"]["base_date"], "2025-04-11")
        self.assertEqual(entry["derived"]["trigger"]["release_id"], "4.6")
        self.assertEqual(entry["derived"]["quote"], RULE_QUOTE)

    def test_openeox_exports_no_derived_deadline(self):
        out = Path(self.temp.name) / "openeox"
        index = openeox.build([self.build()], site=out)
        self.assertEqual(index["counts"]["exported"], 0)
        codes = {}
        for row in index["excluded"]:
            codes.setdefault(row["release"], set()).add(row["code"])
        for line_id in LINES:
            self.assertEqual(codes[line_id], {"end_of_life_derived"}, line_id)
        self.assertEqual(codes[CURRENT], {"end_of_security_support_unknown"})
        derived_row = next(row for row in index["excluded"] if row["release"] == "4.5")
        self.assertIn("release-trigger", derived_row["reason"])
        self.assertIn("2025-04-11", derived_row["reason"])
        written = sorted(path.name for path in (out / "v1" / "openeox").rglob("*.json"))
        self.assertEqual(written, ["index.json"])

    def test_a_rewritten_deadline_is_refused_before_any_feed_sees_it(self):
        # A hand edit that changes the derived deadline cannot reach a feed: the
        # catalog gate refuses the record, so the exact surfaces only ever see
        # the value the stored rule produces.
        record = self.build()
        line = self.lines(record)["4.0"]
        line["milestones"]["eol"] = "2021-05-19"
        with self.assertRaises(ValueError):
            validate_research(record, "software")
        # The set of days the three documents would carry is the vendor-stated
        # ones only: no derived deadline is ever among them.
        events = feeds.upcoming_events([self.build()], today=date(2026, 1, 1))
        days, excluded = feeds.representable(events)
        self.assertEqual([event["date"] for event in days], [CURRENT_GA])
        self.assertTrue(all(event["derived"] for event in excluded))


if __name__ == "__main__":
    unittest.main()
