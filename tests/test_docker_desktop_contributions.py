"""Docker Desktop edition-scoped research records (contributions/, issue #28).

Docker Desktop's supported-versions rule is edition-specific, so one
release-level `eol` cannot state it honestly: Pro/Team are supported on the
latest version only, while Business supports versions up to six months older
than the latest version. The two contributions therefore publish the same
release history twice, each deriving `eol` from its own edition's rule.

These tests pin the contract that makes the pair defensible rather than a
duplicate of Docker's own release-notes page:

* the two editions must disagree about the same release (a split, not a copy);
* an `eol` must be the published date of the release the rule names, never a
  computed anniversary and never a download-availability cutoff;
* the latest release must stay unknown until a newer one actually ships;
* every derived date must re-derive from its stored rule via the catalog's own
  checker, and must stay out of the exact-day feeds.
"""
import json
import unittest
from datetime import datetime, timezone

from engine import derived, feeds
from engine.contribute import (build_record, check_file, date_in_quote, parse_contribution,
                               research_object)
from engine.importer import ROOT

CONTRIBUTIONS = ROOT / "contributions"
FILES = {"pro-team": CONTRIBUTIONS / "docker-desktop-pro-team.json",
         "business": CONTRIBUTIONS / "docker-desktop-business.json"}
CHECKED = "2026-09-23T00:00:00Z"

# The two dates the no-go audit named, one per edition rule. They are the
# sharpest available boundary: the same triggering release (4.92.0,
# 2026-09-21) ends 4.91.0 for Pro/Team, whose window is "the next release", and
# ends 4.65.0 for Business, whose window is "more than six months older".
AUDIT_EXAMPLES = {"pro-team": ("4.91.0", "2026-09-21", "4.92.0"),
                  "business": ("4.65.0", "2026-09-21", "4.92.0")}


def load(edition):
    return json.loads(FILES[edition].read_text(encoding="utf-8"))


def rows(edition):
    return {release["id"]: release for release in load(edition)["releases"]}


class EditionSplitTests(unittest.TestCase):
    """The record pair states one product under two different plan rules."""

    def test_each_edition_is_a_separate_record_with_its_own_rule(self):
        parsed = {edition: parse_contribution(load(edition), path=str(FILES[edition]))
                  for edition in FILES}
        self.assertEqual(parsed["pro-team"]["id"], "researched-docker-desktop-pro-team")
        self.assertEqual(parsed["business"]["id"], "researched-docker-desktop-business")
        # Distinct records in the researched namespace, so neither can displace
        # Docker Engine (data/products/docker-engine.json) or the other.
        self.assertNotEqual(parsed["pro-team"]["id"], parsed["business"]["id"])
        self.assertEqual(parsed["pro-team"]["contributor"], parsed["business"]["contributor"])

        # Each record's derived dates quote its own edition's sentence from the
        # support page, and only that sentence.
        for edition, expected in (("pro-team", "Docker Pro and Team: Latest version only"),
                                  ("business", "Docker Business: Versions up to six months "
                                               "older than the latest version (fixes applied to "
                                               "latest version only)")):
            quotes = {entry.get("quote") for release in rows(edition).values()
                      for entry in (release.get("milestone_provenance") or {}).values()}
            self.assertEqual(quotes, {expected})
            self.assertEqual(
                {entry["source_url"] for release in rows(edition).values()
                 for entry in (release.get("milestone_provenance") or {}).values()},
                {"https://docs.docker.com/support/"})

    def test_the_same_release_gets_different_dates_per_edition(self):
        # 4.66.0 shipped 2026-03-23 with 4.66.1 (2026-03-26) three days later:
        # Pro/Team support ends there, while Business is still inside its window.
        pro, business = rows("pro-team")["4.66.0"], rows("business")["4.66.0"]
        self.assertEqual(pro["milestones"]["ga"], business["milestones"]["ga"])
        self.assertEqual(pro["milestones"]["eol"], "2026-03-26")
        self.assertIsNone(business["milestones"]["eol"])
        # ...and the reverse shape: a release whose Business window has closed
        # but which Pro/Team ended even earlier.
        self.assertEqual(rows("pro-team")["4.65.0"]["milestones"]["eol"], "2026-03-23")
        self.assertEqual(rows("business")["4.65.0"]["milestones"]["eol"], "2026-09-21")

    def test_editions_do_not_share_a_record_and_engine_is_untouched(self):
        ids = {parse_contribution(load(edition))["id"] for edition in FILES}
        self.assertNotIn("docker-engine", ids)
        engine = json.loads((ROOT / "data/products/docker-engine.json").read_text(encoding="utf-8"))
        self.assertEqual(engine["provenance"]["verifier"], "deterministic-endoflife-date-v1")
        self.assertTrue(all("docker-desktop" not in release["id"] for release in engine["releases"]))


