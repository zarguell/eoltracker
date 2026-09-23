"""Qiskit SDK lifecycle: the committed researched contribution (contributions/qiskit.json).

IBM publishes a real major-version support strategy, but it is stated in prose
and its durations are explicit *minimums* ("at least six months ... and one year
for security fixes") measured from a new major release whose date does not exist
yet. A minimum is not a terminal date, so nothing here is derived: every stored
date is one the vendor publishes, and the current 2.x series keeps its
`eossec`/`eol` null rather than projecting the policy onto it.

These tests pin the boundaries where a plausible mistake is silent: the minimum
policy turned into a 2.x deadline, the superseded "2024-08" month padded into a
day, the superseded "March 31st, 2026" security date stored instead of the
release that actually ended 1.x, the 1.4.5 bug-fix transition (2025-10-13)
mistaken for the end of the series, and an end-of-sale date invented for a
milestone IBM never mentions.
"""
import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

from engine import feeds, openeox, site_views
from engine.contribute import (
    build_record, check_file, date_in_quote, install_file, missing_backing,
    parse_contribution, research_object, research_view, validate_research)
from engine.importer import API, dump, normalize

CONTRIBUTION = Path(__file__).resolve().parents[1] / "contributions" / "qiskit.json"
CHECKED = "2026-09-23T00:00:00Z"

STRATEGY = "https://quantum.cloud.ibm.com/docs/en/guides/qiskit-sdk-version-strategy"
NOTES_046 = "https://quantum.cloud.ibm.com/docs/en/api/qiskit/release-notes/0.46"
NOTES_10 = "https://quantum.cloud.ibm.com/docs/en/api/qiskit/release-notes/1.0"
NOTES_14 = "https://quantum.cloud.ibm.com/docs/en/api/qiskit/release-notes/1.4"
NOTES_20 = "https://quantum.cloud.ibm.com/docs/en/api/qiskit/release-notes/2.0"
NOTES_23 = "https://quantum.cloud.ibm.com/docs/en/api/qiskit/release-notes/2.3"
PYPI = "https://pypi.org/project/qiskit/"
GH = "https://api.github.com/repos/Qiskit/qiskit/releases/tags/"
MILESTONE = "https://api.github.com/repos/Qiskit/qiskit/milestones/76"

SOURCES = {STRATEGY, NOTES_046, NOTES_10, NOTES_14, NOTES_20, NOTES_23, PYPI, MILESTONE,
           GH + "0.46.0", GH + "0.46.3", GH + "1.0.0", GH + "1.4.5", GH + "1.4.6", GH + "2.0.0"}

# The vendor's own sentences, pinned verbatim: each is the only thing that
# states the date stored beside it, so a reworded copy in the record is a
# review, not a silent edit.
MINIMUM_POLICY = ("With the release of a new major version, the previous major version is supported "
                  "for at least six months with only bug fixes, and one year for security fixes.")
MINIMUM_CADENCE = "The minimum period between major version releases is one year."
FINAL_PATCH_RULE = ("A final patch version is published when support is dropped, and that release "
                    "also documents the end of support for that major version series.")
END_046 = ("Qiskit 0.46.3 is a minor bugfix and backport release for the 0.46 series. It is also the "
           "last release of the 0.46 minor version, marking its end-of-life.")
SUPERSEDED_MONTH = ("the 0.46.x release will continue to be supported, with periodic patch releases "
                    "that contain bug fixes, for 6 months after the release of 1.0. That is, 0.46.x "
                    "will be supported until 2024-08.")
SUPERSEDED_SECURITY = ("Qiskit v1.4.5 is the last bugfix release in the 1.4 series and marks the "
                       "end-of-life of the series. Support for security fixes in the 1.4 series will "
                       "be continued until March 31st, 2026.")
END_1X = "Qiskit v1.4.6 is a security-only release, and the final release in the Qiskit v1.x series."
UNMAINTAINED = "Qiskit v1.x is no longer maintained in any form."
NO_30 = ("There will be further feature releases of Qiskit in the 2.x series; we do not expect to "
         "release Qiskit 3.0 until much later in 2026, as there is currently no need for breaking changes.")
THREE_ZERO_UNDATED = '"due_on":null,"closed_at":null'

# release line: (ga, eossec, eol) exactly as published.
EXPECTED = {
    "2.x": ("2025-03-31", None, None),
    "1.x": ("2024-02-15", "2026-06-12", "2026-06-12"),
    "0.46": ("2024-02-01", "2024-09-23", "2024-09-23"),
}
PUBLISHED = ["2.x", "1.x", "0.46"]
# Every stored day, and the ones the sources state but the record must not
# publish: the superseded month, the superseded security date, and the end of
# bug-fix-only support (which is not the end of the series).
STORED_DAYS = ["2024-02-01", "2024-02-15", "2024-09-23", "2025-03-31", "2026-06-12"]
NOT_TERMINAL = ["2025-10-13", "2026-03-31"]


