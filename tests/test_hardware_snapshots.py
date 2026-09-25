import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from engine.hardware import publish_records, report_name


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

    def test_empty_snapshot_is_refused(self):
        stored = self.save(self.record)
        original = stored.read_bytes()
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


class ReportSidecarTests(unittest.TestCase):
    """A registered sidecar is staged and checked before anything is written.

    The descriptor is supplied through the registry's own accessor rather than
    by adding a private hook to the collector, so the behaviour under test is
    the one two real sources get: eosl.date (no sidecar) and any source the
    registry gives one.
    """

    SIDECAR = 'example-import.json'
    VERIFIER = 'deterministic-eosl-date'

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'hardware').mkdir()
        self.checked = '2026-09-17T00:00:00Z'
        self.record = {
            '$schema': 'https://zarguell.github.io/eoltracker/v1/schema/hardware.json',
            'id': 'example-model', 'name': 'Example model', 'category': 'hardware',
            'vendor': 'Example', 'product_line': 'Example',
            'milestones': {'ga': None, 'eos': None, 'eossec': None, 'eol': '2030-01-01'},
            'status': 'expiring', 'upstream': {},
            'provenance': {'source_urls': ['https://example.com/lifecycle'],
                           'verifier': self.VERIFIER, 'last_checked': self.checked},
        }

    def registered(self, report):
        """A hardware source descriptor the registry accessors return."""
        source = mock.Mock(verifier=self.VERIFIER, category='hardware', report=report,
                           validator='')
        patchers = [
            mock.patch('engine.sources.all_sources', return_value=(source,)),
            mock.patch('engine.sources.sources_for', return_value=(source,)),
        ]
        for patcher in patchers:
            patcher.start()
            self.addCleanup(patcher.stop)

    def report(self, total, verifier=None):
        return {'source_url': 'https://example.com/lifecycle', 'verifier': verifier or self.VERIFIER,
                'checked_at': self.checked, 'total_records': total}

    def test_the_registry_names_the_sidecar_a_source_declares(self):
        self.registered(self.SIDECAR)
        self.assertEqual(report_name(self.VERIFIER), self.SIDECAR)
        # A source declaring none has none: nothing is invented for it.
        self.registered('')
        self.assertEqual(report_name(self.VERIFIER), '')

    def test_a_prospective_report_is_published_beside_the_records(self):
        self.registered(self.SIDECAR)
        publish_records([self.record], self.VERIFIER, self.root, report=self.report(1))
        self.assertEqual(json.loads((self.root / self.SIDECAR).read_text())['total_records'], 1)
        self.assertTrue((self.root / 'hardware/example-model.json').exists())

    def test_a_report_disagreeing_with_the_snapshot_aborts_before_writes(self):
        """The count is checked as one snapshot, not trusted after the write."""
        self.registered(self.SIDECAR)
        with self.assertRaises(ValueError):
            publish_records([self.record], self.VERIFIER, self.root, report=self.report(2))
        self.assertFalse((self.root / 'hardware/example-model.json').exists())
        self.assertFalse((self.root / self.SIDECAR).exists())

    def test_a_missing_committed_report_aborts_before_writes(self):
        """A source the gate requires a sidecar from cannot publish without one."""
        self.registered(self.SIDECAR)
        with self.assertRaises(ValueError):
            publish_records([self.record], self.VERIFIER, self.root)
        self.assertFalse((self.root / 'hardware/example-model.json').exists())

    def test_a_stale_committed_report_cannot_be_reused_for_a_larger_snapshot(self):
        """A refresh that adds a record without republishing its accounting fails."""
        self.registered(self.SIDECAR)
        (self.root / self.SIDECAR).write_text(json.dumps(self.report(1)))
        second = copy.deepcopy(self.record)
        second['id'] = 'example-second'
        with self.assertRaises(ValueError):
            publish_records([self.record, second], self.VERIFIER, self.root)
        self.assertEqual(json.loads((self.root / self.SIDECAR).read_text())['total_records'], 1)

    def test_an_unchanged_snapshot_reuses_the_committed_report(self):
        """Staging the committed accounting is not an error when it still agrees."""
        self.registered(self.SIDECAR)
        publish_records([self.record], self.VERIFIER, self.root, report=self.report(1))
        before = (self.root / self.SIDECAR).read_bytes()
        publish_records([self.record], self.VERIFIER, self.root)
        self.assertEqual((self.root / self.SIDECAR).read_bytes(), before)

    def test_a_report_naming_another_source_is_refused(self):
        self.registered(self.SIDECAR)
        with self.assertRaises(ValueError):
            publish_records([self.record], self.VERIFIER, self.root,
                            report=self.report(1, verifier='deterministic-opengear'))

    def test_a_source_without_a_sidecar_refuses_to_write_one(self):
        self.registered('')
        with self.assertRaisesRegex(ValueError, 'no accounting sidecar'):
            publish_records([self.record], self.VERIFIER, self.root, report=self.report(1))
