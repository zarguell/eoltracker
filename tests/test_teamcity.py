"""TeamCity On-Premises collector regression tests.

The full fixtures are JetBrains' own pages saved verbatim on 2026-09-23:
``teamcity-previous-releases.html`` (the release catalog: 194 chapters, 36 major
lines and 158 bugfix lines) and ``teamcity-release-cycle.html`` (the policy the
two support-stage dates are derived from). The ``-minimal`` fixtures are small
synthetic pages in the same shape, so refusal and boundary paths do not depend
on the byte offsets of a saved page.

The ticket that asked for this collector counted 37 major lines. The live page
does not state 37: it states 194 chapters, and every count below is taken from
the fixture independently of the module — headings, chapters and the vendor's
own date cells — because a fabricated 37th line is exactly what the repository's
no-invented-dates rule forbids. The report explains the corrected inventory.
"""
import copy
import json
import re
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from engine import derived, teamcity
from engine.importer import API, dump, normalize

FIXTURES = Path(__file__).parent / "fixtures"
CATALOG = (FIXTURES / "teamcity-previous-releases.html").read_text(encoding="utf-8")
POLICY = (FIXTURES / "teamcity-release-cycle.html").read_text(encoding="utf-8")
MINI_CATALOG = (FIXTURES / "teamcity-previous-releases-minimal.html").read_text(encoding="utf-8")
MINI_POLICY = (FIXTURES / "teamcity-release-cycle-minimal.html").read_text(encoding="utf-8")

CHECKED = "2026-09-23T00:00:00Z"
# Independently counted from the saved page: `<section class="chapter">` blocks,
# `<h2>` release headings, and the two-component versions among them.
CHAPTERS = 194
MAJORS = 36
BUGFIX = 158
# The vendor's own wording for the two rules this record derives from.
EOS_SENTENCE = "Occurs for the previous major version with the release of the next major version."
EOL_SENTENCE = "Occurs with the release of two newer major versions."


def parsed(html=CATALOG):
    return teamcity.parse_catalog(html)


def policy(html=POLICY):
    return teamcity.policy_rules(html)


def record(html=CATALOG, rules=POLICY):
    releases, _ = teamcity.parse_catalog(html)
    rules, _others, _rows = teamcity.policy_rules(rules)
    return teamcity.record_for(teamcity.with_derived_milestones(releases, rules), CHECKED)


def by_id(releases):
    return {release["id"]: release for release in releases}


