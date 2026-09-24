"""Flatcar Container Linux collector regression tests.

The record is a deterministic derivation from two project pages: the release
feed states every stream's own release date, and the channel documentation
states the rule that ends a Stable major's support. These tests pin the
inventory, the trigger boundary, the accounting of every feed row, the offline
re-derivation, and the publication transaction.
"""
import copy
import json
import re
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from engine import derived, flatcar, sources
from engine.importer import API, dump, normalize

FIXTURES = Path(__file__).parent / "fixtures"
FEED = json.loads((FIXTURES / "flatcar-releases.json").read_text(encoding="utf-8"))
POLICY = (FIXTURES / "flatcar-switching-channels.html").read_text(encoding="utf-8")

CHECKED = "2026-09-23T00:00:00Z"
# Independently counted from the saved feed: its rows, the rows the Stable
# channel states, the major streams among them, and the rows left over.
FEED_ROWS = 548
STABLE_ROWS = 139
MAJORS = 33
EXCLUDED = FEED_ROWS - MAJORS
CHANNELS = {"alpha": 165, "beta": 152, "edge": 27, "lts": 65, "stable": 139}
# The project's own wording for the rule this record derives from.
STABLE_SENTENCE = ("Any Stable major version remains supported until a new major Stable "
                   "version is released.")


def rules(html=POLICY):
    return flatcar.policy_rules(html)


def parsed(payload=FEED):
    return flatcar.parse_feed(payload)


def VERSION_OF(key):
    """The feed's release-key shape, so a channel pointer can be told apart."""
    return re.fullmatch(r"\d+\.\d+\.\d+", key)


def record(payload=FEED, policy_html=POLICY):
    fresh, _, _ = parsed(payload)
    return flatcar.record_for(
        flatcar.with_derived_milestones(fresh, rules(policy_html)), CHECKED)


def by_id(releases):
    return {release["id"]: release for release in releases}


class PolicyTests(unittest.TestCase):
    def test_the_page_states_the_stable_rule_verbatim(self):
        rule = rules()
        self.assertEqual(rule["quote"], STABLE_SENTENCE)
        self.assertIn(STABLE_SENTENCE, POLICY)
        self.assertEqual(rule["label"], flatcar.RULE_LABEL)

    def test_the_statements_the_record_refuses_to_date_are_recorded(self):
        rule = rules()
        quotes = {entry["quote"] for entry in rule["not_dated"]}
        self.assertTrue(quotes)
        for entry in rule["not_dated"]:
            self.assertIn(entry["quote"], flatcar.page_text(POLICY))
            self.assertTrue(entry["reason"])
        self.assertIn(flatcar.NOT_DATED[0][0], quotes)
        self.assertIn(flatcar.NOT_DATED[1][0], quotes)

    def test_a_reworded_rule_refuses_the_parse(self):
        html = POLICY.replace(STABLE_SENTENCE,
                              "Stable major versions stay supported until the following one ships.")
        with self.assertRaisesRegex(ValueError, "no longer states the Stable support rule"):
            rules(html)

    def test_a_page_without_the_rule_refuses_the_parse(self):
        with self.assertRaises(ValueError):
            rules("<html><body><p>The channel documentation moved.</p></body></html>")


