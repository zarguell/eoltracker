"""DokuWiki lifecycle: the committed researched contribution (contributions/dokuwiki.json).

DokuWiki versions *are* release dates and the project publishes no lifecycle
table, so the record is a researched contribution whose general-availability
dates are the vendor's own stable-release dates. Its end dates are derived, not
stated: SECURITY.md says only the current stable release is supported, so the
next stable release is the dated trigger that ends the previous line. These
tests pin that reasoning end to end -- the vendor sentence, the five derived
transitions, the undated current line, the hotfix releases that are *not*
triggers, and the disclosure that keeps a derived date out of the day-precision
feeds and the OpenEoX export.
"""
import json
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path

from engine import derived, feeds, openeox
from engine.contribute import (build_record, check_file, date_in_quote, install_file,
                               parse_contribution, research_object, validate_research)

CONTRIBUTION = Path(__file__).resolve().parents[1] / "contributions" / "dokuwiki.json"
ARCHIVE = "https://download.dokuwiki.org/archive"
DOWNLOAD = "https://download.dokuwiki.org/"
FEED = "https://download.dokuwiki.org/rss"
SECURITY = "https://raw.githubusercontent.com/dokuwiki/dokuwiki/master/SECURITY.md"
SECURITY_2021 = ("https://raw.githubusercontent.com/dokuwiki/dokuwiki/"
                 "22b04d8db65da89d8f091b893e86c3c3b1568ffb/SECURITY.md")
CHECKED = "2026-09-23T00:00:00Z"

# The vendor's own support rule, quoted verbatim from SECURITY.md. It is stated
# for the current stable release only, which is what makes the *next* stable
# release the dated trigger that ends the previous line.
RULE = ("We only accept reports for the current stable release (branch `stable`) and for the "
        "`master` branch. Older versions are not supported, and any vulnerabilities in them "
        "will not be fixed.")

# The six stable releases, oldest first, each with the next stable release that
# supersedes it. The current line has no successor, so it has no deadline.
STABLE = ["2020-07-29", "2022-07-31", "2023-04-04", "2024-02-06", "2025-05-14", "2026-07-14"]
# The record lists its lines newest first, as every other contribution does.
PUBLISHED = list(reversed(STABLE))
TRANSITIONS = list(zip(STABLE, STABLE[1:]))

# Hotfix releases of each stable line and the day the vendor published them,
# read from the project's own release feed (https://download.dokuwiki.org/rss,
# retrieved 2026-09-23). A hotfix patches the line it belongs to; it does not
# supersede that line as the current stable release, so none of these days may
# appear as a stored deadline.
HOTFIXES = {
    "2020-07-29": ["2022-09-04"],
    "2022-07-31": ["2022-09-03", "2023-05-16"],
    "2023-04-04": ["2023-05-15", "2024-08-05"],
    "2024-02-06": ["2024-02-12", "2024-08-05"],
    "2025-05-14": ["2025-05-26", "2025-09-09"],
    "2026-07-14": ["2026-07-22", "2026-08-11", "2026-09-02"],
}


def load():
    return json.loads(CONTRIBUTION.read_text(encoding="utf-8"))


def parsed():
    return parse_contribution(load(), path=str(CONTRIBUTION))


def record():
    contribution = parsed()
    research = research_object(contribution, contribution["evidence"], None)
    return build_record(contribution, research, CHECKED)


def by_id():
    return {release["id"]: release for release in record()["releases"]}


def releases_note():
    """The review note as published on the record's research provenance."""
    contribution = parsed()
    research = research_object(contribution, contribution["evidence"], None)
    return research["notes"]