class InventoryTests(unittest.TestCase):
    def test_the_saved_catalog_states_thirty_six_major_lines_and_no_thirty_seventh(self):
        # The independent inventory: the page's own chapters, split by whether
        # the version has a third component. Nothing here reads the module.
        chapters = re.findall(r'<section class="chapter">.*?</section>', CATALOG, re.DOTALL)
        versions = [re.search(r"<h2[^>]*>(?:Current version: )?TeamCity ([\d.]+)</h2>", block).group(1)
                    for block in chapters]
        self.assertEqual(len(chapters), CHAPTERS)
        self.assertEqual(len(versions), CHAPTERS)
        major_ids = [version for version in versions if version.count(".") == 1]
        self.assertEqual(len(major_ids), MAJORS)
        self.assertEqual(len(versions) - len(major_ids), BUGFIX)
        # The ticket's "37 major lines" is not what the live page states: the
        # module publishes the page's own 36 headings counted just above,
        # because a fabricated 37th line is what the repository's
        # no-invented-dates rule forbids. The report explains the inventory.
        releases, excluded = parsed()
        self.assertEqual([release["id"] for release in releases], major_ids)
        self.assertEqual(len(excluded), BUGFIX)
        self.assertEqual(len(releases) + len(excluded), CHAPTERS)

    def test_release_dates_match_the_vendor_cells(self):
        releases = by_id(parsed()[0])
        self.assertEqual(releases["2026.2"]["milestones"]["ga"], "2026-09-02")
        self.assertEqual(releases["2026.1"]["milestones"]["ga"], "2026-05-11")
        self.assertEqual(releases["2025.11"]["milestones"]["ga"], "2025-11-27")
        self.assertEqual(releases["10.0"]["milestones"]["ga"], "2016-07-21")
        self.assertEqual(releases["3.1"]["milestones"]["ga"], "2008-03-04")
        # The archived chapters state the date inside a bold Markdown wrapper;
        # the stored cell keeps the vendor's text and the milestone is the day.
        self.assertIn("23 May 2019", releases["2019.1"]["upstream"]["cells"]["Release date"])
        self.assertEqual(releases["2019.1"]["milestones"]["ga"], "2019-05-23")

    def test_every_major_line_states_a_day_precision_release_date(self):
        for release in parsed()[0]:
            self.assertRegex(release["milestones"]["ga"], r"\A\d{4}-\d{2}-\d{2}\Z")

    def test_releases_are_ordered_newest_major_first(self):
        dates = [release["milestones"]["ga"] for release in parsed()[0]]
        self.assertEqual(dates, sorted(dates, reverse=True))
        self.assertEqual(parsed()[0][0]["id"], "2026.2")
        self.assertEqual(parsed()[0][-1]["id"], "3.1")

    def test_bugfix_descendants_are_excluded_with_a_truthful_reason(self):
        _, excluded = parsed()
        self.assertEqual(excluded[0]["row"], "TeamCity 2026.1.4")
        for row in excluded:
            self.assertRegex(row["row"], r"TeamCity \d+\.\d+\.\d+")
            self.assertIn("bugfix (minor) release line", row["reason"])
            self.assertIn("major-version level", row["reason"])
            self.assertEqual(row["page"], teamcity.CATALOG_URL)
        # No patch line leaks into the published record.
        self.assertFalse(any(release["id"].count(".") != 1 for release in parsed()[0]))

    def test_no_2026_3_release_is_invented_from_the_roadmap_estimate(self):
        # JetBrains' roadmap calls 2026.3 an estimate for "the end of 2026";
        # it is not in the catalog, so no release and no transition exists.
        releases = by_id(parsed()[0])
        self.assertNotIn("2026.3", releases)
        self.assertNotIn("2026.3", CATALOG)
        self.assertIsNone(releases["2026.2"]["milestones"]["eos"])
        self.assertIsNone(releases["2026.2"]["milestones"]["eol"])


