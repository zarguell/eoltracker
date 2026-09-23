"""Open vSwitch's derived 3.3.x end date: a month the vendor's rule names.

`contributions/openvswitch.json` publishes Open vSwitch 3.3.x as
`ga 2024-02-16` (the project's own dated release-notes heading) and a DERIVED
`eol 2027-02`. The vendor dates the rule to 2026-08-17 and the trigger to
"the next release in February" only — no version, no day — so the derived
result must stay a month: padding it to a day would invent precision AGENTS.md
rule 4 forbids, and every day-precision surface must exclude it rather than
carry it.

These tests pin the boundaries where a plausible mistake is silent: a month
milestone rewritten to a day, a trigger date that drops to day precision, a
derived month leaking into the day-precision feeds or the OpenEoX export, and
the rule's sentence being reworded in the record.
"""
import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

from engine import derived, feeds, openeox, site_config, site_views
from engine.contribute import (
    build_record, check_file, date_in_quote, install_file, missing_backing,
    parse_contribution, research_object, validate_research)
from engine.importer import API, dump, normalize

CONTRIBUTION = Path(__file__).resolve().parents[1] / "contributions" / "openvswitch.json"
# The vendor's own sentences, pinned verbatim: the rule is the derivation's
# licence, so a reworded copy in the record is a review, not a silent edit.
GA_QUOTE_33 = "v3.3.0 - 16 Feb 2024 --------------------"
GA_QUOTE_40 = "v4.0.0 - 17 Aug 2026 --------------------"
RULE_QUOTE = ("Also, with the release of OVS 4.0, the 3.7.x series becomes our new LTS series. "
              "The old LTS series 3.3.x will be supported until the next release in February.")
ANNOUNCEMENT = "https://mail.openvswitch.org/pipermail/ovs-announce/2026-August/000400.html"
# The vendor names no day for the triggering release, and no version either.
RULE_TRIGGER_RELEASE = "next-release-2027-02"
RULE_TRIGGER_LABEL = ("the next Open vSwitch release after 4.0.0, named by the vendor only as "
                      "the release in February")
MONTH = "2027-02"
GA = "2024-02-16"
BASE = "2026-08-17"
CHECKED = "2026-09-23T00:00:00Z"


def contribution():
    return json.loads(CONTRIBUTION.read_text(encoding="utf-8"))


class OpenVSwitchCase(unittest.TestCase):
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


class AdmissionTests(OpenVSwitchCase):
    """The contribution file passes the admission gate the CLI runs."""

    def test_the_contribution_check_passes(self):
        report = check_file(CONTRIBUTION, root=self.root, fetch=self.offline, allow_stale=True)
        self.assertEqual(report["action"], "check")
        self.assertEqual(report["id"], "researched-openvswitch")
        self.assertEqual(report["verifier"], "researched-eoltracker-agent")
        self.assertFalse(report["written"])

    def test_the_install_lands_the_record_and_its_rule(self):
        report = install_file(CONTRIBUTION, root=self.root, fetch=self.offline, allow_stale=True)
        self.assertEqual(report["action"], "install")
        stored = json.loads((self.root / "products" / "researched-openvswitch.json").read_text())
        validate_research(stored, "software")
        entry = self.lines(stored)["3.3"]["milestone_provenance"]["eol"]
        self.assertEqual(entry["method"], "release-trigger")
        self.assertEqual(entry["base_date"], BASE)
        self.assertEqual(entry["trigger"], {
            "release_id": RULE_TRIGGER_RELEASE, "date": MONTH, "label": RULE_TRIGGER_LABEL})
        self.assertEqual(entry["quote"], RULE_QUOTE)
        self.assertEqual(entry["source_url"], ANNOUNCEMENT)


