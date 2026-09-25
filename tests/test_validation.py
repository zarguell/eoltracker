"""Regression tests for the catalog gate: schema, provenance and chronology.

The schema proves a record's shape; these tests pin the coherence rules it cannot
express. Each case re-derives from the committed files, so the checks are the
ones a hand-edited catalog actually hits. Failures are asserted by type rather
than by diagnostic wording: the message is for an operator reading a log, not a
contract another module depends on (AGENTS.md "assert exception types rather
than incidental Python wording").
"""
import copy
import json
import tempfile
import unittest
from pathlib import Path

from engine import validation
from engine.importer import API, dump, normalize
from engine.validation import (CatalogError, ChronologyError, ManifestError, MilestoneError,
                               ReportError, validate_data)

ROOT = Path(__file__).resolve().parents[1]
CHECKED = "2026-09-17T12:00:00Z"


def release(ga=None, eol=None):
    """One upstream release the importer can map, at the day precision it states."""
    payload = {"name": "1", "label": "1"}
    if ga is not None:
        payload["releaseDate"] = ga
    if eol is not None:
        payload["eolFrom"] = eol
    return payload


def dated(name, ga=None, eol=None):
    """A software record the importer itself produces, so only a rule can fail it."""
    return normalize({"result": {"name": name, "label": name, "category": "lang",
                                 "labels": {"eol": "End of Life"},
                                 "releases": [release(ga, eol)]}}, CHECKED)


def stub():
    """The endoflife.date shard the manifest counts, so a fixture can hold only a shard."""
    return normalize({"result": {"name": "stub", "label": "Stub", "category": "lang",
                                 "labels": {"eol": "End of Life"},
                                 "releases": [{"name": "1", "releaseDate": "2026-01-01",
                                               "eolFrom": "2027-01-01"}]}}, CHECKED)