def contribution():
    return json.loads(CONTRIBUTION.read_text(encoding="utf-8"))


def parsed():
    return parse_contribution(contribution(), path=str(CONTRIBUTION))


def record():
    payload = parsed()
    research = research_object(payload, payload["evidence"], None)
    return build_record(payload, research, CHECKED)


def lines():
    return {release["id"]: release for release in record()["releases"]}


class QiskitCase(unittest.TestCase):
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


class AdmissionTests(QiskitCase):
    """The contribution file passes the admission gate the CLI runs."""

    def test_the_contribution_check_passes(self):
        report = check_file(CONTRIBUTION, root=self.root, fetch=self.offline, allow_stale=True)
        self.assertEqual((report["action"], report["written"]), ("check", False))
        self.assertEqual(report["id"], "researched-qiskit")
        self.assertEqual(report["verifier"], "researched-eoltracker-agent")
        # Every branch the notice covers is named, in published order.
        self.assertEqual([line["id"] for line in report["releases"]], PUBLISHED)
        self.assertEqual(set(report["sources"]), SOURCES)
        # The stored evidence was not refetched, and the report says so.
        self.assertFalse(report["verified"])

    def test_the_install_lands_the_record(self):
        report = install_file(CONTRIBUTION, root=self.root, fetch=self.offline, allow_stale=True)
        self.assertEqual((report["action"], report["written"]), ("install", True))
        stored = json.loads((self.root / "products" / "researched-qiskit.json").read_text())
        validate_research(stored, "software")
        self.assertEqual({release["id"]: release["milestones"] for release in stored["releases"]},
                         {line: {"ga": ga, "eos": None, "eossec": eossec, "eol": eol}
                          for line, (ga, eossec, eol) in EXPECTED.items()})

    def test_a_missing_sentence_blocks_verification(self):
        # Verification is per stored sentence, not per page: a source that has
        # dropped even one of them cannot back the date it states, so the check
        # fails and names that source instead of admitting the record silently.
        payload = contribution()
        dropped = next(entry for entry in payload["evidence"] if entry["source_url"] == NOTES_14)
        page = "<html><body><p>" + "</p><p>".join(
            entry["quote"] for entry in payload["evidence"] if entry is not dropped) + "</p></body></html>"

        with self.assertRaisesRegex(ValueError, "Quote not found in " + NOTES_14 + ":") as caught:
            check_file(CONTRIBUTION, root=self.root, fetch=lambda url: page)
        # The report names the dropped sentence (truncated as every refusal is)
        # rather than admitting the record against a page that lost it.
        self.assertIn(dropped["quote"][:90], str(caught.exception))

    def test_a_reworded_quote_is_refused(self):
        # The date is only admitted because the vendor sentence states it, so a
        # fetch that no longer carries that sentence is refused rather than
        # silently accepted as verification.
        def fetch(url):
            return "<html><body><p>Qiskit is a software development kit.</p></body></html>"

        with self.assertRaisesRegex(ValueError, "Quote not found"):
            check_file(CONTRIBUTION, root=self.root, fetch=fetch)


class DateTests(QiskitCase):
    """Every stored date is the one the vendor publishes, at the day it states."""

    def test_the_stored_milestones_are_exactly_the_published_dates(self):
        for line, (ga, eossec, eol) in EXPECTED.items():
            milestones = lines()[line]["milestones"]
            self.assertEqual(milestones["ga"], ga)
            self.assertEqual(milestones["eossec"], eossec)
            self.assertEqual(milestones["eol"], eol)

    def test_every_stored_date_is_quoted_verbatim_from_its_source(self):
        payload = parsed()
        for release in record()["releases"]:
            self.assertEqual(
                missing_backing(release["milestones"], payload["evidence"]), [],
                f"a stored date on {release['id']} is not stated by any stored quote")

    def test_the_published_dates_are_exactly_the_expected_set(self):
        stated = sorted({release["milestones"][key]
                         for release in record()["releases"]
                         for key in ("ga", "eos", "eossec", "eol")
                         if release["milestones"][key]})
        self.assertEqual(stated, STORED_DAYS)

    def test_general_availability_is_the_first_final_release_of_each_series(self):
        payload = parsed()
        timestamps = {entry["source_url"]: entry["quote"] for entry in payload["evidence"]}
        for source, day in ((GH + "0.46.0", "2024-02-01"),
                            (GH + "1.0.0", "2024-02-15"),
                            (GH + "2.0.0", "2025-03-31")):
            self.assertIn(f'"published_at":"{day}', timestamps[source])
            self.assertTrue(date_in_quote(day, timestamps[source]))

    def test_no_end_of_sale_is_invented(self):
        # IBM says nothing about sale, orderability or commercial availability
        # of the open-source SDK, so eos stays absent on every line.
        for release in record()["releases"]:
            self.assertIsNone(release["milestones"]["eos"])

    def test_no_milestone_is_derived_from_a_rule(self):
        # Neither duration arithmetic nor a release trigger: every end date is
        # a terminal release the vendor published, so no line carries
        # milestone_provenance and every value re-derives literally.
        for release in record()["releases"]:
            self.assertNotIn("milestone_provenance", release)


