"""PrestaShop's direct notice and release triggers produce five terminal dates."""
import json
import unittest
from pathlib import Path

from engine import derived
from engine.contribute import build_record, parse_contribution, research_object, validate_research

CONTRIBUTION = Path(__file__).resolve().parents[1] / "contributions" / "prestashop.json"
CHECKED = "2026-09-23T00:00:00Z"
DIRECT_EOL_QUOTE = "To recap, maintenance for PrestaShop 1.6 has ended on June 30, 2019"
EXPLICIT_17 = (
    "This maintenance period will end when PrestaShop 9.0.0 is released. "
    "When this day comes, PrestaShop 1.7 will not be maintained anymore."
)
EXPLICIT_80 = "Patches for branch 8.0.x will be delivered until PrestaShop 8.1.0 is released."
DEFAULT_81 = (
    "These branches are created and closed following the support window of each version. "
    "Once the support for a version is over and no new patch releases are expected for it, "
    "its corresponding branch becomes closed to contribution. Except for rare cases, a patch "
    "version branch is closed the moment the following minor version is released."
)
EXPLICIT_90 = "PrestaShop 9.0 , up until we release PrestaShop 9.1 ."


def contribution():
    return json.loads(CONTRIBUTION.read_text(encoding="utf-8"))


def build_record_from_contribution():
    payload = contribution()
    parsed = parse_contribution(payload, path=str(CONTRIBUTION))
    return build_record(parsed, research_object(parsed, parsed["evidence"], None), CHECKED)


def lines(record):
    return {release["id"]: release for release in record["releases"]}