class MonthResultTests(OpenVSwitchCase):
    """The derived deadline keeps the width the vendor's rule states."""

    def test_the_3_3_x_end_is_the_stated_month_and_its_ga_is_the_stated_day(self):
        line = self.lines(self.build())["3.3"]
        self.assertEqual(line["milestones"],
                         {"ga": GA, "eos": None, "eossec": None, "eol": MONTH})

    def test_the_derived_month_is_never_padded_to_a_day(self):
        line = self.lines(self.build())["3.3"]
        eol = line["milestones"]["eol"]
        self.assertTrue(site_config.is_month(eol))
        # The value is a month and nothing finer: no day the vendor did not name.
        self.assertNotRegex(eol, r"\d{4}-\d{2}-\d{2}")
        self.assertEqual(site_config.human_date(eol), "February 2027")
        self.assertEqual(site_config.month_end(eol), date(2027, 2, 28))
        # The trigger keeps the same precision, so the rule cannot produce a day.
        self.assertTrue(site_config.is_month(line["milestone_provenance"]["eol"]["trigger"]["date"]))
        self.assertEqual(derived.derive(line["milestones"], line["milestone_provenance"],
                                        "3.3", {"3.3", RULE_TRIGGER_RELEASE}),
                         {"eol": MONTH})

    def test_the_base_date_is_the_vendors_own_dated_release_day(self):
        # The one input that stays a full day: 4.0.0's general availability, the
        # day the vendor dates both its announcement and its release notes.
        entry = self.lines(self.build())["3.3"]["milestone_provenance"]["eol"]
        self.assertEqual(entry["base_date"], BASE)
        self.assertTrue(date_in_quote(BASE, GA_QUOTE_40))
        self.assertFalse(date_in_quote(BASE, RULE_QUOTE))

    def test_no_end_of_security_support_is_read_from_the_generic_support_sentence(self):
        # The rule says the series "will be supported", one combined end: a
        # generic support date never fills eossec, and eos is unpublished too.
        milestones = self.lines(self.build())["3.3"]["milestones"]
        self.assertIsNone(milestones["eossec"])
        self.assertIsNone(milestones["eos"])
        self.assertEqual(set(self.lines(self.build())["3.3"]["milestone_provenance"]), {"eol"})

    def test_the_triggering_release_is_published_undated_rather_than_invented(self):
        # The rule names a release the announcement leaves unnamed, so the record
        # carries that release as its own line with no guessed date or version.
        lines = self.lines(self.build())
        self.assertIn(RULE_TRIGGER_RELEASE, lines)
        self.assertEqual(lines[RULE_TRIGGER_RELEASE]["milestones"],
                         {"ga": None, "eos": None, "eossec": None, "eol": None})

    def test_a_day_rewrite_of_the_derived_month_is_refused(self):
        # A hand edit that pads the month, or drops the trigger to a day, must
        # fail the catalog gate instead of publishing an invented day.
        record = self.build()
        line = self.lines(record)["3.3"]
        line["milestones"]["eol"] = "2027-02-15"
        with self.assertRaisesRegex(ValueError, "precisions|is not the eol milestone"):
            validate_research(record, "software")
        record = self.build()
        line = self.lines(record)["3.3"]
        line["milestone_provenance"]["eol"]["trigger"]["date"] = "2027-02-15"
        with self.assertRaisesRegex(ValueError, "precisions"):
            validate_research(record, "software")


class QuoteTests(OpenVSwitchCase):
    """The rule is stored as the vendor's own sentence, and only it."""

    def test_the_rule_quote_is_the_vendor_sentence_verbatim(self):
        entry = self.lines(self.build())["3.3"]["milestone_provenance"]["eol"]
        self.assertEqual(entry["quote"], RULE_QUOTE)
        self.assertEqual(entry["source_url"], ANNOUNCEMENT)
        # Stored once per source, so the announcement's sentence is citable.
        quotes = [item["quote"] for item in contribution()["evidence"]
                  if item["source_url"] == ANNOUNCEMENT]
        self.assertIn(RULE_QUOTE, quotes)
        # The vendor's own dated headings back the two base dates, verbatim.
        sources = {item["source_url"]: item["quote"] for item in contribution()["evidence"]}
        self.assertEqual(sources["https://www.openvswitch.org/releases/NEWS-3.3.0.txt"], GA_QUOTE_33)
        self.assertEqual(sources["https://www.openvswitch.org/releases/NEWS-4.0.0.txt"], GA_QUOTE_40)

    def test_the_derived_month_is_exempt_from_the_literal_quote_rule(self):
        # The vendor states a month and a rule, never the resulting day, so no
        # sentence contains "2027-02" as a date: the rule's own quote is the
        # evidence for exactly that key and the date stays derived.
        record = self.build()
        line = self.lines(record)["3.3"]
        self.assertEqual(missing_backing(line["milestones"], record["provenance"]["research"]["evidence"],
                                         line["milestone_provenance"]), [])
        self.assertEqual(RULE_QUOTE, self.lines(record)["3.3"]["milestone_provenance"]["eol"]["quote"])

    def test_no_approximate_schedule_day_is_stored_anywhere(self):
        # The release-scheduling table's dates are approximate and the cadence is
        # not evidence, so the record publishes no day beyond the two the vendor
        # dated itself; the derived deadline stays a month.
        record = self.build()
        line = self.lines(record)["3.3"]
        entry = line["milestone_provenance"]["eol"]
        days = {value for value in line["milestones"].values() if value and not site_config.is_month(value)}
        days |= {entry["base_date"]}
        self.assertEqual(days, {GA, BASE})
        for approximate in ("2027-02-15", "2027-02-01", "2026-08-15"):
            self.assertNotIn(approximate, days)


