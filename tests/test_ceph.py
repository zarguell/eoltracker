"""Regression tests for the Ceph community release branch collector.

The fixtures are the two files the published Ceph release page is built from —
its data file ``doc/releases/releases.yml`` and its page source
``doc/releases/index.rst``, both fetched from ``ceph/ceph@main`` and stored
byte-for-byte as the source hashes them — so the tests pin the parse against the
real source rather than against a reduced sample.

The rules these tests exist to defend, in the order they matter:

* an **estimated** end of life (``target_eol``) is not a final one
  (``actual_eol``) and may never become ``milestones.eol``, so a current branch
  publishes no deadline and reaches neither the catalog's derived feeds nor a
  consumer's calendar;
* a branch's identity is its stable series (``20.2``), not the point release it
  currently ships, so a permalink survives the next patch release;
* a row the source states no date for stays absent, and the three retired
  branches the metadata carries no record for are accounted as exclusions
  instead of vanishing;
* this source writes only its own record and leaves a foreign one byte-identical.
"""
import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import yaml

from engine import ceph, importer, net, sources, validation
from engine.importer import API, dump, normalize

ROOT = Path(__file__).resolve().parents[1]
DATA_FIXTURE = ROOT / "tests/fixtures/ceph-releases.yml"
INDEX_FIXTURE = ROOT / "tests/fixtures/ceph-index.rst"
DATA = DATA_FIXTURE.read_text(encoding="utf-8")
INDEX = INDEX_FIXTURE.read_text(encoding="utf-8")
CHECKED = "2026-09-17T12:00:00Z"
# The two dates that exist only as estimates in the source. Neither may appear
# as a milestone anywhere in a published record or a feed document.
ESTIMATED_ONLY = {"20.2": "2027-06-01", "19.2": "2026-10-31"}


def parsed():
    return ceph.parse_releases(DATA, INDEX)


def software_record(name="sample", verifier=sources.source("import-data").verifier):
    record = normalize({"result": {"name": name, "label": name.title(), "category": "lang",
                                   "labels": {"eol": "Security Support"},
                                   "releases": [{"name": "1", "eolFrom": "2028-01-01"}]}}, CHECKED)
    record["provenance"]["verifier"] = verifier
    return record


def catalog_root(directory, records):
    """A data directory holding ``records`` and the manifest the importer writes."""
    (directory / "products").mkdir(parents=True, exist_ok=True)
    for record in records:
        dump(directory / "products" / (record["id"] + ".json"), record)
    counted = [record for record in records
               if record["provenance"]["verifier"] == sources.source("import-data").verifier]
    dump(directory / "manifest.json", {
        "generated_at": CHECKED, "source_url": API, "product_count": len(counted),
        "release_count": sum(len(record["releases"]) for record in counted),
        "excluded_hardware": [], "source": "import-data"})


