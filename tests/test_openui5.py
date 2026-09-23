"""OpenUI5 collector regression tests.

The full fixtures are the project's own documents, saved verbatim on
2026-09-23: ``openui5-versionoverview.json`` (113 version rows — 112 numbered
branches and the loader's wildcard default — plus 1038 patch rows),
``openui5-version.json`` (the 7 currently maintained branches and the two
pointers ``latest``/``active``), ``openui5-releases.json`` (the release feed the
releases page renders) and ``openui5-policy.md`` (the maintenance policy). The
``-mini`` documents are small synthetic ones in the same shape, so refusal and
boundary paths do not depend on the byte offsets of a saved file.

Every count below is taken from the fixtures independently of the module —
regex over the raw JSON and the raw Markdown — because the whole point of this
collector is that OpenUI5's quarter-precision ``eom``/``eomm``/``eocp`` cells
are *not* this catalog's milestones. A fabricated ``eol`` is exactly what the
repository's no-invented-dates rule forbids, and the tests below pin that the
mapped set is empty.
"""
import copy
import json
import re
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from engine import openui5, sources, validation
from engine.importer import API, dump, normalize

FIXTURES = Path(__file__).parent / "fixtures"
OVERVIEW = (FIXTURES / "openui5-versionoverview.json").read_text(encoding="utf-8")
CURRENT = (FIXTURES / "openui5-version.json").read_text(encoding="utf-8")
FEED = (FIXTURES / "openui5-releases.json").read_text(encoding="utf-8")
PAGE = (FIXTURES / "openui5-releases.html").read_text(encoding="utf-8")
POLICY = (FIXTURES / "openui5-policy.md").read_text(encoding="utf-8")

CHECKED = "2026-09-23T00:00:00Z"

# Independently counted from the saved documents.
VERSION_ROWS = 113
NUMBERED_BRANCHES = 112
SKIPPED_BRANCHES = 2
WILDCARD_ROWS = 1
PUBLISHED_BRANCHES = NUMBERED_BRANCHES - SKIPPED_BRANCHES
PATCH_ROWS = 1038
BRANCHES_WITH_PATCHES = 108
CURRENT_ROWS = 9
CURRENT_BRANCHES = 7
FEED_ROWS = 7
GA_BRANCHES = 2
# The two sources disagree for this branch in the snapshot; both cells are kept.
DIVERGENT_BRANCH = "1.142"

MINI_OVERVIEW = json.dumps({
    "versions": [
        {"version": "1.2.*", "support": "Maintenance", "lts": False, "eom": "",
         "eomm": "", "eocp": "Q1/2030"},
        {"version": "1.1.*", "support": "Out of Maintenance", "lts": False,
         "eom": "Q3/2026", "eomm": "Q3/2026", "eocp": "Q3/2027"},
    ],
    "patches": [
        {"version": "1.2.0", "eocp": "To Be Determined"},
        {"version": "1.1.2", "eocp": "Q3/2027", "removed": True},
        {"version": "1.1.0", "eocp": "Q3/2027"},
    ]}, indent=1)
MINI_CURRENT = json.dumps({
    "latest": {"version": "1.2.0", "support": "Maintenance", "lts": False},
    "active": {"version": "1.2.0", "support": "Maintenance", "lts": False},
    "1.2": {"version": "1.2.0", "support": "Maintenance", "lts": False}}, indent=1)
MINI_FEED = json.dumps([{
    "version": "1.2.0", "release_date": "05.07.2026", "eom": "",
    "url_download_runtime": "https://example.invalid/runtime",
    "url_download_sdk": "https://example.invalid/sdk",
    "url_download_mobile": "https://example.invalid/mobile",
    "url_demokit": "https://example.invalid/demokit",
    "url_releasenotes": "https://example.invalid/notes"}], indent=1)


def parsed(overview=OVERVIEW, current=CURRENT, feed=FEED):
    return openui5.parse_releases(overview, current, feed)


def by_id(releases):
    return {release["id"]: release for release in releases}


def record(overview=OVERVIEW, current=CURRENT, feed=FEED):
    releases, _ = parsed(overview, current, feed)
    return openui5.record_for(releases, CHECKED)


def reported(overview=OVERVIEW, current=CURRENT, feed=FEED, kept=()):
    releases, accounting = parsed(overview, current, feed)
    return openui5.report_for(releases, accounting, openui5.policy_rules(POLICY),
                              list(kept), CHECKED)