class InventoryTests(unittest.TestCase):
    def test_the_saved_feed_states_thirty_three_stable_majors(self):
        releases, excluded, accounting = parsed()
        self.assertEqual(len(releases), MAJORS)
        self.assertEqual(len(excluded), EXCLUDED)
        self.assertEqual(accounting["seen"], FEED_ROWS)
        self.assertEqual(accounting["excluded"], EXCLUDED)
        self.assertEqual(accounting["channels"], CHANNELS)

    def test_each_stream_is_its_first_stable_release(self):
        releases = by_id(parsed()[0])
        self.assertEqual(releases["4757"]["milestones"]["ga"], "2026-09-14")
        self.assertEqual(releases["4757"]["upstream"]["name"], "4757.2.0")
        self.assertEqual(releases["4757"]["upstream"]["cells"]["release_date"],
                         "2026-09-14 12:19:07 +0000")
        # The oldest stream this feed states, whose first Stable build is also
        # its only one.
        self.assertEqual(releases["1688"]["milestones"]["ga"], "2018-04-25")

    def test_a_later_stable_build_never_becomes_its_own_release(self):
        releases, _, _ = parsed()
        by_major = by_id(releases)
        self.assertNotIn("4593.2.5", by_major)
        self.assertEqual(by_major["4593"]["milestones"]["ga"], "2026-04-27")
        self.assertEqual(len(releases), len(by_major))

    def test_releases_are_ordered_newest_stream_first(self):
        releases, _, _ = parsed()
        majors = [int(release["id"]) for release in releases]
        self.assertEqual(majors, sorted(majors, reverse=True))
        self.assertEqual(releases[0]["id"], "4757")

    def test_every_published_row_is_a_stable_channel_row(self):
        for release in parsed()[0]:
            cells = release["upstream"]["cells"]
            self.assertEqual(cells["channel"], flatcar.STABLE)
            self.assertEqual(cells["version"], release["upstream"]["name"])
            self.assertEqual(release["upstream"]["table"], flatcar.FEED_TABLE)


class TriggerBoundaryTests(unittest.TestCase):
    def test_a_stream_ends_when_the_next_major_is_released(self):
        releases = by_id(flatcar.with_derived_milestones(parsed()[0], rules()))
        self.assertEqual(releases["4593"]["milestones"]["eol"], "2026-09-14")
        self.assertEqual(releases["4230"]["milestones"]["eol"], "2025-11-12")
        entry = releases["4593"]["milestone_provenance"]["eol"]
        self.assertEqual(entry["kind"], derived.KIND)
        self.assertEqual(entry["method"], "release-trigger")
        self.assertEqual(entry["quote"], STABLE_SENTENCE)
        self.assertEqual(entry["base_date"], "2026-04-27")
        self.assertEqual(entry["base_label"], flatcar.BASE_LABEL)
        self.assertEqual(entry["trigger"],
                         {"release_id": "4757", "date": "2026-09-14",
                          "label": flatcar.TRIGGER_LABEL})

    def test_the_newest_stream_keeps_a_null_end_of_life(self):
        releases = by_id(flatcar.with_derived_milestones(parsed()[0], rules()))
        self.assertIsNone(releases["4757"]["milestones"]["eol"])
        self.assertNotIn(derived.DERIVED_KEY, releases["4757"])

    def test_only_end_of_life_is_derived_and_only_it_is_disclosed(self):
        releases = flatcar.with_derived_milestones(parsed()[0], rules())
        self.assertTrue(all(release["milestones"]["eos"] is None for release in releases))
        self.assertTrue(all(release["milestones"]["eossec"] is None for release in releases))
        for release in releases:
            self.assertEqual(set(release.get(derived.DERIVED_KEY) or {}),
                             {"eol"} if release["milestones"]["eol"] else set())

    def test_a_derived_end_of_life_is_never_stated_as_vendor_wording(self):
        # The label evidence names the feed's own date column only: the derived
        # date is not a column the feed publishes.
        self.assertEqual(record()["labels"], {"ga": "release_date"})


