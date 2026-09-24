"""openEuler collector regression tests.

The record is a deterministic assembly of five official, public sources: the
release-catalog API (identities and LTS flags), the download page's rendered
release cards (month-precision ``Planned EOL``) and its embedded item list, the
lifecycle page's own content component (the support rules), the 24.03 LTS SP4
technical white paper (release days) and the two release announcements that
disagree with the paper about two of them.

The fixtures are the sources saved verbatim on 2026-09-23. These tests pin the
inventory, every published and withheld date, the per-surface accounting, the
offline re-derivation, the source disagreements, and the publication
transaction.
"""
import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from engine import derived, openeuler, sources
from engine.importer import API, dump, normalize

FIXTURES = Path(__file__).parent / "fixtures"
DOWNLOAD = (FIXTURES / "openeuler-download.html").read_text(encoding="utf-8")
API_PAYLOAD = json.loads((FIXTURES / "openeuler-mirrors.json").read_text(encoding="utf-8"))
LIFECYCLE = (FIXTURES / "openeuler-lifecycle.html").read_text(encoding="utf-8")
COMPONENT = (FIXTURES / "openeuler-lifecycle-component.js").read_text(encoding="utf-8")
WHITEPAPER = (FIXTURES / "openeuler-sp4-whitepaper.pdf").read_bytes()
NEWS_2403 = (FIXTURES / "openeuler-news-2403.html").read_text(encoding="utf-8")
NEWS_SP4 = (FIXTURES / "openeuler-news-sp4.html").read_text(encoding="utf-8")

CHECKED = "2026-09-23T00:00:00Z"
# Independently counted from the saved sources: the API's repository rows, the
# dated statements in the paper's release history, the release cards the
# download page renders, and the rows its embedded item list states.
API_ROWS = 22
HISTORY_STATEMENTS = 21
CARDS = 4
LISTING_ROWS = 4
PAGES = {"script": COMPONENT, openeuler.DOWNLOAD_URL: DOWNLOAD,
         openeuler.API_URL: API_PAYLOAD, openeuler.ANNOUNCEMENT_2403: NEWS_2403,
         openeuler.ANNOUNCEMENT_SP4: NEWS_SP4}


def loaded():
    return openeuler.assemble(dict(PAGES), WHITEPAPER)


def parsed():
    return loaded()[0]


def released(sources_=None):
    return openeuler.build(sources_ or parsed(), None)[0]


def record():
    return openeuler.record_for(openeuler.ordered_releases(released()), CHECKED)


def by_id(releases):
    return {release["id"]: release for release in releases}


class LifecycleComponentTests(unittest.TestCase):
    def test_the_page_references_its_own_content_component(self):
        self.assertTrue(openeuler.lifecycle_component(LIFECYCLE).endswith(".js"))
        self.assertIn("TheLifecycle", openeuler.lifecycle_component(LIFECYCLE))

    def test_a_page_without_the_component_refuses(self):
        with self.assertRaisesRegex(ValueError, "no longer references its lifecycle component"):
            openeuler.lifecycle_component("<html><body>moved</body></html>")

    def test_the_component_states_the_innovation_rule_verbatim(self):
        rule = parsed().policy
        self.assertEqual(rule["rules"][0]["quote"], openeuler.INNOVATION_RULE)
        # The stored quote is the sentence the page renders, which is the raw
        # Markdown with its emphasis markers folded away.
        self.assertIn(openeuler.INNOVATION_RULE, openeuler.component_prose(COMPONENT))
        self.assertEqual(rule["url"], openeuler.LIFECYCLE_URL)
        self.assertEqual(rule["effective_from"], "2025-08-01")

    def test_the_statements_the_record_refuses_to_date_are_recorded(self):
        rule = parsed().policy
        quotes = {entry["quote"] for entry in rule["not_dated"]}
        prose = openeuler.component_prose(COMPONENT)
        for entry in rule["not_dated"]:
            self.assertIn(entry["quote"], prose)
            self.assertTrue(entry["reason"])
        # The six-year lifetime, the early-SP0 sentence, the optional extension
        # and the maintenance-support sentence are all read and all set aside.
        for quote, _reason in openeuler.NOT_DATED:
            self.assertIn(quote, quotes)

    def test_a_reworded_rule_refuses_the_component(self):
        script = COMPONENT.replace("with 6 months of community support",
                                   "with six months of community support")
        self.assertNotEqual(script, COMPONENT)
        prose = openeuler.component_prose(script)
        self.assertNotIn(openeuler.INNOVATION_RULE, prose)
        with self.assertRaisesRegex(ValueError, "no longer states its rule verbatim"):
            openeuler.policy_rules(prose)

    def test_a_component_without_its_sections_refuses(self):
        with self.assertRaisesRegex(ValueError, "states no rule sections"):
            openeuler.component_prose("const D={other:`nothing`};")