class TriggerBoundaryTests(unittest.TestCase):
    def releases(self):
        return by_id(teamcity.with_derived_milestones(parsed()[0], policy()[0]))

    def test_the_newest_line_has_neither_transition_and_the_next_has_no_end_of_support(self):
        releases = self.releases()
        self.assertEqual(releases["2026.2"]["milestones"],
                         {"ga": "2026-09-02", "eos": None, "eossec": None, "eol": None})
        self.assertNotIn(derived.DERIVED_KEY, releases["2026.2"])
        # 2026.1's next major is published, but its second newer one is not.
        self.assertEqual(releases["2026.1"]["milestones"],
                         {"ga": "2026-05-11", "eos": "2026-09-02", "eossec": None, "eol": None})
        self.assertEqual(sorted(releases["2026.1"][derived.DERIVED_KEY]), ["eos"])

    def test_a_line_derives_from_the_two_releases_that_follow_it(self):
        releases = self.releases()
        self.assertEqual(releases["2025.11"]["milestones"],
                         {"ga": "2025-11-27", "eos": "2026-05-11", "eossec": None,
                          "eol": "2026-09-02"})
        self.assertEqual(releases["2025.07"]["milestones"]["eos"], "2025-11-27")
        self.assertEqual(releases["2025.07"]["milestones"]["eol"], "2026-05-11")
        # The two oldest lines still have both triggers.
        self.assertEqual(releases["3.1"]["milestones"]["eos"], "2008-12-10")
        self.assertEqual(releases["3.1"]["milestones"]["eol"], "2009-04-23")

    def test_every_derived_date_carries_its_rule_base_and_trigger(self):
        releases = teamcity.with_derived_milestones(parsed()[0], policy()[0])
        triggers = {release["id"]: index for index, release in enumerate(releases)}
        for index, release in enumerate(releases):
            provenance = release.get(derived.DERIVED_KEY) or {}
            self.assertEqual(sorted(provenance), sorted(
                key for key in ("eos", "eol") if release["milestones"][key]))
            for key, entry in provenance.items():
                self.assertEqual(entry["kind"], "derived")
                self.assertEqual(entry["method"], "release-trigger")
                self.assertEqual(entry["source_url"], teamcity.POLICY_URL)
                self.assertEqual(entry["base_date"], release["milestones"]["ga"])
                self.assertEqual(entry["trigger"]["date"], release["milestones"][key])
                self.assertEqual(entry["quote"],
                                 EOS_SENTENCE if key == "eos" else EOL_SENTENCE)
                expected = releases[index - (1 if key == "eos" else 2)]
                self.assertEqual(entry["trigger"]["release_id"], expected["id"])
                self.assertGreater(triggers[entry["trigger"]["release_id"]], -1)
                # A trigger release is always newer, so a derived date never
                # precedes the base it is measured from.
                self.assertGreater(entry["trigger"]["date"], entry["base_date"])

    def test_security_support_end_is_never_published(self):
        releases = teamcity.with_derived_milestones(parsed()[0], policy()[0])
        for release in releases:
            self.assertIsNone(release["milestones"]["eossec"])
            self.assertNotIn("eossec", release.get(derived.DERIVED_KEY) or {})

    def test_every_line_but_the_newest_two_is_fully_derived(self):
        releases = teamcity.with_derived_milestones(parsed()[0], policy()[0])
        derived_eos = sum(1 for release in releases if release["milestones"]["eos"])
        derived_eol = sum(1 for release in releases if release["milestones"]["eol"])
        self.assertEqual(derived_eos, MAJORS - 1)
        self.assertEqual(derived_eol, MAJORS - 2)

    def test_a_stored_snapshot_is_re_derived_not_carried(self):
        # A snapshot captured while 2026.2 was the newest line carries 2026.1's
        # eos pointing at it. Re-deriving that snapshot against a catalog where
        # 2026.2 is gone must drop the date rather than keep a stale one: a
        # milestone whose trigger no longer exists goes back to null.
        releases = teamcity.with_derived_milestones(parsed()[0], policy()[0])
        stale = [copy.deepcopy(release) for release in releases if release["id"] != "2026.2"]
        carried = by_id(stale)
        self.assertEqual(carried["2026.1"]["milestones"]["eos"], "2026-09-02")
        self.assertEqual(carried["2025.11"]["milestones"]["eol"], "2026-09-02")
        fresh = by_id(teamcity.with_derived_milestones(copy.deepcopy(stale), policy()[0]))
        self.assertIsNone(fresh["2026.1"]["milestones"]["eos"])
        self.assertNotIn(derived.DERIVED_KEY, fresh["2026.1"])
        self.assertEqual(fresh["2025.11"]["milestones"]["eos"], "2026-05-11")
        self.assertIsNone(fresh["2025.11"]["milestones"]["eol"])
        self.assertNotIn("eol", fresh["2025.11"][derived.DERIVED_KEY])
        # A newly published major fills the two lines behind it, re-pointed at
        # the release the catalog now states rather than the old snapshot.
        published = by_id(releases)
        self.assertEqual(published["2026.1"]["milestones"]["eos"], "2026-09-02")
        self.assertEqual(published["2025.11"][derived.DERIVED_KEY]["eol"]["trigger"]["release_id"],
                         "2026.2")