class ParseTests(unittest.TestCase):
    def test_real_fixture_covers_current_and_historical_branches(self):
        releases, excluded = parsed()
        self.assertEqual([release["id"] for release in releases],
                         ["20.2", "19.2", "18.2", "17.2", "16.2", "15.2", "14.2", "13.2", "12.2",
                          "11.2", "10.2", "9.2", "0.94", "0.87", "0.80", "0.72", "0.67"])
        # 58 development entries plus the 3 branches the metadata has no record
        # for; both are accounted, neither is dropped.
        self.assertEqual(len(excluded), 61)

    def test_release_id_is_the_stable_series_not_the_current_point_release(self):
        releases, _ = parsed()
        by_id = {release["id"]: release for release in releases}
        # 20.2.4 is what the branch ships today; the branch is 20.2, so the
        # identity survives the next patch release.
        self.assertEqual(by_id["20.2"]["name"], "Tentacle")
        self.assertEqual(by_id["20.2"]["upstream"]["name"], "20.2.4")
        # A branch the vendor documents with a two-component version is that
        # series verbatim, not a padded three-component one.
        self.assertEqual(by_id["0.94"]["name"], "Hammer")
        self.assertEqual(by_id["0.94"]["upstream"]["name"], "0.94.10")

    def test_an_estimate_never_becomes_a_normalized_deadline(self):
        releases, _ = parsed()
        by_id = {release["id"]: release for release in releases}
        # Tentacle and Squid have not ended; the source states an estimate only,
        # which stays the vendor's own cell and produces no milestone.
        for branch, estimate in ESTIMATED_ONLY.items():
            self.assertIsNone(by_id[branch]["milestones"]["eol"])
            self.assertEqual(by_id[branch]["upstream"]["cells"]["End of life (estimated)"], estimate)
            self.assertEqual(by_id[branch]["upstream"]["cells"]["End of life"], ceph.NONE_CELL)
        # Reef is the case that proves the two are different facts: its estimate
        # (2026-03-20) and its realized end of life (2025-03-20) are a year
        # apart, and only the realized one is published.
        reef = by_id["18.2"]
        self.assertEqual(reef["milestones"]["eol"], "2025-03-20")
        self.assertEqual(reef["upstream"]["cells"]["End of life (estimated)"], "2026-03-20")

    def test_the_table_a_branch_is_filed_under_matches_the_rendered_page(self):
        # The split is not inferred from the dates: the vendor's own extension
        # heads the current table "End of life (estimated)" and the archived one
        # "End of life", and emits a branch in one or the other. Verified
        # against https://docs.ceph.com/en/latest/releases/ (rendered
        # 2026-09-17): 2 rows under "End of life (estimated)", 15 under
        # "End of life", exactly these branches.
        releases, _ = parsed()
        current = {release["name"] for release in releases
                   if release["upstream"]["table"] == ceph.CURRENT_TABLE}
        archived = {release["name"] for release in releases
                    if release["upstream"]["table"] == ceph.ARCHIVED_TABLE}
        self.assertEqual(current, {"Tentacle", "Squid"})
        self.assertEqual(archived,
                         {"Reef", "Quincy", "Pacific", "Octopus", "Nautilus", "Mimic", "Luminous",
                          "Kraken", "Jewel", "Infernalis", "Hammer", "Giant", "Firefly", "Emperor",
                          "Dumpling"})
        # The archived table is exactly the branches that state a final date.
        self.assertEqual(archived,
                         {release["name"] for release in releases
                          if release["milestones"]["eol"] is not None})

    def test_ga_is_the_branchs_initial_stable_release(self):
        releases, _ = parsed()
        by_id = {release["id"]: release for release in releases}
        self.assertEqual(by_id["20.2"]["milestones"]["ga"], "2025-11-18")
        self.assertEqual(by_id["18.2"]["milestones"]["ga"], "2023-08-07")
        # The initial release is the oldest point release, not the branch's
        # first entry in the file, which the vendor orders newest first.
        self.assertEqual(by_id["0.94"]["milestones"]["ga"], "2015-04-01")
        # Ceph publishes no end-of-sale and no security-support-end column.
        for release in releases:
            self.assertIsNone(release["milestones"]["eos"])
            self.assertIsNone(release["milestones"]["eossec"])

    def test_a_branch_retired_without_an_estimate_states_no_estimate(self):
        releases, _ = parsed()
        by_id = {release["id"]: release for release in releases}
        # Infernalis, Giant and Emperor were retired with actual_eol only.
        for branch in ("9.2", "0.87", "0.72"):
            self.assertEqual(by_id[branch]["upstream"]["cells"]["End of life (estimated)"],
                             ceph.NONE_CELL)
            self.assertIsNotNone(by_id[branch]["milestones"]["eol"])

    def test_every_release_states_the_vendors_declared_columns(self):
        releases, _ = parsed()
        for release in releases:
            self.assertEqual(tuple(release["upstream"]["cells"]), ceph.CELLS)

    def test_development_builds_and_release_candidates_never_become_branches(self):
        _, excluded = parsed()
        reasons = [entry["reason"] for entry in excluded]
        self.assertEqual(sum(1 for reason in reasons if reason.startswith("development version")), 58)
        # A release candidate (x.1.z) is separated from the stable series it
        # precedes and never becomes a record of its own.
        published = {release["id"] for release in parsed()[0]}
        self.assertNotIn("20.1", published)
        self.assertNotIn("19.1", published)

    def test_a_branch_the_metadata_has_no_record_for_is_accounted_not_dropped(self):
        _, excluded = parsed()
        undocumented = [entry for entry in excluded
                        if entry["reason"].startswith("named in the release page's branch index")]
        self.assertEqual([entry["row"] for entry in undocumented],
                         ["Cuttlefish (0.61)", "Bobtail (0.56)", "Argonaut (0.48)"])
        # None of them carries a date, so none is published.
        published = {release["id"] for release in parsed()[0]}
        self.assertEqual(published & {"0.61", "0.56", "0.48"}, set())

    def test_parse_is_deterministic(self):
        self.assertEqual(parsed(), parsed())