class InventoryTests(unittest.TestCase):
    def test_every_surface_is_counted_and_reconciled(self):
        source = parsed()
        self.assertEqual(len(source.catalog), API_ROWS)
        self.assertEqual(len(source.history), HISTORY_STATEMENTS)
        self.assertEqual(len(source.cards), CARDS)
        self.assertEqual(len(source.listing), LISTING_ROWS)
        counts = openeuler.accounting(source)
        self.assertEqual(counts["by_surface"], {
            "release catalog API": API_ROWS,
            "technical white paper release history": HISTORY_STATEMENTS,
            "download page release cards": CARDS,
            "download page embedded item list": LISTING_ROWS,
        })
        self.assertEqual(counts["seen"],
                         API_ROWS + HISTORY_STATEMENTS + CARDS + LISTING_ROWS)
        # Every surface row names a release, so the rows beyond the identities
        # they reconcile to are exact arithmetic, not an estimate.
        self.assertEqual(counts["identities"] + counts["reconciled"], counts["seen"])
        self.assertEqual(counts["identities"], len(released()))

    def test_the_catalog_states_lts_flags_and_no_dates(self):
        payload = openeuler.parse_api(API_PAYLOAD)
        self.assertTrue(payload[(openeuler.COMMUNITY, "24.03", "sp4")]["lts"])
        self.assertFalse(payload[(openeuler.COMMUNITY, "25.09", None)]["lts"])
        row = payload[(openeuler.COMMUNITY, "22.03", "64kb")]
        self.assertEqual(row["cells"]["Arch"], ["aarch64"])
        # The API states no release or end-of-life field at all.
        for entry in API_PAYLOAD["RepoVersion"]:
            self.assertEqual(set(entry), {"Version", "Scenario", "Arch", "LTS"})

    def test_a_catalog_row_without_its_lists_refuses(self):
        payload = copy.deepcopy(API_PAYLOAD)
        del payload["RepoVersion"][0]["Arch"]
        with self.assertRaisesRegex(ValueError, "states no Arch list"):
            openeuler.parse_api(payload)

    def test_a_duplicated_catalog_identity_refuses(self):
        payload = copy.deepcopy(API_PAYLOAD)
        payload["RepoVersion"].append(dict(payload["RepoVersion"][0]))
        with self.assertRaisesRegex(ValueError, "states .* twice"):
            openeuler.parse_api(payload)

    def test_the_historical_innovation_releases_are_published_from_the_paper(self):
        # The API omits them; the paper is the community's own record that they
        # were released, and a catalog omission is never an end of life.
        releases = by_id(released())
        for name, day in (("20.09", "2020-09-30"), ("21.03", "2021-03-31"),
                          ("21.09", "2021-09-30"), ("22.09", "2022-09-30")):
            self.assertEqual(releases[name]["milestones"]["ga"], day)
            self.assertFalse(releases[name]["upstream"]["in_catalog"])
            self.assertIsNone(releases[name]["milestones"]["eol"])

    def test_the_embedded_line_is_its_own_release(self):
        release = by_id(released())["embedded-26.03"]
        self.assertTrue(release["upstream"]["in_catalog"])
        self.assertIsNone(release["milestones"]["ga"])
        self.assertIsNone(release["milestones"]["eol"])


