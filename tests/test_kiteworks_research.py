"""Accellion FTA: the one dated lifecycle fact in the Kiteworks estate (#123).

`contributions/kiteworks-accellion-fta.json` publishes the retired Accellion FTA
product as `eol 2021-04-30` — the day the vendor's own public notice names
("End of Life for its legacy FTA software effective April 30, 2021"). The notice
labels the milestone "End of Life", so the date fills `eol` only: no GA day, no
end of sale and no separately dated end of security support is published. The
same sentence appears verbatim in the vendor's own FTA EOL PDF, which is stored
as a corroborating link (the fetcher reads raw bytes for `application/pdf`, so a
PDF `source_url` cannot be re-read by the admission check; the HTML notice is
the refetchable primary evidence).

These tests pin the contract offline: the shape, the single milestone, the
absence of the other three, the stored quotes and the corroborating PDF. They
also pin the sibling no-go artifacts (#124/#125/#126) so a decision file cannot
silently disappear while the contribution it scopes remains.
"""
import json
import tempfile
import unittest
from pathlib import Path

from engine.contribute import (
    build_record, check_file, date_in_quote, install_file, missing_backing,
    parse_contribution, research_object, research_view, validate_research)
from engine.importer import API, dump, normalize

ROOT = Path(__file__).resolve().parents[1]
CONTRIBUTION = ROOT / "contributions" / "kiteworks-accellion-fta.json"
NOTICE = ("https://www.kiteworks.com/company/security-updates/"
          "accellion-announces-end-of-life-eol-for-its-legacy-fta-product/")
PDF = "https://www.kiteworks.com/sites/default/files/resources/fta-eol.pdf"
# The vendor's own sentence, pinned verbatim: it is the only thing that states
# the date, so a reworded copy in the record is a review, not a silent edit.
QUOTE = ("Accellion USA, LLC is announcing End of Life for its legacy FTA software "
         "effective April 30, 2021. Accellion will continue to provide support and honor "
         "its FTA contracts for the duration of its existing License Terms.")
RENEWAL = ("If your renewal date for your FTA software is after April 30, 2021, you will "
           "not be allowed to renew and your FTA license will end.")
# The matching sentence the vendor's own PDF carries (SO-DS-CN-022018), stored in
# the record's notes as corroboration beside the PDF link.
PDF_QUOTE = ("Accellion USA, LLC is announcing End of Life for its legacy FTA software "
             "effective April 30, 2021.")
EOL = "2021-04-30"
CONTRIBUTOR = "eoltracker-agent"
VERIFIER = "researched-eoltracker-agent"
CHECKED = "2026-09-26T00:00:00Z"

NO_GO_ARTIFACTS = {
    "platform": ROOT / "contributions" / "kiteworks-platform-no-go.md",
    "subsidiaries": ROOT / "contributions" / "kiteworks-subsidiaries-scope.md",
    "owncloud": ROOT / "contributions" / "owncloud-attribution-decision.md",
}


def contribution():
    return json.loads(CONTRIBUTION.read_text(encoding="utf-8"))


class KiteworksCase(unittest.TestCase):
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

    def notice_page(self, url):
        """The notice's text, so the quote-in-source check runs without network."""
        if url != NOTICE:
            raise AssertionError(f"unexpected fetch: {url}")
        return f"<html><body><p>{QUOTE}</p><p>{RENEWAL}</p></body></html>"

    def build(self):
        payload = contribution()
        parsed = parse_contribution(payload, path=str(CONTRIBUTION))
        research = research_object(parsed, parsed["evidence"], None)
        return build_record(parsed, research, CHECKED)

    def line(self, record):
        releases = record["releases"]
        self.assertEqual(len(releases), 1)
        return releases[0]


class AdmissionTests(KiteworksCase):
    """The contribution file passes the admission gate the CLI runs."""

    def test_the_contribution_check_passes_offline(self):
        report = check_file(CONTRIBUTION, root=self.root, fetch=self.offline, allow_stale=True)
        self.assertEqual(report["action"], "check")
        self.assertEqual(report["id"], "researched-accellion-fta")
        self.assertEqual(report["verifier"], VERIFIER)
        self.assertFalse(report["written"])
        self.assertFalse(report["verified"])

    def test_the_notice_quote_verifies_against_fetched_source_text(self):
        # The HTML notice is refetchable, so the live admission path (not only
        # the offline one) confirms the stored sentence is still published.
        report = check_file(CONTRIBUTION, root=self.root, fetch=self.notice_page)
        self.assertTrue(report["verified"])
        self.assertEqual(report["stated"], f"accellion-fta: eol={EOL}")

    def test_the_install_lands_the_record(self):
        report = install_file(CONTRIBUTION, root=self.root, fetch=self.notice_page)
        self.assertEqual(report["action"], "install")
        stored = json.loads((self.root / "products" / "researched-accellion-fta.json").read_text())
        validate_research(stored, "software")
        self.assertEqual(stored["id"], "researched-accellion-fta")
        self.assertEqual(stored["provenance"]["verifier"], VERIFIER)
        self.assertTrue(stored["provenance"]["research"]["verified_at"])
        self.assertEqual(self.line(stored)["milestones"]["eol"], EOL)

    def test_reinstall_is_byte_identical(self):
        install_file(CONTRIBUTION, root=self.root, fetch=self.notice_page)
        stored = self.root / "products" / "researched-accellion-fta.json"
        before = stored.read_bytes()
        report = install_file(CONTRIBUTION, root=self.root, fetch=self.notice_page)
        self.assertEqual(report["action"], "unchanged")
        self.assertEqual(stored.read_bytes(), before)

    def test_a_reworded_quote_is_refused(self):
        # The stored sentence is the evidence: a page that no longer carries it
        # must fail rather than silently accept a different reading.
        def wrong(url):
            return "<html><body><p>Accellion FTA was discontinued at some point.</p></body></html>"

        with self.assertRaisesRegex(ValueError, "Quote not found"):
            check_file(CONTRIBUTION, root=self.root, fetch=wrong)
        self.assertFalse((self.root / "products" / "researched-accellion-fta.json").exists())