class ReleaseTriggerTests(unittest.TestCase):
    """Every derived eol names the release whose own publication ends the window."""

    def test_the_audit_examples_derive_to_the_named_dates(self):
        for edition, (release_id, expected, trigger_id) in AUDIT_EXAMPLES.items():
            release = rows(edition)[release_id]
            self.assertEqual(release["milestones"]["eol"], expected,
                             f"{edition} {release_id}")
            provenance = release["milestone_provenance"]["eol"]
            self.assertEqual(provenance["method"], "release-trigger")
            self.assertEqual(provenance["trigger"]["release_id"], trigger_id)
            self.assertEqual(provenance["trigger"]["date"], expected)
            # A derived milestone equals its trigger's own published date: the
            # date is the trigger release's, never an anniversary.
            self.assertEqual(set(derived.derive(release["milestones"], release["milestone_provenance"],
                                                release_id, set(rows(edition))).values()),
                             {expected})

    def test_trigger_dates_are_published_release_dates_of_the_named_release(self):
        for edition in FILES:
            table = rows(edition)
            for release_id, release in table.items():
                provenance = (release.get("milestone_provenance") or {}).get("eol")
                if not provenance:
                    continue
                trigger_id = provenance["trigger"]["release_id"]
                self.assertIn(trigger_id, table,
                              f"{edition} {release_id} names an unpublished trigger {trigger_id}")
                # The trigger is a newer version that shipped after this release.
                self.assertNotEqual(trigger_id, release_id)
                self.assertEqual(provenance["trigger"]["date"],
                                 table[trigger_id]["milestones"]["ga"])
                self.assertGreater(provenance["trigger"]["date"], release["milestones"]["ga"])
                self.assertEqual(release["milestones"]["eol"], provenance["trigger"]["date"])

    def test_pro_team_eol_is_the_next_version_to_become_latest(self):
        """A Pro/Team window closes only when a new latest version ships.

        Docker keeps patching older lines in parallel (the six 2025-01-09
        backports), so "the next release" is not the rule Docker states: the
        trigger must be the release that actually succeeded this one as the
        latest version, i.e. one that was higher than every version published
        before it — and the earliest such release after this one.
        """
        table = rows("pro-team")

        def key(version):
            return tuple(int(part) for part in version.split("."))

        def latest_events():
            """(date, version) of every release that was the newest when it shipped."""
            seen, events = (), []
            for release in sorted((r for r in table.values() if r["milestones"]["ga"]),
                                  key=lambda r: (r["milestones"]["ga"], key(r["id"]))):
                if key(release["id"]) > (max(seen) if seen else ()):
                    events.append(release)
                    seen = seen + (key(release["id"]),)
            return events

        events = latest_events()
        event_dates = [e["milestones"]["ga"] for e in events]
        for release_id, release in table.items():
            provenance = (release.get("milestone_provenance") or {}).get("eol")
            if not provenance:
                continue
            later = [e for e in events if key(e["id"]) > key(release_id)]
            self.assertTrue(later, f"{release_id} ends although no newer version shipped")
            self.assertEqual(provenance["trigger"]["date"], later[0]["milestones"]["ga"],
                             f"{release_id} names a release other than the next latest version")
            self.assertEqual(provenance["trigger"]["release_id"], later[0]["id"])
            self.assertIn(provenance["trigger"]["date"], event_dates)

    def test_parallel_backports_are_not_treated_as_successor_releases(self):
        """A backport only ends a window if it was itself the newest version.

        4.32.1/4.33.2/4.34.4/4.35.2/4.36.1 share the 2025-01-09 date of one
        vmnetd/socket fix, and each is a lower version than 4.37.0/4.37.1/
        4.37.2, which had already shipped — so none was ever "the latest
        version" and the rule produces no eol for them. 4.37.2, dated the same
        day, *was* the highest version then, so it does have one (4.38.0,
        2025-01-30); the split is by version, not by that shared date.
        """
        table = rows("pro-team")
        never_latest = {"4.32.1", "4.33.2", "4.34.4", "4.35.2", "4.36.1"}
        for backport in never_latest:
            self.assertEqual(table[backport]["milestones"]["ga"], "2025-01-09")
            self.assertIsNone(table[backport]["milestones"]["eol"], backport)
            self.assertNotIn("milestone_provenance", table[backport])
        # Same date, but it became the latest version, so it is derived normally.
        self.assertEqual(table["4.37.2"]["milestones"]["eol"], "2025-01-30")
        self.assertEqual(table["4.37.2"]["milestone_provenance"]["eol"]["trigger"]["release_id"],
                         "4.38.0")
        # No backport that was never the latest version may be a trigger either.
        triggers = {release["milestone_provenance"]["eol"]["trigger"]["release_id"]
                    for release in table.values() if release.get("milestone_provenance")}
        self.assertEqual(triggers & never_latest, set())

    def test_business_eol_is_the_first_release_past_the_six_month_window(self):
        table = rows("business")
        for release_id, release in table.items():
            provenance = (release.get("milestone_provenance") or {}).get("eol")
            if not provenance:
                continue
            boundary = derived.add_duration(release["milestones"]["ga"], 6, "month")
            # Strictly past the window, and never the window itself: the
            # six-month date is not a release date and is never stored as one.
            self.assertGreater(provenance["trigger"]["date"], boundary, release_id)
            self.assertNotEqual(release["milestones"]["eol"], boundary)
            earlier = [r["milestones"]["ga"] for r in table.values()
                       if r["milestones"]["ga"] and r["milestones"]["ga"] > boundary
                       and r["milestones"]["ga"] < provenance["trigger"]["date"]]
            self.assertEqual(earlier, [], f"{release_id} skipped a release past its window")

    def test_business_window_boundary_is_pinned_by_the_neighbours(self):
        table = rows("business")
        # 4.65.0 (2026-03-16) + six months = 2026-09-16. 4.91.0 (2026-09-14) is
        # inside the window; 4.92.0 (2026-09-21) is the first release past it.
        self.assertEqual(derived.add_duration(table["4.65.0"]["milestones"]["ga"], 6, "month"),
                         "2026-09-16")
        self.assertEqual(table["4.65.0"]["milestone_provenance"]["eol"]["trigger"]["release_id"],
                         "4.92.0")
        # 4.64.0 (2026-03-11) + six months = 2026-09-11, so 4.91.0 already ends it.
        self.assertEqual(table["4.64.0"]["milestone_provenance"]["eol"]["trigger"]["release_id"],
                         "4.91.0")
        self.assertEqual(table["4.64.0"]["milestones"]["eol"], "2026-09-14")

    def test_download_cutoff_and_macos_rules_are_not_lifecycle_evidence(self):
        for edition in FILES:
            payload = load(edition)
            for release in payload["releases"]:
                provenance = (release.get("milestone_provenance") or {}).get("eol")
                if provenance:
                    # The only rule that may license an eol is the edition's
                    # supported-versions sentence from the support page. The
                    # release-notes download cutoff and the macOS compatibility
                    # rule are not it.
                    self.assertEqual(provenance["source_url"], "https://docs.docker.com/support/")
                    self.assertNotIn("download", provenance["quote"].lower())
                    self.assertNotIn("macos", provenance["quote"].lower())
                    self.assertNotIn("not available for download", provenance["quote"])