class RefusalTests(unittest.TestCase):
    """A source that stops stating what the parser reads fails instead of guessing."""

    def document(self):
        return copy.deepcopy(ceph._payload(DATA))

    def render(self, mutate):
        payload = self.document()
        mutate(payload)
        return yaml.safe_dump(payload)

    def test_an_unparseable_date_fails_rather_than_becoming_a_guess(self):
        with self.assertRaisesRegex(ValueError, "unrecognized lifecycle date"):
            ceph.parse_releases(self.render(
                lambda p: p["releases"]["squid"].__setitem__("target_eol", "soon")), INDEX)

    def test_a_version_naming_no_stable_series_fails(self):
        with self.assertRaisesRegex(ValueError, "names no stable series"):
            ceph.parse_releases(self.render(
                lambda p: p["releases"]["squid"]["releases"].append(
                    {"version": "19.2.7.1", "released": "2026-09-01"})), INDEX)

    def test_metadata_without_a_releases_mapping_fails(self):
        with self.assertRaisesRegex(ValueError, "declares no `releases` mapping"):
            ceph.parse_releases("just: a string\n", INDEX)

    def test_a_branch_stating_no_releases_fails(self):
        with self.assertRaisesRegex(ValueError, "states no releases"):
            ceph.parse_releases(self.render(
                lambda p: p["releases"]["squid"].__setitem__("releases", [])), INDEX)

    def test_a_page_index_stating_no_branch_fails(self):
        with self.assertRaisesRegex(ValueError, "states no branch"):
            ceph.parse_releases(DATA, "")

    def test_two_branches_claiming_one_series_fail(self):
        def collide(payload):
            payload["releases"]["squid"]["releases"].append({"version": "20.2.9",
                                                            "released": "2026-09-02"})
        with self.assertRaisesRegex(ValueError, "claim the same series"):
            ceph.parse_releases(self.render(collide), INDEX)