class FeedRefusalTests(unittest.TestCase):
    def test_a_row_without_a_channel_refuses_the_parse(self):
        payload = copy.deepcopy(FEED)
        del payload["4593.2.0"]["channel"]
        with self.assertRaisesRegex(ValueError, "states no"):
            parsed(payload)

    def test_an_unknown_channel_refuses_the_parse(self):
        payload = copy.deepcopy(FEED)
        payload["4593.2.0"]["channel"] = "nightly"
        with self.assertRaisesRegex(ValueError, "unrecognized release channel"):
            parsed(payload)

    def test_an_impossible_release_timestamp_refuses_the_parse(self):
        payload = copy.deepcopy(FEED)
        payload["4593.2.0"]["release_date"] = "2026-02-30 10:26:25 +0000"
        with self.assertRaisesRegex(ValueError, "not a real timestamp"):
            parsed(payload)
        payload = copy.deepcopy(FEED)
        payload["4593.2.0"]["release_date"] = "27 April 2026"
        with self.assertRaisesRegex(ValueError, "unrecognized release date"):
            parsed(payload)

    def test_an_empty_feed_refuses_the_parse(self):
        with self.assertRaisesRegex(ValueError, "states no rows"):
            parsed({})

    def test_a_feed_without_stable_rows_refuses_the_parse(self):
        payload = {key: row for key, row in FEED.items() if row["channel"] != flatcar.STABLE}
        with self.assertRaisesRegex(ValueError, "no Stable release"):
            parsed(payload)

    def test_two_streams_sharing_a_release_date_refuse_the_parse(self):
        # The next-major trigger would be ambiguous: sorting the streams by date
        # could pick either order for the two lines that share one.
        payload = {key: row for key, row in FEED.items() if row["channel"] == flatcar.STABLE}
        payload["9000.2.0"] = {"channel": flatcar.STABLE,
                               "release_date": "2026-09-14 12:19:07 +0000"}
        with self.assertRaisesRegex(ValueError, "the same release date"):
            parsed(payload)


class AccountingTests(unittest.TestCase):
    def report(self, payload=FEED, kept=()):
        fresh, excluded, accounting = parsed(payload)
        rule = rules()
        releases, _ = flatcar.combine_releases(
            flatcar.with_derived_milestones(fresh, rule), None)
        releases = flatcar.with_derived_milestones(releases, rule)
        return flatcar.report_for(releases, excluded, accounting, rule, list(kept), CHECKED)

    def test_every_feed_row_is_accounted_for(self):
        report = self.report()
        rows = report["rows"]
        self.assertEqual(rows["seen"], FEED_ROWS)
        self.assertEqual(rows["published"], MAJORS)
        self.assertEqual(rows["excluded"], EXCLUDED)
        self.assertEqual(rows["seen"], rows["published"] + rows["excluded"])
        self.assertEqual(rows["retained"], 0)
        self.assertEqual(rows["derived_eol"], MAJORS - 1)
        self.assertEqual(report["total_records"], 1)

    def test_every_excluded_row_names_its_reason(self):
        report = self.report()
        self.assertEqual(len(report["excluded"]), EXCLUDED)
        pointers = {key for key in FEED if VERSION_OF(key) is None}
        self.assertTrue(pointers)
        rows = {entry["row"] for entry in report["excluded"]}
        self.assertLessEqual(pointers, rows)
        for entry in report["excluded"]:
            self.assertEqual(entry["page"], flatcar.FEED_URL)
            self.assertTrue(entry["row"])
            self.assertTrue(entry["reason"])
        reasons = " ".join(entry["reason"] for entry in report["excluded"])
        for channel in ("alpha", "beta", "edge", "lts"):
            self.assertIn(channel, reasons)
        self.assertIn("channel pointer", reasons)
        self.assertIn("later Stable build", reasons)

    def test_every_channel_row_is_accounted_in_the_channel_counts(self):
        report = self.report()
        self.assertEqual(report["channels"], CHANNELS)
        self.assertEqual(sum(report["channels"].values()), FEED_ROWS)

    def test_the_report_states_what_is_not_modelled(self):
        report = self.report()
        self.assertIn("derives", report["record_scope"])
        limitations = " ".join(report["limitations"])
        self.assertIn("derived, not vendor-stated", limitations)
        self.assertIn("eos and eossec are null", limitations)
        self.assertIn("LTS stream is not modelled", limitations)
        self.assertIn("cadence", limitations)
        self.assertEqual(report["policy"]["rules"],
                         [{"label": flatcar.RULE_LABEL, "quote": STABLE_SENTENCE}])
        self.assertEqual([entry["quote"] for entry in report["policy"]["not_dated"]],
                         [quote for quote, _ in flatcar.NOT_DATED])


