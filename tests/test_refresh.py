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
        self.assertEqual(refresh.exit_code(outcomes), 0)

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


if __name__ == "__main__":
    unittest.main()