class DateTests(unittest.TestCase):
    def test_the_stated_planned_eols_keep_their_month_precision(self):
        releases = by_id(released())
        self.assertEqual(releases["24.03-lts-sp4"]["milestones"]["eol"], "2027-03")
        self.assertEqual(releases["24.03-lts-sp3"]["milestones"]["eol"], "2027-12")
        self.assertEqual(releases["24.03-lts-sp1"]["milestones"]["eol"], "2026-12")
        for name in ("24.03-lts-sp4", "24.03-lts-sp3", "24.03-lts-sp1"):
            self.assertRegex(releases[name]["milestones"]["eol"], r"^\d{4}-\d{2}$")
            self.assertEqual(releases[name]["upstream"]["planned_eol"]["label"], "Planned EOL")

    def test_every_other_release_has_a_null_end_of_life(self):
        for name, release in by_id(released()).items():
            if name in ("24.03-lts-sp4", "24.03-lts-sp3", "24.03-lts-sp1", "25.09"):
                continue
            self.assertIsNone(release["milestones"]["eol"], name)

    def test_the_innovation_window_is_derived_with_its_rule(self):
        release = by_id(released())["25.09"]
        self.assertEqual(release["milestones"]["ga"], "2025-09-30")
        self.assertEqual(release["milestones"]["eol"], "2026-03-30")
        entry = release[derived.DERIVED_KEY]["eol"]
        self.assertEqual(entry["kind"], "derived")
        self.assertEqual(entry["method"], "release-plus-duration")
        self.assertEqual(entry["quote"], openeuler.INNOVATION_RULE)
        self.assertEqual(entry["source_url"], openeuler.LIFECYCLE_URL)
        self.assertEqual(entry["base_date"], "2025-09-30")
        self.assertEqual(entry["base_label"], openeuler.BASE_LABEL)
        self.assertEqual(entry["duration"], {"value": 6, "unit": "month"})

    def test_no_window_is_applied_before_the_policys_effective_date(self):
        releases = by_id(released())
        for name in ("24.09", "25.03"):
            self.assertEqual(releases[name]["milestones"]["ga"], "2024-09-30"
                             if name == "24.09" else "2025-03-30")
            self.assertIsNone(releases[name]["milestones"]["eol"])
            self.assertNotIn(derived.DERIVED_KEY, releases[name])

    def test_the_innovation_window_is_never_applied_to_an_lts_release(self):
        releases = by_id(released())
        for name in ("24.03-lts", "22.03-lts", "20.03-lts", "22.03-lts-sp2"):
            self.assertNotIn(derived.DERIVED_KEY, releases[name])

    def test_the_derived_window_uses_calendar_arithmetic(self):
        self.assertEqual(openeuler.innovation_window("2025-09-30",
                                                     (openeuler.COMMUNITY, "25.09", None), False),
                         "2026-03-30")
        # An LTS release, a service pack, an embedded release and a release
        # before the effective date all keep a null end of life.
        self.assertIsNone(openeuler.innovation_window("2025-09-30",
                                                      (openeuler.COMMUNITY, "25.09", None), True))
        self.assertIsNone(openeuler.innovation_window("2025-09-30",
                                                      (openeuler.COMMUNITY, "25.09", "sp1"), False))
        self.assertIsNone(openeuler.innovation_window(
            "2025-09-30", (openeuler.EMBEDDED, "26.03", None), False))
        self.assertIsNone(openeuler.innovation_window("2024-09-30",
                                                      (openeuler.COMMUNITY, "24.09", None), False))

    def test_eos_eossec_and_the_disputed_gas_stay_null(self):
        for release in released():
            self.assertIsNone(release["milestones"]["eos"])
            self.assertIsNone(release["milestones"]["eossec"])
        releases = by_id(released())
        self.assertIsNone(releases["24.03-lts"]["milestones"]["ga"])
        self.assertIsNone(releases["24.03-lts-sp4"]["milestones"]["ga"])


class DisputeTests(unittest.TestCase):
    def test_the_disputed_releases_store_every_side_of_the_disagreement(self):
        releases = by_id(released())
        for name in ("24.03-lts", "24.03-lts-sp4"):
            hold = releases[name]["upstream"]["history"]["hold"]
            urls = {entry["source_url"] for entry in hold["evidence"]}
            self.assertIn(openeuler.WHITEPAPER_URL, urls)
            self.assertEqual(len(hold["evidence"]), 3 if name == "24.03-lts" else 3)
            for entry in hold["evidence"]:
                self.assertIn(entry["source_url"],
                              (openeuler.WHITEPAPER_URL, openeuler.LIFECYCLE_URL,
                               openeuler.ANNOUNCEMENT_2403, openeuler.ANNOUNCEMENT_SP4))
                self.assertTrue(entry["quote"])
            self.assertIn("May 30" if name == "24.03-lts" else "June 30", hold["reason"])

    def test_a_disputed_release_still_stores_the_papers_own_day(self):
        release = by_id(released())["24.03-lts"]
        self.assertEqual(release["upstream"]["history"]["date"], "2024-05-30")
        self.assertEqual(release["upstream"]["history"]["quote"],
                         "On May 30, 2024, openEuler 24.03 LTS was released.")

    def test_a_relocated_quote_refuses_the_import(self):
        # The announcement no longer carries the dateline the hold names, so the
        # disagreement can no longer be verified and the run must refuse rather
        # than publish the paper's day as if the sources agreed.
        pages = dict(PAGES)
        pages[openeuler.ANNOUNCEMENT_2403] = "<html><body>moved</body></html>"
        with self.assertRaisesRegex(ValueError, "no longer states"):
            openeuler.assemble(pages, WHITEPAPER)

    def test_a_reworded_paper_quote_refuses_the_import(self):
        text = b"On May 31, 2024, openEuler 24.03 LTS was released."
        # Replacing the paper's own sentence in the extracted text is what the
        # hold re-verification reads; an unchanged quote would not refuse.
        with mock.patch.object(openeuler, "pdf_pages", return_value=[text.decode()]):
            with self.assertRaisesRegex(ValueError, "no longer states"):
                openeuler.assemble(dict(PAGES), WHITEPAPER)