class MilestoneTests(KiteworksCase):
    """Only `eol` is stated; the other three milestones stay absent."""

    def test_only_end_of_life_is_published(self):
        milestones = self.line(self.build())["milestones"]
        self.assertEqual(milestones["eol"], EOL)
        for key in ("ga", "eos", "eossec"):
            self.assertIsNone(milestones[key], key)

    def test_the_date_is_day_precision(self):
        self.assertRegex(EOL, r"\d{4}-\d{2}-\d{2}")

    def test_no_derivation_is_claimed(self):
        line = self.line(self.build())
        self.assertNotIn("milestone_provenance", line)
        self.assertEqual(missing_backing(line["milestones"], contribution()["evidence"]), [])

    def test_the_notice_label_is_end_of_life(self):
        # The mapping evidence is the label itself, so the quote must carry it.
        self.assertIn("End of Life", QUOTE)


class QuoteTests(KiteworksCase):
    """The stored quotes are the vendor's own sentences, verbatim."""

    def test_the_primary_quote_names_the_day(self):
        entry = next(item for item in contribution()["evidence"] if item["quote"] == QUOTE)
        self.assertEqual(entry["milestones"], ["eol"])
        self.assertEqual(entry["source_url"], NOTICE)
        self.assertEqual(entry["retrieved_at"], "2026-09-26")
        self.assertTrue(date_in_quote(EOL, entry["quote"]))

    def test_the_renewal_cutoff_is_not_mapped_to_end_of_sale(self):
        # The renewal sentence is stored for context but backs no milestone, so
        # a licensing renewal rule is never published as an end of sale.
        entries = [item for item in contribution()["evidence"] if item["quote"] == RENEWAL]
        self.assertEqual(len(entries), 1)
        self.assertNotIn("milestones", entries[0])
        self.assertIsNone(self.line(self.build())["milestones"]["eos"])

    def test_no_day_other_than_the_stated_one_is_backed(self):
        for day in ("2021-02-25", "2021-05-01", "2021-04-29"):
            self.assertFalse(date_in_quote(day, QUOTE))

    def test_the_pdf_is_stored_as_corroboration(self):
        payload = contribution()
        self.assertEqual(payload["links"]["endOfLifePdf"], PDF)
        # The identical sentence is quoted in the notes beside the PDF link: the
        # PDF cannot be an evidence entry (the fetcher reads raw bytes for it),
        # so the corroboration is the verbatim sentence plus the citation.
        self.assertIn(PDF_QUOTE, payload["notes"])
        self.assertNotIn(PDF, [item["source_url"] for item in payload["evidence"]])


class ProvenanceTests(KiteworksCase):
    """The research provenance makes staleness and authorship visible."""

    def test_contributor_method_and_stale_after_are_set(self):
        payload = contribution()
        self.assertEqual(payload["contributor"], CONTRIBUTOR)
        self.assertEqual(payload["method"], "agent")
        self.assertEqual(payload["stale_after"], "2027-03-25")
        self.assertEqual(VERIFIER, "researched-" + CONTRIBUTOR)

    def test_the_research_view_reports_the_source_and_date(self):
        view = research_view(self.build())
        self.assertEqual(view["contributor"], CONTRIBUTOR)
        self.assertEqual(view["method"], "agent")
        self.assertEqual(view["source_url"], NOTICE)
        self.assertEqual(view["retrieved_at"], "2026-09-26")
        self.assertEqual(view["stale_after"], "2027-03-25")

    def test_the_record_keeps_its_vendor_context(self):
        research = self.build()["provenance"]["research"]
        self.assertEqual(research["vendor"], "Accellion")
        self.assertEqual(research["retrieved_at"], "2026-09-26")


class DecisionArtifactTests(unittest.TestCase):
    """The sibling no-go / scoping decisions exist and stay attributable."""

    def test_every_decision_artifact_exists(self):
        for label, path in NO_GO_ARTIFACTS.items():
            self.assertTrue(path.is_file(), label)

    def test_the_platform_no_go_records_each_access_shape(self):
        text = NO_GO_ARTIFACTS["platform"].read_text(encoding="utf-8")
        for shape in ("login-gated", "does not resolve", "machine-readable JSON"):
            self.assertIn(shape, text)
        # The advisory feed is named and rejected as a lifecycle source.
        self.assertIn("security-advisories", text)
        self.assertIn("rejected as a lifecycle source", text)
        self.assertIn("NO-GO", text)

    def test_the_subsidiaries_scope_names_every_brand(self):
        text = NO_GO_ARTIFACTS["subsidiaries"].read_text(encoding="utf-8")
        for brand in ("Zivver", "DRACOON", "totemo", "WAMNET", "Maytech",
                      "Bonfy.ai", "123FormBuilder"):
            self.assertIn(brand, text)

    def test_the_owncloud_decision_keeps_month_precision_and_tba_unknown(self):
        text = NO_GO_ARTIFACTS["owncloud"].read_text(encoding="utf-8")
        self.assertIn("2027-01", text)
        self.assertIn("TBA", text)
        self.assertIn("ownCloud", text)
        self.assertIn("CHANGELOG.md", text)


if __name__ == "__main__":
    unittest.main()