class PrestaShopContributionTests(unittest.TestCase):
    def setUp(self):
        self.payload = contribution()
        self.record = build_record_from_contribution()
        self.lines = lines(self.record)

    def test_identity_and_complete_line_catalog_are_pinned(self):
        self.assertEqual(self.payload["target"], "software")
        self.assertEqual(self.payload["id"], "researched-prestashop")
        self.assertEqual(self.payload["name"], "PrestaShop")
        self.assertEqual(self.payload["vendor"], "PrestaShop")
        self.assertEqual(self.payload["category"], "app")
        self.assertEqual(self.payload["release"], "9.1")
        self.assertEqual(self.payload["contributor"], "eoltracker-agent")
        self.assertEqual(self.payload["method"], "agent")
        self.assertEqual(self.payload["stale_after"], "2027-09-23")
        self.assertEqual(set(self.lines), {"1.6", "1.7", "8.0", "8.1", "8.2", "9.0", "9.1"})

    def test_direct_1_6_eol_is_vendor_stated(self):
        line = self.lines["1.6"]
        self.assertEqual(line["milestones"], {
            "ga": "2014-03-17", "eos": None, "eossec": None, "eol": "2019-06-30"
        })
        self.assertNotIn("milestone_provenance", line)
        evidence = {entry["source_url"]: entry for entry in self.payload["evidence"]}
        self.assertEqual(
            evidence["https://prestashop.com/blog/tech-en/end-of-maintenance-for-prestashop-1-6"]["quote"],
            DIRECT_EOL_QUOTE,
        )
        self.assertEqual(
            evidence["https://prestashop.com/blog/tech-en/end-of-maintenance-for-prestashop-1-6"]["milestones"],
            ["eol"],
        )

    def test_explicit_release_triggers_derive_1_7_8_0_and_9_0(self):
        expected = {
            "1.7": ("2025-06-10", {"eossec", "eol"}, "9.0", "2025-06-10", EXPLICIT_17,
                    "https://build.prestashop-project.org/news/2023/178-in-extended-support-phase/"),
            "8.0": ("2023-06-26", {"eol"}, "8.1", "2023-06-26", EXPLICIT_80,
                    "https://build.prestashop-project.org/news/2023/178-in-extended-support-phase/"),
            "9.0": ("2026-03-23", {"eol"}, "9.1", "2026-03-23", EXPLICIT_90,
                    "https://build.prestashop-project.org/news/2026/cleaning-old-branches/"),
        }
        release_ids = set(self.lines)
        for release_id, (date, derived_keys, trigger_id, trigger_date, quote, url) in expected.items():
            with self.subTest(release=release_id):
                line = self.lines[release_id]
                self.assertEqual(set(line["milestone_provenance"]), derived_keys)
                for key in derived_keys:
                    entry = line["milestone_provenance"][key]
                    self.assertEqual(line["milestones"][key], date)
                    self.assertEqual(entry["kind"], "derived")
                    self.assertEqual(entry["method"], "release-trigger")
                    self.assertEqual(entry["source_url"], url)
                    self.assertEqual(entry["quote"], quote)
                    self.assertEqual(entry["trigger"]["release_id"], trigger_id)
                    self.assertEqual(entry["trigger"]["date"], trigger_date)
                self.assertEqual(self.lines[trigger_id]["milestones"]["ga"], trigger_date)
                self.assertEqual(
                    derived.derive(line["milestones"], line["milestone_provenance"], release_id, release_ids),
                    {key: date for key in derived_keys},
                )

    def test_8_1_uses_caveated_default_next_minor_rule(self):
        line = self.lines["8.1"]
        self.assertEqual(line["milestones"]["eol"], "2024-09-26")
        entry = line["milestone_provenance"]["eol"]
        self.assertEqual(entry["kind"], "derived")
        self.assertEqual(entry["method"], "release-trigger")
        self.assertEqual(entry["quote"], DEFAULT_81)
        self.assertEqual(entry["trigger"], {
            "release_id": "8.2",
            "date": "2024-09-26",
            "label": "PrestaShop 8.2.0 release under the default next-minor rule",
        })
        self.assertIn("deliberately weaker", self.payload["notes"])
        self.assertIn("8.1.7 maintenance release corroborate", self.payload["notes"])

    def test_future_8_2_and_current_9_1_terminal_dates_stay_unknown(self):
        for release_id, ga in (("8.2", "2024-09-26"), ("9.1", "2026-03-23")):
            with self.subTest(release=release_id):
                line = self.lines[release_id]
                self.assertEqual(line["milestones"], {
                    "ga": ga, "eos": None, "eossec": None, "eol": None
                })
                self.assertNotIn("milestone_provenance", line)

    def test_exact_release_evidence_and_maintenance_quotes_are_stored(self):
        urls = {entry["source_url"]: entry["quote"] for entry in self.payload["evidence"]}
        self.assertEqual(
            urls["https://api.github.com/repos/PrestaShop/PrestaShop/releases/tags/9.0.0"],
            '"published_at":"2025-06-10T12:13:17Z"',
        )
        self.assertEqual(
            urls["https://api.github.com/repos/PrestaShop/PrestaShop/releases/tags/8.2.0"],
            '"published_at":"2024-09-26T14:55:42Z"',
        )
        self.assertEqual(
            urls["https://api.github.com/repos/PrestaShop/PrestaShop/releases/tags/9.1.0"],
            '"published_at":"2026-03-23T10:11:22Z"',
        )
        self.assertEqual(
            urls["https://build.prestashop-project.org/news/2025/82x-extended-support-phase/"],
            "This maintenance period will end when PrestaShop 10.0.0 is released. "
            "When this day comes, PrestaShop 8.2 will not be maintained anymore.",
        )

    def test_bad_trigger_and_guessed_future_eol_are_refused(self):
        record = build_record_from_contribution()
        lines(record)["8.0"]["milestone_provenance"]["eol"]["trigger"]["date"] = "2023-06-27"
        with self.assertRaisesRegex(ValueError, "is not the eol milestone"):
            validate_research(record, "software")

        record = build_record_from_contribution()
        lines(record)["8.2"]["milestones"]["eol"] = "2027-01-01"
        with self.assertRaisesRegex(ValueError, "no stored quote states the end of life date"):
            validate_research(record, "software")


if __name__ == "__main__":
    unittest.main()