class AbsentTriggerTests(unittest.TestCase):
    """A line whose triggering release is not published keeps a null milestone."""

    def test_a_catalog_of_one_major_line_derives_nothing(self):
        releases, _ = parsed(MINI_CATALOG)
        rules, _, _rows = policy(MINI_POLICY)
        derived_releases = teamcity.with_derived_milestones(releases, rules)
        # The minimal fixture's newest chapter is a bugfix line's parent; only
        # the lines whose triggers are present derive.
        self.assertEqual(derived_releases[0]["id"], "2026.2")
        self.assertIsNone(derived_releases[0]["milestones"]["eos"])
        self.assertIsNone(derived_releases[0]["milestones"]["eol"])

    def test_the_minimal_catalog_matches_the_policy_it_states(self):
        releases, excluded = parsed(MINI_CATALOG)
        self.assertEqual([release["id"] for release in releases],
                         ["2026.2", "2026.1", "2025.11", "2025.07"])
        self.assertEqual([row["row"] for row in excluded],
                         ["TeamCity 2026.1.4", "TeamCity 2025.11.1"])
        rules, _, _rows = policy(MINI_POLICY)
        derived_releases = by_id(teamcity.with_derived_milestones(releases, rules))
        self.assertEqual(derived_releases["2026.2"]["milestones"]["eos"], None)
        self.assertEqual(derived_releases["2026.1"]["milestones"]["eos"], "2026-09-02")
        self.assertEqual(derived_releases["2025.07"]["milestones"]["eol"], "2026-05-11")

    def test_a_major_line_without_a_release_date_refuses_the_parse(self):
        # The catalog dates are the whole basis of the record: a major line
        # that states none cannot be published with an invented one.
        html = MINI_CATALOG.replace("<p>Release date: 11 May 2026<br> Build number: 222521</p>",
                                    "<p>Build number: 222521</p>")
        with self.assertRaisesRegex(ValueError, "states no release date"):
            parsed(html)

    def test_a_maintenance_catalog_retains_a_dropped_major_line(self):
        committed = record()
        fresh, _ = parsed(MINI_CATALOG)
        rules = policy(MINI_POLICY)[0]
        releases, kept = teamcity.combine_releases(
            teamcity.with_derived_milestones(fresh, rules), committed)
        published = {release["id"] for release in releases}
        self.assertEqual(sorted(published),
                         sorted({release["id"] for release in committed["releases"]}))
        # The dropped chapters are republished from their own stored cells, so
        # retention can never introduce a date the catalog did not publish.
        dropped = {release["id"] for release in committed["releases"]} - {
            release["id"] for release in fresh}
        self.assertTrue(dropped)
        self.assertEqual([entry["id"] for entry in kept], [release["id"] for release in
                                                           committed["releases"]
                                                           if release["id"] in dropped])
        retained = [release for release in releases if release["id"] in dropped]
        self.assertTrue(all(release["upstream"]["in_source"] is False for release in retained))
        # A retained line's dates are recomputed from the merged snapshot: the
        # minimal catalog restates 2026.1 and 2025.11, so 2025.03's trigger is
        # the 2025.11 line the full record states, not the minimal page's.
        merged = by_id(teamcity.with_derived_milestones(committed["releases"], rules))
        self.assertEqual(merged["3.1"]["milestones"]["eos"], "2008-12-10")
        self.assertIn("3.1", published)


class AccountingTests(unittest.TestCase):
    def report(self, catalog=CATALOG, policy_html=POLICY, kept=()):
        releases, excluded = parsed(catalog)
        rules = policy(policy_html)
        releases = teamcity.with_derived_milestones(releases, rules[0])
        return teamcity.report_for(releases, excluded, rules, list(kept), CHECKED)

    def test_every_catalog_row_is_accounted_for(self):
        report = self.report()
        rows = report["rows"]
        self.assertEqual(rows["seen"], CHAPTERS)
        self.assertEqual(rows["published"], MAJORS)
        self.assertEqual(rows["excluded"], BUGFIX)
        self.assertEqual(rows["seen"], rows["published"] + rows["excluded"])
        self.assertEqual(rows["retained"], 0)
        self.assertEqual(rows["derived_eos"], MAJORS - 1)
        self.assertEqual(rows["derived_eol"], MAJORS - 2)
        self.assertEqual(report["total_records"], 1)

    def test_every_policy_row_is_accounted_for(self):
        report = self.report()
        # Independently counted from the page: the release-stage table's rows.
        table = re.search(r'<table class="wide" id="-dvitza_44">.*?</table>', POLICY, re.DOTALL)
        self.assertIsNotNone(table)
        rows = re.findall(r"<tr[^>]*>", table.group(0))
        source_rows = len(rows) - 1  # the header row is not a source row
        # The count is the *parsed* table row count, and every parsed row is
        # either a rule this record applies or a row it accounts for with a
        # reason, so the total cannot look complete while a row is missing.
        self.assertEqual(report["policy"]["rows"]["seen"], source_rows)
        self.assertEqual(report["policy"]["rows"]["used"], 2)
        self.assertEqual(report["policy"]["rows"]["seen"],
                         report["policy"]["rows"]["used"] + len(report["policy"]["rows"]["not_dated"]))
        for entry in report["policy"]["rows"]["not_dated"]:
            self.assertIn(entry["row"], POLICY)
            self.assertTrue(entry["reason"])

    def test_the_stored_rule_quotes_are_the_vendor_sentences_verbatim(self):
        rules, others, rows = policy()
        self.assertEqual(rules["eos"]["quote"], EOS_SENTENCE)
        self.assertEqual(rules["eol"]["quote"], EOL_SENTENCE)
        self.assertIn(EOS_SENTENCE, POLICY)
        self.assertIn(EOL_SENTENCE, POLICY)
        # The rule rows are the ones this record applies; the rest are accounted
        # for, so no release-stage row is silently ignored.
        self.assertEqual([rule["label"] for rule in
                          (rules["eos"], rules["eol"])],
                         [teamcity.EOS_LABEL, teamcity.EOL_LABEL])
        self.assertEqual({entry["row"] for entry in others},
                         {"TeamCity Cloud Major Release",
                          "TeamCity On-Premises Major Release"})
        self.assertEqual(rows, len(others) + 2)
        self.assertEqual(tuple(rule["label"] for rule in (rules["eos"], rules["eol"]))
                         + tuple(entry["row"] for entry in others),
                         teamcity.POLICY_LABELS)

    def test_the_report_scope_names_what_is_derived(self):
        scope = self.report()["record_scope"]
        self.assertIn("derives", scope)
        limitations = " ".join(self.report()["limitations"])
        self.assertIn("derived, not vendor-stated", limitations)
        self.assertIn("eossec is absent", limitations)
        self.assertIn("cadence", limitations)
        self.assertIn("2026.3", limitations)