class InventoryTests(unittest.TestCase):
    def test_every_numbered_branch_is_published_and_the_exclusions_add_up(self):
        # The independent inventory: the raw document's own rows, split by the
        # project's own markers. Nothing here reads the module.
        payload = json.loads(OVERVIEW)
        rows = payload["versions"]
        self.assertEqual(len(rows), VERSION_ROWS)
        wildcard = [row for row in rows if row["version"] == "*"]
        skipped = [row for row in rows if row["support"].lower() == "skipped"]
        numbered = [row for row in rows if re.fullmatch(r"\d+\.\d+\.\*", row["version"])]
        self.assertEqual(len(wildcard), WILDCARD_ROWS)
        self.assertEqual(len(skipped), SKIPPED_BRANCHES)
        self.assertEqual(len(numbered), NUMBERED_BRANCHES)
        releases, accounting = parsed()
        self.assertEqual([release["id"] for release in releases],
                         [row["version"][:-2] for row in numbered
                          if row["support"].lower() != "skipped"])
        self.assertEqual(len(releases), PUBLISHED_BRANCHES)
        rows = accounting["branches"]
        self.assertEqual(rows["seen"], VERSION_ROWS)
        self.assertEqual(rows["published"], PUBLISHED_BRANCHES)
        self.assertEqual(rows["excluded"], WILDCARD_ROWS + SKIPPED_BRANCHES)
        self.assertEqual(rows["seen"], rows["published"] + rows["excluded"])
        # The two Skipped rows are excluded on their own reason, and neither
        # becomes a release the project never published.
        reasons = {entry["row"]: entry["reason"] for entry in accounting["excluded"]}
        self.assertEqual(sorted(reasons), ["*", "1.137.*", "1.83.*"])
        self.assertIn("Skipped", reasons["1.137.*"])
        self.assertIn("wildcard", reasons["*"])
        self.assertNotIn("1.137", by_id(releases))
        self.assertNotIn("1.83", by_id(releases))

    def test_every_patch_row_is_retained_under_its_branch(self):
        payload = json.loads(OVERVIEW)
        self.assertEqual(len(payload["patches"]), PATCH_ROWS)
        releases, accounting = parsed()
        stored = [row for release in releases for row in release["upstream"]["patches"]]
        self.assertEqual(len(stored), PATCH_ROWS)
        self.assertEqual([row["version"] for row in stored],
                         [row["version"] for row in payload["patches"]])
        self.assertEqual(accounting["patches"]["seen"], PATCH_ROWS)
        self.assertEqual(accounting["patches"]["published"], PATCH_ROWS)
        self.assertEqual(accounting["patches"]["branches"], BRANCHES_WITH_PATCHES)
        with_patches = sum(1 for release in releases if release["upstream"]["patches"])
        self.assertEqual(with_patches, BRANCHES_WITH_PATCHES)
        self.assertEqual(accounting["patches"]["branches_without"],
                         PUBLISHED_BRANCHES - BRANCHES_WITH_PATCHES)
        # Every patch sits under the branch its own version names.
        for release in releases:
            for row in release["upstream"]["patches"]:
                self.assertTrue(row["version"].startswith(release["id"] + "."),
                                f"{row['version']} under {release['id']}")

    def test_the_oldest_branches_without_patch_rows_are_published_anyway(self):
        # 1.24 and 1.22 are stated by the overview and carry no patch of their
        # own; absence of a patch is not absence of a branch.
        releases = by_id(parsed()[0])
        for branch in ("1.24", "1.22"):
            self.assertEqual(releases[branch]["upstream"]["patches"], [])
            self.assertEqual(releases[branch]["milestones"],
                             dict.fromkeys(("ga", "eos", "eossec", "eol")))

    def test_the_current_rows_and_the_pointers_are_both_accounted_for(self):
        payload = json.loads(CURRENT)
        self.assertEqual(len(payload), CURRENT_ROWS)
        branch_rows = [key for key in payload if re.fullmatch(r"\d+\.\d+", key)]
        self.assertEqual(len(branch_rows), CURRENT_BRANCHES)
        releases, accounting = parsed()
        current = accounting["current"]
        self.assertEqual(current["seen"], CURRENT_ROWS)
        self.assertEqual(current["used"], CURRENT_BRANCHES)
        self.assertEqual(current["excluded"], CURRENT_ROWS - CURRENT_BRANCHES)
        self.assertEqual(current["seen"], current["used"] + current["excluded"])
        self.assertEqual(sorted(entry["row"] for entry in accounting["current_excluded"]),
                         ["active", "latest"])
        # The seven maintained branches are the ones the feed dates, and only
        # those seven carry a current release row.
        carried = {release["id"] for release in releases if "current" in release["upstream"]}
        self.assertEqual(carried, set(branch_rows))
        self.assertEqual(accounting["feed"]["seen"], FEED_ROWS)
        self.assertEqual(accounting["feed"]["used"], FEED_ROWS)

    def test_branches_are_ordered_newest_first(self):
        releases = parsed()[0]
        keys = [tuple(int(part) for part in release["id"].split(".")) for release in releases]
        self.assertEqual(keys, sorted(keys, reverse=True))
        self.assertEqual(releases[0]["id"], "1.152")
        self.assertEqual(releases[-1]["id"], "1.22")