class RecordTests(unittest.TestCase):
    def record(self):
        return ceph.record_for(parsed()[0], CHECKED)

    def test_record_names_its_registered_source_and_publishes_no_identifier(self):
        record = self.record()
        self.assertEqual(record["provenance"]["verifier"], ceph.VERIFIER)
        self.assertEqual(sources.source_for(ceph.VERIFIER).id, "import-ceph")
        self.assertEqual(record["provenance"]["source_url"], ceph.SOURCE_URL)
        # The Ceph project publishes no CPE for its release branches.
        self.assertEqual(record["identifiers"], [])

    def test_a_release_is_publishable_only_through_the_schema(self):
        from jsonschema import Draft202012Validator, FormatChecker

        schema = json.loads((ROOT / "schema/product.json").read_text())
        Draft202012Validator(schema, format_checker=FormatChecker()).validate(self.record())

    def test_validate_record_accepts_what_the_source_states(self):
        ceph.validate_record(self.record())

    def test_validate_record_refuses_an_estimate_written_into_eol(self):
        # This is the rule the whole collector exists to hold: the estimate must
        # not be publishable as a final date even by editing the file.
        record = self.record()
        record["releases"][0]["milestones"]["eol"] = ESTIMATED_ONLY["20.2"]
        with self.assertRaisesRegex(ValueError, "eol contradicts its stored cells"):
            ceph.validate_record(record)

    def test_validate_record_refuses_a_ga_the_cells_do_not_state(self):
        record = self.record()
        record["releases"][5]["milestones"]["ga"] = "1999-01-01"
        with self.assertRaisesRegex(ValueError, "ga contradicts its stored initial release"):
            ceph.validate_record(record)

    def test_validate_record_refuses_a_milestone_ceph_does_not_publish(self):
        record = self.record()
        record["releases"][3]["milestones"]["eos"] = "2025-01-01"
        with self.assertRaisesRegex(ValueError, "claims a milestone the Ceph source does not publish"):
            ceph.validate_record(record)

    def test_validate_record_refuses_reordered_or_missing_columns(self):
        record = self.record()
        cells = record["releases"][2]["upstream"]["cells"]
        record["releases"][2]["upstream"]["cells"] = dict(reversed(list(cells.items())))
        with self.assertRaisesRegex(ValueError, "does not carry the vendor's declared columns"):
            ceph.validate_record(record)

    def test_validate_record_refuses_a_release_naming_the_wrong_series(self):
        record = self.record()
        record["releases"][1]["id"] = "18.2"
        with self.assertRaisesRegex(ValueError, "does not name its own series"):
            ceph.validate_record(record)

    def test_validate_record_refuses_another_sources_verifier(self):
        record = self.record()
        record["provenance"]["verifier"] = sources.source("import-data").verifier
        with self.assertRaisesRegex(ValueError, "Invalid Ceph source identity"):
            ceph.validate_record(record)

    def test_validate_record_refuses_a_table_the_cells_contradict(self):
        record = self.record()
        # A branch with no realized end of life belongs to the current table;
        # filing it under the archived one would present it as ended.
        record["releases"][0]["upstream"]["table"] = ceph.ARCHIVED_TABLE
        with self.assertRaisesRegex(ValueError, "disagrees with the table its own cells"):
            ceph.validate_record(record)

    def test_a_branch_the_metadata_no_longer_states_is_retained_not_deleted(self):
        releases, _ = parsed()
        committed = ceph.record_for(releases, CHECKED)
        fresh = [release for release in releases if release["id"] != "18.2"]
        combined, kept = ceph.combine_releases(fresh, committed)
        self.assertEqual([entry["id"] for entry in kept], ["18.2"])
        self.assertEqual([entry["name"] for entry in kept], ["Reef"])
        retained = {release["id"]: release for release in combined}["18.2"]
        self.assertIs(retained["upstream"]["in_source"], False)
        self.assertEqual(retained["milestones"]["eol"], "2025-03-20")
        # Absence from the metadata is not an end of life; the row stays publishable.
        ceph.validate_record(ceph.record_for(combined, CHECKED))

    def test_freshly_parsed_releases_carry_no_retention_marker(self):
        combined, kept = ceph.combine_releases(parsed()[0], None)
        self.assertEqual(kept, [])
        self.assertTrue(all("in_source" not in release["upstream"] for release in combined))

    def test_estimated_only_lists_the_branches_without_a_final_date(self):
        entries = ceph.estimated_only(parsed()[0])
        self.assertEqual([entry["id"] for entry in entries], ["20.2", "19.2"])
        self.assertEqual({entry["estimated_eol"] for entry in entries},
                         set(ESTIMATED_ONLY.values()))
        for entry in entries:
            self.assertIn("not normalized into milestones.eol", entry["reason"])