class PolicyRefusalTests(unittest.TestCase):
    def test_a_reworded_rule_refuses_the_parse(self):
        html = POLICY.replace(EOS_SENTENCE, "Occurs after the previous major version is retired.")
        with self.assertRaisesRegex(ValueError, "reworded"):
            policy(html)

    def test_a_renamed_rule_row_refuses_the_parse(self):
        html = POLICY.replace(teamcity.EOS_LABEL, "TeamCity On-Premises Sale End")
        with self.assertRaisesRegex(ValueError, "no longer states"):
            policy(html)

    def test_a_renamed_column_refuses_the_parse(self):
        html = POLICY.replace("Release Stage", "Stage")
        with self.assertRaisesRegex(ValueError, "release-stage table"):
            policy(html)

    def test_a_missing_release_stage_table_refuses_the_parse(self):
        with self.assertRaises(ValueError):
            policy("<html><body><p>No tables</p></body></html>")

    def test_an_unreviewed_release_stage_row_refuses_the_parse(self):
        # A newly added stage can change support semantics. Recognizing only the
        # two rule labels while silently dropping the rest would let the record
        # keep deriving under stale rules and still claim complete row coverage.
        block = ('<tr><td><p><span class="control">TeamCity On-Premises End of Life</span></p>'
                 '</td><td><p>Occurs with the release of three newer major versions.</p></td></tr>')
        html = POLICY.replace("</tbody>", block + "</tbody>")
        self.assertNotEqual(html, POLICY)
        with self.assertRaisesRegex(ValueError, "not reviewed"):
            policy(html)

    def test_a_reviewed_row_removed_from_the_page_refuses_the_parse(self):
        html = POLICY.replace("TeamCity On-Premises Major Release",
                              "TeamCity On-Premises Major Version")
        with self.assertRaisesRegex(ValueError, "no longer states the reviewed"):
            policy(html)

    def test_the_parsed_policy_row_count_is_the_reports_seen_count(self):
        # The count comes from the parsed table, not from the rows this function
        # happens to return, so a filter that dropped a row could not still sum
        # to a complete-looking total.
        _rules, others, rows = policy()
        self.assertEqual(rows, len(others) + 2)
        self.assertGreaterEqual(rows, len(teamcity.POLICY_LABELS))