class LifecyclePreservationTests(unittest.TestCase):
    def test_the_quarter_cells_are_kept_as_the_project_states_them(self):
        payload = {row["version"]: row for row in json.loads(OVERVIEW)["versions"]}
        releases = by_id(parsed()[0])
        for row in payload.values():
            if row["version"] == "*":
                continue
            branch = row["version"][:-2]
            if branch not in releases:
                continue
            cells = releases[branch]["upstream"]["cells"]
            for key in ("eom", "eomm", "eocp"):
                if key in row:
                    self.assertEqual(cells[key], row[key], f"{branch} {key}")
        # The rows whose cells state the project's own long-term extension, and
        # the two whose eom and eomm differ.
        self.assertEqual(releases["1.148"]["upstream"]["cells"]["eom"],
                         "Long-term Maintenance, Q3/2027")
        self.assertEqual(releases["1.120"]["upstream"]["cells"],
                         {"version": "1.120.*", "support": "Maintenance", "lts": True,
                          "eom": "Long-term Maintenance, Q4/2030",
                          "eomm": "Long-term Maintenance, Q4/2026",
                          "eocp": "Q4/2031"})
        self.assertEqual(releases["1.38"]["upstream"]["cells"]["eom"],
                         "Long-Term Maintenance, Q4/2027")

    def test_the_patch_metadata_is_kept_verbatim_including_the_odd_rows(self):
        payload = json.loads(OVERVIEW)["patches"]
        stored = [row for release in parsed()[0] for row in release["upstream"]["patches"]]
        source = {row["version"]: row for row in payload}
        for row in stored:
            self.assertEqual(row, source[row["version"]])
        # The four shapes the array carries beyond the plain row: removed,
        # hidden, extended_eocp and the legacy-free builds. Each is retained
        # exactly as the source states it.
        special = {row["version"]: row for row in stored}
        source_special = {row["version"]: row for row in payload}
        self.assertEqual(special["1.48.6"], source_special["1.48.6"])
        self.assertEqual(special["1.48.6"]["extended_eocp"], "Q4/2022")
        self.assertTrue(special["1.120.5"]["hidden"])
        self.assertTrue(special["1.121.0"]["removed"])
        self.assertEqual(special["1.142.0-legacy-free"]["eocp"], "Q4/2026")
        self.assertEqual(special["1.142.10"]["eocp"], "To Be Determined")
        self.assertEqual(sum(1 for row in stored if row["eocp"] == "To Be Determined"), 13)
        self.assertEqual(sum(1 for row in stored if row.get("removed")), 899)
        self.assertEqual(sum(1 for row in stored if row.get("hidden")), 3)
        self.assertEqual(sum(1 for row in stored if "legacy-free" in row["version"]), 4)

    def test_the_current_release_rows_are_kept_with_the_feed_date_they_state(self):
        releases = by_id(parsed()[0])
        self.assertEqual(releases["1.148"]["upstream"]["current"]["version"],
                         {"version": "1.148.9", "support": "Maintenance", "lts": True})
        self.assertEqual(releases["1.148"]["upstream"]["current"]["release"]["release_date"],
                         "23.09.2026")
        # The feed and the current row are two separate documents and both are
        # stored under the branch, each with the table it came from.
        self.assertEqual(releases["1.148"]["upstream"]["current"]["table"],
                         openui5.CURRENT_TABLE)
        self.assertEqual(releases["1.148"]["upstream"]["patches"][0]["version"], "1.148.9")

    def test_the_two_sources_disagreeing_for_one_branch_keeps_both_cells(self):
        # The release feed states an empty eom for 1.142 while the branch row
        # states Q3/2026. Neither is reconciled away: the branch lifecycle is
        # read from the overview and the feed's own cell is stored beside it.
        release = by_id(parsed()[0])[DIVERGENT_BRANCH]
        self.assertEqual(release["upstream"]["cells"]["eom"], "Q3/2026")
        self.assertEqual(release["upstream"]["current"]["release"]["eom"], "")
        self.assertEqual(release["upstream"]["current"]["release"]["version"], "1.142.10")


class NoMisMappingTests(unittest.TestCase):
    def test_no_branch_publishes_an_end_milestone(self):
        # The project's eom is the end of bug-fix maintenance, and the policy
        # says security fixes continue for a year past it; eocp is removal from
        # the CDN. None of the three is eos, eossec or eol, so every branch's
        # three end milestones stay null.
        for release in parsed()[0]:
            self.assertEqual(release["milestones"]["eos"], None, release["id"])
            self.assertEqual(release["milestones"]["eossec"], None, release["id"])
            self.assertEqual(release["milestones"]["eol"], None, release["id"])

    def test_a_quarter_never_appears_in_a_normalized_milestone(self):
        quarter = re.compile(r"Q[1-4]/\d{4}")
        cells_with_quarters = 0
        for release in parsed()[0]:
            for key, value in release["milestones"].items():
                if value:
                    self.assertIsNone(quarter.search(value), f"{release['id']} {key} {value}")
            # A quarter in the vendor cells is the evidence the withholding is
            # about: the record retains 30 eom quarters and publishes none.
            cells = release["upstream"]["cells"]
            cells_with_quarters += 1 if quarter.search(cells["eom"]) else 0
        self.assertEqual(cells_with_quarters, 30)

    def test_the_only_label_mapped_is_the_stated_release_date(self):
        self.assertEqual(record()["labels"], {"ga": openui5.GA_LABEL})
        # The eom/eomm/eocp cell names appear in no label and no milestone key.
        labels = json.dumps(record()["labels"])
        for cell in ("eom", "eomm", "eocp"):
            self.assertNotIn(cell, labels)

    def test_eol_stays_null_even_where_the_project_states_a_long_extension(self):
        # 1.71 and 1.108 run to Q4/2030, which the policy's nominal LTS duration
        # would contradict. The stated quarter is retained and no derived EOL is
        # published from either the duration or the quarter: the record carries
        # no milestone_provenance at all, because it derives nothing.
        releases = by_id(parsed()[0])
        for branch in ("1.71", "1.108"):
            self.assertEqual(releases[branch]["milestones"]["eol"], None)
            self.assertIn("Q4/2030", releases[branch]["upstream"]["cells"]["eom"])
            self.assertNotIn("milestone_provenance", releases[branch])
        self.assertEqual([release for release in parsed()[0]
                          if "milestone_provenance" in release], [])

    def test_no_patch_row_becomes_a_release(self):
        releases = parsed()[0]
        for release in releases:
            self.assertNotRegex(release["id"], r"\d+\.\d+\.\d+")
        # Every patch version, including the four legacy-free builds, is
        # retained and none is published as a release of its own.
        branch_versions = {release["id"] for release in releases}
        patch_versions = {row["version"] for release in releases
                          for row in release["upstream"]["patches"]}
        self.assertEqual(len(patch_versions), PATCH_ROWS)
        self.assertFalse(branch_versions & patch_versions)


