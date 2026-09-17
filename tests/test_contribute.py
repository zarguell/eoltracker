"""Admission tests for one-time researched contributions (engine/contribute.py)."""
import copy
import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

from engine.contribute import (RESEARCHED_VERIFIER_PREFIX, check_file, install_file,
                               parse_contribution, research_view, validate_research)
from engine.importer import API, dump, normalize

NOTICE = "https://www.synology.com/en-ca/products/status/eol-dsm62"
QUOTE = ("DSM 6.2 will reach the end of the Extended Life Phase on October 1, 2024. After which, "
         "DSM 6.2 and related packages or applications will no longer receive functionality, "
         "security, and package updates.")
SYNOLOGY = {
    "target": "software",
    "id": "researched-synology-dsm-6-2",
    "name": "Synology DSM 6.2",
    "vendor": "Synology",
    "category": "os",
    "release": "6.2",
    "links": {"about": "https://www.synology.com/en-global/dsm/6.2"},
    "identifiers": [{"type": "purl", "id": "pkg:generic/synology-dsm@6.2"}],
    "milestones": {"eol": "2024-10-01"},
    "evidence": [{"quote": QUOTE, "source_url": NOTICE, "retrieved_at": "2026-09-17"}],
    "contributor": "zarguell",
    "notes": "Synology publishes no machine-readable lifecycle data.",
}
HARDWARE = {
    "target": "hardware",
    "id": "researched-acme-edge-router-100",
    "name": "ACME Edge Router 100",
    "vendor": "ACME",
    "milestones": {"ga": "2018-04-01", "eos": "2024-03-31", "eol": "2025-03-31"},
    "evidence": [{"quote": "The ACME Edge Router 100 became generally available on April 1, 2018, "
                           "reached end of sale on March 31, 2024 and end of support on March 31, 2025.",
                  "source_url": "https://example.com/acme/lifecycle",
                  "retrieved_at": "2026-09-17", "milestones": ["ga", "eos", "eol"]}],
    "contributor": "zarguell",
    "method": "agent",
}
CHECKED = "2026-09-17T12:00:00Z"


class ContributionCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "products").mkdir()
        self.deterministic = normalize({"result": {"name": "sample", "label": "Sample", "category": "lang",
            "labels": {"eol": "Security Support"}, "releases": [{"name": "1", "eolFrom": "2028-01-01"}]}},
            CHECKED)
        dump(self.root / "products" / "sample.json", self.deterministic)
        dump(self.root / "manifest.json", {"generated_at": CHECKED, "source_url": API,
             "product_count": 1, "release_count": 1, "excluded_hardware": []})

    def contribution(self, payload, name="contribution.json"):
        path = self.root / name
        dump(path, payload)
        return path

    @staticmethod
    def fetch(pages):
        def fetcher(url):
            if url not in pages:
                raise AssertionError(f"unexpected fetch: {url}")
            return pages[url]
        return fetcher

    def pages(self, text):
        return self.fetch({NOTICE: f"<html><body><p>{text}</p></body></html>"})


