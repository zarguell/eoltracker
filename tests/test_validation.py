import json
import tempfile
import unittest
from pathlib import Path

from engine.importer import API, dump, normalize
from engine.validation import validate_data


class ProvenanceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.record = normalize({"result": {"name": "sample", "label": "Sample", "category": "lang",
            "labels": {"eol": "Security Support"}, "releases": [{"name": "1", "eolFrom": "2028-01-01"}]}},
            "2026-09-17T12:00:00Z")
        self.path = self.root / "products/sample.json"
        dump(self.path, self.record)
        dump(self.root / "manifest.json", {"generated_at": "2026-09-17T12:00:00Z", "source_url": API,
             "product_count": 1, "release_count": 1, "excluded_hardware": []})

    def test_date_disagreeing_with_source_is_rejected(self):
        validate_data(self.root)
        self.record["releases"][0]["milestones"]["eossec"] = "2029-01-01"
        dump(self.path, self.record)
        with self.assertRaisesRegex(ValueError, "contradict source"):
            validate_data(self.root)

    def test_missing_product_aborts_snapshot(self):
        self.path.unlink()
        with self.assertRaisesRegex(ValueError, "counts"):
            validate_data(self.root)

    def test_duplicate_release_is_rejected(self):
        self.record["releases"].append(self.record["releases"][0])
        dump(self.path, self.record)
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            validate_data(self.root)