class GeneralAvailabilityTests(unittest.TestCase):
    def test_ga_is_published_only_where_the_feed_dates_the_branchs_own_release(self):
        payload = json.loads(OVERVIEW)
        feed = json.loads(FEED)
        dot_zero = [row["version"] for row in feed if row["version"].endswith(".0")]
        self.assertEqual(len(dot_zero), GA_BRANCHES)
        releases = parsed()[0]
        dated = {release["id"]: release["milestones"]["ga"] for release in releases
                 if release["milestones"]["ga"]}
        self.assertEqual(len(dated), GA_BRANCHES)
        self.assertEqual(dated, {"1.152": "2026-08-31", "1.150": "2026-07-07"})
        for branch, version in (("1.152", "1.152.0"), ("1.150", "1.150.0")):
            row = next(row for row in feed if row["version"] == version)
            self.assertEqual(dated[branch], openui5.feed_day(row["release_date"], "test"))

    def test_a_branchs_patch_release_date_is_never_promoted_to_ga(self):
        # The feed dates the latest patch, not the branch: 1.148's row dates
        # 1.148.9, so the branch keeps a null ga and the row is retained.
        release = by_id(parsed()[0])["1.148"]
        self.assertIsNone(release["milestones"]["ga"])
        self.assertEqual(release["upstream"]["current"]["release"]["version"], "1.148.9")
        self.assertEqual(release["upstream"]["current"]["release"]["release_date"], "23.09.2026")
        self.assertNotIn("2026-09-23", json.dumps(release["milestones"]))

    def test_a_branch_with_no_current_row_states_no_ga(self):
        release = by_id(parsed()[0])["1.120"]
        self.assertIsNone(release["milestones"]["ga"])
        self.assertIn("current", release["upstream"])
        self.assertEqual(release["upstream"]["current"]["release"]["version"], "1.120.50")

    def test_the_mini_documents_date_the_one_dot_zero_branch(self):
        releases = by_id(parsed(MINI_OVERVIEW, MINI_CURRENT, MINI_FEED)[0])
        self.assertEqual(releases["1.2"]["milestones"]["ga"], "2026-07-05")
        self.assertEqual(releases["1.1"]["milestones"]["ga"], None)
        self.assertEqual(releases["1.1"]["upstream"]["cells"]["eom"], "Q3/2026")


class PolicyTests(unittest.TestCase):
    def test_the_policy_sentences_are_required_verbatim(self):
        rules = openui5.policy_rules(POLICY)["rules"]
        page = openui5._folded(POLICY)
        for key, quote in openui5.QUOTES.items():
            self.assertEqual(rules[key], quote)
            self.assertIn(openui5._folded(quote), page)
        # The EOM sentence is the reason eom fills no milestone, and it names
        # what happens after it, which is what the withholding rests on.
        self.assertIn("end of maintenance", rules["eom"])
        self.assertIn("only critical security patches are offered for a year", rules["eol_rule"])

    def test_the_support_period_table_is_read_row_by_row(self):
        periods = openui5.policy_rules(POLICY)["periods"]
        self.assertEqual(len(periods), 3)
        self.assertEqual([row["support_period"] for row in periods],
                         ["6 weeks", "9 months", "15 months"])
        self.assertEqual(openui5._folded(periods[1]["release_type"]), "Mid-Term Support (MTS)")

    def test_a_reworded_policy_refuses_the_parse(self):
        text = POLICY.replace("until the version’s end of life \\(EOL\\) date",
                              "until the version reaches its sunset")
        with self.assertRaisesRegex(ValueError, "no longer states the 'security' sentence"):
            openui5.policy_rules(text)

    def test_a_renamed_support_type_refuses_the_parse(self):
        text = POLICY.replace("Mid-Term Support \\(MTS\\)", "Mid-Term Release")
        with self.assertRaisesRegex(ValueError, re.escape(
                "no longer states 'Mid-Term Support (MTS)'")):
            openui5.policy_rules(text)

    def test_a_missing_table_refuses_the_parse(self):
        with self.assertRaises(ValueError):
            openui5.policy_rules("# Versioning and Maintenance of OpenUI5\n\nNo tables here.\n")


class ReleasePageTests(unittest.TestCase):
    def test_the_page_declares_the_column_the_record_labels_ga_with(self):
        page = openui5.release_columns(PAGE)
        self.assertEqual(page["columns"], list(openui5.RELEASE_COLUMNS))
        self.assertEqual(page["columns"][-1], openui5.GA_LABEL)
        # The body renders from the feed, so the page's own data rows are not
        # read; the header is what licenses the label.
        self.assertEqual(page["rows"], 1)

    def test_a_renamed_release_date_column_refuses_the_parse(self):
        html = PAGE.replace(">Release Date<", ">Published<")
        with self.assertRaisesRegex(ValueError, "missing or duplicate release table"):
            openui5.release_columns(html)

    def test_a_page_without_the_release_table_refuses_the_parse(self):
        with self.assertRaisesRegex(ValueError, "missing or duplicate release table"):
            openui5.release_columns("<html><body><p>Changed layout</p></body></html>")