class ListingTests(unittest.TestCase):
    def test_the_embedded_item_list_is_disclosed_not_published(self):
        _source, conflicts = loaded()
        kinds = {(entry["kind"], entry["identity"]) for entry in conflicts}
        self.assertIn(("not_rendered", "community:24.03:sp2"), kinds)
        self.assertIn(("not_listed", "community:24.03:sp4"), kinds)
        for entry in conflicts:
            self.assertTrue(entry["reason"])
        # No milestone is read from the list: SP2's stated month is disclosed and
        # never becomes an end of life.
        self.assertIsNone(by_id(released())["24.03-lts-sp2"]["milestones"]["eol"])

    def test_two_renderings_that_disagree_refuse_the_import(self):
        # SP3 is both rendered as a card and listed in the embedded item list, so
        # moving the list's value for it is a disagreement between the page's two
        # renderings of one field.
        html = DOWNLOAD.replace("Planned EOL: 2027/12. Built",
                                "Planned EOL: 2028/01. Built")
        self.assertNotEqual(html, DOWNLOAD)
        cards, _listing = openeuler.parse_cards(html)
        with self.assertRaisesRegex(ValueError, "different planned end of life"):
            openeuler.listing_conflicts(cards, openeuler.item_list(html))

    def test_a_card_stating_an_unrecognized_end_of_life_refuses(self):
        html = DOWNLOAD.replace("Planned EOL: 2027/03", "Planned EOL: March 2027")
        with self.assertRaisesRegex(ValueError, "unrecognized Planned EOL"):
            openeuler.parse_cards(html)

    def test_a_stated_month_is_checked_against_the_calendar(self):
        self.assertEqual(openeuler.card_month("2027/03", "row"), "2027-03")
        for bad in ("2027/13", "2027-03", "March 2027", "", None):
            with self.assertRaises(ValueError):
                openeuler.card_month(bad, "row")


class CrossCheckTests(unittest.TestCase):
    def test_a_stated_month_is_compared_with_the_policys_own_window(self):
        checks = {entry["release"]: entry for entry in openeuler.cross_checks(released())}
        # SP3's December 2025 release plus the major-SP 24 months is exactly the
        # 2027/12 the download card states.
        self.assertEqual(checks["24.03-lts-sp3"]["kind"], "major")
        self.assertEqual(checks["24.03-lts-sp3"]["base"], "2025-12-30")
        self.assertEqual(checks["24.03-lts-sp3"]["computed"], "2027-12")
        self.assertEqual(checks["24.03-lts-sp3"]["stated"], "2027/12")
        # SP4's June 2026 release plus the minor-SP 9 months is exactly the
        # 2027/03 its card states.
        self.assertEqual(checks["24.03-lts-sp4"]["kind"], "minor")
        self.assertEqual(checks["24.03-lts-sp4"]["base"], "2026-06-30")
        self.assertEqual(checks["24.03-lts-sp4"]["computed"], "2027-03")
        # SP1's December 2024 release predates the policy's effective date, so
        # its card is published but its window is not compared.
        self.assertNotIn("24.03-lts-sp1", checks)

    def test_the_comparison_refuses_when_a_card_moves(self):
        rec = record()
        target = next(r for r in rec["releases"] if r["id"] == "24.03-lts-sp3")
        target["milestones"]["eol"] = "2027-11"
        target["upstream"]["planned_eol"]["value"] = "2027/11"
        with self.assertRaisesRegex(ValueError, "service-pack window"):
            openeuler.validate_record(rec)

    def test_a_service_pack_kind_comes_from_the_release_month(self):
        self.assertEqual(openeuler.service_pack_kind("2025-12-30"), "major")
        self.assertEqual(openeuler.service_pack_kind("2025-06-30"), "minor")
        self.assertIsNone(openeuler.service_pack_kind("2025-03-30"))


