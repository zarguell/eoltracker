"""FreeRTOS LTS: a day-precision deadline with a month-precision release.

`contributions/freertos-lts.json` publishes the AWS-maintained FreeRTOS LTS
distribution, one row per LTS branch initial release, from the branch's own
pinned `.00` tag:

* `202604.00-LTS` — `ga 2026-04`, `eossec 2028-04-30`, `eol 2028-04-30`;
* `202406.00-LTS` — `ga 2024-06`, `eossec 2026-06-30`, `eol 2026-06-30`.

The two widths are the point. The `LTS Until` cell of the branch README table
states a day, quoted verbatim, so `eossec`/`eol` are days; the official
changelog heading states the release as a month ("## 202406.00-LTS (June
2024)"), so `ga` is a month and is never padded to `2024-06-01` (AGENTS.md rule
4). Both end milestones carry that one day because the labelled window *is* the
LTS support window and its stated content is "security updates and critical bug
fixes" — the day security fixes stop is the day the branch's support ends.
`eos` stays unknown (open source, nothing is sold) and AWS's EMP ("up to an
additional 10 years") is conditional on a subscription, so it is stored as a
quote and never as a deadline.

These tests pin the boundaries where a plausible mistake is silent: a month
padded into a day, a day cited from a mutable branch name instead of the pinned
tag, an ordinary kernel tag published as a lifecycle-bearing line, the
conditional EMP window turned into a universal EOL, and the vendor sentences
reworded in the record.
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

CONTRIBUTION = Path(__file__).resolve().parents[1] / "contributions" / "freertos-lts.json"
CHECKED = "2026-09-23T00:00:00Z"

# The branch tables, pinned to the release tag rather than the branch name: the
# mutable 202406-LTS branch README now shows the patched component versions,
# while the `.00` tag still states the initial ones under the same deadline.
README_202604 = "https://raw.githubusercontent.com/FreeRTOS/FreeRTOS-LTS/202604.00-LTS/README.md"
README_202406 = "https://raw.githubusercontent.com/FreeRTOS/FreeRTOS-LTS/202406.00-LTS/README.md"
CHANGELOG_202604 = "https://raw.githubusercontent.com/FreeRTOS/FreeRTOS-LTS/202604.00-LTS/CHANGELOG.md"
CHANGELOG_202406 = "https://raw.githubusercontent.com/FreeRTOS/FreeRTOS-LTS/202406.00-LTS/CHANGELOG.md"

# The vendor's own sentences, pinned verbatim: each stored date is read from
# one of them, so a reworded copy in the record is a review, not a silent edit.
TABLE_202604 = ("Libraries in this GitHub branch (also listed below) are part of the FreeRTOS "
                "202604-LTS release. Learn more at https://freertos.org/lts-libraries.html. | Library "
                "| Version | LTS Until | LTS Repo URL | |------------------------- "
                "|---------------------|------------|------------------------------------------------"
                "------------------------------- | | FreeRTOS Kernel | 11.3.0 | 04/30/2028 | "
                "https://github.com/FreeRTOS/FreeRTOS-Kernel/tree/V11.3.0 |")
TABLE_202406 = ("Libraries in this GitHub branch (also listed below) are part of the FreeRTOS "
                "202406-LTS release. Learn more at https://freertos.org/lts-libraries.html. | Library "
                "| Version | LTS Until | LTS Repo URL | |------------------------- "
                "|---------------------|------------|------------------------------------------------"
                "------------------------------- | | FreeRTOS Kernel | 11.1.0 | 06/30/2026 | "
                "https://github.com/FreeRTOS/FreeRTOS-Kernel/tree/V11.1.0 |")
HEADING_202604 = ("## 202604.00-LTS (April 2026) Long Term Support (LTS) release of the following "
                  "libraries:")
HEADING_202406 = ("## 202406.00-LTS (June 2024) Long Term Support (LTS) release of the following "
                  "libraries:")
POLICY = ("FreeRTOS offers feature stability with long term support (LTS) releases. FreeRTOS LTS "
          "libraries come with security updates and critical bug fixes to the FreeRTOS kernel and "
          "IoT libraries listed below for two years, and are maintained by AWS for the benefit of "
          "the FreeRTOS community.")
EMP = ("AWS also offers FreeRTOS Extended Maintenance Plan (EMP) that provides you with security "
       "patches and critical bug fixes on your chosen FreeRTOS LTS version for up to an additional "
       "10 years.")

# The two LTS branches, newest first, as the record publishes them.
CURRENT, PREVIOUS = "202604.00-LTS", "202406.00-LTS"
STATED = {
    CURRENT: {"ga": "2026-04", "eos": None, "eossec": "2028-04-30", "eol": "2028-04-30"},
    PREVIOUS: {"ga": "2024-06", "eos": None, "eossec": "2026-06-30", "eol": "2026-06-30"},
}
# Ordinary kernel tags: release notes and no support deadline, so they are not
# lifecycle lines and none of these days may appear in the record.
KERNEL_TAGS = ("V11.3.1", "V11.3.0", "V11.1.0")


def contribution():
    return json.loads(CONTRIBUTION.read_text(encoding="utf-8"))


def parsed():
    return parse_contribution(contribution(), path=str(CONTRIBUTION))


def record():
    parsed_contribution = parsed()
    research = research_object(parsed_contribution, parsed_contribution["evidence"], None)
    return build_record(parsed_contribution, research, CHECKED)


def by_id():
    return {release["id"]: release for release in record()["releases"]}


class FreeRTOSCase(unittest.TestCase):
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
        parsed_contribution = parsed()
        research = research_object(parsed_contribution, parsed_contribution["evidence"], None)
        return build_record(parsed_contribution, research, CHECKED)

    def lines(self, record_value=None):
        return {release["id"]: release for release in (record_value or self.build())["releases"]}


class AdmissionTests(FreeRTOSCase):
    """The contribution file passes the admission gate the CLI runs."""

    def test_the_contribution_checks_and_installs_without_a_fetch(self):
        report = check_file(CONTRIBUTION, root=self.root, fetch=self.offline, allow_stale=True)
        self.assertEqual(report["action"], "check")
        self.assertEqual(report["id"], "researched-freertos-lts")
        self.assertEqual(report["verifier"], "researched-eoltracker-agent")
        self.assertFalse(report["written"])
        self.assertEqual([line["id"] for line in report["releases"]], [CURRENT, PREVIOUS])

    def test_the_installed_record_re_derives_every_date_from_its_own_quotes(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            report = install_file(CONTRIBUTION, root=root, allow_stale=True)
            self.assertEqual((report["action"], report["written"]), ("install", True))
            stored = json.loads((root / "products" / "researched-freertos-lts.json").read_text())
            validate_research(stored, "software")
            self.assertEqual({release["id"]: release["milestones"] for release in stored["releases"]},
                             STATED)


class StatedDateTests(FreeRTOSCase):
    """The two explicit `LTS Until` days, and the branches they belong to."""

    def test_the_branch_deadlines_are_the_stated_ltu_until_days(self):
        lines = self.lines()
        self.assertEqual(lines[CURRENT]["milestones"], STATED[CURRENT])
        self.assertEqual(lines[PREVIOUS]["milestones"], STATED[PREVIOUS])
        # One labelled window with "security updates and critical bug fixes" in
        # it: the day security fixes stop is the day the branch's support ends,
        # so both end milestones the record publishes are that same day.
        for release_id, release in lines.items():
            self.assertEqual(release["milestones"]["eossec"], release["milestones"]["eol"], release_id)

    def test_each_deadline_is_backed_by_the_branchs_own_table_quote(self):
        self.assertTrue(date_in_quote("2028-04-30", TABLE_202604))
        self.assertTrue(date_in_quote("2026-06-30", TABLE_202406))
        # A day the table does not state is never backed by it.
        self.assertFalse(date_in_quote("2028-04-01", TABLE_202604))
        self.assertFalse(date_in_quote("2026-06-01", TABLE_202406))
        self.assertEqual(missing_backing(by_id()[CURRENT]["milestones"], contribution()["evidence"]), [])
        self.assertEqual(missing_backing(by_id()[PREVIOUS]["milestones"], contribution()["evidence"]), [])

    def test_the_deadlines_carry_no_derivation(self):
        # The days are vendor-stated, so nothing here is arithmetic on a rule:
        # no line carries milestone_provenance and the four keys are complete.
        for release in record()["releases"]:
            self.assertNotIn("milestone_provenance", release)
            self.assertEqual(set(release["milestones"]), {"ga", "eos", "eossec", "eol"})

    def test_the_previous_branchs_deadline_is_published_even_though_it_has_passed(self):
        # 2026-06-30 predates the research date; a historical deadline stays
        # published rather than being dropped or advanced.
        self.assertLess(by_id()[PREVIOUS]["milestones"]["eol"], "2026-09-23")
        self.assertEqual(by_id()[PREVIOUS]["milestones"]["eol"], "2026-06-30")


class MonthPrecisionTests(FreeRTOSCase):
    """GA is the month the changelog heading states, and never a day."""

    def test_the_release_month_is_stored_as_a_month(self):
        expected = {CURRENT: "April 2026", PREVIOUS: "June 2024"}
        for release_id, release in by_id().items():
            ga = release["milestones"]["ga"]
            self.assertTrue(site_config.is_month(ga), release_id)
            self.assertEqual(site_config.human_date(ga), expected[release_id])

    def test_no_day_is_invented_for_the_release(self):
        for release_id, release in by_id().items():
            self.assertNotRegex(release["milestones"]["ga"], r"\d{4}-\d{2}-\d{2}", release_id)
        # The headings name the month; they state no day, so no day is backed.
        self.assertTrue(date_in_quote("2026-04", HEADING_202604))
        self.assertTrue(date_in_quote("2024-06", HEADING_202406))
        for heading, month in ((HEADING_202604, "2026-04"), (HEADING_202406, "2024-06")):
            self.assertFalse(date_in_quote(month + "-01", heading))
            self.assertFalse(date_in_quote(month + "-28", heading))

    def test_a_padded_release_day_is_refused(self):
        # Padding the month is not a formatting change: no stored quote states
        # a day, so admission refuses it and the month stays a month.
        payload = contribution()
        payload["releases"][0]["milestones"]["ga"] = "2026-04-01"
        with self.assertRaisesRegex(ValueError, "no stored quote states the general availability"):
            parse_contribution(payload, path=str(CONTRIBUTION))
        # The same edit on a hand-edited record fails the catalog gate.
        stored = self.build()
        stored["releases"][0]["milestones"]["ga"] = "2026-04-01"
        with self.assertRaisesRegex(ValueError, "general availability"):
            validate_research(stored, "software")

    def test_a_tampered_deadline_is_refused(self):
        stored = self.build()
        stored["releases"][0]["milestones"]["eol"] = "2028-05-31"
        with self.assertRaisesRegex(ValueError, "end of life"):
            validate_research(stored, "software")

    def test_the_month_release_is_excluded_from_openeox_with_its_reason(self):
        with tempfile.TemporaryDirectory() as temp:
            index = openeox.build([self.build()], site=Path(temp))
            self.assertEqual(index["counts"]["exported"], 0)
            codes = {row["release"]: row["code"] for row in index["excluded"]}
            self.assertEqual(codes, {CURRENT: "general_availability_month_precision",
                                     PREVIOUS: "general_availability_month_precision"})
            # No day was invented for either release, so no release record is
            # written, only the index that accounts for them.
            self.assertEqual(index["records"], [])
            self.assertEqual([path.name for path in (Path(temp) / "v1" / "openeox").glob("*.json")],
                             ["index.json"])


class ExactSurfaceTests(FreeRTOSCase):
    """The stated days are syndicated; the stated months are disclosed."""

    def test_the_day_deadlines_reach_the_feeds_and_the_months_do_not(self):
        products = [self.build()]
        # A window before both branches, so every milestone in the record is
        # upcoming and the split covers the whole record rather than a slice.
        events = feeds.upcoming_events(products, today=date(2023, 1, 1))
        days, excluded = feeds.representable(events)
        # The three day documents carry exactly the four stated days and no
        # month-precision one: both branches' eossec and eol, nothing else.
        self.assertEqual({(event["release_id"], event["milestone"], event["date"]) for event in days},
                         {(CURRENT, "eossec", "2028-04-30"), (CURRENT, "eol", "2028-04-30"),
                          (PREVIOUS, "eossec", "2026-06-30"), (PREVIOUS, "eol", "2026-06-30")})
        self.assertEqual([event["date"] for event in days],
                         sorted(event["date"] for event in days))
        self.assertEqual({(event["release_id"], event["date"]) for event in excluded},
                         {(CURRENT, "2026-04"), (PREVIOUS, "2024-06")})
        for event in excluded:
            self.assertTrue(event["month"])
            self.assertFalse(event["derived"])
        document = feeds.exclusions_document(excluded, len(days),
                                             feeds.generated_at({"generated_at": CHECKED}))
        self.assertEqual(document["counts"], {"upcoming_events": 6, "feeds": 4, "excluded": 2,
                                              "by_code": {feeds.MONTH_EXCLUSION_CODE: 2,
                                                          feeds.DERIVED_EXCLUSION_CODE: 0}})

    def test_the_page_shows_both_widths_as_stated(self):
        rows = {row["id"]: row for row in site_views.release_rows(self.build())}
        self.assertEqual(rows[CURRENT]["cells"]["ga"]["value"], "2026-04")
        self.assertEqual(rows[CURRENT]["cells"]["ga"]["human"], "April 2026")
        self.assertTrue(rows[CURRENT]["cells"]["ga"]["month"])
        self.assertEqual(rows[CURRENT]["cells"]["eol"]["value"], "2028-04-30")
        self.assertFalse(rows[CURRENT]["cells"]["eol"]["month"])
        self.assertIsNone(rows[CURRENT]["cells"]["eos"]["value"])


class ScopeTests(FreeRTOSCase):
    """One record for the LTS distribution, not the kernel release stream."""

    def test_the_published_name_and_scope_are_the_lts_distribution(self):
        stored = self.build()
        self.assertEqual(stored["name"], "FreeRTOS LTS")
        self.assertEqual([release["id"] for release in stored["releases"]], [CURRENT, PREVIOUS])

    def test_no_ordinary_kernel_tag_is_a_lifecycle_line(self):
        # The kernel repository publishes release notes but no support deadline,
        # so a kernel tag is never a line here and its version string never
        # becomes a milestone value.
        stored = record()
        ids = {release["id"] for release in stored["releases"]}
        values = {value for release in stored["releases"]
                  for value in release["milestones"].values() if value}
        for tag in KERNEL_TAGS:
            self.assertNotIn(tag, ids)
            self.assertNotIn(tag, values)
        # Every line is an LTS branch, and each one's release is quoted from the
        # branch's own pinned tag rather than from the kernel repository.
        self.assertEqual(ids, {CURRENT, PREVIOUS})
        self.assertFalse(any("FreeRTOS-Kernel/releases" in entry["source_url"]
                             for entry in contribution()["evidence"]))

    def test_every_source_is_a_pinned_tag_and_never_a_mutable_branch(self):
        sources = {entry["source_url"] for entry in contribution()["evidence"]}
        self.assertEqual(sources, {README_202604, README_202406,
                                   CHANGELOG_202604, CHANGELOG_202406})
        for url in sources:
            self.assertRegex(url, r"/(?:202604|202406)\.00-LTS/")
            self.assertNotRegex(url, r"/(?:202604|202406)-LTS/")

    def test_the_pinned_tag_quotes_state_the_initial_component_versions(self):
        # The mutable branch moved to the patched components; the stored quote
        # is the tag's own row, so the record cites the release it names.
        self.assertIn("| FreeRTOS Kernel | 11.1.0 | 06/30/2026 |", TABLE_202406)
        self.assertIn("| FreeRTOS Kernel | 11.3.0 | 04/30/2028 |", TABLE_202604)
        self.assertNotIn("4.2.6", TABLE_202406)
        self.assertNotIn("11.3.1", TABLE_202604)

    def test_end_of_sale_stays_unknown(self):
        # Open source and sold by nobody: no orderability cut-off is stated, so
        # the key is published null on both branches rather than filled.
        for release in record()["releases"]:
            self.assertIsNone(release["milestones"]["eos"])
        entry = next(item for item in contribution()["evidence"] if item["quote"] == TABLE_202604)
        self.assertNotIn("eos", entry["milestones"])
        self.assertFalse(any("end of sale" in entry["quote"].lower()
                             for entry in contribution()["evidence"]))

    def test_the_conditional_emp_window_is_a_quote_and_never_a_deadline(self):
        # "up to an additional 10 years" is subscription-conditional; it must
        # not become a universal EOL, so no milestone is dated from it.
        self.assertIn(EMP, [entry["quote"] for entry in contribution()["evidence"]])
        self.assertEqual(missing_backing({"eol": "2038-04-30"}, contribution()["evidence"]), ["eol"])
        stored = {value for release in record()["releases"]
                  for value in release["milestones"].values() if value}
        for conditional in ("2038-04-30", "2036-06-30", "2038-06-30"):
            self.assertNotIn(conditional, stored)
        # The EMP sentence states a duration, never a date, so it backs nothing.
        self.assertFalse(date_in_quote("2028-04-30", EMP))


class QuoteTests(FreeRTOSCase):
    """Every stored date is the vendor's own sentence, stored verbatim."""

    def test_the_stored_quotes_are_the_pinned_sentences(self):
        stored = {entry["quote"] for entry in contribution()["evidence"]}
        for quote in (TABLE_202604, TABLE_202406, HEADING_202604, HEADING_202406, POLICY, EMP):
            self.assertIn(quote, stored)

    def test_the_policy_quote_is_what_licenses_eossec(self):
        # A generic "support" date never fills eossec; this sentence names
        # security updates explicitly, which is why the branch deadline does.
        self.assertIn("security updates and critical bug fixes", POLICY)
        entry = next(item for item in contribution()["evidence"] if item["quote"] == POLICY)
        self.assertEqual(entry["milestones"], ["eossec", "eol"])

    def test_the_research_provenance_names_the_contributor_and_its_review_date(self):
        research = self.build()["provenance"]["research"]
        self.assertEqual(research["contributor"], "eoltracker-agent")
        self.assertEqual(research["method"], "agent")
        self.assertEqual(research["retrieved_at"], "2026-09-23")
        self.assertEqual(research["stale_after"], "2027-03-22")
        self.assertEqual({entry["retrieved_at"] for entry in research["evidence"]}, {"2026-09-23"})

    def test_a_reworded_quote_no_longer_matches_the_record(self):
        # The quote is the evidence: an edited copy fails the gate offline.
        stored = self.build()
        stored["provenance"]["research"]["evidence"][0]["quote"] = TABLE_202604.replace(
            "04/30/2028", "04/30/2029")
        with self.assertRaisesRegex(ValueError, "research.quote is not the evidence quotes joined"):
            validate_research(stored, "software")

    def test_the_unverified_admission_path_is_visible_on_the_record(self):
        parsed_contribution = parsed()
        research = research_object(parsed_contribution, parsed_contribution["evidence"], None)
        stored = build_record(parsed_contribution, research, CHECKED)
        view = research_view(stored, today=date(2026, 9, 23))
        self.assertFalse(view["verified"])
        self.assertIsNone(view["verified_at"])
        self.assertFalse(view["stale"])


if __name__ == "__main__":
    unittest.main()