class ReshapeRefusalTests(unittest.TestCase):
    def test_a_duplicate_branch_row_refuses_the_parse(self):
        payload = json.loads(OVERVIEW)
        payload["versions"].append(dict(payload["versions"][0]))
        with self.assertRaisesRegex(ValueError, "stated twice"):
            openui5.parse_version_overview(json.dumps(payload))

    def test_a_duplicate_patch_row_refuses_the_parse(self):
        payload = json.loads(OVERVIEW)
        payload["patches"].append(dict(payload["patches"][0]))
        with self.assertRaisesRegex(ValueError, "stated twice"):
            openui5.parse_version_overview(json.dumps(payload))

    def test_a_renamed_or_added_row_field_refuses_the_parse(self):
        payload = json.loads(OVERVIEW)
        payload["versions"][0]["eolm"] = "Q1/2030"
        with self.assertRaisesRegex(ValueError, "unrecognized source fields"):
            openui5.parse_version_overview(json.dumps(payload))

    def test_a_missing_patch_field_refuses_the_parse(self):
        payload = json.loads(OVERVIEW)
        del payload["patches"][0]["eocp"]
        with self.assertRaisesRegex(ValueError, "missing"):
            openui5.parse_version_overview(json.dumps(payload))

    def test_a_quarter_converted_to_a_month_or_day_refuses_the_parse(self):
        for value in ("2026-09", "2026-09-30"):
            payload = json.loads(OVERVIEW)
            row = next(row for row in payload["versions"] if row["version"] == "1.142.*")
            row["eom"] = value
            with self.assertRaisesRegex(ValueError, "unrecognized lifecycle cell"):
                openui5.parse_version_overview(json.dumps(payload))

    def test_an_unrecognized_support_status_refuses_the_parse(self):
        payload = json.loads(OVERVIEW)
        payload["versions"][0]["support"] = "Extended"
        with self.assertRaisesRegex(ValueError, "unrecognized maintenance status"):
            openui5.parse_version_overview(json.dumps(payload))

    def test_a_patch_naming_an_unstated_branch_refuses_the_parse(self):
        payload = json.loads(OVERVIEW)
        payload["patches"].append({"version": "9.9.9", "eocp": "Q1/2030"})
        with self.assertRaisesRegex(ValueError, "does not state"):
            openui5.parse_version_overview(json.dumps(payload))

    def test_a_current_row_contradicting_the_overview_refuses_the_parse(self):
        branches, _, _ = openui5.parse_version_overview(OVERVIEW)
        payload = json.loads(CURRENT)
        payload["1.148"]["lts"] = False
        with self.assertRaisesRegex(ValueError, "contradicts the version overview"):
            openui5.parse_current(json.dumps(payload), branches)

    def test_a_current_row_naming_an_unstated_branch_refuses_the_parse(self):
        branches, _, _ = openui5.parse_version_overview(OVERVIEW)
        payload = json.loads(CURRENT)
        payload["1.999"] = {"version": "1.999.1", "support": "Maintenance", "lts": False}
        with self.assertRaisesRegex(ValueError, "which the version overview does not publish"):
            openui5.parse_current(json.dumps(payload), branches)

    def test_a_stale_latest_patch_refuses_the_parse(self):
        payload = json.loads(CURRENT)
        payload["1.148"]["version"] = "1.148.8"
        with self.assertRaisesRegex(ValueError, "newest patch is"):
            parsed(current=json.dumps(payload))

    def test_a_feed_row_disagreeing_with_the_current_row_refuses_the_parse(self):
        payload = json.loads(FEED)
        payload[3]["version"] = "1.148.8"
        with self.assertRaisesRegex(ValueError, "but https://sdk.openui5.org/version.json states"):
            parsed(feed=json.dumps(payload))

    def test_a_feed_row_for_an_unmaintained_branch_refuses_the_parse(self):
        # 1.99 is a real branch the overview states, but version.json does not
        # list it as maintained, so the feed cannot date a release in it.
        payload = json.loads(FEED)
        payload.append({**payload[0], "version": "1.99.0"})
        with self.assertRaisesRegex(ValueError, "does not list as maintained"):
            parsed(feed=json.dumps(payload))

    def test_a_duplicate_feed_branch_refuses_the_parse(self):
        payload = json.loads(FEED)
        payload.append(dict(payload[0]))
        with self.assertRaisesRegex(ValueError, "stated twice"):
            openui5.parse_feed(json.dumps(payload))

    def test_an_impossible_feed_day_refuses_the_parse(self):
        payload = json.loads(FEED)
        payload[0]["release_date"] = "31.02.2026"
        with self.assertRaisesRegex(ValueError, "not a real calendar day"):
            openui5.parse_feed(json.dumps(payload))
        payload[0]["release_date"] = "2026-08-31"
        with self.assertRaisesRegex(ValueError, "unrecognized release date"):
            openui5.parse_feed(json.dumps(payload))

    def test_a_non_json_body_refuses_the_parse(self):
        with self.assertRaisesRegex(ValueError, "not JSON"):
            openui5.parse_version_overview("<html>Changed layout</html>")