class UnknownCurrentMajorTests(QiskitCase):
    """The current 2.x series has no announced end, and none is projected."""

    def test_the_current_series_publishes_no_terminal_date(self):
        self.assertEqual(lines()["2.x"]["milestones"],
                         {"ga": "2025-03-31", "eos": None, "eossec": None, "eol": None})

    def test_no_stored_date_is_later_than_the_research(self):
        # A projected 2.x deadline would necessarily land after the research
        # date; every stored date is a past release instead.
        self.assertLess(max(STORED_DAYS), "2026-09-23")
        self.assertLess(max(STORED_DAYS), research_object(
            parsed(), parsed()["evidence"], None)["retrieved_at"])

    def test_the_minimum_policy_is_stored_as_evidence_but_never_as_a_date(self):
        # "At least six months" and "one year" are lower bounds measured from a
        # major release that has not happened, so they license no date at all.
        payload = contribution()
        quotes = [entry["quote"] for entry in payload["evidence"]]
        self.assertIn(MINIMUM_POLICY, quotes)
        self.assertIn(MINIMUM_CADENCE, quotes)
        self.assertIn(FINAL_PATCH_RULE, quotes)
        for entry in payload["evidence"]:
            if entry["quote"] in (MINIMUM_POLICY, MINIMUM_CADENCE, FINAL_PATCH_RULE):
                self.assertNotIn("milestones", entry, "a policy sentence states no date")

    def test_the_undated_3_0_milestone_is_recorded_as_the_reason_the_clock_has_not_started(self):
        payload = contribution()
        entry = next(item for item in payload["evidence"] if item["source_url"] == MILESTONE)
        self.assertEqual(entry["quote"], THREE_ZERO_UNDATED)
        self.assertNotIn("milestones", entry)
        self.assertIn(NO_30, [item["quote"] for item in payload["evidence"]])


class SupersededStatementTests(QiskitCase):
    """A superseded or non-terminal statement is never stored as the deadline."""

    def test_the_superseded_month_is_not_padded_into_a_day(self):
        # The 1.0 notes said 0.46.x would be supported "until 2024-08", a month
        # whose later exact terminal release was 0.46.3 on 2024-09-23.
        self.assertIn(SUPERSEDED_MONTH, [entry["quote"] for entry in contribution()["evidence"]])
        self.assertTrue(date_in_quote("2024-08", SUPERSEDED_MONTH))
        for padded in ("2024-08-01", "2024-08-31"):
            self.assertFalse(date_in_quote(padded, SUPERSEDED_MONTH))
            self.assertNotIn(padded, STORED_DAYS)

    def test_the_superseded_security_date_is_not_stored(self):
        # 1.4.5 named 2026-03-31 for security fixes, then shipped a further
        # security-only release on 2026-06-12 that actually ended the series.
        self.assertIn(SUPERSEDED_SECURITY, [entry["quote"] for entry in contribution()["evidence"]])
        self.assertTrue(date_in_quote("2026-03-31", SUPERSEDED_SECURITY))
        self.assertNotIn("2026-03-31", STORED_DAYS)
        self.assertEqual(lines()["1.x"]["milestones"]["eossec"], "2026-06-12")

    def test_the_end_of_bug_fix_support_is_not_the_end_of_the_series(self):
        # 2025-10-13 (the 1.4.5 release) ends bug fixes only; that same sentence
        # continues security support, so it fills neither eossec nor eol.
        for day in NOT_TERMINAL:
            for release in record()["releases"]:
                self.assertNotIn(day, release["milestones"].values())
        entry = next(item for item in contribution()["evidence"]
                     if item["source_url"] == GH + "1.4.5")
        self.assertIn('"published_at":"2025-10-13', entry["quote"])
        self.assertNotIn("milestones", entry)

    def test_the_terminal_statements_back_the_dates_they_state(self):
        payload = contribution()
        quotes = [entry["quote"] for entry in payload["evidence"]]
        self.assertIn(END_046, quotes)
        self.assertIn(END_1X, quotes)
        self.assertIn(UNMAINTAINED, quotes)
        self.assertTrue(date_in_quote("2024-09-23", 'The 0.46.3 release "published_at":"2024-09-23T09:58:02Z"'))
        self.assertTrue(date_in_quote("2026-06-12", 'The 1.4.6 release "published_at":"2026-06-12T17:37:39Z"'))

    def test_both_ended_series_share_their_security_and_life_dates(self):
        # No separate security-only phase is stated for 0.46, and 1.x's last
        # release *is* its last security fix, so eossec and eol coincide: a
        # distinct eossec would have to be invented.
        for line in ("0.46", "1.x"):
            milestones = lines()[line]["milestones"]
            self.assertEqual(milestones["eossec"], milestones["eol"])


