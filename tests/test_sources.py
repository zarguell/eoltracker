"""Regression tests for the source registry, registry-checked validation and net.

The registry is what makes a record's ``provenance.verifier`` meaningful: it is
the single place that says which pipelines exist, which catalog each owns and
how each is refreshed. These tests pin the enforcement the schema alone cannot
express — a syntactically valid verifier that no source registered must not be
publishable, a registered source's report must account for the records it owns,
and a registered collector's module/entry/validator must actually resolve — so a
newly registered source cannot first fail during a scheduled refresh.

Failures are asserted by type rather than by diagnostic wording: a message is for
an operator reading a log, not a contract another module depends on (AGENTS.md
"assert exception types rather than incidental Python wording").
"""
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from engine import net, sources, validation

ROOT = Path(__file__).resolve().parents[1]


def hardware_record(verifier="deterministic-eosl-date"):
    return {
        "$schema": "https://zarguell.github.io/eoltracker/v1/schema/hardware.json",
        "id": "example-model", "name": "Example model", "category": "hardware",
        "vendor": "Example", "product_line": "Example",
        "milestones": {"ga": None, "eos": None, "eossec": None, "eol": "2030-01-01"},
        "status": "expiring", "upstream": {},
        "provenance": {"source_urls": ["https://example.com/lifecycle"], "verifier": verifier,
                       "last_checked": "2026-09-17T00:00:00Z"},
    }


def software_record(verifier="deterministic-endoflife-date-v1"):
    from engine.importer import normalize

    record = normalize({"result": {"name": "sample", "label": "Sample", "category": "lang",
                                   "labels": {"eol": "Security Support"},
                                   "releases": [{"name": "1", "eolFrom": "2028-01-01"}]}},
                       "2026-09-17T00:00:00Z")
    record["provenance"]["verifier"] = verifier
    return record


def committed_verifier_counts():
    """How many committed records carry each verifier, across both catalogs."""
    counts = {}
    for category in ("products", "hardware"):
        for path in (ROOT / "data" / category).glob("*.json"):
            verifier = json.loads(path.read_text())["provenance"]["verifier"]
            counts[verifier] = counts.get(verifier, 0) + 1
    return counts


def resolve_source(source):
    """Every callable a registered source names, resolved as a refresh would.

    A source declares a module and the entry point that refreshes it, plus — for
    a source that re-derives its records offline — a dotted validator callable.
    Registration alone proves none of those exist: the misspelling only surfaces
    when a scheduled refresh imports the module, which is far too late. Resolving
    each here turns a typo into a failing test instead of a failed production run.
    """
    if not importlib.util.find_spec(source.module):
        raise LookupError(f"{source.id}: module {source.module!r} does not exist")
    module = importlib.import_module(source.module)
    entry = getattr(module, source.entry, None)
    if not callable(entry):
        raise LookupError(f"{source.id}: {source.module}.{source.entry} is not callable")
    if source.validator:
        module_name, _, name = source.validator.rpartition(".")
        if not module_name or not importlib.util.find_spec(module_name):
            raise LookupError(f"{source.id}: validator module {module_name!r} does not exist")
        if not callable(getattr(importlib.import_module(module_name), name, None)):
            raise LookupError(f"{source.id}: {source.validator} is not callable")
    return entry