class ReDerivationTests(unittest.TestCase):
    def test_the_fetched_record_re_derives_offline(self):
        openui5.validate_record(record())

    def test_a_tampered_ga_is_refused(self):
        rec = record()
        rec["releases"][0]["milestones"]["ga"] = "2000-01-01"
        with self.assertRaisesRegex(ValueError, "contradicts the release date"):
            openui5.validate_record(rec)

    def test_a_ga_planted_where_no_current_row_dates_the_branch_is_refused(self):
        rec = record()
        target = next(release for release in rec["releases"]
                      if release["id"] == "1.148")
        target["milestones"]["ga"] = "2026-05-12"
        with self.assertRaisesRegex(ValueError, "contradicts the release date"):
            openui5.validate_record(rec)

    def test_a_ga_on_a_branch_with_no_current_row_is_refused(self):
        rec = record()
        target = next(release for release in rec["releases"] if release["id"] == "1.120")
        del target["upstream"]["current"]
        target["milestones"]["ga"] = "2023-10-31"
        with self.assertRaisesRegex(ValueError, "no current release row"):
            openui5.validate_record(rec)

    def test_a_published_end_milestone_is_refused(self):
        # The whole point of the record: a quarter in the vendor's cell is not a
        # deadline, so a stored eol that no cell states can never be published.
        for key, value in (("eol", "2030-12-31"), ("eossec", "2030-12-31"),
                           ("eos", "2030-12-31")):
            rec = record()
            target = next(release for release in rec["releases"] if release["id"] == "1.71")
            target["milestones"][key] = value
            with self.assertRaisesRegex(ValueError, "publishes an end milestone"):
                openui5.validate_record(rec)

    def test_tampered_source_cells_are_refused(self):
        rec = record()
        target = next(release for release in rec["releases"] if release["id"] == "1.148")
        target["upstream"]["cells"]["version"] = "1.147.*"
        with self.assertRaisesRegex(ValueError, "name a different branch"):
            openui5.validate_record(rec)

    def test_a_cell_mutated_into_a_month_is_refused(self):
        rec = record()
        target = next(release for release in rec["releases"] if release["id"] == "1.148")
        target["upstream"]["cells"]["eom"] = "2027-09"
        with self.assertRaisesRegex(ValueError, "unrecognized lifecycle cell"):
            openui5.validate_record(rec)

    def test_a_patch_moved_to_another_branch_is_refused(self):
        rec = record()
        target = next(release for release in rec["releases"] if release["id"] == "1.148")
        target["upstream"]["patches"][0]["version"] = "1.147.9"
        with self.assertRaisesRegex(ValueError, "belongs to another branch"):
            openui5.validate_record(rec)

    def test_a_patch_stored_under_two_branches_is_refused(self):
        # A patch row is kept once, under the branch its own version names. The
        # record's branch identity is the prefix, so two branches cannot both
        # store one patch version: the second copy would double-count source
        # rows the project published once.
        rec = record()
        for release in rec["releases"]:
            row = next((row for row in release["upstream"]["patches"]
                        if row["version"] == "1.148.0"), None)
            if row is not None:
                release["upstream"]["patches"].append(dict(row))
                break
        with self.assertRaisesRegex(ValueError, "stored twice"):
            openui5.validate_record(rec)

    def test_a_current_row_contradicting_its_branch_is_refused(self):
        rec = record()
        target = next(release for release in rec["releases"] if release["id"] == "1.148")
        target["upstream"]["current"]["version"]["lts"] = False
        with self.assertRaisesRegex(ValueError, "current row contradicts"):
            openui5.validate_record(rec)

    def test_a_current_row_that_is_not_the_newest_patch_is_refused(self):
        rec = record()
        target = next(release for release in rec["releases"] if release["id"] == "1.148")
        current = target["upstream"]["current"]
        current["version"]["version"] = current["release"]["version"] = "1.148.8"
        with self.assertRaisesRegex(ValueError, "not the branch's newest patch"):
            openui5.validate_record(rec)

    def test_a_foreign_verifier_is_refused(self):
        rec = record()
        rec["provenance"]["verifier"] = "deterministic-something-else"
        with self.assertRaisesRegex(ValueError, "source identity"):
            openui5.validate_record(rec)

    def test_a_record_ordered_against_the_branch_numbers_is_refused(self):
        rec = record()
        rec["releases"][0], rec["releases"][1] = rec["releases"][1], rec["releases"][0]
        with self.assertRaisesRegex(ValueError, "not ordered newest branch first"):
            openui5.validate_record(rec)

    def test_a_branch_published_twice_is_refused(self):
        rec = record()
        rec["releases"].append(copy.deepcopy(rec["releases"][2]))
        with self.assertRaisesRegex(ValueError, "published twice"):
            openui5.validate_record(rec)

    def test_the_registry_validator_is_the_one_validation_calls(self):
        source = sources.source("import-openui5")
        self.assertEqual(source.verifier, openui5.VERIFIER)
        self.assertEqual(sources.record_validator(source), openui5.validate_record)