class ContributionFileTests(unittest.TestCase):
    """The committed file admits offline, and states only what the pages state."""

    def test_the_contribution_passes_the_gate_without_a_fetch(self):
        report = check_file(CONTRIBUTION, allow_stale=True)
        self.assertEqual(report["id"], "researched-dokuwiki")
        self.assertEqual(report["verifier"], "researched-eoltracker-agent")
        self.assertEqual([line["id"] for line in report["releases"]], PUBLISHED)
        self.assertEqual(set(report["sources"]), {ARCHIVE, DOWNLOAD, FEED, SECURITY, SECURITY_2021})

    def test_the_record_installs_and_matches_its_own_evidence(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            report = install_file(CONTRIBUTION, root=root, allow_stale=True)
            self.assertEqual((report["action"], report["written"]), ("install", True))
            stored = json.loads((root / "products" / "researched-dokuwiki.json").read_text())
            self.assertEqual([release["id"] for release in stored["releases"]], PUBLISHED)
            # The catalog gate re-derives every quote and every rule offline.
            validate_research(stored, "software")

    def test_every_general_availability_date_is_the_vendors_stable_release_date(self):
        contribution = parsed()
        quotes = [entry for entry in contribution["evidence"] if entry["source_url"] == ARCHIVE]
        record_ids = [release["id"] for release in record()["releases"]]
        self.assertEqual(record_ids, PUBLISHED)
        for release in record()["releases"]:
            ga = release["milestones"]["ga"]
            self.assertEqual(ga, release["id"], "the version string is the release date")
            self.assertTrue(
                any(date_in_quote(ga, entry["quote"]) for entry in quotes),
                f"no stored archive quote states {ga} at day precision")

    def test_the_record_publishes_no_vendor_stated_end_date(self):
        # "only the current stable release" is a rule, never a date, so every
        # end milestone in the record is a derived one and every line's end-of-
        # sale stays absent (the project sells nothing and dates no cut-off).
        for release in record()["releases"]:
            milestones = release["milestones"]
            self.assertIsNone(milestones["eos"])
            for key in ("eossec", "eol"):
                if milestones[key] is None:
                    continue
                self.assertIn(key, release.get("milestone_provenance") or {},
                              f"{release['id']} states {key} without its rule")
                self.assertEqual(release["milestone_provenance"][key]["kind"], derived.KIND)


class TransitionTests(unittest.TestCase):
    """Each superseded line ends on the day the next stable release shipped."""

    def test_each_line_ends_exactly_on_the_next_stable_releases_date(self):
        releases = by_id()
        for older, newer in TRANSITIONS:
            milestones = releases[older]["milestones"]
            self.assertEqual(milestones["eol"], releases[newer]["milestones"]["ga"], older)
            self.assertEqual(milestones["eossec"], milestones["eol"], older)

    def test_the_derivation_recomputes_from_the_stored_trigger(self):
        releases = by_id()
        ids = set(releases)
        for older, newer in TRANSITIONS:
            release = releases[older]
            provenance = release["milestone_provenance"]
            for key in ("eossec", "eol"):
                entry = provenance[key]
                self.assertEqual(entry["method"], "release-trigger")
                self.assertEqual(entry["base_date"], release["milestones"]["ga"])
                self.assertEqual(entry["base_label"], f"DokuWiki {older} stable release")
                self.assertEqual(entry["trigger"]["release_id"], newer)
                self.assertEqual(entry["trigger"]["date"], release["milestones"]["eol"])
                self.assertEqual(entry["source_url"], SECURITY)
            # The engine's own re-derivation must agree with the stored dates.
            self.assertEqual(derived.derive(release["milestones"], provenance, release_ids=ids),
                             {"eossec": release["milestones"]["eol"], "eol": release["milestones"]["eol"]})

    def test_the_rule_quoted_is_the_vendors_current_stable_only_sentence(self):
        evidence = [entry for entry in parsed()["evidence"] if entry["source_url"] == SECURITY]
        self.assertEqual([entry["quote"] for entry in evidence], [RULE])
        for release in record()["releases"]:
            for key, entry in (release.get("milestone_provenance") or {}).items():
                self.assertEqual(entry["quote"], RULE, f"{release['id']}.{key}")

    def test_a_hotfix_release_is_never_the_trigger(self):
        releases = by_id()
        later_hotfix_after_the_stored_end = 0
        for older, newer in TRANSITIONS:
            milestones = releases[older]["milestones"]
            self.assertNotIn(milestones["eol"], HOTFIXES[older],
                             f"{older} took a hotfix date as its end")
            self.assertEqual(releases[older]["milestone_provenance"]["eol"]["trigger"]["release_id"], newer)
            if any(day > milestones["eol"] for day in HOTFIXES[older]):
                later_hotfix_after_the_stored_end += 1
        # 2022-07-31 and 2023-04-04 both received a hotfix *after* the day their
        # support ended, so "the last patch we shipped" would have produced a
        # different, later date. The rule is the next stable release, not that.
        self.assertGreaterEqual(later_hotfix_after_the_stored_end, 2)

    def test_the_rule_was_already_published_when_the_oldest_trigger_fired(self):
        # Every derived deadline is a transition the vendor's current-stable-only
        # rule already covered on the day it happened, so the dates are not
        # retrofitted onto lines from an anachronistic policy. The historical
        # revision ships in the evidence -- and is cited, not paraphrased.
        stored = load()
        historical = [entry for entry in stored["evidence"] if entry["source_url"] == SECURITY_2021]
        self.assertEqual({entry["quote"] for entry in historical}, {
            "Security vulnerabilities can be reported for the current stable release (branch `stable`) and "
            "the `master` branch.",
            "Depending on the severity we may release hotfixes for the current stable release or may simply "
            "incorporate the fix in the next proper release.",
        })
        # The earliest derived trigger (2022-07-31) postdates the 2021-12-12 file.
        earliest = min(release["milestones"]["eol"] for release in record()["releases"]
                       if release["milestones"]["eol"])
        self.assertGreater(earliest, "2021-12-12")

    def test_the_record_discloses_that_security_hotfixes_outlived_the_deadline(self):
        # The derived date is the vendor's policy deadline, not the last patch
        # the project actually shipped: 2020-07-29, 2022-07-31 and 2023-04-04
        # each took a security hotfix after the next stable release ended them.
        # The record must say so rather than imply support simply stopped.
        releases = by_id()
        observed = {"2020-07-29": "2022-09-04", "2022-07-31": "2023-05-16", "2023-04-04": "2024-08-05"}
        for older, hotfix_day in observed.items():
            self.assertIn(hotfix_day, HOTFIXES[older], older)
            self.assertGreater(hotfix_day, releases[older]["milestones"]["eol"], older)
        quotes = {entry["quote"] for entry in load()["evidence"] if entry["source_url"] == FEED}
        self.assertEqual(len(quotes), 3, "each counterexample's own feed row must be stored")
        # ...and the disclosure sentence is on the record, not only in a test.
        self.assertIn("DISCLOSED CONTRADICTION", releases_note())

    def test_the_trigger_chain_is_contiguous_and_end_at_the_undated_current_line(self):
        releases = by_id()
        triggers = [releases[older]["milestone_provenance"]["eol"]["trigger"]["release_id"]
                    for older, _ in TRANSITIONS]
        self.assertEqual(triggers, STABLE[1:])
        # Every derived deadline is some released line's own GA date...
        for older, _ in TRANSITIONS:
            self.assertIn(releases[older]["milestones"]["eol"],
                          [release["milestones"]["ga"] for release in releases.values()])
        # ...and no line is dated from the release cadence between them.
        self.assertIsNone(releases["2026-07-14"]["milestones"]["eol"])


class CurrentLineTests(unittest.TestCase):
    """The current stable release has no announced end, and none is projected."""

    def test_the_current_line_states_no_end_and_carries_no_rule(self):
        current = by_id()["2026-07-14"]
        self.assertEqual(current["milestones"],
                         {"ga": "2026-07-14", "eos": None, "eossec": None, "eol": None})
        self.assertNotIn("milestone_provenance", current)

    def test_its_hotfixes_are_published_but_create_no_milestone(self):
        # The download page itself offers the current line's hotfix (2026-07-14c)
        # and the previous line's (2025-05-14b); neither becomes a date. The
        # check is against stored milestone values, which is where a smuggled
        # patch date would land.
        self.assertEqual(HOTFIXES["2026-07-14"], ["2026-07-22", "2026-08-11", "2026-09-02"])
        stored = {value for release in record()["releases"]
                  for value in release["milestones"].values() if value}
        for hotfix in HOTFIXES["2026-07-14"]:
            self.assertNotIn(hotfix, stored)

    def test_the_previous_line_ends_when_the_current_one_shipped(self):
        releases = by_id()
        self.assertEqual(releases["2025-05-14"]["milestones"]["eol"],
                         releases["2026-07-14"]["milestones"]["ga"])


class DisclosureTests(unittest.TestCase):
    """A derived date stays out of the day-precision surfaces, with its reason."""

    def test_the_rule_does_not_move_the_general_availability_dates(self):
        # GA is vendor-stated, so it is the only thing the record syndicates.
        for release in record()["releases"]:
            self.assertNotIn("ga", release.get("milestone_provenance") or {},
                             "a beginning is never derived from a rule")
            self.assertEqual(derived.NonDerivedMilestones(release["milestones"],
                                                          release.get("milestone_provenance")),
                             {"ga": release["milestones"]["ga"]})

    def test_derived_deadlines_never_reach_the_day_precision_feeds(self):
        # A window before the oldest line's GA, so every milestone in the record
        # is upcoming and the split covers the whole record rather than a slice.
        events = feeds.upcoming_events([record()], today=date(2020, 1, 1))
        days, excluded = feeds.representable(events)
        self.assertEqual({event["milestone"] for event in days}, {"ga"})
        self.assertEqual(len(days), len(STABLE))
        self.assertEqual(len(excluded), 2 * len(TRANSITIONS))
        for event in excluded:
            self.assertTrue(event["derived"])
            self.assertEqual(event["derived"]["method"], "release-trigger")
        # The split is an account, not a silent drop.
        document = feeds.exclusions_document(excluded, len(days),
                                             datetime.fromisoformat(CHECKED.replace("Z", "+00:00")))
        self.assertEqual(len(document["excluded"]), len(excluded))

    def test_derived_deadlines_are_excluded_from_openeox_with_their_rule(self):
        with tempfile.TemporaryDirectory() as temp:
            index = openeox.build([record()], site=Path(temp))
            self.assertEqual(index["counts"]["exported"], 0)
            self.assertEqual(index["counts"]["excluded"], len(STABLE))
            codes = {exclusion["release"]: exclusion["code"] for exclusion in index["excluded"]}
            for older, _ in TRANSITIONS:
                self.assertEqual(codes[older], "end_of_security_support_derived", older)
                self.assertIn("milestone_provenance", index["excluded"][0]["reason"])
            # The current line is excluded for the honest reason instead.
            self.assertEqual(codes["2026-07-14"], "end_of_security_support_unknown")
            # No day was invented for any line, so no record file is written.
            self.assertEqual(index["records"], [])
            self.assertEqual(list((Path(temp) / "v1" / "openeox").rglob("dokuwiki*")), [])


if __name__ == "__main__":
    unittest.main()