class UnknownCurrentReleaseTests(unittest.TestCase):
    """A window that has not closed publishes no date."""

    def test_latest_release_has_no_eol_in_either_edition(self):
        for edition in FILES:
            table = rows(edition)
            latest = max(table, key=lambda version: tuple(map(int, version.split("."))))
            self.assertEqual(latest, "4.92.0")
            self.assertIsNone(table[latest]["milestones"]["eol"], edition)
            self.assertNotIn("milestone_provenance", table[latest])
            self.assertEqual(table[latest]["milestones"]["ga"], "2026-09-21")

    def test_no_published_eol_is_in_the_future_of_its_own_record(self):
        # A derived deadline is a release that already happened. If a stored eol
        # were ahead of the newest release date, it would be a prediction.
        for edition in FILES:
            table = rows(edition)
            newest = max(r["milestones"]["ga"] for r in table.values() if r["milestones"]["ga"])
            for release_id, release in table.items():
                if release["milestones"]["eol"]:
                    self.assertLessEqual(release["milestones"]["eol"], newest, release_id)

    def test_business_releases_inside_the_window_stay_unknown(self):
        table = rows("business")
        for release_id in ("4.66.0", "4.70.0", "4.80.0", "4.90.0", "4.91.0"):
            self.assertIsNone(table[release_id]["milestones"]["eol"], release_id)

    def test_undated_release_rows_stay_undated_rather_than_padded(self):
        # The page states no ISO release date for these rows: 4.31.0/4.31.1 are
        # undated and 4.4.2 is written "22-01-13". None may be filled in.
        for edition in FILES:
            table = rows(edition)
            for release_id in ("4.31.0", "4.31.1", "4.4.2"):
                self.assertIsNone(table[release_id]["milestones"]["ga"], release_id)
                self.assertIsNone(table[release_id]["milestones"]["eol"], release_id)
                self.assertNotIn("milestone_provenance", table[release_id])