class ParsingTests(ContributionCase):
    def test_milestone_absent_from_quote_is_rejected(self):
        payload = copy.deepcopy(SYNOLOGY)
        payload["milestones"] = {"eol": "2024-10-01", "eos": "2023-10-01"}
        with self.assertRaisesRegex(ValueError, "no stored quote states the end of sale date"):
            parse_contribution(payload)

    def test_month_precision_never_proves_a_day(self):
        payload = copy.deepcopy(SYNOLOGY)
        payload["evidence"][0]["quote"] = "DSM 6.2 reaches the end of the Extended Life Phase in October 2024."
        with self.assertRaisesRegex(ValueError, "no stored quote states the end of life date"):
            parse_contribution(payload)

    def test_short_quote_and_unsafe_id_are_rejected(self):
        payload = copy.deepcopy(SYNOLOGY)
        payload["evidence"][0]["quote"] = "Ends 2024-10-01"
        with self.assertRaisesRegex(ValueError, "at least 20 characters"):
            parse_contribution(payload)
        payload = copy.deepcopy(SYNOLOGY)
        del payload["evidence"][0]["quote"]
        with self.assertRaisesRegex(ValueError, r"evidence\[0\]: quote must be a non-empty string"):
            parse_contribution(payload)
        for bad in ("synology-dsm-6-2", "researched-Synology_DSM"):
            payload = copy.deepcopy(SYNOLOGY)
            payload["id"] = bad
            with self.assertRaisesRegex(ValueError, "slug|namespace"):
                parse_contribution(payload)
        payload = copy.deepcopy(SYNOLOGY)
        payload["milestones"] = {"eol": "October 2024"}
        with self.assertRaisesRegex(ValueError, "not an ISO day"):
            parse_contribution(payload)


class EvidenceTests(ContributionCase):
    def test_quote_must_match_the_fetched_source(self):
        path = self.contribution(SYNOLOGY)
        with self.assertRaisesRegex(ValueError, "Quote not found"):
            install_file(path, root=self.root, fetch=self.pages("A different page about DSM 7."))
        self.assertFalse((self.root / "products/researched-synology-dsm-6-2.json").exists())
        self.assertFalse((self.root / "contributions-log.json").exists())

    def test_unreachable_source_needs_the_offline_flag(self):
        path = self.contribution(SYNOLOGY)

        def broken(url):
            raise ConnectionError("offline")

        with self.assertRaisesRegex(ValueError, "Cannot verify evidence"):
            check_file(path, root=self.root, fetch=broken)
        report = check_file(path, root=self.root, fetch=broken, allow_stale=True)
        self.assertFalse(report["verified"])

    def test_offline_install_marks_the_evidence_unverified(self):
        path = self.contribution(SYNOLOGY)

        def broken(url):
            raise ConnectionError("offline")

        report = install_file(path, root=self.root, fetch=broken, allow_stale=True)
        self.assertEqual(report["action"], "install")
        record = json.loads((self.root / "products/researched-synology-dsm-6-2.json").read_text())
        self.assertIsNone(record["provenance"]["research"]["verified_at"])
        view = research_view(record, today=date(2026, 9, 17))
        self.assertFalse(view["stale"])
        self.assertGreater(research_view(record, today=date(2027, 4, 1))["age_days"], 180)
        self.assertTrue(research_view(record, today=date(2027, 4, 1))["stale"])