class RetentionTests(unittest.TestCase):
    def test_a_stream_the_feed_drops_is_retained_from_its_own_cells(self):
        committed = record()
        payload = {key: row for key, row in FEED.items() if not key.startswith("4757.")}
        fresh, _, _ = parsed(payload)
        releases, kept = flatcar.combine_releases(
            flatcar.with_derived_milestones(fresh, rules()), committed)
        published = {release["id"] for release in releases}
        self.assertEqual(published, {release["id"] for release in committed["releases"]})
        self.assertEqual([entry["id"] for entry in kept], ["4757"])
        retained = by_id(releases)["4757"]
        self.assertIs(retained["upstream"]["in_source"], False)
        # A retained stream's dates are recomputed from the merged snapshot, so
        # 4593's trigger is still the 4757 stream the committed record states.
        self.assertEqual(retained["milestones"]["ga"], "2026-09-14")
        self.assertEqual(by_id(flatcar.with_derived_milestones(
            releases, rules()))["4593"]["milestones"]["eol"], "2026-09-14")

    def test_a_first_fetch_retains_nothing(self):
        releases, kept = flatcar.combine_releases(parsed()[0], None)
        self.assertEqual(kept, [])
        self.assertEqual(len(releases), MAJORS)


class ReDerivationTests(unittest.TestCase):
    def test_the_fetched_record_re_derives_offline(self):
        flatcar.validate_record(record())

    def test_a_tampered_derived_milestone_is_refused(self):
        rec = record()
        rec["releases"][1]["milestones"]["eol"] = "2099-01-01"
        with self.assertRaisesRegex(ValueError, "contradicts the feed row it stores"):
            flatcar.validate_record(rec)

    def test_a_tampered_trigger_stream_is_refused(self):
        # Repointing the id at a real, older stream while its date still equals
        # the derived milestone keeps the entry internally consistent, so only
        # the project's own next-major rule rejects it.
        rec = record()
        entry = rec["releases"][2]["milestone_provenance"]["eol"]
        entry["trigger"]["release_id"] = "4230"
        with self.assertRaisesRegex(ValueError, "wrong major"):
            flatcar.validate_record(rec)

    def test_a_trigger_lifted_from_two_streams_ahead_is_refused(self):
        rec = record()
        entry = rec["releases"][2]["milestone_provenance"]["eol"]
        entry["trigger"]["release_id"] = "4757"
        with self.assertRaisesRegex(ValueError, "wrong major"):
            flatcar.validate_record(rec)

    def test_a_trigger_date_that_is_not_the_derived_milestone_is_refused(self):
        # The shared module owns this one: the trigger's own date IS the derived
        # deadline, so a different date is not the rule this record applies.
        rec = record()
        rec["releases"][2]["milestone_provenance"]["eol"]["trigger"]["date"] = "2025-01-01"
        with self.assertRaisesRegex(ValueError, "is not the eol milestone"):
            flatcar.validate_record(rec)

    def test_a_tampered_quote_or_base_is_refused(self):
        for mutate, message in (
                (lambda entry: entry.update(quote="A sentence about release cadence and support."),
                 "does not quote the project rule"),
                (lambda entry: entry.update(base_date="2020-01-01"),
                 "wrong base date"),
                (lambda entry: entry.update(base_label="the previous major version"),
                 "wrong base date")):
            rec = record()
            mutate(rec["releases"][2]["milestone_provenance"]["eol"])
            with self.assertRaisesRegex(ValueError, message):
                flatcar.validate_record(rec)

    def test_a_derived_milestone_stripped_of_its_rule_is_refused(self):
        rec = record()
        del rec["releases"][2]["milestone_provenance"]
        with self.assertRaisesRegex(ValueError, "no rule recorded for it"):
            flatcar.validate_record(rec)

    def test_an_end_of_life_without_a_published_trigger_refuses(self):
        # The newest stream has no successor, so a date on it contradicts its
        # own stored row before any policy check runs.
        rec = record()
        rec["releases"][0]["milestones"]["eol"] = "2027-01-01"
        rec["releases"][0][derived.DERIVED_KEY] = {
            "eol": copy.deepcopy(rec["releases"][1][derived.DERIVED_KEY]["eol"])}
        with self.assertRaises(ValueError):
            flatcar.validate_record(rec)

    def test_tampered_source_cells_are_refused(self):
        rec = record()
        rec["releases"][0]["upstream"]["cells"]["release_date"] = "2026-09-15 12:19:07 +0000"
        with self.assertRaisesRegex(ValueError, "contradicts the release date cell"):
            flatcar.validate_record(rec)
        rec = record()
        rec["releases"][0]["upstream"]["cells"]["version"] = "9999.2.0"
        with self.assertRaisesRegex(ValueError, "contradicts the feed row it stores"):
            flatcar.validate_record(rec)
        rec = record()
        rec["releases"][0]["upstream"]["cells"]["channel"] = "beta"
        with self.assertRaisesRegex(ValueError, "not a Stable release"):
            flatcar.validate_record(rec)

    def test_a_foreign_verifier_or_source_url_is_refused(self):
        rec = record()
        rec["provenance"]["verifier"] = "deterministic-something-else"
        with self.assertRaisesRegex(ValueError, "source identity"):
            flatcar.validate_record(rec)
        rec = record()
        rec["provenance"]["source_url"] = "https://example.com/releases.json"
        with self.assertRaisesRegex(ValueError, "source identity"):
            flatcar.validate_record(rec)

    def test_a_record_order_that_contradicts_the_dates_is_refused(self):
        rec = record()
        rec["releases"][0], rec["releases"][1] = rec["releases"][1], rec["releases"][0]
        with self.assertRaisesRegex(ValueError, "not ordered by the feed's release dates"):
            flatcar.validate_record(rec)

    def test_a_release_without_its_stored_row_is_refused(self):
        rec = record()
        rec["releases"][0]["upstream"] = {"name": "4757.2.0"}
        with self.assertRaisesRegex(ValueError, "does not store its feed row's cells"):
            flatcar.validate_record(rec)


