"""Vite's rolling support rule produces nine dated release-trigger EOLs.

`contributions/vite.json` keeps Vite's explicit supported-version policy and
pairs every retired 5.x/6.x line with the dated release that moves it beyond
Vite's supported ranges. Vite 6.4 is still in the researched policy snapshot,
so its terminal support date remains unknown rather than being extrapolated.
"""
import json
import unittest
from pathlib import Path

from engine import derived
from engine.contribute import build_record, parse_contribution, research_object, validate_research

CONTRIBUTION = Path(__file__).resolve().parents[1] / "contributions" / "vite.json"
CHECKED = "2026-09-23T00:00:00Z"
POLICY = (
    "The supported version ranges are automatically determined by: Current Minor gets regular fixes. "
    "Previous Major (only for its latest minor) and Previous Minor receives important fixes and "
    "security patches. Second-to-last Major (only for its latest minor) and Second-to-last Minor "
    "receives security patches. All versions before these are no longer supported."
)
# release line: (GA, derived EOL, trigger line, trigger GA)
EXPECTED = {
    "5.0": ("2023-11-16", "2024-06-13", "5.3", "2024-06-13"),
    "5.1": ("2024-02-08", "2024-08-07", "5.4", "2024-08-07"),
    "5.2": ("2024-03-20", "2024-11-26", "6.0", "2024-11-26"),
    "5.3": ("2024-06-13", "2025-06-24", "7.0", "2025-06-24"),
    "5.4": ("2024-08-07", "2026-03-12", "8.0", "2026-03-12"),
    "6.0": ("2024-11-26", "2025-02-25", "6.2", "2025-02-25"),
    "6.1": ("2025-02-05", "2025-04-16", "6.3", "2025-04-16"),
    "6.2": ("2025-02-25", "2025-06-24", "7.0", "2025-06-24"),
    "6.3": ("2025-04-16", "2026-03-12", "8.0", "2026-03-12"),
}


def contribution():
    return json.loads(CONTRIBUTION.read_text(encoding="utf-8"))


def build_record_from_contribution():
    payload = contribution()
    parsed = parse_contribution(payload, path=str(CONTRIBUTION))
    research = research_object(parsed, parsed["evidence"], None)
    return build_record(parsed, research, CHECKED)


def lines(record):
    return {release["id"]: release for release in record["releases"]}


class ViteContributionTests(unittest.TestCase):
    def setUp(self):
        self.payload = contribution()
        self.record = build_record_from_contribution()
        self.lines = lines(self.record)

    def test_researched_record_identity_is_pinned(self):
        self.assertEqual(self.payload["target"], "software")
        self.assertEqual(self.payload["id"], "researched-vite")
        self.assertEqual(self.payload["name"], "Vite")
        self.assertEqual(self.payload["vendor"], "Vite")
        self.assertEqual(self.payload["category"], "framework")
        self.assertEqual(self.payload["contributor"], "eoltracker-agent")
        self.assertEqual(self.payload["method"], "agent")
        self.assertEqual(self.payload["stale_after"], "2027-09-23")
        self.assertEqual(self.payload["release"], "6.4")

    def test_every_line_has_its_official_release_date(self):
        release_evidence = {
            item["source_url"]: item["quote"] for item in self.payload["evidence"]
            if "/releases/tags/" in item["source_url"]
        }
        for release_id, (ga, _eol, _trigger, _trigger_ga) in EXPECTED.items():
            with self.subTest(release=release_id):
                line = self.lines[release_id]
                self.assertEqual(line["milestones"]["ga"], ga)
                url = f"https://api.github.com/repos/vitejs/vite/releases/tags/v{release_id}.0"
                self.assertTrue(release_evidence[url].startswith(f'"published_at":"{ga}T'))

        for release_id, ga in (("7.0", "2025-06-24"), ("8.0", "2026-03-12")):
            with self.subTest(trigger=release_id):
                self.assertEqual(self.lines[release_id]["milestones"]["ga"], ga)

    def test_every_derived_eol_recomputes_from_its_named_release(self):
        release_ids = set(self.lines)
        for release_id, (ga, eol, trigger_id, trigger_ga) in EXPECTED.items():
            with self.subTest(release=release_id):
                line = self.lines[release_id]
                self.assertEqual(line["milestones"]["eol"], eol)
                self.assertIsNone(line["milestones"]["eos"])
                self.assertIsNone(line["milestones"]["eossec"])
                self.assertEqual(set(line["milestone_provenance"]), {"eol"})
                entry = line["milestone_provenance"]["eol"]
                self.assertEqual(entry["kind"], "derived")
                self.assertEqual(entry["method"], "release-trigger")
                self.assertEqual(entry["source_url"], "https://vite.dev/releases")
                self.assertEqual(entry["quote"], POLICY)
                self.assertEqual(entry["base_date"], ga)
                self.assertEqual(entry["base_label"], f"Vite {release_id}.0 general availability")
                self.assertEqual(entry["trigger"], {
                    "release_id": trigger_id,
                    "date": trigger_ga,
                    "label": f"Vite {trigger_id}.0 release",
                })
                self.assertEqual(self.lines[trigger_id]["milestones"]["ga"], trigger_ga)
                self.assertEqual(
                    derived.derive(line["milestones"], line["milestone_provenance"], release_id, release_ids),
                    {"eol": eol},
                )

    def test_current_6_4_line_remains_undated(self):
        current = self.lines["6.4"]
        self.assertEqual(current["milestones"], {
            "ga": "2025-10-15", "eos": None, "eossec": None, "eol": None
        })
        self.assertNotIn("milestone_provenance", current)

    def test_policy_evidence_is_stored_verbatim(self):
        policy_entries = [item for item in self.payload["evidence"]
                           if item["source_url"] == "https://vite.dev/releases"]
        self.assertEqual(len(policy_entries), 1)
        self.assertEqual(policy_entries[0]["quote"], POLICY)
        self.assertEqual(policy_entries[0]["retrieved_at"], "2026-09-23")

    def test_a_trigger_date_that_does_not_recompute_is_refused(self):
        record = build_record_from_contribution()
        entry = lines(record)["5.0"]["milestone_provenance"]["eol"]
        entry["trigger"]["date"] = "2024-06-14"
        with self.assertRaisesRegex(ValueError, "is not the eol milestone"):
            validate_research(record, "software")

    def test_a_guessed_current_eol_is_refused_without_a_dated_rule(self):
        record = build_record_from_contribution()
        lines(record)["6.4"]["milestones"]["eol"] = "2027-09-23"
        with self.assertRaisesRegex(ValueError, "no stored quote states the end of life date"):
            validate_research(record, "software")


if __name__ == "__main__":
    unittest.main()