class InstallTests(ContributionCase):
    def test_install_writes_record_and_log(self):
        path = self.contribution(SYNOLOGY)
        report = install_file(path, root=self.root, fetch=self.pages(QUOTE))
        self.assertEqual(report["action"], "install")
        self.assertTrue(report["verified"])
        record = json.loads((self.root / "products/researched-synology-dsm-6-2.json").read_text())
        self.assertEqual(record["id"], "researched-synology-dsm-6-2")
        self.assertEqual(record["provenance"]["verifier"], RESEARCHED_VERIFIER_PREFIX + "zarguell")
        self.assertEqual(record["provenance"]["source_url"], NOTICE)
        self.assertEqual(record["provenance"]["last_checked"], record["provenance"]["research"]["verified_at"])
        self.assertEqual(record["releases"], [{
            "id": "6.2", "name": "6.2",
            "milestones": {"ga": None, "eos": None, "eossec": None, "eol": "2024-10-01"},
            "upstream": {"name": "6.2",
                         "Contribution": {"text": QUOTE, "value": None, "datetime": None,
                                          "role": None, "links": [NOTICE]}}}])
        validate_research(record, "software")
        log = json.loads((self.root / "contributions-log.json").read_text())
        self.assertEqual([entry["action"] for entry in log], ["install"])
        self.assertEqual(log[0]["id"], "researched-synology-dsm-6-2")
        self.assertEqual(log[0]["at"], record["provenance"]["last_checked"])
        # The researched record is admitted beside the deterministic catalog,
        # whose manifest counts are unchanged.
        self.assertEqual(json.loads((self.root / "manifest.json").read_text())["product_count"], 1)

    def test_reinstall_is_byte_identical_and_not_logged_twice(self):
        path = self.contribution(SYNOLOGY)
        install_file(path, root=self.root, fetch=self.pages(QUOTE))
        stored = self.root / "products/researched-synology-dsm-6-2.json"
        before = stored.read_bytes()
        report = install_file(path, root=self.root, fetch=self.pages(QUOTE))
        self.assertEqual(report["action"], "unchanged")
        self.assertEqual(stored.read_bytes(), before)
        self.assertEqual(len(json.loads((self.root / "contributions-log.json").read_text())), 1)

    def test_contribution_update_appends_to_the_log(self):
        path = self.contribution(SYNOLOGY)
        install_file(path, root=self.root, fetch=self.pages(QUOTE))
        payload = copy.deepcopy(SYNOLOGY)
        payload["evidence"][0]["retrieved_at"] = "2026-10-01"
        self.contribution(payload)
        report = install_file(path, root=self.root, fetch=self.pages(QUOTE))
        self.assertEqual(report["action"], "update")
        self.assertEqual([entry["action"] for entry in
                          json.loads((self.root / "contributions-log.json").read_text())],
                         ["install", "update"])

    def test_release_id_defaults_to_the_namespaced_slug(self):
        payload = {key: value for key, value in SYNOLOGY.items() if key != "release"}
        contribution = parse_contribution(payload)
        self.assertEqual(contribution["release"], "synology-dsm-6-2")

    def test_check_writes_nothing(self):
        path = self.contribution(SYNOLOGY)
        report = check_file(path, root=self.root, fetch=self.pages(QUOTE))
        self.assertFalse(report["written"])
        self.assertFalse(report["existing"])
        self.assertFalse((self.root / "products/researched-synology-dsm-6-2.json").exists())
        self.assertFalse((self.root / "contributions-log.json").exists())

    def test_schema_invalid_date_is_rejected(self):
        path = self.contribution(SYNOLOGY)
        payload = copy.deepcopy(SYNOLOGY)
        payload["milestones"] = {"eol": "2024-02-30"}
        path = self.contribution(payload, name="bad.json")
        with self.assertRaisesRegex(ValueError, "not a real calendar day"):
            install_file(path, root=self.root, fetch=self.pages(QUOTE))


class ClobberTests(ContributionCase):
    def test_deterministic_record_is_never_replaced(self):
        path = self.contribution(SYNOLOGY)
        target = self.root / "products/researched-synology-dsm-6-2.json"
        foreign = copy.deepcopy(self.deterministic)
        foreign["id"] = "researched-synology-dsm-6-2"
        dump(target, foreign)
        before = target.read_bytes()
        with self.assertRaisesRegex(ValueError, "deterministic-endoflife-date-v1"):
            install_file(path, root=self.root, fetch=self.pages(QUOTE))
        self.assertEqual(target.read_bytes(), before)

    def test_another_contributors_record_is_never_replaced(self):
        path = self.contribution(SYNOLOGY)
        target = self.root / "products/researched-synology-dsm-6-2.json"
        dump(target, {"id": "researched-synology-dsm-6-2",
                      "provenance": {"verifier": "researched-someone-else"}})
        before = target.read_bytes()
        with self.assertRaisesRegex(ValueError, "researched-someone-else"):
            install_file(path, root=self.root, fetch=self.pages(QUOTE))
        self.assertEqual(target.read_bytes(), before)

    def test_failed_catalog_validation_rolls_the_write_back(self):
        path = self.contribution(SYNOLOGY)
        install_file(path, root=self.root, fetch=self.pages(QUOTE))
        stored = self.root / "products/researched-synology-dsm-6-2.json"
        before = stored.read_bytes()
        payload = copy.deepcopy(SYNOLOGY)
        payload["milestones"] = {"eol": "2025-10-01"}
        payload["evidence"][0]["quote"] = QUOTE.replace("October 1, 2024", "October 1, 2025")
        self.contribution(payload)
        manifest = json.loads((self.root / "manifest.json").read_text())
        manifest["product_count"] = 2
        dump(self.root / "manifest.json", manifest)
        with self.assertRaisesRegex(ValueError, "Manifest counts"):
            install_file(path, root=self.root, fetch=self.pages(payload["evidence"][0]["quote"]))
        self.assertEqual(stored.read_bytes(), before)
        self.assertEqual([entry["action"] for entry in
                          json.loads((self.root / "contributions-log.json").read_text())], ["install"])