class CatalogCase(unittest.TestCase):
    """A temporary catalog root whose manifest counts the endoflife.date shard alone."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.products = self.root / "products"
        self.products.mkdir()

    def publish(self, *records):
        """Write ``records``; a stub import-data product keeps the manifest satisfiable."""
        for file in self.products.glob("*.json"):
            file.unlink()
        for record in records:
            dump(self.products / (record["id"] + ".json"), record)
        counted = [record for record in records
                   if record["provenance"]["verifier"] == validation.sources.source("import-data").verifier]
        if not counted:
            counted = [stub()]
            dump(self.products / "stub.json", counted[0])
        dump(self.root / "manifest.json", {
            "generated_at": CHECKED, "source_url": API, "product_count": len(counted),
            "release_count": sum(len(record["releases"]) for record in counted),
            "excluded_hardware": [], "source": "import-data"})


class ProvenanceTests(CatalogCase):
    def setUp(self):
        super().setUp()
        self.record = normalize({"result": {"name": "sample", "label": "Sample", "category": "lang",
            "labels": {"eol": "Security Support"}, "releases": [{"name": "1", "eolFrom": "2028-01-01"}]}},
            CHECKED)
        self.publish(self.record)

    def test_date_disagreeing_with_source_is_rejected(self):
        validate_data(self.root)
        self.record["releases"][0]["milestones"]["eossec"] = "2029-01-01"
        self.publish(self.record)
        with self.assertRaises(MilestoneError):
            validate_data(self.root)

    def test_missing_product_aborts_snapshot(self):
        (self.products / "sample.json").unlink()
        with self.assertRaises(ManifestError):
            validate_data(self.root)

    def test_duplicate_release_is_rejected(self):
        self.record["releases"].append(copy.deepcopy(self.record["releases"][0]))
        self.publish(self.record)
        with self.assertRaises(CatalogError):
            validate_data(self.root)


class SoftwareChronologyTests(CatalogCase):
    """A release's stated end may not precede the general availability it states.

    The schema admits each date on its own; only these rules prove the interval
    between them can exist at all. A month is compared by the first day it can
    cover, never padded into a day (AGENTS.md rule 4), so the comparison is
    conservative in the direction that refuses a value rather than assuming it
    falls later.
    """

    def test_a_deterministic_end_before_its_own_ga_is_refused(self):
        # The record re-derives from its own upstream object, so the only rule it
        # can break here is the chronology between the two dates it states.
        record = dated("chrono", ga="2026-01-01", eol="2025-01-01")
        self.publish(record)
        with self.assertRaises(ChronologyError):
            validate_data(self.root)

    def test_a_deterministic_end_equal_to_its_own_ga_is_published(self):
        # The boundary is inclusive: a release sold and ended the same day is an
        # impossible-looking but stated fact, and the gate must not invent a rule
        # stricter than the source.
        record = dated("same-day", ga="2026-01-01", eol="2026-01-01")
        self.publish(record)
        self.assertEqual([r["id"] for r in validate_data(self.root)], ["same-day"])

    def test_a_later_end_still_validates(self):
        record = dated("later", ga="2026-01-01", eol="2027-01-01")
        self.publish(record)
        self.assertIn("later", [r["id"] for r in validate_data(self.root)])

    def test_a_researched_end_before_its_own_ga_is_refused(self):
        # Researched records never reach the importer's re-derivation, so the
        # chronology rule has to be applied to them independently — a human- or
        # agent-authored date is exactly as publishable as a fetched one.
        record = json.loads((ROOT / "data/products/researched-cpanel.json").read_text())
        target = next(r for r in record["releases"] if r["milestones"]["ga"])
        target["milestones"]["eol"] = "2023-01"  # its ga is 2023-03
        self.publish(record)
        with self.assertRaises(ChronologyError):
            validate_data(self.root)

    def test_a_month_precision_researched_record_validates(self):
        # Real month-precision records stay publishable: the comparison uses each
        # value's own width, so a month end later than a month ga never fails.
        record = json.loads((ROOT / "data/products/researched-cpanel.json").read_text())
        monthly = [r for r in record["releases"]
                   if validation.MONTH_PRECISION.fullmatch(r["milestones"]["ga"] or "")
                   and validation.MONTH_PRECISION.fullmatch(r["milestones"]["eol"] or "")]
        self.assertTrue(monthly, "fixture must carry a month-precision ga and end")
        self.publish(record)
        self.assertIn(record["id"], [r["id"] for r in validate_data(self.root)])

    def test_chronology_compares_month_precision_without_padding(self):
        # The helper every catalog pass runs, exercised at both widths directly:
        # equal months pass; an earlier month fails; and a month ga beside a day
        # end in the same month fails because the month *could* begin before the
        # day, which is the conservative direction.
        def record(ga, end):
            return {"id": "x", "releases": [{"id": "1", "milestones": {
                "ga": ga, "eos": None, "eossec": None, "eol": end}}]}

        validation.check_chronology(record("2026-03", "2026-03"))
        with self.assertRaises(ChronologyError):
            validation.check_chronology(record("2026-03", "2026-02"))
        with self.assertRaises(ChronologyError):
            validation.check_chronology(record("2026-03-15", "2026-03"))
        validation.check_chronology(record("2026-03", "2026-03-31"))

    def test_every_end_milestone_is_ordered_against_ga(self):
        for key in validation.END_MILESTONES:
            with self.subTest(key=key):
                milestones = {"ga": "2026-06-01", "eos": None, "eossec": None, "eol": None}
                record = {"id": "x", "releases": [{"id": "1", "milestones": milestones}]}
                milestones[key] = "2026-05-31"
                with self.assertRaises(ChronologyError):
                    validation.check_chronology(record)
                milestones[key] = "2026-06-01"
                validation.check_chronology(record)

    def test_an_absent_ga_states_no_interval(self):
        # An absent date stays absent: with no ga stated there is nothing for an
        # end to precede, and refusing the record would be inventing a claim.
        validation.check_chronology({"id": "x", "releases": [{"id": "1", "milestones": {
            "ga": None, "eos": None, "eossec": None, "eol": "2020-01-01"}}]})

    def test_the_committed_catalogs_pass_the_new_rule(self):
        # A rule that failed the real catalog would be a rule the data does not
        # obey. Both shards are exercised through the same helper each pass runs.
        for record in (json.loads((ROOT / "data/products/xenserver.json").read_text()),
                       json.loads((ROOT / "data/products/researched-cpanel.json").read_text()),
                       json.loads((ROOT / "data/products/apache-hadoop.json").read_text())):
            with self.subTest(record=record["id"]):
                validation.check_chronology(record)

    def test_no_ordering_is_asserted_between_end_milestones(self):
        # Citrix's own tables publish XenServer 5.5's eol (2013-09-15) before its
        # eos (2013-09-23). Refusing that pair would refuse a real vendor
        # statement, so only ga is ordered against — pinned here against the
        # committed record that carries the exception.
        record = json.loads((ROOT / "data/products/xenserver.json").read_text())
        exception = next(r for r in record["releases"]
                         if r["milestones"]["eos"] and r["milestones"]["eol"]
                         and r["milestones"]["eol"] < r["milestones"]["eos"])
        self.assertLess(exception["milestones"]["eol"], exception["milestones"]["eos"])
        validation.check_chronology(record)


class SourceReportTests(CatalogCase):
    """#86: a source that owns committed records must publish its accounting.

    AGENTS.md rule 6 makes a dropped source row published data, so a missing
    sidecar is not an optional convenience: the records are live, the report URL
    is documented, and the exclusions it accounts for would silently vanish.
    """

    def setUp(self):
        super().setUp()
        # A committed vendor shard (Ceph) beside the stub the manifest counts; its
        # sidecar is the one the report checks look for.
        self.report = json.loads((ROOT / "data/ceph-import.json").read_text())
        self.publish(json.loads((ROOT / "data/products/ceph.json").read_text()))

    def test_a_missing_report_for_an_owning_source_is_refused(self):
        # The committed record is live and reproducible; without its sidecar the
        # catalog can no longer account for the rows the source dropped.
        self.assertFalse((self.root / "ceph-import.json").exists())
        with self.assertRaises(ReportError):
            validate_data(self.root)

    def test_the_same_catalog_validates_once_the_report_is_restored(self):
        dump(self.root / "ceph-import.json", self.report)
        records = validate_data(self.root)
        self.assertEqual(sorted(record["id"] for record in records), ["ceph", "stub"])

    def test_a_report_that_miscounts_its_own_records_is_refused(self):
        dump(self.root / "ceph-import.json", dict(self.report, total_records=2))
        with self.assertRaises(ReportError):
            validate_data(self.root)

    def test_a_report_naming_another_source_is_refused(self):
        dump(self.root / "ceph-import.json", dict(self.report, verifier="deterministic-netscaler"))
        with self.assertRaises(ReportError):
            validate_data(self.root)


if __name__ == "__main__":
    unittest.main()