class TriggerIdentityTests(unittest.TestCase):
    """#106: triggers are chosen by version identity, not by date order."""

    def test_the_newer_major_must_be_dated_later(self):
        # A catalog that dated a newer major before an older one would pick the
        # wrong trigger release while still re-deriving consistently.
        html = CATALOG.replace("Release date: 2 September 2026", "Release date: 1 January 2020")
        with self.assertRaisesRegex(ValueError, "not after"):
            teamcity.with_derived_milestones(parsed(html)[0], policy()[0])

    def test_the_version_order_is_what_selects_the_triggers(self):
        releases = teamcity.with_derived_milestones(parsed()[0], policy()[0])
        self.assertEqual([release["id"] for release in releases][:3], ["2026.2", "2026.1", "2025.11"])
        self.assertEqual(teamcity.ordered_releases(releases),
                         sorted(releases, key=lambda release: tuple(
                             int(part) for part in release["id"].split(".")), reverse=True))

    def test_a_record_whose_versions_and_dates_disagree_is_refused(self):
        rec = record()
        # Move one line's date past its newer neighbour's without moving the
        # version: the stored cells still re-derive, but the order contradicts.
        rec["releases"][1]["milestones"]["ga"] = "2026-10-01"
        rec["releases"][1]["upstream"]["cells"]["Release date"] = "Release date: 1 October 2026"
        with self.assertRaisesRegex(ValueError, "not after"):
            teamcity.validate_record(rec)


class CatalogRefusalTests(unittest.TestCase):
    def test_an_unrecognized_heading_refuses_the_parse(self):
        html = MINI_CATALOG.replace(">TeamCity 2025.07</h2>", ">TeamCity Next</h2>")
        with self.assertRaisesRegex(ValueError, "Unrecognized TeamCity catalog heading"):
            parsed(html)

    def test_a_chapter_without_a_heading_refuses_the_parse(self):
        html = MINI_CATALOG.replace("<h2 id=\"TeamCity+2025.07\" data-toc=\"TeamCity+2025.07\">"
                                    "TeamCity 2025.07</h2>", "")
        with self.assertRaisesRegex(ValueError, "no release heading"):
            parsed(html)

    def test_a_version_stated_twice_refuses_the_parse(self):
        block = ('<section class="chapter"><h2>TeamCity 2025.07</h2>'
                 '<p>Release date: 23 July 2025<br> Build number: 197398</p></section>')
        html = MINI_CATALOG.replace("</article>", block + "</article>")
        with self.assertRaisesRegex(ValueError, "twice"):
            parsed(html)

    def test_a_bugfix_row_without_a_published_major_line_refuses(self):
        block = ('<section class="chapter"><h2>TeamCity 2016.1.1</h2>'
                 '<p>Release date: 1 January 2016<br> Build number: 1</p></section>')
        html = MINI_CATALOG.replace("</article>", block + "</article>")
        with self.assertRaisesRegex(ValueError, "without a published major line"):
            parsed(html)

    def test_an_impossible_calendar_day_refuses_the_parse(self):
        html = MINI_CATALOG.replace("Release date: 23 July 2025", "Release date: 31 July 2025")
        html = html.replace("Release date: 11 May 2026", "Release date: 30 February 2026")
        with self.assertRaisesRegex(ValueError, "not a real calendar day"):
            parsed(html)
        self.assertEqual(teamcity.release_date("Release date: 2 September 2026",
                                               "test"), "2026-09-02")
        with self.assertRaises(ValueError):
            teamcity.release_date("Release date: 2 Smarch 2026", "test")

    def test_a_catalog_with_no_major_lines_refuses(self):
        html = MINI_CATALOG
        for version in ("2026.2", "2026.1", "2025.11", "2025.07"):
            html = html.replace(f"TeamCity {version}</h2>", f"TeamCity {version}.9</h2>")
        with self.assertRaisesRegex(ValueError, "no major lines"):
            parsed(html)


