"""Regression tests for the NVIDIA vGPU collector, its registry entry and ownership.

The fixture is the vendor page's own Markdown mirror (the tables the refresh
parses), so these tests pin the parse against the real source: every branch row
is accounted for, the month precision the vendor states never becomes a day, a
table's latest-release date never becomes a branch GA, and a branch the current
tables no longer state is retained rather than deleted. They also pin the two
ownership rules the shared catalog depends on — this source writes only its own
record, and import-data carries foreign software records through untouched.
"""
import json
import re
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from engine import importer, net, sources, validation, vgpu
from engine.importer import API, dump, normalize

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/vgpu-index.md"
MARKDOWN = FIXTURE.read_text(encoding="utf-8")
CHECKED = "2026-09-17T12:00:00Z"
MONTH = re.compile(r"\d{4}-(?:0[1-9]|1[0-2])$")


def parsed():
    return vgpu.parse_branches(MARKDOWN)


def software_record(name="sample", verifier=sources.source("import-data").verifier):
    record = normalize({"result": {"name": name, "label": name.title(), "category": "lang",
                                   "labels": {"eol": "Security Support"},
                                   "releases": [{"name": "1", "eolFrom": "2028-01-01"}]}}, CHECKED)
    record["provenance"]["verifier"] = verifier
    return record


def stage_sidecars(directory, records):
    """Stage the accounting sidecar each written record's source owns.

    Validation requires a source's report beside the records it owns, so a test
    that writes a collector's record directly stages the minimal honest sidecar
    (its verifier and record count) instead of bypassing the gate. The
    import-data source publishes no sidecar, so it contributes none.
    """
    counts = {}
    for record in records:
        verifier = record["provenance"]["verifier"]
        counts[verifier] = counts.get(verifier, 0) + 1
    for verifier, count in counts.items():
        report = sources.source_for(verifier).report
        if report:
            dump(directory / report, {"verifier": verifier, "total_records": count})


def catalog_root(directory, records):
    """A data directory holding ``records`` and the manifest the importer writes."""
    (directory / "products").mkdir(parents=True, exist_ok=True)
    for record in records:
        dump(directory / "products" / (record["id"] + ".json"), record)
    stage_sidecars(directory, records)
    counted = [record for record in records
               if record["provenance"]["verifier"] == sources.source("import-data").verifier]
    dump(directory / "manifest.json", {
        "generated_at": CHECKED, "source_url": API, "product_count": len(counted),
        "release_count": sum(len(record["releases"]) for record in counted),
        "excluded_hardware": [], "source": "import-data"})


class SchemaFormatTests(unittest.TestCase):
    """The milestone shape both precision forms, and admits nothing else."""

    def validator(self):
        from jsonschema import Draft202012Validator, FormatChecker

        return Draft202012Validator(json.loads((ROOT / "schema/product.json").read_text()),
                                    format_checker=FormatChecker())

    def record(self, value):
        record = software_record()
        record["releases"][0]["milestones"]["eol"] = value
        return record

    def test_a_month_is_admitted_beside_a_full_day(self):
        validator = self.validator()
        for value in ("2028-07", "2028-07-01", None):
            validator.validate(self.record(value))

    def test_nothing_coarser_than_a_month_is_ever_admitted(self):
        validator = self.validator()
        for value in ("2028", "2028-7", "2028-13", "2028-00", "July 2028", "2028-07-01T00:00:00Z",
                      202807, True):
            with self.assertRaises(Exception, msg=repr(value)):
                validator.validate(self.record(value))