class RegistryContractTests(unittest.TestCase):
    def test_registry_agrees_with_the_collectors_it_names(self):
        # The registry is the source of truth for ids and provenance; each
        # collector reads its own verifier from there, so the two cannot drift.
        from engine import hardware, importer, opengear

        self.assertEqual(sources.source("import-data").verifier, importer.VERIFIER)
        self.assertEqual(sources.source("import-hardware").verifier, hardware.VERIFIER)
        self.assertEqual(sources.source("import-opengear").verifier, opengear.VERIFIER)
        self.assertEqual(sources.source("import-data").category, "software")
        for source_id in ("import-hardware", "import-opengear"):
            self.assertEqual(sources.source(source_id).category, "hardware")
        # The XenServer collector is a separate software source from the
        # NetScaler one: broadening NetScaler's parser to XenServer is exactly
        # what the registry's per-verifier ownership is meant to prevent.
        from engine import xenserver

        self.assertEqual(sources.source("import-xenserver").verifier, xenserver.VERIFIER)
        self.assertEqual(sources.source("import-xenserver").category, "software")
        self.assertEqual(sources.source("import-xenserver").report, "xenserver-import.json")
        self.assertNotEqual(sources.source("import-xenserver").verifier,
                            sources.source("import-netscaler").verifier)
        # Validation lets researched-* verifiers through to the contribution
        # admission rules; that only holds while both modules agree on the prefix.
        from engine import contribute

        self.assertEqual(contribute.RESEARCHED_VERIFIER_PREFIX, sources.RESEARCHED_PREFIX)

    def test_every_registered_source_resolves_its_module_entry_and_validator(self):
        # The table-driven registry matrix: each real source is exercised, not a
        # hand-picked sample, so a newly registered collector whose module, entry
        # or validator path is misspelled fails here rather than at refresh time.
        for source in sources.all_sources():
            with self.subTest(source=source.id):
                self.assertTrue(callable(resolve_source(source)))
                self.assertIn(source.category, ("software", "hardware"))
                self.assertTrue(source.verifier, "a source must own a verifier")
                self.assertFalse(source.verifier.startswith(sources.RESEARCHED_PREFIX),
                                 "a deterministic source may not claim the researched namespace")
                self.assertTrue(source.name.strip(), "a source carries a display name")
                self.assertTrue(source.attribution.strip(),
                                "a source states the sentence the site credits it with")
                # The source's own page is one of the pages it reads, which is
                # what the site credits and what a reader opens to check a row.
                self.assertTrue(source.pages, "a source reads at least one page")
                self.assertIn(source.url, source.urls)
                for page in source.pages:
                    self.assertRegex(page.url, r"^https?://")
                    self.assertTrue(page.label, "a registered page carries a label")
                # `record_validator` is the lazy import path the registry
                # promises for a source that re-derives offline: it must resolve
                # to a callable for a validator-bearing source and to None for a
                # source with no offline re-derivation.
                if source.validator:
                    self.assertTrue(callable(sources.record_validator(source)))
                else:
                    self.assertIsNone(sources.record_validator(source))

    def test_report_bearing_sources_publish_a_committed_accounting_sidecar(self):
        # A sidecar is how a source accounts for the rows it dropped (AGENTS.md
        # rule 6). Declaring one in the registry without committing it would 404
        # the documented URL and hide the exclusions, so the two must agree.
        counts = committed_verifier_counts()
        report_bearing = [source for source in sources.all_sources() if source.report]
        self.assertTrue(report_bearing, "at least one source publishes a sidecar")
        for source in report_bearing:
            with self.subTest(source=source.id):
                path = ROOT / "data" / source.report
                self.assertTrue(path.is_file(), f"{source.report} is not committed")
                report = json.loads(path.read_text())
                self.assertIsInstance(report, dict)
                self.assertEqual(report.get("verifier"), source.verifier)
                self.assertEqual(report.get("total_records"), counts.get(source.verifier, 0))

    def test_every_committed_deterministic_verifier_is_registered(self):
        # The registry is the sole authority on which pipelines exist, so a
        # verifier that appears in the committed catalog but not in the registry
        # means a record claims a pipeline this checkout cannot run.
        registered = {source.verifier for source in sources.all_sources()}
        committed = {verifier for verifier in committed_verifier_counts()
                     if not verifier.startswith(sources.RESEARCHED_PREFIX)}
        self.assertNotEqual(committed, set())
        self.assertEqual(committed - registered, set())

    def test_the_matrix_catches_a_misspelled_registry_entry(self):
        # The mutation the matrix is for: a source registered with a module that
        # does not exist, an entry that is not callable, or a validator path that
        # resolves to nothing must fail resolution before any refresh runs.
        page = (sources.Page("https://x.example/", "X"),)
        broken = (
            dict(module="engine.collector_that_does_not_exist", entry="refresh", validator=""),
            dict(module="engine.hardware", entry="refresh_misspelled", validator=""),
            dict(module="engine.hardware", entry="publish_records", validator="engine.hardware.nope"),
            dict(module="engine.hardware", entry="publish_records", validator="engine.nope.validate"),
        )
        for fields in broken:
            with self.subTest(fields=fields):
                source = sources.Source(
                    id="import-mutation", verifier="deterministic-mutation", category="hardware",
                    name="Mutation", url=page[0].url, pages=page, attribution="", **fields)
                with self.assertRaises(LookupError):
                    resolve_source(source)

    def test_source_ids_are_the_cli_commands(self):
        # The CLI's choices are derived from the registry, so importing COMMANDS
        # and comparing it to the registry would prove nothing. Ask the real
        # parser instead: `--help` runs no collector and prints what is accepted.
        done = subprocess.run([sys.executable, "-m", "engine", "--help"],
                              cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(done.returncode, 0, done.stderr)
        for source in sources.all_sources():
            self.assertIn(source.id, done.stdout)
        for command in ("refresh", "validate", "contribute", "build"):
            self.assertIn(command, done.stdout)

    def test_unknown_verifier_is_refused_by_lookup_and_by_validation(self):
        with self.assertRaises(sources.UnknownVerifier):
            sources.source_for("deterministic-nonesuch")
        with self.assertRaises(sources.UnknownSource):
            sources.source("import-nothing")
        # The presentation path never raises: a researched verifier names a
        # contributor, and an unknown one simply has no registered source.
        self.assertEqual(sources.sources_for("researched-zarguell"), ())
        self.assertEqual(sources.sources_for("deterministic-nonesuch"), ())

    def test_verifier_owning_another_catalog_is_refused(self):
        with self.assertRaises(sources.CategoryMismatch):
            sources.verify_category("deterministic-endoflife-date-v1", "hardware")
        with self.assertRaises(sources.CategoryMismatch):
            sources.verify_category("deterministic-eosl-date", "software")

    def test_registry_imports_no_collector(self):
        # Enumerating sources (CLI help, validation, a site build) must not pull
        # in an HTTP client, which is also what keeps the registry cycle-free.
        code = ("import sys; import engine.sources; "
                "print(sorted(m for m in sys.modules if m in "
                "{'engine.hardware', 'engine.opengear', 'engine.importer', 'engine.contribute'}))")
        done = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(done.stdout.strip(), "[]")

    def test_source_run_forwards_the_directory_lazily(self):
        module = mock.Mock(refresh=mock.Mock(return_value="refreshed"))
        with mock.patch.object(sources.importlib, "import_module", return_value=module) as importer:
            source = sources.Source(
                id="import-x", module="engine.some_collector", entry="refresh",
                verifier="deterministic-x", category="hardware", name="X",
                url="https://x.example/", pages=(sources.Page("https://x.example/", "X"),),
                attribution="")
            self.assertEqual(source.run(Path("/tmp/x")), "refreshed")
        importer.assert_called_once_with("engine.some_collector")
        module.refresh.assert_called_once_with(Path("/tmp/x"))

    def test_registered_validator_is_lazy_and_bound_to_the_owning_source(self):
        source = sources.source("import-opengear")
        check = sources.record_validator(source)
        from engine.opengear import validate_record

        self.assertIs(check, validate_record)
        # A source that re-derives nothing offline has no record validator.
        self.assertIsNone(sources.record_validator(sources.source("import-hardware")))

    def test_labels_and_attribution_come_from_the_registry(self):
        self.assertEqual(sources.source_label("https://opengear.com/configure/"),
                         "Opengear product configurator")
        # A URL the registry does not know is labelled by its host, not guessed.
        self.assertEqual(sources.source_label("https://resources.opengear.com/x.pdf"),
                         "resources.opengear.com")
        self.assertEqual(sources.source_label("https://www.example.com/x"), "example.com")
        self.assertEqual(sources.attribution("deterministic-eosl-date"),
                         sources.source("import-hardware").attribution)
        self.assertEqual(sources.attribution("researched-zarguell"), "")


class ValidationEnforcementTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "hardware").mkdir()
        (self.root / "products").mkdir()

    def save_hardware(self, record):
        (self.root / "hardware" / (record["id"] + ".json")).write_text(json.dumps(record))

    def save_software(self, record):
        (self.root / "products" / (record["id"] + ".json")).write_text(json.dumps(record))
        (self.root / "manifest.json").write_text(json.dumps({
            "generated_at": "2026-09-17T00:00:00Z", "source_url": "https://endoflife.date/api/v1/products/",
            "product_count": 1, "release_count": 1, "excluded_hardware": [], "source": "import-data"}))

    def test_hardware_record_with_an_unregistered_verifier_is_refused(self):
        # The schema's deterministic-* pattern admits it; the registry must not.
        self.save_hardware(hardware_record("deterministic-new-vendor"))
        with self.assertRaises(sources.UnknownVerifier):
            validation.validate_hardware(self.root)

    def test_hardware_record_claiming_the_software_source_is_refused(self):
        self.save_hardware(hardware_record("deterministic-endoflife-date-v1"))
        with self.assertRaises(sources.CategoryMismatch):
            validation.validate_hardware(self.root)

    def test_software_record_claiming_a_hardware_source_is_refused(self):
        self.save_software(software_record("deterministic-eosl-date"))
        with self.assertRaises(sources.CategoryMismatch):
            validation.validate_data(self.root)

    def test_software_record_with_an_unregistered_verifier_is_refused(self):
        self.save_software(software_record("deterministic-nonesuch"))
        with self.assertRaises(sources.UnknownVerifier):
            validation.validate_data(self.root)

    def test_registered_software_record_validates(self):
        self.save_software(software_record())
        records = validation.validate_data(self.root)
        self.assertEqual([record["id"] for record in records], ["sample"])

    def test_researched_records_are_left_to_their_own_admission(self):
        record = hardware_record()
        record["id"] = "researched-example"
        record["provenance"]["verifier"] = "researched-zarguell"
        record["provenance"]["research"] = {"quote": "q" * 20, "source_url": "https://example.com/",
                                            "retrieved_at": "2026-09-17", "contributor": "zarguell",
                                            "method": "manual", "verified_at": None, "stale_after": None,
                                            "evidence": [{"quote": "q" * 20, "source_url": "https://example.com/",
                                                          "retrieved_at": "2026-09-17"}]}
        self.save_hardware(record)
        # Not a registry failure: the researched admission rules decide, and they
        # are the only place a researched record's dates are judged.
        with self.assertRaises(ValueError):
            validation.validate_hardware(self.root)

    def test_manifest_naming_a_foreign_source_is_refused(self):
        self.save_software(software_record())
        manifest = json.loads((self.root / "manifest.json").read_text())
        manifest["source"] = "import-hardware"
        (self.root / "manifest.json").write_text(json.dumps(manifest))
        with self.assertRaises(validation.ManifestError):
            validation.validate_data(self.root)

    def report_bearing_source(self, report_name="eosl-import.json"):
        """A hardware source declaring a sidecar, standing in for a vendor collector."""
        return sources.Source(
            id="import-hardware", module="engine.hardware", entry="import_hardware",
            verifier="deterministic-eosl-date", category="hardware", name="eosl.date",
            url="https://eosl.date/", pages=(sources.Page("https://eosl.date/", "eosl.date"),),
            attribution="", report=report_name)

    def test_source_sidecar_must_account_for_the_records_it_owns(self):
        # data/opengear-import.json states how many records the Opengear refresh
        # wrote; a sidecar claiming more than the catalog holds would report
        # coverage the committed records do not show.
        self.save_hardware(hardware_record())
        report = {"verifier": "deterministic-eosl-date", "total_records": 1,
                  "source_url": "https://eosl.date/"}
        (self.root / "eosl-import.json").write_text(json.dumps(report))
        with mock.patch.object(sources, "all_sources", return_value=(self.report_bearing_source(),)):
            self.assertEqual(len(validation.validate_hardware(self.root)), 1)
            (self.root / "eosl-import.json").write_text(
                json.dumps(dict(report, total_records=2)))
            with self.assertRaises(validation.ReportError):
                validation.validate_hardware(self.root)
            (self.root / "eosl-import.json").write_text(
                json.dumps(dict(report, verifier="deterministic-opengear")))
            with self.assertRaises(validation.ReportError):
                validation.validate_hardware(self.root)

    def test_a_missing_sidecar_for_an_owning_source_is_refused(self):
        # #86: the sidecar is not optional while the source owns committed
        # records — a successful validation would otherwise publish records whose
        # dropped-row accounting, and the documented report URL, silently vanished.
        self.save_hardware(hardware_record())
        with mock.patch.object(sources, "all_sources", return_value=(self.report_bearing_source(),)):
            with self.assertRaises(validation.ReportError):
                validation.validate_hardware(self.root)
            (self.root / "eosl-import.json").write_text(
                json.dumps({"verifier": "deterministic-eosl-date", "total_records": 1}))
            self.assertEqual(len(validation.validate_hardware(self.root)), 1)

    def test_a_sidecar_that_is_not_an_object_is_refused(self):
        self.save_hardware(hardware_record())
        (self.root / "eosl-import.json").write_text(json.dumps(["not", "an", "object"]))
        with mock.patch.object(sources, "all_sources", return_value=(self.report_bearing_source(),)):
            with self.assertRaises(validation.ReportError):
                validation.validate_hardware(self.root)

    def test_schema_admits_a_new_verifier_that_the_registry_refuses(self):
        from jsonschema import Draft202012Validator

        schema = json.loads((ROOT / "schema/hardware.json").read_text())
        Draft202012Validator(schema).validate(hardware_record("deterministic-new-vendor"))
        with self.assertRaises(sources.UnknownVerifier):
            sources.verify_category("deterministic-new-vendor", "hardware")