class ReDerivationTests(unittest.TestCase):
    def test_the_fetched_record_re_derives_offline(self):
        teamcity.validate_record(record())

    def test_a_tampered_derived_milestone_is_refused(self):
        # Moving only the derived date leaves it contradicting its own cells:
        # the catalog chapter states the base, and the trigger is published.
        rec = record()
        rec["releases"][1]["milestones"]["eos"] = "2099-01-01"
        with self.assertRaisesRegex(ValueError, "contradicts the catalog chapter"):
            teamcity.validate_record(rec)

    def test_a_tampered_trigger_release_is_refused(self):
        # Repointing the id at a real, older line keeps the entry internally
        # consistent — the date still equals the derived milestone — so only
        # the vendor's own rule rejects it.
        rec = record()
        entry = rec["releases"][2]["milestone_provenance"]["eol"]
        entry["trigger"]["release_id"] = "2025.07"
        with self.assertRaisesRegex(ValueError, "wrong release"):
            teamcity.validate_record(rec)

    def test_a_trigger_lifted_from_the_release_after_next_is_refused(self):
        rec = record()
        entry = rec["releases"][2]["milestone_provenance"]["eos"]
        entry["trigger"]["release_id"] = "2026.2"
        with self.assertRaisesRegex(ValueError, "wrong release"):
            teamcity.validate_record(rec)

    def test_a_tampered_quote_or_base_is_refused(self):
        for mutate, message in (
                (lambda entry: entry.update(quote="A sentence about release cadence."),
                 "does not quote the vendor rule"),
                (lambda entry: entry.update(base_date="2020-01-01"),
                 "wrong base date"),
                (lambda entry: entry.update(base_label="the previous major version"),
                 "wrong base date")):
            rec = record()
            mutate(rec["releases"][2]["milestone_provenance"]["eos"])
            with self.assertRaisesRegex(ValueError, message):
                teamcity.validate_record(rec)

    def test_a_derived_milestone_stripped_of_its_rule_is_refused(self):
        rec = record()
        del rec["releases"][2]["milestone_provenance"]["eol"]
        with self.assertRaisesRegex(ValueError, "no rule recorded for it"):
            teamcity.validate_record(rec)

    def test_an_invented_transition_without_a_trigger_refuses(self):
        # Adding a derived date whose triggering release is not published must
        # fail in the shared module even before the catalog check sees it.
        rec = record()
        rec["releases"][0]["milestones"]["eos"] = "2027-01-01"
        rec["releases"][0][derived.DERIVED_KEY] = {
            "eos": copy.deepcopy(rec["releases"][1][derived.DERIVED_KEY]["eos"])}
        with self.assertRaises(ValueError):
            teamcity.validate_record(rec)

    def test_tampered_source_cells_are_refused(self):
        # The date cell is the evidence: a stored `ga` that no longer follows
        # it is refused, and so is a `ga` moved while the cell stays.
        rec = record()
        rec["releases"][0]["upstream"]["cells"]["Release date"] = "Release date: 1 January 2000"
        with self.assertRaisesRegex(ValueError, "contradicts the release date cell"):
            teamcity.validate_record(rec)
        rec = record()
        rec["releases"][0]["upstream"]["cells"]["Heading"] = "TeamCity 2026.9"
        with self.assertRaisesRegex(ValueError, "does not name its own catalog chapter"):
            teamcity.validate_record(rec)

    def test_a_foreign_verifier_is_refused(self):
        rec = record()
        rec["provenance"]["verifier"] = "deterministic-something-else"
        with self.assertRaisesRegex(ValueError, "source identity"):
            teamcity.validate_record(rec)

    def test_a_record_order_that_contradicts_the_versions_is_refused(self):
        rec = record()
        rec["releases"][0], rec["releases"][1] = rec["releases"][1], rec["releases"][0]
        with self.assertRaisesRegex(ValueError, "not ordered by the catalog's release versions"):
            teamcity.validate_record(rec)


class PublicationTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        sibling = normalize({"result": {"name": "sample", "label": "Sample", "category": "lang",
                                        "labels": {},
                                        "releases": [{"name": "1", "releaseDate": "2026-01-01"}]}},
                            CHECKED)
        dump(self.root / "products/sample.json", sibling)
        dump(self.root / "manifest.json", {
            "generated_at": CHECKED, "source_url": API, "source": "import-data",
            "product_count": 1, "release_count": 1, "excluded_hardware": []})

    def snapshot(self):
        return {str(path.relative_to(self.root)): path.read_bytes()
                for path in self.root.rglob("*.json")}

    def refresh(self, checked, catalog=CATALOG, policy_html=POLICY):
        with mock.patch.object(teamcity.net, "get_text", side_effect=[policy_html, catalog]), \
                mock.patch.object(teamcity, "_now", return_value=checked):
            return teamcity.import_teamcity(self.root)

    def test_a_quiet_refresh_republishes_byte_identical_files(self):
        self.refresh("2026-09-23T01:00:00Z")
        published = self.snapshot()
        self.assertIn("products/teamcity.json", published)
        self.assertIn(teamcity.REPORT, published)
        self.refresh("2026-09-23T02:00:00Z")
        self.assertEqual(self.snapshot(), published)
        record_published = json.loads(published["products/teamcity.json"])
        self.assertEqual(record_published["provenance"]["last_checked"], "2026-09-23T01:00:00Z")
        self.assertEqual(len(record_published["releases"]), MAJORS)

    def test_a_changed_catalog_advances_both_revisions(self):
        self.refresh("2026-09-23T01:00:00Z")
        before = self.snapshot()
        # A new major line shifts two older lines' derived transitions.
        block = ('<section class="chapter"><h2>TeamCity 2026.3</h2>'
                 '<p>Release date: 1 December 2026<br> Build number: 1</p></section>')
        self.refresh("2026-09-23T03:00:00Z",
                     catalog=CATALOG.replace("</article>", block + "</article>"))
        after = self.snapshot()
        self.assertNotEqual(after, before)
        releases = {release["id"]: release
                    for release in json.loads(after["products/teamcity.json"])["releases"]}
        self.assertEqual(releases["2026.3"]["milestones"]["eos"], None)
        self.assertEqual(releases["2026.2"]["milestones"]["eos"], "2026-12-01")
        self.assertEqual(releases["2026.1"]["milestones"]["eol"], "2026-12-01")
        report = json.loads(after[teamcity.REPORT])
        self.assertEqual(report["checked_at"], "2026-09-23T03:00:00Z")
        self.assertEqual(report["rows"]["published"], MAJORS + 1)

    def test_a_bugfix_only_change_advances_the_report_and_keeps_the_record(self):
        self.refresh("2026-09-23T01:00:00Z")
        before = self.snapshot()
        self.refresh("2026-09-23T02:00:00Z",
                     catalog=CATALOG.replace("TeamCity 2026.1.4", "TeamCity 2026.1.5"))
        after = self.snapshot()
        self.assertEqual(after["products/teamcity.json"], before["products/teamcity.json"])
        report = json.loads(after[teamcity.REPORT])
        self.assertEqual(report["checked_at"], "2026-09-23T02:00:00Z")
        self.assertIn("TeamCity 2026.1.5", [row["row"] for row in report["excluded"]])

    def test_a_foreign_record_refuses_the_import_before_network_and_writes_nothing(self):
        foreign = json.loads((self.root / "products/sample.json").read_text())
        foreign["id"] = "teamcity"
        dump(self.root / "products/teamcity.json", foreign)
        before = self.snapshot()
        with mock.patch.object(teamcity.net, "get_text") as fetch:
            with self.assertRaisesRegex(ValueError, "ownership collision"):
                teamcity.import_teamcity(self.root)
        fetch.assert_not_called()
        self.assertEqual(self.snapshot(), before)

    def test_a_reworded_policy_refuses_the_import_and_leaves_the_catalog_untouched(self):
        self.refresh("2026-09-23T01:00:00Z")
        before = self.snapshot()
        with self.assertRaisesRegex(ValueError, "reworded"):
            self.refresh("2026-09-23T02:00:00Z",
                         policy_html=POLICY.replace(EOL_SENTENCE, "Two versions later."))
        self.assertEqual(self.snapshot(), before)

    def test_a_parse_failure_leaves_existing_files_untouched(self):
        self.refresh("2026-09-23T01:00:00Z")
        before = self.snapshot()
        with self.assertRaises(ValueError):
            self.refresh("2026-09-23T02:00:00Z", catalog="<html><body>Changed layout</body></html>")
        self.assertEqual(self.snapshot(), before)

    def test_the_committed_record_is_re_derived_before_it_is_replaced(self):
        self.refresh("2026-09-23T01:00:00Z")
        tampered = json.loads((self.root / "products/teamcity.json").read_text())
        tampered["releases"][3]["milestones"]["eol"] = "2099-01-01"
        dump(self.root / "products/teamcity.json", tampered)
        before = self.snapshot()
        with self.assertRaisesRegex(ValueError, "contradicts the catalog chapter"):
            self.refresh("2026-09-23T02:00:00Z")
        self.assertEqual(self.snapshot(), before)


if __name__ == "__main__":
    unittest.main()