class SurfaceTests(QiskitCase):
    """The dates reach the surfaces that carry a stated day, and the nulls do not."""

    def test_the_page_shows_the_stated_dates_and_the_current_series_as_unknown(self):
        rows = {row["id"]: row for row in site_views.release_rows(record())}
        self.assertIsNone(rows["2.x"]["cells"]["eol"]["value"])
        self.assertIsNone(rows["2.x"]["cells"]["eossec"]["value"])
        self.assertEqual(rows["2.x"]["cells"]["ga"]["value"], "2025-03-31")
        self.assertEqual(rows["1.x"]["cells"]["eol"]["value"], "2026-06-12")
        self.assertEqual(rows["0.46"]["cells"]["eol"]["value"], "2024-09-23")
        for row in rows.values():
            for key in ("ga", "eos", "eossec", "eol"):
                self.assertFalse(row["cells"][key]["month"])
                self.assertIsNone(row["cells"][key]["derived"])

    def test_the_feeds_carry_the_stated_terminal_days_as_days(self):
        # A vendor-stated day is exactly what the day-precision formats carry,
        # so the 1.x terminal release is syndicated in its own window and is
        # not listed in the exclusion document.
        events = feeds.upcoming_events([record()], today=date(2026, 6, 1))
        self.assertEqual({event["release_id"] for event in events}, {"1.x"})
        self.assertEqual({event["date"] for event in events}, {"2026-06-12"})
        days, excluded = feeds.representable(events)
        self.assertEqual(excluded, [])
        self.assertEqual({event["milestone"] for event in days}, {"eossec", "eol"})

    def test_no_past_or_nonexistent_deadline_is_syndicated(self):
        # Today is past every date this record states, so nothing is upcoming
        # and the null 2.x terminals contribute no event at all.
        events = feeds.upcoming_events([record()], today=date(2026, 9, 23))
        self.assertEqual(events, [])
        self.assertEqual({event["release_id"] for event in feeds.software_events([record()])},
                         {"0.46", "1.x", "2.x"})

    def test_openeox_exports_the_ended_series_and_discloses_the_current_one(self):
        out = Path(self.temp.name) / "openeox"
        index = openeox.build([record()], site=out)
        self.assertEqual(index["counts"],
                         {"products": 1, "releases": 3, "exported": 2, "excluded": 1})
        self.assertEqual({row["release"] for row in index["records"]}, {"0.46", "1.x"})
        # 2.x has no stated end of security support or end of life, so it is
        # excluded with its reason rather than given a projected date or "tba".
        self.assertEqual([(row["product"], row["release"], row["code"]) for row in index["excluded"]],
                         [("researched-qiskit", "2.x", "end_of_security_support_unknown")])
        exported = {row["release"]: json.loads((out / row["path"]).read_text())
                    for row in index["records"]}
        self.assertEqual(exported["0.46"]["end_of_life"], "2024-09-23T23:59:59Z")
        self.assertEqual(exported["1.x"]["end_of_security_support"], "2026-06-12T23:59:59Z")
        self.assertNotIn("end_of_sales", exported["1.x"])
        # No record substitutes "tba" for a date the source does not state.
        for row in index["records"]:
            self.assertNotIn("tba", (out / row["path"]).read_text())

    def test_the_research_provenance_carries_the_review_window(self):
        view = research_view(record(), today=date(2026, 9, 23))
        self.assertEqual(view["contributor"], "eoltracker-agent")
        self.assertEqual(view["method"], "agent")
        self.assertEqual(view["retrieved_at"], "2026-09-23")
        self.assertEqual(view["stale_after"], "2027-03-22")
        self.assertFalse(view["verified"])
        self.assertFalse(view["stale"])
        self.assertEqual(set(view["sources"][0]), {"source_url", "retrieved_at", "quote"})


if __name__ == "__main__":
    unittest.main()