class DisclosureTests(unittest.TestCase):
    """Derived dates stay labeled, recomputable, and out of the day feeds."""

    def records(self):
        records = {}
        for edition in FILES:
            payload = load(edition)
            contribution = parse_contribution(payload, path=str(FILES[edition]))
            research = research_object(contribution, contribution["evidence"], CHECKED)
            records[edition] = build_record(contribution, research, CHECKED)
        return records

    def test_every_derived_date_recomputes_from_its_stored_rule(self):
        for edition in FILES:
            table = rows(edition)
            for release_id, release in table.items():
                provenance = release.get("milestone_provenance")
                if not provenance:
                    continue
                derived.validate_milestone_provenance(
                    release["milestones"], provenance, f"{edition}/{release_id}", set(table))

    def test_derived_eol_is_excluded_from_the_exact_day_feeds(self):
        records = self.records()
        events = feeds.software_events(list(records.values()))
        day_events, excluded = feeds.representable(events)
        derived_events = [event for event in events if event["derived"]]
        self.assertTrue(derived_events)
        # No derived date may reach a format that carries an exact day...
        self.assertEqual([event for event in day_events if event["derived"]], [])
        # ...and every derived eol in each record is in the excluded set, so
        # neither record's derived dates are syndicated.
        excluded_ids = {event["release_id"] for event in excluded}
        for edition in FILES:
            derived_ids = {release["id"] for release in load(edition)["releases"]
                           if (release.get("milestone_provenance") or {}).get("eol")}
            self.assertTrue(derived_ids, edition)
            self.assertTrue(derived_ids <= excluded_ids, edition)
        # Each one is published as an exclusion instead, under the derived
        # reason code, with the rule its date came from.
        document = feeds.exclusions_document(excluded, len(day_events),
                                             datetime(2026, 9, 23, tzinfo=timezone.utc))
        entries = {entry["id"]: entry for entry in document["excluded"]}
        for event in derived_events:
            self.assertIn(event["id"], entries)
            entry = entries[event["id"]]
            self.assertEqual(entry["code"], "derived_not_vendor_stated")
            self.assertEqual(entry["product"], event["product_id"])
            self.assertEqual(entry["release"], event["release_id"])
            self.assertEqual(entry["milestone"], "eol")
            self.assertEqual(entry["date"], event["date"])
            self.assertEqual(entry["derived"]["quote"], event["derived"]["quote"])
            self.assertEqual(entry["derived"]["trigger"], event["derived"]["trigger"])
        self.assertEqual(document["counts"]["by_code"]["derived_not_vendor_stated"],
                         len(derived_events))

    def test_only_derived_and_unknown_releases_are_absent_from_openeox(self):
        from engine import openeox

        for edition, record in self.records().items():
            entries, exclusions = openeox._export_product(record)
            self.assertEqual(entries, [], edition)
            table = rows(edition)
            derived_ids = {release_id for release_id, release in table.items()
                           if (release.get("milestone_provenance") or {}).get("eol")}
            derived_excluded = {entry["release"] for entry in exclusions
                                if entry["code"] == "end_of_life_derived"}
            self.assertEqual(derived_excluded, derived_ids, edition)
            # Every release is accounted for exactly once, by code.
            self.assertEqual({entry["release"] for entry in exclusions}, set(table), edition)
            self.assertEqual(len(exclusions), len(table), edition)

    def test_eossec_is_never_filled_from_the_fixes_latest_only_wording(self):
        # "fixes applied to latest version only" scopes which version receives
        # fixes; it is not a dated security-support end.
        for edition in FILES:
            for release_id, release in rows(edition).items():
                self.assertIsNone(release["milestones"]["eossec"], f"{edition} {release_id}")

    def test_both_contributions_check_without_writing(self):
        for edition, path in FILES.items():
            report = check_file(path, allow_stale=True)
            self.assertEqual(report["action"], "check", edition)
            self.assertFalse(report["written"], edition)
            self.assertEqual(report["id"], f"researched-docker-desktop-{edition}")