class ParseTests(unittest.TestCase):
    def test_real_fixture_accounts_for_every_branch_row(self):
        releases, excluded = parsed()
        self.assertEqual(excluded, [])
        self.assertEqual(len(releases), 18)
        self.assertEqual([release["id"] for release in releases],
                         ["19", "18", "17", "16", "15", "14", "13", "12", "11", "10",
                          "9", "8", "7", "6", "5", "4", "3", "2"])
        # Both tables contribute: the active ones first, exactly as published.
        tables = [release["upstream"]["table"] for release in releases]
        self.assertEqual(tables.count(vgpu.ACTIVE), 3)
        self.assertEqual(tables.count(vgpu.OLDER), 15)

    def test_release_id_is_the_branch_not_the_mutable_latest_release(self):
        releases, _ = parsed()
        latest = {release["id"]: release for release in releases}
        # 19.1 is what the branch currently ships; the branch is 19, so the id
        # survives the next patch release.
        self.assertEqual(latest["19"]["name"], "NVIDIA vGPU 19")
        self.assertEqual(latest["19"]["upstream"]["name"], "19.1")
        self.assertEqual(latest["16"]["upstream"]["name"], "16.11")
        self.assertEqual(latest["4"]["upstream"]["name"], "4.10")
        # GRID-branded historical rows are the same product's earlier branches.
        self.assertEqual(latest["2"]["name"], "NVIDIA GRID 2")

    def test_row_cells_are_stored_verbatim(self):
        releases, _ = parsed()
        row = {release["id"]: release for release in releases}["19"]["upstream"]["cells"]
        self.assertEqual(row, {
            "vGPU Software Release": "NVIDIA vGPU 19",
            "Driver Branch": "R580",
            "vGPU Branch Type": "Long-Term Support",
            "Latest Release in Branch": "19.1",
            "Release Date": "September 2025",
            "EOL Date": "July 2028",
        })

    def test_link_cells_are_read_as_text_never_as_href(self):
        # The 18 row's branch type is redirected through a mail scanner; the
        # vendor's words are "Production", so the scan URL is never parsed.
        releases, _ = parsed()
        published = json.dumps(releases)
        self.assertNotIn("safelinks", published)
        self.assertEqual({release["id"]: release for release in releases}["18"]
                         ["upstream"]["cells"]["vGPU Branch Type"], "Production")

    def test_footnote_marker_does_not_glue_onto_the_value_it_annotates(self):
        # "EOL[1](...)" is the branch type EOL plus a footnote reference; were
        # the marker kept, the type would not be recognized at all.
        releases, _ = parsed()
        cells = {release["id"]: release for release in releases}["6"]["upstream"]["cells"]
        self.assertEqual(cells["vGPU Branch Type"], "EOL")
        self.assertNotIn("[1]", "".join(cells.values()))

    def test_month_precision_never_becomes_a_day(self):
        releases, _ = parsed()
        for release in releases:
            for field, value in release["milestones"].items():
                if value is not None:
                    self.assertRegex(value, MONTH, f"{release['id']} {field}")
        stored = {release["id"]: release["milestones"] for release in releases}
        self.assertEqual(stored["19"]["eol"], "2028-07")
        self.assertEqual(stored["18"]["eol"], "2026-03")
        self.assertEqual(stored["16"]["eol"], "2026-07")
        self.assertEqual(stored["10"]["eol"], "2020-12")
        # A month that happens to be the first is still a month: 12.0 and 4.0
        # end in the literal "-01" the source never stated.
        self.assertEqual([release["id"] for release in releases
                          if release["milestones"]["eol"].endswith("-01")], ["12", "4"])
        for release in releases:
            if release["id"] in {"12", "4"}:
                self.assertEqual(len(release["milestones"]["eol"]), 7)

    def test_a_branchs_latest_release_date_is_never_mapped_to_ga(self):
        # "Release Date" belongs to the latest release in the branch, not to the
        # branch itself, so no GA is claimed from it.
        releases, _ = parsed()
        self.assertTrue(all(release["milestones"]["ga"] is None for release in releases))
        self.assertEqual({release["id"]: release for release in releases}["19"]
                         ["upstream"]["cells"]["Release Date"], "September 2025")

    def test_month_value_accepts_only_a_month_and_never_pads_it(self):
        self.assertEqual(vgpu.month_value("July 2028", "row"), "2028-07")
        self.assertEqual(vgpu.month_value("Sept 2020", "row"), "2020-09")
        self.assertIsNone(vgpu.month_value("TBD", "row"))
        for text in ("2028-07", "Q3 2028", "July 2028-01", "July"):
            with self.assertRaisesRegex(ValueError, "unrecognized month-precision date"):
                vgpu.month_value(text, "row")

    def test_a_row_without_an_eol_keeps_a_null_milestone(self):
        markdown = MARKDOWN.replace("| July 2028 |", "| TBD |", 1)
        releases, excluded = vgpu.parse_branches(markdown)
        self.assertEqual(excluded, [])
        self.assertIsNone({release["id"]: release for release in releases}["19"]
                          ["milestones"]["eol"])

    def test_unplaceable_rows_are_reported_not_dropped(self):
        orphan = "| NVIDIA vGPU preview | R590 | Production | 20.0 | August 2025 | July 2030 |\n"
        duplicate = [line for line in MARKDOWN.splitlines() if line.startswith("| [NVIDIA vGPU 16]")][0]
        markdown = MARKDOWN.replace("#### Older", orphan + "\n#### Older", 1)
        markdown = markdown.replace("#### Older vGPU", duplicate + "\n#### Older vGPU", 1)
        releases, excluded = vgpu.parse_branches(markdown)
        self.assertEqual(len(releases), 18)
        self.assertEqual([entry["reason"] for entry in excluded],
                         ["no branch number in the release name",
                          "duplicate branch row for release '16'"])
        self.assertEqual([entry["table"] for entry in excluded], [vgpu.ACTIVE, vgpu.ACTIVE])

    def test_an_identical_duplicate_row_is_reconciled_and_every_cell_is_compared(self):
        # An exact restatement is a duplicate, not a conflict: the branch is
        # published once and the second row is accounted.
        duplicate = [line for line in MARKDOWN.splitlines() if line.startswith("| [NVIDIA vGPU 19]")][0]
        markdown = MARKDOWN.replace("#### Older", duplicate + "\n#### Older", 1)
        releases, excluded = vgpu.parse_branches(markdown)
        self.assertEqual([release["id"] for release in releases].count("19"), 1)
        self.assertEqual([entry["reason"] for entry in excluded],
                         ["duplicate branch row for release '19'"])
        self.assertEqual(vgpu.parse_branches(markdown), vgpu.parse_branches(markdown))

    def test_a_duplicate_row_contradicting_a_lifecycle_cell_refuses_the_parse(self):
        # The driver branch is a lifecycle-bearing cell the old first-wins path
        # never compared: a second row claiming 19 under another branch is the
        # vendor contradicting itself about the branch, not a duplicate.
        original = [line for line in MARKDOWN.splitlines() if line.startswith("| [NVIDIA vGPU 19]")][0]
        for column, replacement in (
                ("Driver Branch", original.replace("| R580 |", "| R560 |")),
                ("vGPU Branch Type", original.replace("Long-Term Support", "Production")),
                ("Latest Release in Branch", original.replace("| 19.1 |", "| 19.2 |")),
                ("Release Date", original.replace("September 2025", "October 2025")),
                ("EOL Date", original.replace("July 2028", "August 2028"))):
            with self.subTest(column=column):
                markdown = MARKDOWN.replace("#### Older", replacement + "\n#### Older", 1)
                with self.assertRaisesRegex(ValueError, "stated twice with contradicting values"):
                    vgpu.parse_branches(markdown)

    def test_a_header_only_branch_table_refuses_the_refresh(self):
        # A partial inventory is a table with its headers and no rows; without
        # this check the other table's rows would publish as the whole catalog.
        def header_only(markdown, heading):
            lines = markdown.splitlines()
            start = lines.index("#### " + heading)
            index = start + 3  # the heading, the header row and the separator
            while index < len(lines) and lines[index].strip().startswith("|"):
                index += 1
            return "\n".join(lines[:start + 3] + lines[index:])

        with self.assertRaisesRegex(ValueError, "Active vGPU Software Releases.*no data rows"):
            vgpu.parse_branches(header_only(MARKDOWN, vgpu.ACTIVE))
        with self.assertRaisesRegex(ValueError, "Older vGPU Software Releases.*no data rows"):
            vgpu.parse_branches(header_only(MARKDOWN, vgpu.OLDER))

    def test_reshaped_headers_refuse_the_parse(self):
        markdown = MARKDOWN.replace("| EOL Date |", "| End of Life |", 1)
        with self.assertRaisesRegex(ValueError, "Unexpected vGPU table headers"):
            vgpu.parse_branches(markdown)

    def test_a_missing_table_refuses_the_parse(self):
        markdown = MARKDOWN.split("#### Older vGPU Software Releases")[0]
        with self.assertRaisesRegex(ValueError, "Missing vGPU branch table"):
            vgpu.parse_branches(markdown)

    def test_unknown_branch_type_refuses_the_parse(self):
        markdown = MARKDOWN.replace("| EOL | 5.4 |", "| Retired | 5.4 |", 1)
        with self.assertRaisesRegex(ValueError, "unknown vGPU branch type"):
            vgpu.parse_branches(markdown)

    def test_parsing_twice_is_identical(self):
        self.assertEqual(parsed(), parsed())