class NetworkPolicyTests(unittest.TestCase):
    def test_politeness_varies_by_host(self):
        small = net.profile("https://eosl.date/network/routers/vendor/cisco/isr/")
        api = net.profile("https://endoflife.date/api/v1/products/")
        vendor = net.profile("https://opengear.com/end-life-products")
        # The crawl-heavy HTML sources stay small and paced; the JSON API is
        # fetched in parallel with no pause and no retry.
        self.assertEqual((small.workers, small.pause, small.attempts), (2, 0.5, 2))
        self.assertEqual((vendor.workers, vendor.pause, vendor.attempts), (2, 0.5, 2))
        self.assertEqual((api.workers, api.pause, api.attempts), (8, 0.0, 1))
        unknown = net.profile("https://example.com/notice")
        self.assertEqual((unknown.workers, unknown.attempts, unknown.retry_delay), (1, 2, 5.0))

    def test_connection_error_is_retried_then_raises_the_last_failure(self):
        response = mock.Mock(status_code=200, text="page")
        response.raise_for_status.return_value = None
        failures = [net.requests.ConnectionError("reset")]

        def flaky(url, **kwargs):
            if failures:
                raise failures.pop()
            self.assertEqual(kwargs["headers"]["User-Agent"], net.USER_AGENT)
            self.assertEqual(kwargs["timeout"], net.profile(url).timeout)
            return response

        with mock.patch.object(net.requests, "get", flaky), mock.patch.object(net.time, "sleep") as slept:
            self.assertEqual(net.get_text("https://eosl.date/x/"), "page")
        slept.assert_called_once_with(5.0)

        # Every attempt fails: the caller sees the network failure, not a wrapper.
        with mock.patch.object(net.requests, "get",
                               side_effect=net.requests.ConnectionError("down")) as getter, \
                mock.patch.object(net.time, "sleep"):
            with self.assertRaises(net.requests.ConnectionError):
                net.get_text("https://eosl.date/x/")
        self.assertEqual(getter.call_count, 2)

    def test_timeout_is_transient_but_a_4xx_is_not_retried(self):
        with mock.patch.object(net.requests, "get",
                               side_effect=net.requests.Timeout("slow")) as timeout, \
                mock.patch.object(net.time, "sleep"):
            with self.assertRaises(net.requests.Timeout):
                net.get_text("https://eosl.date/x/")
        self.assertEqual(timeout.call_count, 2)

        not_found = net.requests.HTTPError("404 Client Error")
        not_found.response = mock.Mock(status_code=404)
        with mock.patch.object(net.requests, "get", side_effect=not_found) as getter, \
                mock.patch.object(net.time, "sleep") as slept:
            with self.assertRaises(net.requests.HTTPError):
                net.get_text("https://eosl.date/missing/")
        self.assertEqual(getter.call_count, 1)
        slept.assert_not_called()

    def test_a_server_error_is_retried_and_a_rate_limit_counts_as_transient(self):
        response = mock.Mock(status_code=200, text="page")
        response.raise_for_status.return_value = None
        outage = net.requests.HTTPError("503 Server Error")
        outage.response = mock.Mock(status_code=503)
        calls = []

        def once(url, **kwargs):
            calls.append(url)
            if len(calls) == 1:
                raise outage
            return response

        with mock.patch.object(net.requests, "get", once), mock.patch.object(net.time, "sleep") as slept:
            self.assertEqual(net.get_text("https://eosl.date/x/"), "page")
        slept.assert_called_once()
        self.assertTrue(net.transient(outage))
        limited = net.requests.HTTPError("429 Too Many Requests")
        limited.response = mock.Mock(status_code=429)
        self.assertTrue(net.transient(limited))
        self.assertFalse(net.transient(not_found_status(404)))
        self.assertFalse(net.transient(ValueError("not a request failure")))

    def test_every_fetch_helper_sends_the_shared_user_agent(self):
        response = mock.Mock(status_code=200, text="body")
        response.raise_for_status.return_value = None
        response.json.return_value = {"ok": True}
        with mock.patch.object(net.requests, "get", return_value=response) as getter:
            self.assertTrue(net.get_json("https://endoflife.date/api/v1/products/")["ok"])
            self.assertEqual(net.get_text("https://eosl.date/", encoding="utf-8"), "body")
        for call in getter.call_args_list:
            self.assertEqual(call.kwargs["headers"]["User-Agent"], net.USER_AGENT)
            self.assertIn("timeout", call.kwargs)


def not_found_status(status):
    error = net.requests.HTTPError(f"{status}")
    error.response = mock.Mock(status_code=status)
    return error


if __name__ == "__main__":
    unittest.main()