class RefreshTests(ContributionCase):
    def test_upstream_refresh_keeps_researched_records(self):
        from engine import importer

        install_file(self.contribution(SYNOLOGY), root=self.root, fetch=self.pages(QUOTE),
                     allow_stale=True)
        stored = self.root / "products/researched-synology-dsm-6-2.json"
        before = stored.read_bytes()
        listing = {"total": 1, "result": [{"name": "sample", "label": "Sample", "category": "lang"}]}
        detail = {"result": {"name": "sample", "label": "Sample", "category": "lang", "labels": {},
                             "releases": [{"name": "1", "releaseDate": "2020-01-01"}],
                             "links": {}, "identifiers": []},
                  "last_modified": None}
        original_root, original_fetch = importer.ROOT, importer.fetch
        importer.ROOT = self.root
        importer.fetch = lambda url: listing if url == API else detail
        self.addCleanup(setattr, importer, "ROOT", original_root)
        self.addCleanup(setattr, importer, "fetch", original_fetch)
        importer.import_data()
        # The refresh re-derives the upstream snapshot; the researched record is
        # not in that listing and is carried through unchanged.
        self.assertEqual(stored.read_bytes(), before)
        self.assertEqual(sorted(file.name for file in (self.root / "products").glob("*.json")),
                         ["researched-synology-dsm-6-2.json", "sample.json"])


class HardwareTests(ContributionCase):
    def test_install_hardware_record(self):
        path = self.contribution(HARDWARE, name="hardware.json")
        report = install_file(path, root=self.root,
                              fetch=self.fetch({"https://example.com/acme/lifecycle":
                                                f"<p>{HARDWARE['evidence'][0]['quote']}</p>"}),
                              now=None)
        self.assertEqual(report["action"], "install")
        record = json.loads((self.root / "hardware/researched-acme-edge-router-100.json").read_text())
        self.assertEqual(record["vendor"], "ACME")
        self.assertEqual(record["product_line"], "ACME")
        self.assertEqual(record["status"], "eol")
        self.assertEqual(record["provenance"]["source_urls"], ["https://example.com/acme/lifecycle"])
        self.assertEqual(record["provenance"]["research"]["method"], "agent")
        self.assertEqual(record["upstream"]["Contribution"]["links"],
                         ["https://example.com/acme/lifecycle"])
        validate_research(record, "hardware")

    def test_hardware_status_uses_the_nearest_stated_end(self):
        from engine.contribute import hardware_status
        today = date(2026, 9, 17)
        self.assertEqual(hardware_status({"ga": None, "eos": None, "eossec": None, "eol": "2027-01-01"},
                                         today), "expiring")
        self.assertEqual(hardware_status({"ga": None, "eos": None, "eossec": None, "eol": "2029-06-01"},
                                         today), "supported")
        self.assertEqual(hardware_status({"ga": None, "eos": None, "eossec": None, "eol": None},
                                         today), "unknown")


if __name__ == "__main__":
    unittest.main()