class ExactSurfaceTests(OpenVSwitchCase):
    """A derived month is disclosed everywhere and carried by no exact surface."""

    def test_the_deadline_reaches_the_page_as_a_derived_month(self):
        record = self.build()
        rows = site_views.release_rows(record)
        row = next(item for item in rows if item["id"] == "3.3")
        cell = row["cells"]["eol"]
        self.assertEqual(cell["value"], MONTH)
        self.assertEqual(cell["human"], "February 2027")
        self.assertEqual(cell["derived"]["label"], "derived")
        self.assertEqual(cell["derived"]["method"], "release-trigger")
        self.assertEqual(cell["derived"]["quote"], RULE_QUOTE)
        self.assertEqual(row["cells"]["ga"]["derived"], None)
        # The summary does not advertise a derived deadline as the next one.
        summary = site_views.summarize(record, rows, date(2026, 9, 23))
        self.assertIsNone(summary["next"])
        self.assertTrue(summary["derived"])

    def test_the_feeds_exclude_the_derived_month_with_its_rule(self):
        out = Path(self.temp.name) / "site"
        result = feeds.build([self.build()], None, out_dir=out,
                             manifest={"generated_at": CHECKED})
        self.assertEqual((result["events"], result["excluded"]), (0, 1))
        for path in feeds.FEED_PATHS.values():
            self.assertNotIn(MONTH, (out / path).read_text(encoding="utf-8"))
        excluded = json.loads((out / feeds.EXCLUSIONS_PATH).read_text(encoding="utf-8"))
        entry = excluded["excluded"][0]
        self.assertEqual(entry["code"], feeds.DERIVED_EXCLUSION_CODE)
        self.assertEqual(entry["date"], MONTH)
        self.assertEqual(entry["month"], MONTH)
        self.assertEqual(entry["milestone"], "eol")
        self.assertEqual(entry["derived"]["base_date"], BASE)
        self.assertEqual(entry["derived"]["trigger"]["release_id"], RULE_TRIGGER_RELEASE)
        self.assertEqual(entry["derived"]["quote"], RULE_QUOTE)

    def test_openeox_excludes_the_derived_month_and_never_writes_a_day(self):
        out = Path(self.temp.name) / "openeox"
        index = openeox.build([self.build()], site=out)
        codes = {row["code"] for row in index["excluded"]}
        self.assertEqual(codes, {"end_of_life_month_precision",
                                 "end_of_security_support_unknown"})
        month = next(row for row in index["excluded"]
                     if row["code"] == "end_of_life_month_precision")
        self.assertEqual((month["product"], month["release"]), ("researched-openvswitch", "3.3"))
        self.assertIn(MONTH, month["reason"])
        written = sorted(path.name for path in (out / "v1" / "openeox").rglob("*.json"))
        self.assertEqual(written, ["index.json"])

    def test_the_month_is_upcoming_and_still_excluded_not_syndicated(self):
        # The month is upcoming through its own end, so it lands in the split —
        # on the exclusion side, never syndicated as a padded day.
        products = [self.build()]
        events = feeds.upcoming_events(products, today=date(2026, 9, 23))
        self.assertEqual([event["date"] for event in events], [MONTH])
        self.assertTrue(events[0]["derived"])
        days, excluded = feeds.representable(events)
        self.assertEqual((days, [event["id"] for event in excluded]), ([], [events[0]["id"]]))


if __name__ == "__main__":
    unittest.main()