class AccountingTests(unittest.TestCase):
    def test_every_source_row_is_accounted_for(self):
        report = reported()
        rows = report["rows"]
        self.assertEqual(rows["branches"]["seen"], VERSION_ROWS)
        self.assertEqual(rows["patches"]["seen"], PATCH_ROWS)
        self.assertEqual(rows["current"]["seen"], CURRENT_ROWS)
        self.assertEqual(rows["feed"]["seen"], FEED_ROWS)
        self.assertEqual(rows["retained"], 0)
        self.assertEqual(report["total_records"], 1)
        self.assertEqual(report["verifier"], openui5.VERIFIER)

    def test_the_report_states_the_milestones_it_publishes_and_the_ones_it_holds_back(self):
        published = reported()["milestones_published"]
        self.assertEqual(published, {"ga": GA_BRANCHES, "eos": 0, "eossec": 0, "eol": 0})

    def test_the_report_names_the_three_vendor_end_cells_and_the_quarter_precision(self):
        limitations = " ".join(reported()["limitations"])
        self.assertIn("No end milestone is published", limitations)
        self.assertIn("eom, eomm and eocp", limitations)
        self.assertIn("Quarter precision is not normalized", limitations)
        self.assertIn("1038 patch rows", limitations)
        self.assertIn(DIVERGENT_BRANCH, limitations)
        scope = reported()["record_scope"]
        self.assertIn("no normalized end milestone", scope)

    def test_every_policy_row_is_accounted_for(self):
        policy = reported()["policy"]
        self.assertEqual(policy["rows"]["seen"], 3)
        self.assertEqual(policy["rows"]["dated"], 0)
        self.assertEqual(policy["rows"]["seen"], len(policy["rows"]["not_dated"]))
        for entry in policy["rows"]["not_dated"]:
            self.assertIn(entry["row"], POLICY)
            self.assertTrue(entry["reason"])
        self.assertEqual([rule["key"] for rule in policy["rules"]],
                         ["security", "eom", "eol_rule", "eocp"])
        for rule in policy["rules"]:
            self.assertIn(openui5._folded(rule["quote"]), openui5._folded(POLICY))

    def test_a_retained_branch_is_reported_separately(self):
        committed = record()
        fresh, _ = parsed(MINI_OVERVIEW, MINI_CURRENT, MINI_FEED)
        releases, kept = openui5.combine_releases(fresh, committed)
        self.assertEqual({release["id"] for release in releases},
                         {release["id"] for release in committed["releases"]} |
                         {release["id"] for release in fresh})
        dropped = {release["id"] for release in committed["releases"]} - {
            release["id"] for release in fresh}
        self.assertEqual(len(dropped), PUBLISHED_BRANCHES)
        self.assertEqual(sorted(entry["id"] for entry in kept), sorted(dropped))
        retained_rows = [release for release in releases if release["id"] in dropped]
        self.assertTrue(all(release["upstream"]["in_source"] is False
                            for release in retained_rows))
        self.assertEqual(reported(kept=kept)["rows"]["retained"], len(kept))
        # A retained branch is republished from its own rows, so retention can
        # never introduce a date the project did not publish.
        merged = by_id(releases)
        self.assertEqual(merged["1.148"]["upstream"]["cells"]["eom"],
                         "Long-term Maintenance, Q3/2027")
        # The union is re-sorted on the branch numbers the project uses, so the
        # mini branches land below 1.22 rather than after the retained history.
        self.assertEqual([release["id"] for release in releases][-2:], ["1.2", "1.1"])
        self.assertEqual([release["id"] for release in releases][0], "1.152")
        openui5.validate_record(openui5.record_for(releases, CHECKED))

    def test_a_retained_branch_still_refuses_a_planted_end_milestone(self):
        committed = record()
        releases, _ = openui5.combine_releases([], committed)
        releases[0]["milestones"]["eol"] = "2030-12-31"
        with self.assertRaisesRegex(ValueError, "publishes an end milestone"):
            openui5.validate_record(openui5.record_for(releases, CHECKED))


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

    def refresh(self, checked, overview=OVERVIEW, current=CURRENT, feed=FEED, policy=POLICY,
                page=PAGE):
        with mock.patch.object(openui5.net, "get_text",
                               side_effect=[policy, page, overview, current, feed]), \
                mock.patch.object(openui5, "_now", return_value=checked):
            return openui5.import_openui5(self.root)

    def test_a_quiet_refresh_republishes_byte_identical_files(self):
        summary = self.refresh("2026-09-23T01:00:00Z")
        published = self.snapshot()
        self.assertIn("products/openui5.json", published)
        self.assertIn(openui5.REPORT, published)
        self.assertIn("110 OpenUI5 branches", summary)
        self.assertIn("2 with a stated general availability", summary)
        self.refresh("2026-09-23T02:00:00Z")
        self.assertEqual(self.snapshot(), published)
        record_published = json.loads(published["products/openui5.json"])
        self.assertEqual(record_published["provenance"]["last_checked"], "2026-09-23T01:00:00Z")
        self.assertEqual(len(record_published["releases"]), PUBLISHED_BRANCHES)
        self.assertEqual(json.loads(published[openui5.REPORT])["checked_at"],
                         "2026-09-23T01:00:00Z")

    def test_a_changed_branch_cell_advances_the_record_and_keeps_the_report_revision(self):
        # A revision marks a content revision, not a fetch attempt. A moved
        # vendor quarter changes the record, so the record advances; the
        # sidecar's own accounting is unchanged, so its revision stands.
        self.refresh("2026-09-23T01:00:00Z")
        before = self.snapshot()
        payload = json.loads(OVERVIEW)
        row = next(row for row in payload["versions"] if row["version"] == "1.148.*")
        row["eom"] = "Long-term Maintenance, Q4/2027"
        self.refresh("2026-09-23T03:00:00Z", overview=json.dumps(payload))
        after = self.snapshot()
        self.assertNotEqual(after["products/openui5.json"], before["products/openui5.json"])
        releases = by_id(json.loads(after["products/openui5.json"])["releases"])
        self.assertEqual(releases["1.148"]["upstream"]["cells"]["eom"],
                         "Long-term Maintenance, Q4/2027")
        self.assertIsNone(releases["1.148"]["milestones"]["eol"])
        self.assertEqual(json.loads(after["products/openui5.json"])["provenance"]["last_checked"],
                         "2026-09-23T03:00:00Z")
        self.assertEqual(after[openui5.REPORT], before[openui5.REPORT])

    def test_a_new_skipped_row_advances_the_report_and_keeps_the_record(self):
        # A row the project marks Skipped publishes no branch, so it changes
        # only the accounting: the sidecar's revision advances and the record is
        # republished byte-identically.
        self.refresh("2026-09-23T01:00:00Z")
        before = self.snapshot()
        payload = json.loads(OVERVIEW)
        payload["versions"].append({"version": "1.999.*", "support": "Skipped", "lts": False,
                                    "eom": "", "eomm": ""})
        self.refresh("2026-09-23T02:00:00Z", overview=json.dumps(payload))
        after = self.snapshot()
        self.assertEqual(after["products/openui5.json"], before["products/openui5.json"])
        report = json.loads(after[openui5.REPORT])
        self.assertEqual(report["checked_at"], "2026-09-23T02:00:00Z")
        self.assertEqual(report["rows"]["branches"]["seen"], VERSION_ROWS + 1)
        self.assertEqual(report["rows"]["branches"]["excluded"],
                         WILDCARD_ROWS + SKIPPED_BRANCHES + 1)

    def test_a_new_patch_row_advances_the_record_and_is_retained(self):
        self.refresh("2026-09-23T01:00:00Z")
        before = self.snapshot()
        payload = json.loads(OVERVIEW)
        payload["patches"].append({"version": "1.148.10", "eocp": "To Be Determined"})
        current = json.loads(CURRENT)
        current["1.148"]["version"] = "1.148.10"
        feed = json.loads(FEED)
        next(row for row in feed if row["version"] == "1.148.9")["version"] = "1.148.10"
        self.refresh("2026-09-23T02:00:00Z", overview=json.dumps(payload),
                     current=json.dumps(current), feed=json.dumps(feed))
        after = self.snapshot()
        self.assertNotEqual(after["products/openui5.json"], before["products/openui5.json"])
        # Still no end milestone, and still no promoted GA for a patch release.
        releases = by_id(json.loads(after["products/openui5.json"])["releases"])
        self.assertEqual(releases["1.148"]["milestones"],
                         dict.fromkeys(("ga", "eos", "eossec", "eol")))
        self.assertEqual(releases["1.148"]["upstream"]["current"]["release"]["version"], "1.148.10")
        report = json.loads(after[openui5.REPORT])
        self.assertEqual(report["checked_at"], "2026-09-23T02:00:00Z")
        self.assertEqual(report["rows"]["patches"]["published"], PATCH_ROWS + 1)

    def test_a_foreign_record_refuses_the_import_before_network_and_writes_nothing(self):
        foreign = json.loads((self.root / "products/sample.json").read_text())
        foreign["id"] = "openui5"
        dump(self.root / "products/openui5.json", foreign)
        before = self.snapshot()
        with mock.patch.object(openui5.net, "get_text") as fetch:
            with self.assertRaisesRegex(ValueError, "ownership collision"):
                openui5.import_openui5(self.root)
        fetch.assert_not_called()
        self.assertEqual(self.snapshot(), before)

    def test_a_reworded_policy_refuses_the_import_and_leaves_the_catalog_untouched(self):
        self.refresh("2026-09-23T01:00:00Z")
        before = self.snapshot()
        with self.assertRaisesRegex(ValueError, "no longer states"):
            self.refresh("2026-09-23T02:00:00Z", policy=POLICY.replace(
                "After the EOM date, only critical security patches are offered for a year",
                "After the EOM date, security patches stop."))
        self.assertEqual(self.snapshot(), before)

    def test_a_reshaped_document_leaves_existing_files_untouched(self):
        self.refresh("2026-09-23T01:00:00Z")
        before = self.snapshot()
        with self.assertRaises(ValueError):
            self.refresh("2026-09-23T02:00:00Z", overview="<html>Changed layout</html>")
        self.assertEqual(self.snapshot(), before)

    def test_the_committed_record_is_re_derived_before_it_is_replaced(self):
        self.refresh("2026-09-23T01:00:00Z")
        tampered = json.loads((self.root / "products/openui5.json").read_text())
        target = next(release for release in tampered["releases"] if release["id"] == "1.148")
        target["milestones"]["eol"] = "2030-12-31"
        dump(self.root / "products/openui5.json", tampered)
        before = self.snapshot()
        with self.assertRaisesRegex(ValueError, "publishes an end milestone"):
            self.refresh("2026-09-23T02:00:00Z")
        self.assertEqual(self.snapshot(), before)

    def test_a_renamed_release_page_column_refuses_the_import(self):
        self.refresh("2026-09-23T01:00:00Z")
        before = self.snapshot()
        with self.assertRaisesRegex(ValueError, "missing or duplicate release table"):
            self.refresh("2026-09-23T02:00:00Z", page=PAGE.replace(">Release Date<", ">Published<"))
        self.assertEqual(self.snapshot(), before)

    def test_the_published_catalog_validates_through_the_shared_gate(self):
        self.refresh("2026-09-23T01:00:00Z")
        records = validation.validate_data(self.root)
        self.assertEqual([record["id"] for record in records], ["openui5", "sample"])
        published = json.loads((self.root / "products/openui5.json").read_text())
        self.assertEqual(published["provenance"]["verifier"],
                         sources.source("import-openui5").verifier)


if __name__ == "__main__":
    unittest.main()
