import copy
import json
import tempfile
import unittest
from pathlib import Path

from engine.hardware import publish_records


class HardwareSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'hardware').mkdir()
        self.record = {
            '$schema': 'https://zarguell.github.io/eoltracker/v1/schema/hardware.json',
            'id': 'example-model', 'name': 'Example model', 'category': 'hardware',
            'vendor': 'Example', 'product_line': 'Example',
            'milestones': {'ga': None, 'eos': None, 'eossec': None, 'eol': '2030-01-01'},
            'status': 'expiring', 'upstream': {},
            'provenance': {'source_urls': ['https://example.com/lifecycle'],
                           'verifier': 'deterministic-eosl-date',
                           'last_checked': '2026-09-17T00:00:00Z'},
        }

    def save(self, record):
        path = self.root / 'hardware' / (record['id'] + '.json')
        path.write_text(json.dumps(record))
        return path

    def test_refresh_prunes_only_owned_records(self):
        obsolete = copy.deepcopy(self.record)
        obsolete['id'] = 'obsolete-model'
        removed = self.save(obsolete)
        foreign = copy.deepcopy(self.record)
        foreign['id'] = 'opengear-existing'
        foreign['provenance']['verifier'] = 'deterministic-opengear'
        retained = self.save(foreign)
        original = retained.read_bytes()
        publish_records([self.record], 'deterministic-eosl-date', self.root)
        self.assertEqual(retained.read_bytes(), original)
        self.assertFalse(removed.exists())
        self.assertTrue((self.root / 'hardware/example-model.json').exists())

    def test_failed_snapshot_does_not_modify_catalog(self):
        stored = self.save(self.record)
        original = stored.read_bytes()
        invalid = copy.deepcopy(self.record)
        invalid['milestones']['eol'] = '2030-02-30'
        with self.assertRaises(Exception):
            publish_records([invalid], 'deterministic-eosl-date', self.root)
        self.assertEqual(stored.read_bytes(), original)
        with self.assertRaisesRegex(ValueError, 'Empty'):
            publish_records([], 'deterministic-eosl-date', self.root)
        self.assertEqual(stored.read_bytes(), original)

    def test_foreign_identity_collision_aborts_before_writes(self):
        stored = self.save(self.record)
        original = stored.read_bytes()
        other = copy.deepcopy(self.record)
        other['provenance']['verifier'] = 'deterministic-opengear'
        with self.assertRaisesRegex(ValueError, 'ownership collision'):
            publish_records([other], 'deterministic-opengear', self.root)
        self.assertEqual(stored.read_bytes(), original)

    def test_unchanged_snapshot_keeps_revision_timestamp(self):
        publish_records([self.record], 'deterministic-eosl-date', self.root)
        path = self.root / 'hardware/example-model.json'
        before = path.read_bytes()
        later = copy.deepcopy(self.record)
        later['provenance']['last_checked'] = '2026-09-18T00:00:00Z'
        publish_records([later], 'deterministic-eosl-date', self.root)
        self.assertEqual(path.read_bytes(), before)