class ReDerivationTests(unittest.TestCase):
    def test_the_fetched_record_re_derives_offline(self):
        rec = record()
        openeuler.validate_record(rec)
        for release in rec["releases"]:
            openeuler.validate_record({"id": openeuler.PRODUCT_ID,
                                       "labels": openeuler.LABELS,
                                       "provenance": rec["provenance"],
                                       "releases": [release]})

    def test_a_tampered_release_date_is_refused(self):
        rec = record()
        target = next(r for r in rec["releases"] if r["id"] == "25.09")
        target["milestones"]["ga"] = "2025-10-01"
        with self.assertRaisesRegex(ValueError, "contradicts the release date cell"):
            openeuler.validate_record(rec)

    def test_a_tampered_catalog_row_is_refused(self):
        rec = record()
        target = next(r for r in rec["releases"] if r["id"] == "24.03-lts-sp4")
        target["upstream"]["cells"]["Version"] = "openEuler-24.03-LTS-SP5"
        # The stored history statement still names SP4, so the row and the
        # statement it sits beside no longer describe one release.
        with self.assertRaisesRegex(ValueError, "release-history statement it stores"):
            openeuler.validate_record(rec)

    def test_a_tampered_planned_eol_is_refused(self):
        rec = record()
        target = next(r for r in rec["releases"] if r["id"] == "24.03-lts-sp4")
        target["milestones"]["eol"] = "2028-01"
        with self.assertRaisesRegex(ValueError, "contradicts the planned end of life"):
            openeuler.validate_record(rec)

    def test_a_tampered_derived_window_is_refused(self):
        rec = record()
        target = next(r for r in rec["releases"] if r["id"] == "25.09")
        target["milestone_provenance"]["eol"]["duration"] = {"value": 12, "unit": "month"}
        with self.assertRaisesRegex(ValueError, "12 month"):
            openeuler.validate_record(rec)
        rec = record()
        target = next(r for r in rec["releases"] if r["id"] == "25.09")
        target["milestone_provenance"]["eol"]["quote"] = "Innovation releases get half a year."
        with self.assertRaisesRegex(ValueError, "does not quote the rule"):
            openeuler.validate_record(rec)

    def test_a_derived_milestone_stripped_of_its_rule_is_refused(self):
        rec = record()
        target = next(r for r in rec["releases"] if r["id"] == "25.09")
        del target["milestone_provenance"]
        with self.assertRaisesRegex(ValueError, "no rule recorded for it"):
            openeuler.validate_record(rec)

    def test_a_withheld_general_availability_cannot_be_filled_in(self):
        rec = record()
        target = next(r for r in rec["releases"] if r["id"] == "24.03-lts")
        target["milestones"]["ga"] = "2024-05-30"
        with self.assertRaisesRegex(ValueError, "sources disagree about"):
            openeuler.validate_record(rec)

    def test_a_rewritten_hold_is_refused(self):
        rec = record()
        target = next(r for r in rec["releases"] if r["id"] == "24.03-lts-sp4")
        target["upstream"]["history"]["hold"]["reason"] = "we picked the paper's date"
        with self.assertRaisesRegex(ValueError, "disputed general availability was rewritten"):
            openeuler.validate_record(rec)

    def test_an_end_of_life_with_no_stated_or_derived_source_is_refused(self):
        rec = record()
        target = next(r for r in rec["releases"] if r["id"] == "24.09")
        target["milestones"]["eol"] = "2026-03"
        with self.assertRaisesRegex(ValueError, "no source states"):
            openeuler.validate_record(rec)

    def test_a_record_order_that_contradicts_the_dates_is_refused(self):
        rec = record()
        rec["releases"][0], rec["releases"][1] = rec["releases"][1], rec["releases"][0]
        with self.assertRaisesRegex(ValueError, "not ordered by the release dates"):
            openeuler.validate_record(rec)

    def test_a_foreign_verifier_or_source_url_is_refused(self):
        rec = record()
        rec["provenance"]["verifier"] = "deterministic-something-else"
        with self.assertRaisesRegex(ValueError, "source identity"):
            openeuler.validate_record(rec)
        rec = record()
        rec["provenance"]["source_url"] = "https://example.com/releases"
        with self.assertRaisesRegex(ValueError, "source identity"):
            openeuler.validate_record(rec)

    def test_a_release_without_its_stored_row_is_refused(self):
        rec = record()
        target = next(r for r in rec["releases"] if r["id"] == "25.09")
        target["upstream"] = {"name": "openEuler-25.09"}
        with self.assertRaises(ValueError):
            openeuler.validate_record(rec)

    def test_a_catalog_table_claim_without_cells_is_refused(self):
        rec = record()
        target = next(r for r in rec["releases"] if r["id"] == "22.03-lts-64kb")
        target["upstream"]["cells"] = {}
        with self.assertRaisesRegex(ValueError, "claims a catalog table"):
            openeuler.validate_record(rec)

    def test_a_regression_that_survives_is_a_null_milestone(self):
        # Every withheld date in the record is null rather than a guess, and the
        # count of withheld dates is what the report states.
        rec = record()
        withheld = [r for r in rec["releases"]
                    if r["upstream"]["history"]
                    and r["upstream"]["history"].get("hold")]
        self.assertEqual(len(withheld), 2)
        for release in withheld:
            self.assertIsNone(release["milestones"]["ga"])