class RegistryTests(unittest.TestCase):
    def test_the_source_is_registered_as_a_software_collector(self):
        source = sources.source("import-flatcar")
        self.assertEqual(source.verifier, "deterministic-flatcar")
        self.assertEqual(source.category, "software")
        self.assertEqual(source.report, "flatcar-import.json")
        self.assertEqual(flatcar.VERIFIER, source.verifier)
        self.assertEqual((flatcar.FEED_URL, flatcar.POLICY_URL), source.urls)
        self.assertEqual(flatcar.REPORT, source.report)
        self.assertIs(sources.record_validator(source), flatcar.validate_record)

    def test_the_cli_exposes_the_source_command(self):
        from engine.__main__ import COMMANDS

        self.assertIn("import-flatcar", COMMANDS)

    def test_the_registered_pages_carry_one_label_each(self):
        for page in sources.source("import-flatcar").pages:
            self.assertEqual(sources.source_label(page.url), page.label)


class OwnershipTests(unittest.TestCase):
    def test_a_foreign_record_is_refused(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "products").mkdir()
            other = {"provenance": {"verifier": "deterministic-ceph"}}
            dump(root / "products" / (flatcar.PRODUCT_ID + ".json"), other)
            with self.assertRaisesRegex(ValueError, "source ownership collision"):
                flatcar.committed_record(root)

    def test_a_missing_record_is_not_a_collision(self):
        with tempfile.TemporaryDirectory() as temp:
            self.assertIsNone(flatcar.committed_record(Path(temp)))

    def test_an_unpublishable_committed_record_is_refused_before_any_fetch(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "products").mkdir()
            rec = record()
            rec["releases"][0]["milestones"]["eol"] = "2099-01-01"
            dump(root / "products" / (flatcar.PRODUCT_ID + ".json"), rec)
            with self.assertRaises(ValueError):
                flatcar.committed_record(root)


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

    def refresh(self, checked, payload=FEED, policy_html=POLICY):
        with mock.patch.object(flatcar.net, "get_text", side_effect=[policy_html]), \
                mock.patch.object(flatcar.net, "get_json", side_effect=[payload]), \
                mock.patch.object(flatcar, "_now", return_value=checked):
            return flatcar.import_flatcar(self.root)

    def test_a_quiet_refresh_republishes_byte_identical_files(self):
        self.refresh("2026-09-23T01:00:00Z")
        published = self.snapshot()
        self.assertIn("products/flatcar-container-linux.json", published)
        self.assertIn(flatcar.REPORT, published)
        self.refresh("2026-09-23T02:00:00Z")
        self.assertEqual(self.snapshot(), published)
        rec = json.loads(published["products/flatcar-container-linux.json"])
        self.assertEqual(rec["provenance"]["last_checked"], "2026-09-23T01:00:00Z")
        self.assertEqual(len(rec["releases"]), MAJORS)
        report = json.loads(published[flatcar.REPORT])
        self.assertEqual(report["rows"]["seen"], FEED_ROWS)

    def test_a_new_major_fills_the_previous_stream_and_advances_revisions(self):
        self.refresh("2026-09-23T01:00:00Z")
        before = self.snapshot()
        payload = copy.deepcopy(FEED)
        payload["4900.2.0"] = {"channel": "stable", "release_date": "2026-11-02 10:00:00 +0000"}
        payload["4900.3.0"] = {"channel": "stable", "release_date": "2026-12-01 10:00:00 +0000"}
        payload["current"]["release_date"] = "2026-11-02 10:00:00 +0000"
        self.refresh("2026-09-23T03:00:00Z", payload=payload)
        after = self.snapshot()
        self.assertNotEqual(after, before)
        releases = {release["id"]: release
                    for release in json.loads(after["products/flatcar-container-linux.json"])["releases"]}
        self.assertEqual(releases["4900"]["milestones"]["ga"], "2026-11-02")
        self.assertIsNone(releases["4900"]["milestones"]["eol"])
        self.assertNotIn(derived.DERIVED_KEY, releases["4900"])
        self.assertEqual(releases["4757"]["milestones"]["eol"], "2026-11-02")
        report = json.loads(after[flatcar.REPORT])
        self.assertEqual(report["rows"]["published"], MAJORS + 1)
        self.assertEqual(report["rows"]["excluded"], EXCLUDED + 1)
        self.assertEqual(report["rows"]["derived_eol"], MAJORS)

    def test_a_refused_fetch_leaves_every_committed_file_untouched(self):
        self.refresh("2026-09-23T01:00:00Z")
        before = self.snapshot()
        with self.assertRaises(ValueError):
            self.refresh("2026-09-23T02:00:00Z",
                         policy_html="<html><body><p>The documentation moved.</p></body></html>")
        self.assertEqual(self.snapshot(), before)

    def test_a_foreign_committed_record_refuses_the_run_before_any_fetch(self):
        dump(self.root / "products" / (flatcar.PRODUCT_ID + ".json"),
             {"provenance": {"verifier": "deterministic-ceph"}})
        with mock.patch.object(flatcar.net, "get_text") as get_text, \
                mock.patch.object(flatcar.net, "get_json") as get_json:
            with self.assertRaisesRegex(ValueError, "source ownership collision"):
                flatcar.import_flatcar(self.root)
        get_text.assert_not_called()
        get_json.assert_not_called()

    def test_the_registered_entry_point_publishes_the_record(self):
        # The registry's own call path, so the CLI command is what the tests
        # exercise rather than a private helper beside it.
        with mock.patch.object(flatcar.net, "get_text", return_value=POLICY), \
                mock.patch.object(flatcar.net, "get_json", return_value=FEED), \
                mock.patch.object(flatcar, "_now", return_value="2026-09-23T01:00:00Z"):
            detail = sources.source("import-flatcar").run(self.root)
        self.assertIn("33 Flatcar Container Linux Stable major streams", detail)
        published = json.loads((self.root / "products" /
                                (flatcar.PRODUCT_ID + ".json")).read_text())
        flatcar.validate_record(published)
        self.assertEqual(len(published["releases"]), MAJORS)


if __name__ == "__main__":
    unittest.main()
