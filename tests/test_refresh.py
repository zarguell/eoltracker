"""A failed source must restore records and sidecars without losing peers' work."""
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from engine import refresh


def snapshot(root):
    return {str(path.relative_to(root)): path.read_bytes()
            for path in root.rglob("*") if path.is_file()}


class RefreshTransactionTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        (self.root / "products").mkdir()
        for name in ("products/sample.json", "manifest.json", "source-import.json", "source-changes.json"):
            (self.root / name).write_bytes(b'{"original":true}\n')

    def failing_source(self, root):
        (root / "products/sample.json").unlink()
        (root / "products/new.json").write_bytes(b'{"partial":true}')
        (root / "manifest.json").write_bytes(b'{"product_count":99}')
        (root / "source-import.json").write_bytes(b'{"rows":99}')
        (root / "source-changes.json").write_bytes(b'{"events":["partial"]}')
        raise OSError("interrupted after partial writes")

    def test_failed_source_restores_records_manifest_and_ledger_before_next_source(self):
        before = snapshot(self.root)

        def succeeding_source(root):
            self.assertEqual(snapshot(root), before)
            (root / "products/good.json").write_bytes(b'{"good":true}')

        outcomes = refresh.refresh_all([
            SimpleNamespace(id="failed", run=self.failing_source),
            SimpleNamespace(id="good", run=succeeding_source),
        ], self.root)
        self.assertEqual([result.ok for result in outcomes], [False, True])
        self.assertIn("interrupted after partial writes", outcomes[0].error)
        self.assertEqual(snapshot(self.root), {**before, "products/good.json": b'{"good":true}'})
        # A partial refresh is a partially stale catalog, so it must not exit
        # zero and must not be publishable (#87): the successful peer's work is
        # kept, but the run's verdict is failure.
        self.assertEqual(refresh.exit_code(outcomes), 1)
        verdict = refresh.freshness(outcomes)
        self.assertEqual((verdict["refreshed"], verdict["sources"]), (1, 2))
        self.assertEqual(verdict["failed"], ["failed"])
        self.assertFalse(verdict["complete"])
        self.assertTrue(verdict["blocking"])
        self.assertIn("publication is blocked", refresh.report(outcomes)[-1])

    def test_failure_preserves_preceding_success(self):
        before = snapshot(self.root)

        def succeeding_source(root):
            (root / "products/good.json").write_bytes(b'{"good":true}')

        outcomes = refresh.refresh_all([
            SimpleNamespace(id="good", run=succeeding_source),
            SimpleNamespace(id="failed", run=self.failing_source),
        ], self.root)
        self.assertEqual([result.ok for result in outcomes], [True, False])
        self.assertEqual(snapshot(self.root), {**before, "products/good.json": b'{"good":true}'})

    def test_total_failure_is_nonzero_and_leaves_catalog_unchanged(self):
        before = snapshot(self.root)
        outcomes = refresh.refresh_all([
            SimpleNamespace(id="one", run=self.failing_source),
            SimpleNamespace(id="two", run=self.failing_source),
        ], self.root)
        self.assertEqual(refresh.exit_code(outcomes), 1)
        self.assertEqual(snapshot(self.root), before)

    def test_no_registered_sources_is_not_success(self):
        self.assertEqual(refresh.exit_code([]), 1)
        self.assertEqual(refresh.freshness([]),
                         {"sources": 0, "refreshed": 0, "failed": [], "complete": False, "blocking": True})

    def test_all_sources_succeeding_is_the_only_publishable_outcome(self):
        def good(root):
            (root / f"products/{id(root)}.json").write_bytes(b'{"good":true}')

        outcomes = refresh.refresh_all([SimpleNamespace(id="a", run=good),
                                        SimpleNamespace(id="b", run=good)], self.root)
        self.assertEqual(refresh.exit_code(outcomes), 0)
        verdict = refresh.freshness(outcomes)
        self.assertTrue(verdict["complete"])
        self.assertFalse(verdict["blocking"])
        self.assertEqual(verdict["failed"], [])
        self.assertIn("All 2 sources refreshed.", refresh.report(outcomes)[-1])

    def test_baseline_source_failure_blocks_publication(self):
        # The software importer owns the manifest counts and most records, so its
        # failure is the case the old "any success" rule let through: every other
        # source refreshed, and the largest catalog slice kept its stale data.
        def good(root):
            (root / "products/collector.json").write_bytes(b'{"collector":true}')

        outcomes = refresh.refresh_all([
            SimpleNamespace(id="import-data", run=self.failing_source),
            SimpleNamespace(id="import-hardware", run=good),
            SimpleNamespace(id="import-opengear", run=good),
        ], self.root)
        self.assertEqual([result.ok for result in outcomes], [False, True, True])
        self.assertEqual(refresh.exit_code(outcomes), 1)
        verdict = refresh.freshness(outcomes)
        self.assertEqual(verdict["failed"], ["import-data"])
        self.assertTrue(verdict["blocking"])
        self.assertIn("publication is blocked", refresh.report(outcomes)[-1])
        self.assertIn("import-data", refresh.report(outcomes)[-1])

    def test_the_step_summary_states_the_freshness_verdict(self):
        import os

        summary_path = self.root / "summary.md"
        previous = os.environ.get(refresh.STEP_SUMMARY)
        os.environ[refresh.STEP_SUMMARY] = str(summary_path)
        self.addCleanup(lambda: os.environ.__setitem__(refresh.STEP_SUMMARY, previous)
                        if previous is not None else os.environ.pop(refresh.STEP_SUMMARY, None))
        outcomes = refresh.refresh_all([
            SimpleNamespace(id="good", run=lambda root: None),
            SimpleNamespace(id="failed", run=self.failing_source),
        ], self.root)
        text = refresh.summary_markdown(outcomes)
        self.assertIn("Freshness: 1/2 sources refreshed", text)
        self.assertIn("incomplete — publication blocked", text)
        self.assertIn("| `failed` | failed |", text)