class RegistryTests(unittest.TestCase):
    def test_the_source_is_registered_as_a_software_collector(self):
        source = sources.source("import-openeuler")
        self.assertEqual(source.verifier, "deterministic-openeuler")
        self.assertEqual(source.category, "software")
        self.assertEqual(source.report, "openeuler-import.json")
        self.assertEqual(openeuler.VERIFIER, source.verifier)
        self.assertEqual(openeuler.REPORT, source.report)
        self.assertEqual(openeuler.DOWNLOAD_URL, source.pages[0].url)
        self.assertIs(sources.record_validator(source), openeuler.validate_record)

    def test_the_cli_exposes_the_source_command(self):
        from engine.__main__ import COMMANDS

        self.assertIn("import-openeuler", COMMANDS)

    def test_the_registered_pages_carry_one_label_each(self):
        for page in sources.source("import-openeuler").pages:
            self.assertEqual(sources.source_label(page.url), page.label)

    def test_the_record_only_names_registered_pages(self):
        registered = set(sources.source("import-openeuler").urls)
        for release in record()["releases"]:
            for entry in (release["upstream"]["history"] or {}).get("hold", {}).get("evidence",
                                                                                     []):
                self.assertIn(entry["source_url"], registered)


class OwnershipTests(unittest.TestCase):
    def test_a_foreign_record_is_refused(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "products").mkdir()
            dump(root / "products" / (openeuler.PRODUCT_ID + ".json"),
                 {"provenance": {"verifier": "deterministic-ceph"}})
            with self.assertRaisesRegex(ValueError, "source ownership collision"):
                openeuler.committed_record(root)

    def test_a_missing_record_is_not_a_collision(self):
        with tempfile.TemporaryDirectory() as temp:
            self.assertIsNone(openeuler.committed_record(Path(temp)))

    def test_an_unpublishable_committed_record_is_refused_before_any_fetch(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "products").mkdir()
            rec = record()
            rec["releases"][0]["milestones"]["ga"] = "2099-01-01"
            dump(root / "products" / (openeuler.PRODUCT_ID + ".json"), rec)
            with self.assertRaises(ValueError):
                openeuler.committed_record(root)