class EvidenceTests(unittest.TestCase):
    """Every stated date is quoted from Docker's own pages at its own precision."""

    def test_every_ga_day_is_quoted_from_the_release_notes(self):
        for edition in FILES:
            payload = load(edition)
            quotes = [entry["quote"] for entry in payload["evidence"]
                      if entry["source_url"] == "https://docs.docker.com/desktop/release-notes/"]
            for release in payload["releases"]:
                ga = release["milestones"]["ga"]
                if not ga:
                    continue
                self.assertTrue(any(date_in_quote(ga, quote) and release["id"] in quote
                                    for quote in quotes),
                                f"{edition} {release['id']} {ga}")

    def test_no_dated_release_is_missing_a_ga_value(self):
        # 147 of the 150 published rows carry an ISO release date; the three
        # that do not are the documented exception, not a parsing loss.
        for edition in FILES:
            payload = load(edition)
            undated = [r["id"] for r in payload["releases"] if not r["milestones"]["ga"]]
            self.assertEqual(sorted(undated), ["4.31.0", "4.31.1", "4.4.2"], edition)
            self.assertEqual(len(payload["releases"]), 150, edition)

    def test_the_release_notes_history_is_complete_and_ordered(self):
        for edition in FILES:
            payload = load(edition)
            ids = [release["id"] for release in payload["releases"]]
            self.assertEqual(len(set(ids)), len(ids))
            self.assertEqual(ids[0], "4.92.0")
            self.assertEqual(ids[-1], "4.0.0")

    def test_audit_claims_about_the_sources_hold(self):
        # The audit named 4.92.0/2026-09-21 as the current release, and the two
        # example rows it derived from. Those are the stored values.
        for edition in FILES:
            table = rows(edition)
            self.assertEqual(table["4.92.0"]["milestones"]["ga"], "2026-09-21")
            self.assertEqual(table["4.91.0"]["milestones"]["ga"], "2026-09-14")
            self.assertEqual(table["4.65.0"]["milestones"]["ga"], "2026-03-16")

    def test_focus_rule_quote_is_the_support_page_sentence(self):
        # The edition rule is quote-backed evidence, and its wording is what the
        # support page publishes (checked 2026-09-23).
        for edition, expected in (("pro-team", "Docker Pro and Team: Latest version only"),
                                  ("business", "Docker Business: Versions up to six months older "
                                               "than the latest version (fixes applied to latest "
                                               "version only)")):
            quotes = [entry["quote"] for entry in load(edition)["evidence"]
                      if entry["source_url"] == "https://docs.docker.com/support/"]
            self.assertIn(expected, quotes, edition)

    def test_no_eol_is_derived_from_download_availability(self):
        """The download cutoff is not the rule behind any stored eol.

        Deriving from the release-notes cutoff would put each release's eol at
        its own six-month anniversary — a day no release was published on. Every
        stored eol here is instead the published date of the release the edition
        rule names, and none of them is its own release's anniversary.
        """
        for edition in FILES:
            table = rows(edition)
            release_days = {r["milestones"]["ga"] for r in table.values() if r["milestones"]["ga"]}
            stored = {r["milestones"]["eol"] for r in table.values() if r["milestones"]["eol"]}
            self.assertTrue(stored, edition)
            self.assertTrue(stored <= release_days, edition)
            for release_id, release in table.items():
                if not release["milestones"]["eol"]:
                    continue
                anniversary = derived.add_duration(release["milestones"]["ga"], 6, "month")
                self.assertNotEqual(release["milestones"]["eol"], anniversary,
                                    f"{edition} {release_id} matches the download cutoff")


if __name__ == "__main__":
    unittest.main()