class RecordTests(unittest.TestCase):
    def test_record_names_its_registered_source_and_publishes_no_identifier(self):
        releases, _ = parsed()
        record = vgpu.record_for(releases, CHECKED)
        self.assertEqual(record["id"], "nvidia-vgpu")
        self.assertEqual(record["category"], "software")
        self.assertEqual(record["provenance"]["verifier"], sources.source("import-vgpu").verifier)
        self.assertEqual(record["provenance"]["source_url"], sources.NVIDIA_VGPU_DOCS)
        self.assertEqual(record["links"]["html"], sources.NVIDIA_VGPU_DOCS)
        # The vendor states no CPE for this product; none is invented.
        self.assertEqual(record["identifiers"], [])

    def test_validate_record_rederives_every_milestone_from_the_stored_cells(self):
        releases, _ = parsed()
        record = vgpu.record_for(releases, CHECKED)
        vgpu.validate_record(record)
        drifted = json.loads(json.dumps(record))
        drifted["releases"][0]["milestones"]["eol"] = "2029-07"
        with self.assertRaisesRegex(ValueError, "contradicts its stored cells"):
            vgpu.validate_record(drifted)

    def test_validate_record_refuses_a_release_claiming_another_branch(self):
        releases, _ = parsed()
        record = vgpu.record_for(releases, CHECKED)
        record["releases"][0]["id"] = "20"
        with self.assertRaisesRegex(ValueError, "does not name its own branch"):
            vgpu.validate_record(record)

    def test_validate_record_refuses_another_sources_verifier(self):
        releases, _ = parsed()
        record = vgpu.record_for(releases, CHECKED)
        record["provenance"]["verifier"] = sources.source("import-data").verifier
        with self.assertRaisesRegex(ValueError, "Invalid NVIDIA vGPU source identity"):
            vgpu.validate_record(record)

    def test_a_branch_the_tables_no_longer_state_is_retained_not_deleted(self):
        releases, _ = parsed()
        committed = vgpu.record_for(releases, CHECKED)
        fresh = [release for release in releases if release["id"] != "16"]
        combined, kept = vgpu.combine_releases(fresh, committed)
        self.assertEqual([entry["id"] for entry in kept], ["16"])
        retained = {release["id"]: release for release in combined}["16"]
        self.assertIs(retained["upstream"]["in_source"], False)
        self.assertEqual(retained["milestones"]["eol"], "2026-07")
        # The retained row is still publishable: absence from a table is not an
        # end of life, and its dates stay the ones the vendor published.
        vgpu.validate_record(vgpu.record_for(combined, CHECKED))

    def test_freshly_parsed_releases_carry_no_retention_marker(self):
        combined, kept = vgpu.combine_releases(parsed()[0], None)
        self.assertEqual(kept, [])
        self.assertTrue(all("in_source" not in release["upstream"] for release in combined))