class RetentionTests(unittest.TestCase):
    def test_a_release_no_current_source_states_is_retained(self):
        dropped = next(release for release in released() if release["id"] == "20.09")
        committed = {"releases": [dropped]}
        combined, kept = openeuler.combine_releases(released(), committed)
        self.assertEqual(kept, [])
        # A release the current sources no longer state at all is republished
        # from its own stored cells and marked as such.
        fresh_without = [release for release in released() if release["id"] != "20.09"]
        combined, kept = openeuler.combine_releases(fresh_without, committed)
        self.assertEqual([entry["id"] for entry in kept], ["20.09"])
        held = next(release for release in combined if release["id"] == "20.09")
        self.assertFalse(held["upstream"]["in_sources"])
        self.assertEqual(held["milestones"]["ga"], "2020-09-30")
        self.assertTrue(kept[0]["reason"])

    def test_a_retained_release_is_recorded_in_the_report(self):
        self.assertEqual(openeuler.combine_releases(released(), None)[1], [])


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

    def refresh(self, checked, pages=None, document=None):
        """One real import through the registry's own entry point.

        The network layer is replaced, so the record, the report and the
        publication transaction are the collector's own code.
        """
        source, conflicts = openeuler.assemble(dict(pages or PAGES),
                                               document or WHITEPAPER)
        with mock.patch.object(openeuler, "fetch", return_value=(source, conflicts)), \
                mock.patch.object(openeuler, "_now", return_value=checked):
            return openeuler.import_openeuler(self.root)

    def test_a_quiet_refresh_republishes_byte_identical_files(self):
        self.refresh("2026-09-23T01:00:00Z")
        published = self.snapshot()
        self.assertIn("products/openeuler.json", published)
        self.assertIn(openeuler.REPORT, published)
        self.refresh("2026-09-23T02:00:00Z")
        self.assertEqual(self.snapshot(), published)
        rec = json.loads(published["products/openeuler.json"])
        self.assertEqual(rec["provenance"]["last_checked"], "2026-09-23T01:00:00Z")
        report = json.loads(published[openeuler.REPORT])
        self.assertEqual(report["rows"]["identities"], len(rec["releases"]))
        self.assertEqual(report["rows"]["seen"],
                         API_ROWS + HISTORY_STATEMENTS + CARDS + LISTING_ROWS)
        self.assertEqual(report["rows"]["ga_withheld"], 2)
        self.assertEqual(report["rows"]["eol_stated"], 3)
        self.assertEqual(report["rows"]["eol_derived"], 1)
        self.assertEqual(report["rows"]["history_only"], 4)

    def test_a_changed_source_advances_the_revision(self):
        self.refresh("2026-09-23T01:00:00Z")
        before = self.snapshot()
        payload = copy.deepcopy(API_PAYLOAD)
        payload["RepoVersion"].append({
            "Version": "openEuler-26.03", "Scenario": ["ISO"], "Arch": ["x86_64"], "LTS": False})
        pages = dict(PAGES)
        pages[openeuler.API_URL] = payload
        self.refresh("2026-09-23T03:00:00Z", pages=pages)
        after = self.snapshot()
        self.assertNotEqual(after, before)
        rec = json.loads(after["products/openeuler.json"])
        self.assertIn("26.03", {release["id"] for release in rec["releases"]})
        self.assertEqual(rec["provenance"]["last_checked"], "2026-09-23T03:00:00Z")

    def test_a_refused_fetch_leaves_every_committed_file_untouched(self):
        self.refresh("2026-09-23T01:00:00Z")
        before = self.snapshot()
        pages = dict(PAGES)
        pages[openeuler.ANNOUNCEMENT_SP4] = "<html>gone</html>"
        with self.assertRaises(ValueError):
            self.refresh("2026-09-23T02:00:00Z", pages=pages)
        self.assertEqual(self.snapshot(), before)

    def test_a_foreign_committed_record_refuses_the_run_before_any_fetch(self):
        dump(self.root / "products" / (openeuler.PRODUCT_ID + ".json"),
             {"provenance": {"verifier": "deterministic-ceph"}})
        with mock.patch.object(openeuler.net, "get_text") as get_text, \
                mock.patch.object(openeuler.net, "get_json") as get_json, \
                mock.patch.object(openeuler.net, "get") as get:
            with self.assertRaisesRegex(ValueError, "source ownership collision"):
                openeuler.import_openeuler(self.root)
        get_text.assert_not_called()
        get_json.assert_not_called()
        get.assert_not_called()

    def test_the_registered_entry_point_publishes_the_record(self):
        # The registry's own call path, so the CLI command is what the tests
        # exercise rather than a private helper beside it.
        source, conflicts = loaded()
        with mock.patch.object(openeuler, "fetch", return_value=(source, conflicts)), \
                mock.patch.object(openeuler, "_now", return_value="2026-09-23T01:00:00Z"):
            detail = sources.source("import-openeuler").run(self.root)
        self.assertIn("openEuler releases", detail)
        published = json.loads((self.root / "products" /
                                (openeuler.PRODUCT_ID + ".json")).read_text())
        openeuler.validate_record(published)
        self.assertEqual(len(published["releases"]), len(released()))

    def test_the_report_accounts_for_every_surface_row(self):
        self.refresh("2026-09-23T01:00:00Z")
        report = json.loads((self.root / openeuler.REPORT).read_text())
        rows = report["rows"]
        self.assertEqual(sum(rows["by_surface"].values()), rows["seen"])
        self.assertEqual(rows["identities"] + rows["reconciled"], rows["seen"])
        self.assertEqual(rows["excluded"], 0)
        self.assertEqual(report["total_records"], 1)
        self.assertEqual(report["verifier"], openeuler.VERIFIER)
        self.assertEqual(len(report["conflicts"]), 2)
        self.assertEqual(len(report["disputed"]), 2)
        self.assertEqual(len(report["cross_checks"]), 2)
        self.assertEqual(report["set_aside"][0]["table"], openeuler.HISTORY_TABLE)
        self.assertEqual(report["policy"]["url"], openeuler.LIFECYCLE_URL)
        # Every statement the policy page states and the record refuses to date
        # is disclosed with its reason.
        self.assertTrue(report["policy"]["not_dated"])
        self.assertTrue(report["limitations"])