class FeedSafetyTests(unittest.TestCase):
    """An estimate must not leave the catalog as a syndicated deadline."""

    def record(self):
        return ceph.record_for(parsed()[0], CHECKED)

    def documents(self):
        """Every feed document the build writes, by file name."""
        from engine import feeds

        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        feeds.build([self.record()], [], Path(temp.name))
        return {path.name: path.read_text(encoding="utf-8")
                for path in sorted(Path(temp.name).rglob("*")) if path.is_file()}

    def test_no_estimated_date_appears_in_any_published_document(self):
        documents = self.documents()
        self.assertTrue(documents)
        for name, text in documents.items():
            self.assertNotIn(ESTIMATED_ONLY["20.2"], text, name)
            self.assertNotIn(ESTIMATED_ONLY["19.2"], text, name)

    def test_only_facts_the_source_states_as_final_become_events(self):
        from engine import feeds

        events = feeds.software_events([self.record()])
        self.assertEqual({event["milestone"] for event in events}, {"ga", "eol"})
        dates = {event["date"] for event in events}
        self.assertEqual(dates & set(ESTIMATED_ONLY.values()), set())
        # Reef's estimate is not an event; its realized end of life is.
        self.assertNotIn("2026-03-20", dates)
        self.assertIn("2025-03-20", dates)

    def test_a_branch_with_only_an_estimate_contributes_no_eol_event(self):
        from engine import feeds

        events = feeds.software_events([self.record()])
        asserted = {event["release_id"] for event in events if event["milestone"] == "eol"}
        self.assertEqual(asserted & set(ESTIMATED_ONLY), set())
        self.assertEqual(len(asserted), 15)

    def test_the_absence_of_an_estimate_is_not_an_artifact_of_the_test(self):
        # Control for the tests above: were the estimate normalized into eol, it
        # would be syndicated immediately. So their passing is a property of the
        # record, not of a feed that happens to carry nothing, and the guard
        # that stops such a record being published at all still fires.
        from engine import feeds

        wrong = copy.deepcopy(self.record())
        wrong["releases"][0]["milestones"]["eol"] = ESTIMATED_ONLY["20.2"]
        dates = {event["date"] for event in feeds.software_events([wrong])}
        self.assertIn(ESTIMATED_ONLY["20.2"], dates)
        with self.assertRaisesRegex(ValueError, "eol contradicts its stored cells"):
            ceph.validate_record(wrong)


class CatalogRootCase(unittest.TestCase):
    """A data directory holding an import-data product, as the committed one does."""

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.sibling = software_record()
        catalog_root(self.root, [self.sibling])
        self.sibling_bytes = (self.root / "products/sample.json").read_bytes()

    def publish(self, data=DATA, index=INDEX):
        releases, excluded = ceph.parse_releases(data, index)
        record = ceph.record_for(releases, CHECKED)
        report = ceph.report_for(releases, excluded, [], CHECKED)
        return ceph.publish_record(record, report, self.root)