class CatalogRootCase(unittest.TestCase):
    """A data directory holding an import-data product, as the committed one does."""

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.sibling = software_record()
        catalog_root(self.root, [self.sibling])
        self.sibling_bytes = (self.root / "products/sample.json").read_bytes()

    def publish(self, markdown=MARKDOWN):
        releases, excluded = vgpu.parse_branches(markdown)
        record = vgpu.record_for(releases, CHECKED)
        report = vgpu.report_for(releases, excluded, [], CHECKED)
        return vgpu.publish_record(record, report, self.root)


class PublicationTests(CatalogRootCase):
    def test_publish_writes_only_its_own_record_and_report(self):
        self.publish()
        record = json.loads((self.root / "products/nvidia-vgpu.json").read_text())
        self.assertEqual(record["id"], "nvidia-vgpu")
        self.assertEqual((self.root / "products/sample.json").read_bytes(), self.sibling_bytes)
        report = json.loads((self.root / vgpu.REPORT).read_text())
        self.assertEqual(report["total_records"], 1)
        self.assertEqual(report["rows"]["published"], 18)
        self.assertEqual(report["rows"]["excluded"], 0)
        self.assertEqual(len(validation.validate_data(self.root)), 2)

    def test_report_accounts_for_every_row_it_saw(self):
        orphan = "| NVIDIA vGPU preview | R590 | EOL | 1.0 | January 2020 | January 2020 |\n"
        releases, excluded = vgpu.parse_branches(
            MARKDOWN.replace("#### Older", orphan + "\n#### Older", 1))
        report = vgpu.report_for(releases, excluded, [], CHECKED)
        self.assertEqual(report["rows"]["seen"], report["rows"]["published"] + report["rows"]["excluded"])
        self.assertEqual(report["rows"]["seen"], 19)
        self.assertEqual([entry["reason"] for entry in report["excluded"]],
                         ["no branch number in the release name"])
        self.assertTrue(any("Month precision" in line for line in report["limitations"]))
        self.assertTrue(any("ga is absent" in line for line in report["limitations"]))

    def test_republishing_an_unchanged_source_is_byte_identical(self):
        published = self.publish()
        before = (self.root / "products/nvidia-vgpu.json").read_bytes()
        again = self.publish()
        self.assertEqual((self.root / "products/nvidia-vgpu.json").read_bytes(), before)
        self.assertEqual(published["provenance"]["last_checked"],
                         again["provenance"]["last_checked"])
        self.assertEqual(again["provenance"]["last_checked"], CHECKED)

    def test_a_record_another_source_owns_is_never_overwritten(self):
        # The product file carries a verifier this pipeline does not own.
        self.sibling["id"] = "nvidia-vgpu"
        dump(self.root / "products/nvidia-vgpu.json", self.sibling)
        with mock.patch.object(net, "get_text") as fetch:
            with self.assertRaisesRegex(ValueError, "ownership collision"):
                vgpu.import_vgpu(self.root)
        fetch.assert_not_called()
        self.assertEqual(json.loads((self.root / "products/nvidia-vgpu.json").read_text()),
                         self.sibling)

    def test_a_parse_failure_writes_nothing(self):
        with mock.patch.object(net, "get_text", return_value=MARKDOWN.split("#### Older")[0]):
            with self.assertRaisesRegex(ValueError, "Missing vGPU branch table"):
                vgpu.import_vgpu(self.root)
        self.assertEqual(sorted(path.name for path in (self.root / "products").glob("*.json")),
                         ["sample.json"])
        self.assertFalse((self.root / vgpu.REPORT).exists())

    def test_a_header_only_current_table_refuses_both_the_first_run_and_a_refresh(self):
        # The required tables are authoritative; a header-only one is a partial
        # snapshot, not a smaller catalog. On a first run there is no committed
        # record to fall back on, and the same refusal keeps an existing snapshot
        # rather than replacing it with the other table's rows.
        def header_only(markdown, heading):
            lines = markdown.splitlines()
            start = lines.index("#### " + heading)
            index = start + 3
            while index < len(lines) and lines[index].strip().startswith("|"):
                index += 1
            return "\n".join(lines[:start + 3] + lines[index:])

        partial = header_only(MARKDOWN, vgpu.ACTIVE)
        with mock.patch.object(net, "get_text", return_value=partial):
            with self.assertRaisesRegex(ValueError, "Active vGPU Software Releases.*no data rows"):
                vgpu.import_vgpu(self.root)
        self.assertEqual(sorted(path.name for path in (self.root / "products").glob("*.json")),
                         ["sample.json"])
        self.assertFalse((self.root / vgpu.REPORT).exists())
        with mock.patch.object(net, "get_text", return_value=MARKDOWN):
            vgpu.import_vgpu(self.root)
        published = (self.root / "products/nvidia-vgpu.json").read_bytes()
        with mock.patch.object(net, "get_text", return_value=partial):
            with self.assertRaisesRegex(ValueError, "Active vGPU Software Releases.*no data rows"):
                vgpu.import_vgpu(self.root)
        self.assertEqual((self.root / "products/nvidia-vgpu.json").read_bytes(), published)

    def test_a_contradicting_duplicate_row_refuses_the_refresh(self):
        # The duplicate check is part of the fetch path, not only the parser: a
        # contradicting row leaves the committed record and report untouched.
        with mock.patch.object(net, "get_text", return_value=MARKDOWN):
            vgpu.import_vgpu(self.root)
        published = (self.root / "products/nvidia-vgpu.json").read_bytes()
        row = next(line for line in MARKDOWN.splitlines() if line.startswith("| [NVIDIA vGPU 19]"))
        conflicting = MARKDOWN.replace("| July 2028 |", "| August 2028 |", 1)
        conflicting = conflicting.replace("#### Older", row + "\n#### Older", 1)
        with mock.patch.object(net, "get_text", return_value=conflicting):
            with self.assertRaisesRegex(ValueError, "stated twice with contradicting values"):
                vgpu.import_vgpu(self.root)
        self.assertEqual((self.root / "products/nvidia-vgpu.json").read_bytes(), published)

    def test_import_publishes_the_record_and_its_registry_report(self):
        with mock.patch.object(net, "get_text", return_value=MARKDOWN) as fetch:
            detail = vgpu.import_vgpu(self.root)
        fetch.assert_called_once_with(vgpu.MARKDOWN_URL)
        self.assertEqual(vgpu.MARKDOWN_URL, sources.NVIDIA_VGPU_DOCS + ".md")
        self.assertEqual((self.root / "products/sample.json").read_bytes(), self.sibling_bytes)
        self.assertIn("18 NVIDIA vGPU branch releases (3 active", detail)
        self.assertIn(vgpu.REPORT, detail)
        self.assertEqual(json.loads((self.root / vgpu.REPORT).read_text())["verifier"], vgpu.VERIFIER)

    def test_import_retains_a_committed_branch_the_tables_dropped(self):
        with mock.patch.object(net, "get_text", return_value=MARKDOWN):
            vgpu.import_vgpu(self.root)
        dropped = [line for line in MARKDOWN.splitlines() if line.startswith("| [NVIDIA vGPU 16]")][0]
        with mock.patch.object(net, "get_text", return_value=MARKDOWN.replace(dropped + "\n", "")):
            detail = vgpu.import_vgpu(self.root)
        self.assertIn("retained 1", detail)
        record = json.loads((self.root / "products/nvidia-vgpu.json").read_text())
        retained = {release["id"]: release for release in record["releases"]}["16"]
        self.assertIs(retained["upstream"]["in_source"], False)
        report = json.loads((self.root / vgpu.REPORT).read_text())
        self.assertEqual(report["retained"][0]["id"], "16")
        # The retained row is accounted apart from the rows this fetch saw.
        self.assertEqual(report["rows"]["seen"], 17)
        self.assertEqual(report["rows"]["retained"], 1)
        self.assertEqual(report["rows"]["active"] + report["rows"]["older"], 17)
        validation.validate_data(self.root)