class DirectImportRollbackTests(unittest.TestCase):
    """Direct single-source commands roll back like the aggregate refresh (#94)."""

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        (self.root / "products").mkdir()
        for name in ("products/sample.json", "manifest.json", "source-import.json"):
            (self.root / name).write_bytes(b'{"original":true}\n')

    def test_each_final_write_boundary_is_faulted_and_the_tree_is_restored(self):
        # A failure injected at any point — after the record, after the report,
        # or after the manifest — must leave the directory byte-for-byte as it
        # was, not a mixture of new and old files.
        boundaries = {
            "record": lambda root: (root / "products/sample.json").write_bytes(b'{"partial":record}'),
            "new-record": lambda root: (root / "products/new.json").write_bytes(b'{"partial":new}'),
            "manifest": lambda root: (root / "manifest.json").write_bytes(b'{"partial":manifest}'),
            "report": lambda root: (root / "source-import.json").write_bytes(b'{"partial":report}'),
        }
        for name, inject in boundaries.items():
            with self.subTest(boundary=name):
                before = snapshot(self.root)

                def failing(root, inject=inject):
                    inject(root)
                    raise OSError(f"disk full after {name} write")

                outcome = refresh.refresh_source(SimpleNamespace(id="import-data", run=failing), self.root)
                self.assertFalse(outcome.ok, name)
                self.assertIn(f"disk full after {name} write", outcome.error)
                self.assertEqual(snapshot(self.root), before, name)

    def test_a_forbidden_extra_file_is_removed_on_rollback(self):
        before = snapshot(self.root)

        def failing(root):
            (root / "unexpected.json").write_bytes(b'{"junk":true}')
            raise OSError("interrupted")

        refresh.refresh_source(SimpleNamespace(id="import-opengear", run=failing), self.root)
        self.assertEqual(snapshot(self.root), before)
        self.assertFalse((self.root / "unexpected.json").exists())

    def test_the_cli_import_command_uses_the_transaction_and_exits_nonzero(self):
        from unittest import mock

        from engine import __main__ as cli

        failing = SimpleNamespace(id="import-opengear")
        with mock.patch.object(cli.sources, "source", return_value=failing), \
                mock.patch.object(refresh, "refresh_source",
                                  return_value=refresh.Outcome("import-opengear", False, "OSError: disk full")) as called:
            with self.assertRaises(SystemExit) as caught:
                cli.run_import("import-opengear")
        self.assertEqual(caught.exception.code, 1)
        # The command goes through the rollback wrapper rather than calling the
        # source directly, which is the fix for the unrolled-back direct writes.
        called.assert_called_once_with(failing)


if __name__ == "__main__":
    unittest.main()