class PDFTests(unittest.TestCase):
    def test_the_white_paper_extracts_to_its_own_release_history(self):
        pages = openeuler.pdf_pages(WHITEPAPER)
        self.assertEqual(len(pages), 95)
        dated = [index for index, page in enumerate(pages) if openeuler.HISTORY_DAY.search(page)]
        self.assertEqual(dated, [0, 1, 2])
        flat = " ".join(" ".join(page.split()) for page in pages[:3])
        for sentence in ("On May 30, 2024, openEuler 24.03 LTS was released.",
                         "On June 30, 2026, openEuler 24.03 LTS SP4 was officially released"):
            self.assertIn(sentence, flat)
        # A wrapped hyphenated word is rejoined as the page renders it.
        self.assertIn("all-scenario", flat)
        self.assertNotIn("all - scenario", flat)

    def test_the_history_parser_reads_every_dated_statement(self):
        history, set_aside = openeuler.parse_history(WHITEPAPER)
        self.assertEqual(len(history), HISTORY_STATEMENTS)
        self.assertEqual(history[(openeuler.COMMUNITY, "21.03", None)]["date"], "2021-03-31")
        self.assertEqual(history[(openeuler.COMMUNITY, "24.03", "sp3")]["date"], "2025-12-30")
        # The community's own establishment is dated in the same style and is set
        # aside with its reason rather than published as a release.
        self.assertEqual(len(set_aside), 1)
        self.assertIn("establishment", set_aside[0]["reason"])
        self.assertNotIn(openeuler.COMMUNITY, {key[0] for key in history
                                               if key[1] == "2019"})

    def test_a_dated_statement_that_names_no_release_refuses(self):
        with mock.patch.object(openeuler, "pdf_pages",
                               return_value=["On May 1, 2026, something shipped."]):
            with self.assertRaisesRegex(ValueError, "dates an unnamed statement"):
                openeuler.parse_history(WHITEPAPER)

    def test_a_release_dated_twice_refuses(self):
        page = ("On May 30, 2024, openEuler 24.03 LTS was released. "
                "On June 1, 2024, openEuler 24.03 LTS was released again.")
        with mock.patch.object(openeuler, "pdf_pages", return_value=[page]):
            with self.assertRaisesRegex(ValueError, "dates a release twice"):
                openeuler.parse_history(WHITEPAPER)

    def test_an_interrupted_history_refuses(self):
        pages = ["On May 30, 2024, openEuler 24.03 LTS was released.",
                 "No release is dated on this page.",
                 "On May 30, 2024, openEuler 23.03 was released."]
        with mock.patch.object(openeuler, "pdf_pages", return_value=pages):
            with self.assertRaisesRegex(ValueError, "not consecutive"):
                openeuler.parse_history(WHITEPAPER)

    def test_a_document_without_a_page_tree_refuses(self):
        with self.assertRaisesRegex(ValueError, "no page tree"):
            openeuler.pdf_pages(b"%PDF-1.7\n1 0 obj\n<< /Type /NotPages >>\nendobj\n")


class IdentityTests(unittest.TestCase):
    def test_names_and_ids_are_read_from_the_sources_own_text(self):
        self.assertEqual(openeuler.release_id((openeuler.COMMUNITY, "24.03", "sp4"), True),
                         "24.03-lts-sp4")
        self.assertEqual(openeuler.display_name((openeuler.COMMUNITY, "24.03", "sp4"), True),
                         "openEuler 24.03 LTS SP4")
        # The separately catalogued kernel flavour is one identity of its own.
        self.assertEqual(openeuler.release_id((openeuler.COMMUNITY, "22.03", "64kb"), True),
                         "22.03-lts-64kb")
        self.assertEqual(openeuler.release_id((openeuler.EMBEDDED, "26.03", None), False),
                         "embedded-26.03")

    def test_a_mention_of_a_shorter_name_is_not_its_subject(self):
        names = openeuler.scan_names(
            "On June 30, 2026, openEuler 24.03 LTS SP4 was released, an update to "
            "openEuler 24.03 LTS.")
        self.assertEqual([key for _position, key, _text in names],
                         [(openeuler.COMMUNITY, "24.03", "sp4"),
                          (openeuler.COMMUNITY, "24.03", None)])

    def test_an_api_form_and_a_prose_form_are_one_identity(self):
        self.assertEqual(openeuler._identity_of_text("openEuler-24.03-LTS-SP4"),
                         openeuler._identity_of_text("openEuler 24.03 LTS SP4"))

    def test_an_unknown_name_is_refused(self):
        with self.assertRaisesRegex(ValueError, "does not name one release"):
            openeuler.parse_cards(
                '<div class="download-version-card" id="openWrt 24.03"><p class="subtitle">'
                'Planned EOL: 2027/03</p></div>')


if __name__ == "__main__":
    unittest.main()