class PublicationTests(CatalogRootCase):
    def test_publish_writes_only_its_own_record_and_report(self):
        self.publish()
        record = json.loads((self.root / "products/ceph.json").read_text())
        self.assertEqual(record["id"], "ceph")
        self.assertEqual(len(record["releases"]), 17)
        self.assertEqual((self.root / "products/sample.json").read_bytes(), self.sibling_bytes)
        report = json.loads((self.root / ceph.REPORT).read_text())
        self.assertEqual(report["total_records"], 1)
        self.assertEqual(report["rows"]["published"], 17)
        self.assertEqual(report["rows"]["active"], 2)
        self.assertEqual(report["rows"]["archived"], 15)
        self.assertEqual(len(validation.validate_data(self.root)), 2)

    def test_report_accounts_for_every_row_it_saw(self):
        releases, excluded = parsed()
        report = ceph.report_for(releases, excluded, [], CHECKED)
        self.assertEqual(report["rows"]["seen"],
                         report["rows"]["published"] - report["rows"]["retained"]
                         + report["rows"]["excluded"])
        self.assertEqual(report["rows"]["seen"], 78)
        self.assertEqual({entry["id"] for entry in report["estimated_only"]},
                         set(ESTIMATED_ONLY))
        self.assertTrue(any("estimated end of life" in line for line in report["limitations"]))
        self.assertTrue(any("24" in line and "months" in line for line in report["limitations"]))
        self.assertTrue(any("Commercial downstream" in line for line in report["limitations"]))

    def test_republishing_an_unchanged_source_is_byte_identical(self):
        published = self.publish()
        before = (self.root / "products/ceph.json").read_bytes()
        again = self.publish()
        self.assertEqual((self.root / "products/ceph.json").read_bytes(), before)
        self.assertEqual(published["provenance"]["last_checked"],
                         again["provenance"]["last_checked"])
        self.assertEqual(again["provenance"]["last_checked"], CHECKED)

    def test_a_record_another_source_owns_is_never_overwritten(self):
        self.sibling["id"] = "ceph"
        dump(self.root / "products/ceph.json", self.sibling)
        with mock.patch.object(net, "get_text") as fetch:
            with self.assertRaisesRegex(ValueError, "ownership collision"):
                ceph.import_ceph(self.root)
        fetch.assert_not_called()
        self.assertEqual(json.loads((self.root / "products/ceph.json").read_text()),
                         self.sibling)

    def test_a_parse_failure_writes_nothing(self):
        # Valid YAML that declares no branches is the shape a source change
        # would actually produce; the run must abort rather than publish a
        # record that silently drops every branch.
        with mock.patch.object(net, "get_text", return_value="releases: {}\n"):
            with self.assertRaisesRegex(ValueError, "produced no branches"):
                ceph.import_ceph(self.root)
        self.assertEqual(sorted(path.name for path in (self.root / "products").glob("*.json")),
                         ["sample.json"])
        self.assertFalse((self.root / ceph.REPORT).exists())

    def test_import_publishes_the_record_and_its_registry_report(self):
        with mock.patch.object(net, "get_text", side_effect=[DATA, INDEX]) as fetch:
            detail = ceph.import_ceph(self.root)
        self.assertEqual(fetch.call_args_list,
                         [mock.call(ceph.DATA_URL), mock.call(ceph.INDEX_URL)])
        self.assertEqual((self.root / "products/sample.json").read_bytes(), self.sibling_bytes)
        self.assertIn("17 Ceph release branches (2 active", detail)
        self.assertIn("2 carry an estimate only", detail)
        self.assertIn(ceph.REPORT, detail)
        self.assertEqual(json.loads((self.root / ceph.REPORT).read_text())["verifier"],
                         ceph.VERIFIER)

    def without(self, branch="reef"):
        """The fixture with one whole branch block removed, as a dropped row."""
        payload = yaml.safe_load(DATA)
        del payload["releases"][branch]
        return yaml.safe_dump(payload)

    def test_import_retains_a_committed_branch_the_metadata_dropped(self):
        with mock.patch.object(net, "get_text", side_effect=[DATA, INDEX]):
            ceph.import_ceph(self.root)
        with mock.patch.object(net, "get_text",
                               side_effect=[self.without("reef"), INDEX]):
            detail = ceph.import_ceph(self.root)
        self.assertIn("retained 1", detail)
        record = json.loads((self.root / "products/ceph.json").read_text())
        retained = {release["id"]: release for release in record["releases"]}["18.2"]
        self.assertIs(retained["upstream"]["in_source"], False)
        report = json.loads((self.root / ceph.REPORT).read_text())
        self.assertEqual(report["retained"][0]["id"], "18.2")
        self.assertEqual(report["rows"]["retained"], 1)
        # The retained row is accounted apart from the rows this fetch saw, and
        # the row identity still holds: the 16 branches this fetch published
        # plus 62 excluded rows (58 development entries, and now 4 index-only
        # branches, reef among them) are the 78 rows the two sources stated.
        self.assertEqual(report["rows"]["published"], 17)
        self.assertEqual(report["rows"]["seen"],
                         report["rows"]["published"] - report["rows"]["retained"]
                         + report["rows"]["excluded"])
        self.assertIn("Reef (18.2)", [entry["row"] for entry in report["excluded"]])
        validation.validate_data(self.root)