class RegistryIntegrationTests(CatalogRootCase):
    def save_vgpu(self, verifier=None):
        releases, _ = parsed()
        record = vgpu.record_for(releases, CHECKED)
        if verifier:
            record["provenance"]["verifier"] = verifier
        dump(self.root / "products/nvidia-vgpu.json", record)
        stage_sidecars(self.root, [record])
        return record

    def test_validate_data_dispatches_to_the_owning_sources_validator(self):
        self.save_vgpu()
        records = validation.validate_data(self.root)
        self.assertEqual(sorted(record["id"] for record in records), ["nvidia-vgpu", "sample"])

    def test_validate_data_refuses_a_vgpu_milestone_that_drifted(self):
        record = self.save_vgpu()
        record["releases"][0]["milestones"]["eol"] = "2029-07"
        dump(self.root / "products/nvidia-vgpu.json", record)
        with self.assertRaisesRegex(ValueError, "contradicts its stored cells"):
            validation.validate_data(self.root)

    def test_manifest_counts_cover_only_the_source_that_publishes_them(self):
        self.save_vgpu()
        # The manifest still describes the endoflife.date snapshot alone: its
        # counts exclude another source's shard, carried additively beside it.
        validation.validate_data(self.root)
        manifest = json.loads((self.root / "manifest.json").read_text())
        self.assertEqual(manifest["product_count"], 1)
        manifest["product_count"] = 2
        dump(self.root / "manifest.json", manifest)
        with self.assertRaisesRegex(ValueError, "Manifest counts do not match"):
            validation.validate_data(self.root)

    def test_sidecar_must_account_for_the_records_its_source_owns(self):
        self.save_vgpu()
        dump(self.root / vgpu.REPORT, {"verifier": vgpu.VERIFIER, "total_records": 1})
        validation.validate_data(self.root)
        dump(self.root / vgpu.REPORT, {"verifier": vgpu.VERIFIER, "total_records": 2})
        with self.assertRaisesRegex(ValueError, "reports 2 records but 1 carry"):
            validation.validate_data(self.root)

    def test_a_sidecar_of_the_other_catalog_is_not_this_passes_business(self):
        self.save_vgpu()
        # An Opengear sidecar describes hardware records; the software pass
        # neither reads its counts nor fails on a missing hardware catalog.
        dump(self.root / "opengear-import.json", {"verifier": "deterministic-opengear",
                                                 "total_records": 99})
        self.assertEqual(len(validation.validate_data(self.root)), 2)


class ImportPreservationTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        releases, _ = parsed()
        self.vgpu = vgpu.record_for(releases, CHECKED)
        catalog_root(self.root, [software_record(), self.vgpu])
        self.bytes = (self.root / "products/nvidia-vgpu.json").read_bytes()

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
        self.assertEqual((self.root / "products/nvidia-vgpu.json").read_bytes(), self.bytes)
        # The manifest counts stay the importer's own snapshot: 1 product, 1 release.
        manifest = json.loads((self.root / "manifest.json").read_text())
        self.assertEqual((manifest["product_count"], manifest["release_count"]), (1, 1))
        self.assertEqual(len(validation.validate_data(self.root)), 2)


if __name__ == "__main__":
    unittest.main()