class RegistryIntegrationTests(CatalogRootCase):
    def save_ceph(self, verifier=None):
        releases, _ = parsed()
        record = ceph.record_for(releases, CHECKED)
        if verifier:
            record["provenance"]["verifier"] = verifier
        dump(self.root / "products/ceph.json", record)
        return record

    def test_validate_data_dispatches_to_the_owning_sources_validator(self):
        self.save_ceph()
        records = validation.validate_data(self.root)
        self.assertEqual(sorted(record["id"] for record in records), ["ceph", "sample"])

    def test_validate_data_refuses_a_ceph_milestone_that_drifted(self):
        record = self.save_ceph()
        record["releases"][3]["milestones"]["eol"] = "2030-01-01"
        dump(self.root / "products/ceph.json", record)
        with self.assertRaisesRegex(ValueError, "contradicts its stored cells"):
            validation.validate_data(self.root)

    def test_validate_data_refuses_an_estimate_published_as_eol(self):
        record = self.save_ceph()
        record["releases"][1]["milestones"]["eol"] = ESTIMATED_ONLY["19.2"]
        dump(self.root / "products/ceph.json", record)
        with self.assertRaisesRegex(ValueError, "eol contradicts its stored cells"):
            validation.validate_data(self.root)

    def test_manifest_counts_cover_only_the_source_that_publishes_them(self):
        self.save_ceph()
        # The manifest still describes the endoflife.date snapshot alone; the
        # Ceph shard is carried additively beside it and is not counted in.
        validation.validate_data(self.root)
        manifest = json.loads((self.root / "manifest.json").read_text())
        self.assertEqual(manifest["product_count"], 1)
        manifest["product_count"] = 2
        dump(self.root / "manifest.json", manifest)
        with self.assertRaisesRegex(ValueError, "Manifest counts do not match"):
            validation.validate_data(self.root)

    def test_sidecar_must_account_for_the_records_its_source_owns(self):
        self.save_ceph()
        dump(self.root / ceph.REPORT, {"verifier": ceph.VERIFIER, "total_records": 1})
        validation.validate_data(self.root)
        dump(self.root / ceph.REPORT, {"verifier": ceph.VERIFIER, "total_records": 2})
        with self.assertRaisesRegex(ValueError, "reports 2 records but 1 carry"):
            validation.validate_data(self.root)

    def test_the_registry_registers_the_pages_this_collector_reads(self):
        source = sources.source("import-ceph")
        self.assertEqual(source.category, "software")
        self.assertEqual(source.report, ceph.REPORT)
        self.assertEqual(source.validator, "engine.ceph.validate_record")
        # The data file is the page the registry publishes for this source, so
        # the site can credit the file the dates were actually read from.
        self.assertIn(ceph.DATA_URL, source.urls)
        self.assertIn(ceph.SOURCE_URL, source.urls)


class ImportPreservationTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.ceph = ceph.record_for(parsed()[0], CHECKED)
        catalog_root(self.root, [software_record(), self.ceph])
        self.bytes = (self.root / "products/ceph.json").read_bytes()

    def test_import_data_carries_a_foreign_software_record_through_untouched(self):
        listing = {"result": [{"name": "sample", "category": "lang"}], "total": 1}
        detail = {"result": {"name": "sample", "label": "Sample", "category": "lang",
                             "labels": {"eol": "Security Support"},
                             "releases": [{"name": "1", "eolFrom": "2028-01-01"}]},
                  "last_modified": None}

        def fetch(url):
            return listing if url == API else detail

        with mock.patch.object(importer, "fetch", side_effect=fetch):
            summary = importer.import_data(self.root)
        self.assertIn("imported 1 software products", summary)
        self.assertEqual((self.root / "products/ceph.json").read_bytes(), self.bytes)
        manifest = json.loads((self.root / "manifest.json").read_text())
        self.assertEqual((manifest["product_count"], manifest["release_count"]), (1, 1))
        self.assertEqual(len(validation.validate_data(self.root)), 2)


if __name__ == "__main__":
    unittest.main()
