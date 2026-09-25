import copy
import json
import unittest
from unittest import mock

from engine import opengear

from engine.opengear import (CATALOG_FAMILY, CONFIGURE_SOURCE, HEADERS, combine_records,
                             parse_catalog, parse_date, parse_page, validate_record)


def lifecycle_page(hardware=(('OM2200', 'OM2216<br>OM2232', '30 Jun 2026', '30 Jun 2031', 'CM8100', 'EoS Notice'),
                             ('CMS6100', 'CMS6100-SAC', '30 Apr 2013', '30 Apr 2014', 'Lighthouse', 'EoS Notice')),
                   revision=(('SD4001 Device Server', 'SD4001', '31 May 2012', '31 May 2016', 'SD4001 Rev 01', 'Note'),)):
    tables = []
    for headers, rows in ((HEADERS['hardware'], hardware), (HEADERS['revision'], revision)):
        body = ''.join('<tr>' + ''.join(
            f'<td><a href="/notice.pdf">{cell}</a></td>' if cell == 'EoS Notice' else f'<td>{cell}</td>'
            for cell in row) + '</tr>' for row in rows)
        tables.append('<table><tr>' + ''.join(f'<th>{h}</th>' for h in headers) + '</tr>' + body + '</table>')
    return ''.join(tables)


def catalog_page(*skus):
    products = [{"sku": sku, "title": sku, "console_ports": 4, "support_series": "OM2200",
                 "families": ["Operations Managers"], "datasheet_url": f"https://resources.opengear.com/{sku}/",
                 "thumbnail": f"https://opengear.com/wp-content/uploads/{sku}.png", "short_desc": ""}
                for sku in skus]
    payload = json.dumps({"ajaxUrl": "https://opengear.com/wp-admin/admin-ajax.php", "products": products})
    return f'<html><script id="og-data-js-extra">var ogData = {payload};\n//# sourceURL=og-data-js-extra</script>' \
           '<nav>OM2216 Configure Your Solution</nav></html>'


CHECKED = '2026-09-17T00:00:00Z'


def page(sale='30 Jun 2026', support='30 Jun 2031'):
    # Representative Opengear lifecycle rows, including HTML-separated part groups.
    return lifecycle_page(hardware=(('OM2200', 'OM2216<br>OM2232', sale, support, 'CM8100', 'EoS Notice'),
                                    ('CMS6100', 'CMS6100-SAC', '30 Apr 2013', '30 Apr 2014', 'Lighthouse', 'EoS Notice')),
                          revision=(('IM7200 Infrastructure Manager', 'IM7200 Rev 06', 'N/A', 'N/A', 'N/A', 'Revision'),))


class OpengearTests(unittest.TestCase):
    def test_grouped_parts_dates_and_software_exclusion(self):
        records, excluded, announced = parse_page(lifecycle_page(hardware=(
            ('OM2200', 'OM2216<br>OM2232', '30 Jun 2026', '30 Jun 2031', 'CM8100', 'EoS Notice'),
            ('VCMS', 'VCMS', '01 Mar 2013', '01 Mar 2014', 'Lighthouse', 'EoS Notice'),
        )), CHECKED)
        self.assertEqual([record['name'] for record in records], ['OM2200', 'SD4001 Device Server'])
        record = records[0]
        self.assertEqual(record['model_number'], 'OM2216 OM2232')
        self.assertEqual(record['milestones'],
                         {'ga': None, 'eos': '2026-06-30', 'eossec': None, 'eol': '2031-06-30'})
        self.assertEqual(record['status'], 'expiring')
        self.assertEqual(excluded[0]['product'], 'VCMS')
        self.assertEqual(announced, [])
        self.assertIn('https://opengear.com/notice.pdf', record['provenance']['source_urls'])
        validate_record(record)

    def test_date_correction_keeps_identity_and_changes_status(self):
        initial = parse_page(page(), CHECKED)[0][0]
        corrected = parse_page(page('30 Jun 2025', '30 Jun 2026'), CHECKED)[0][0]
        self.assertEqual(initial['id'], corrected['id'])
        self.assertEqual(corrected['status'], 'eol')
        changed = copy.deepcopy(initial)
        changed['milestones']['eol'] = '2032-06-30'
        with self.assertRaisesRegex(ValueError, 'contradicts'):
            validate_record(changed)

    def test_missing_tables_and_changed_headers_fail(self):
        for html in ['', page().replace('End of Support', 'Maintenance')]:
            with self.assertRaises(ValueError):
                parse_page(html, CHECKED)

    def test_month_precision_and_impossible_dates_fail(self):
        self.assertEqual(parse_date('1 Sept 2016'), '2016-09-01')
        for value in ['July 2028', '31 Feb 2026', 'true']:
            with self.assertRaises(ValueError):
                parse_date(value)

    def test_duplicate_rows_fail_instead_of_overwriting(self):
        html = lifecycle_page(hardware=(('OM2200', 'OM2216', '30 Jun 2026', '30 Jun 2031', 'CM8100', 'Note'),
                                        ('OM2200', 'OM2216', '30 Jun 2026', '30 Jun 2031', 'CM8100', 'Note')))
        with self.assertRaisesRegex(ValueError, 'Duplicate'):
            parse_page(html, CHECKED)

    def test_announcement_without_a_date_is_published_unknown(self):
        """A retirement announced without a deadline is hardware, not an exclusion."""
        records, excluded, announced = parse_page(
            page(support='N/A'), CHECKED)
        announced_record = next(record for record in records if record['name'] == 'OM2200')
        self.assertEqual(announced_record['milestones'],
                         {'ga': None, 'eos': '2026-06-30', 'eossec': None, 'eol': None})
        self.assertEqual(announced_record['status'], 'unknown')
        self.assertEqual([item['part_scope'] for item in announced
                          if item['name'] == 'OM2200'], ['OM2216 OM2232'])
        self.assertNotIn('OM2200', [item.get('product') for item in excluded])
        validate_record(announced_record)

    def test_announcement_transition_keeps_identity(self):
        """The undated announcement and the dated notice are the same record."""
        announced = parse_page(page(support='N/A'), CHECKED)[0]
        dated = parse_page(page(), CHECKED)[0]
        before = next(record for record in announced if record['name'] == 'OM2200')
        after = next(record for record in dated if record['name'] == 'OM2200')
        self.assertEqual(before['id'], after['id'])
        self.assertEqual((before['status'], after['status']), ('unknown', 'expiring'))
        validate_record(before)
        validate_record(after)

    def test_catalog_is_sku_keyed_and_validated(self):
        records, unmatched = parse_catalog(catalog_page('OM2216-LSP', 'OM2216'), CHECKED, [])
        self.assertEqual([record['name'] for record in records], ['OM2216', 'OM2216-LSP'])
        ids = {record['name']: record['id'] for record in records}
        self.assertEqual(len(set(ids.values())), 2)
        self.assertEqual(records[0]['family'], CATALOG_FAMILY)
        self.assertEqual(records[0]['catalog'], {'listed': True, 'source_url': CONFIGURE_SOURCE})
        self.assertEqual(records[0]['lifecycle'], {'listed': False, 'matches': []})
        self.assertEqual(records[0]['status'], 'unknown')
        self.assertEqual(sorted(unmatched), ['OM2216', 'OM2216-LSP'])
        self.assertEqual(records[0]['upstream']['SKU'],
                         {'text': 'OM2216', 'value': None, 'datetime': None, 'role': None, 'links': []})
        self.assertIn(CONFIGURE_SOURCE, records[0]['provenance']['source_urls'])
        for record in records:
            validate_record(record)

    def test_invalid_catalog_snapshots_fail(self):
        for html in ['<html></html>', catalog_page().replace('"sku"', '"title"'),
                     catalog_page('OM2216', 'OM2216'), catalog_page('om2216'), catalog_page()]:
            with self.assertRaises(ValueError):
                parse_catalog(html, CHECKED, [])

    def test_only_exact_part_scope_matches_and_never_the_replacement(self):
        lifecycle, _, _ = parse_page(lifecycle_page(hardware=(
            ('OM2200', 'OM2216<br>OM2216-LSP', '30 Jun 2026', '30 Jun 2031', 'OM2224-24E', 'EoS Notice'),
        )), CHECKED)
        records, unmatched = parse_catalog(catalog_page('OM2216', 'OM2216-LSP', 'OM2224-24E', 'OM221'), CHECKED,
                                           lifecycle)
        matched = {record['name']: record for record in records}
        notice = lifecycle[0]['id']
        for sku in ('OM2216', 'OM2216-LSP'):
            self.assertEqual(matched[sku]['lifecycle'], {'listed': True, 'matches': [notice]})
            self.assertEqual(matched[sku]['milestones']['eol'], '2031-06-30')
            self.assertEqual(matched[sku]['status'], 'expiring')
            self.assertIn('https://opengear.com/notice.pdf', matched[sku]['provenance']['source_urls'])
        # The replacement column is not a part scope, and a prefix is not the part.
        for sku in ('OM2224-24E', 'OM221'):
            self.assertEqual(matched[sku]['lifecycle'], {'listed': False, 'matches': []})
            self.assertEqual(matched[sku]['milestones']['eol'], None)
        self.assertEqual(sorted(unmatched), ['OM221', 'OM2224-24E'])
        for record in records:
            validate_record(record)

    def test_revision_notice_never_retires_the_whole_sku(self):
        """A revision row names a revision; the catalog SKU it revises stays unlinked."""
        lifecycle, _, _ = parse_page(page(), CHECKED)
        records, _ = parse_catalog(catalog_page('IM7200'), CHECKED, lifecycle)
        self.assertEqual(records[0]['lifecycle'], {'listed': False, 'matches': []})
        self.assertEqual(records[0]['status'], 'unknown')

    def test_catalog_removal_is_retained_not_eol(self):
        lifecycle, _, _ = parse_page(page(), CHECKED)
        catalog, _ = parse_catalog(catalog_page('OM2216', 'CM8004'), CHECKED, lifecycle)
        previous = list(lifecycle) + list(catalog)
        shorter, _ = parse_catalog(catalog_page('OM2216'), CHECKED, lifecycle)
        combined = combine_records(lifecycle, shorter, previous, '2026-10-01T00:00:00Z')
        retained = next(record for record in combined if record['name'] == 'CM8004')
        original = next(record for record in catalog if record['name'] == 'CM8004')
        self.assertEqual(retained['catalog'], {'listed': False, 'source_url': CONFIGURE_SOURCE})
        self.assertEqual(retained['milestones'], original['milestones'])
        self.assertEqual(retained['upstream'], original['upstream'])
        self.assertEqual(retained['status'], 'unknown')
        validate_record(retained)

    def test_lifecycle_row_removal_is_retained_and_marked(self):
        lifecycle, _, _ = parse_page(page(), CHECKED)
        previous = list(lifecycle)
        shorter = [record for record in lifecycle if record['name'] != 'CMS6100']
        combined = combine_records(shorter, [], previous, '2026-10-01T00:00:00Z')
        retained = next(record for record in combined if record['name'] == 'CMS6100')
        self.assertEqual(retained['evidence'], {'in_source': False})
        self.assertEqual(retained['milestones'], {'ga': None, 'eos': '2013-04-30', 'eossec': None,
                                                  'eol': '2014-04-30'})
        self.assertNotIn('evidence', next(r for r in combined if r['name'] == 'OM2200'))
        validate_record(retained)
    def test_lifecycle_disappearance_keeps_catalog_date_coherent(self):
        lifecycle, _, _ = parse_page(page(), CHECKED)
        catalog, _ = parse_catalog(catalog_page('OM2216'), CHECKED, lifecycle)
        previous = list(lifecycle) + list(catalog)
        shorter = [record for record in lifecycle if record['name'] != 'OM2200']
        fresh_catalog, _ = parse_catalog(catalog_page('OM2216'), '2026-10-01T00:00:00Z', shorter)
        combined = combine_records(shorter, fresh_catalog, previous,
                                   '2026-10-01T00:00:00Z', status_checked='2026-10-01T00:00:00Z')
        current = next(record for record in combined if record['name'] == 'OM2216')
        self.assertEqual(current['milestones']['eol'], '2031-06-30')
        self.assertEqual(current['lifecycle']['listed'], True)
        self.assertEqual(current['provenance']['last_checked'], '2026-10-01T00:00:00Z')
        validate_record(current)

    def test_retained_status_uses_current_evaluation_date(self):
        lifecycle, _, _ = parse_page(lifecycle_page(hardware=(
            ('OM2200', 'OM2216', '01 Oct 2026', '01 Oct 2026', 'CM8100', 'EoS Notice'),
        )), CHECKED)
        combined = combine_records([], [], list(lifecycle), '2026-11-01T00:00:00Z',
                                   status_checked='2026-11-01T00:00:00Z')
        retained = combined[0]
        self.assertEqual(retained['status'], 'eol')
        self.assertEqual(retained['status_as_of'], '2026-11-01T00:00:00Z')
        self.assertEqual(retained['provenance']['last_checked'], CHECKED)
        validate_record(retained)

    def test_catalog_count_drift_fails_before_publication(self):
        with mock.patch.object(opengear, 'fetch', return_value=''), \
             mock.patch.object(opengear, 'parse_page', return_value=([], [], [])), \
             mock.patch.object(opengear, 'parse_catalog', return_value=([{'id': 'one'}], ['one'])), \
             mock.patch.object(opengear, 'get_records', return_value=[]), \
             mock.patch.object(opengear, 'publish_records') as publish:
            with self.assertRaisesRegex(ValueError, 'Review the change'):
                opengear.import_opengear()
        publish.assert_not_called()

    def test_conflicting_notices_do_not_silently_choose_a_date(self):
        """Two notices naming one SKU with different deadlines is a contradiction."""
        lifecycle, _, _ = parse_page(lifecycle_page(hardware=(
            ('OM2200', 'OM2216', '30 Jun 2026', '30 Jun 2031', 'X', 'EoS Notice'),
            ('OM2200-10G', 'OM2216', '30 Jun 2026', '30 Jun 2032', 'Y', 'EoS Notice'),
        )), CHECKED)
        self.assertEqual(len(lifecycle), 3)
        with self.assertRaisesRegex(ValueError, 'Conflicting'):
            parse_catalog(catalog_page('OM2216'), CHECKED, lifecycle)

    def test_announcement_notice_links_but_adds_no_date(self):
        """A matched notice without dates links the SKU and keeps it unknown."""
        lifecycle, _, announced = parse_page(lifecycle_page(hardware=(
            ('OM2200', 'OM2216', 'N/A', 'N/A', 'CM8100', 'EoS Notice'),
        )), CHECKED)
        self.assertEqual([item['id'] for item in announced], [lifecycle[0]['id']])
        record = parse_catalog(catalog_page('OM2216'), CHECKED, lifecycle)[0][0]
        self.assertEqual(record['lifecycle'], {'listed': True, 'matches': [lifecycle[0]['id']]})
        self.assertEqual(record['milestones'],
                         {'ga': None, 'eos': None, 'eossec': None, 'eol': None})
        self.assertEqual(record['status'], 'unknown')
        validate_record(record)

    def test_validate_record_rejects_catalog_tampering(self):
        lifecycle, _, _ = parse_page(lifecycle_page(hardware=(
            ('OM2200', 'OM2216', '30 Jun 2026', '30 Jun 2031', 'CM8100', 'EoS Notice'),
        )), CHECKED)
        record = parse_catalog(catalog_page('OM2216'), CHECKED, lifecycle)[0][0]
        self.assertEqual(record['lifecycle']['matches'], [lifecycle[0]['id']])
        for path, value in ((('milestones', 'eol'), '2030-01-01'),
                            (('milestones', 'eos'), '2030-01-31'),
                            (('status',), 'supported'),
                            (('lifecycle', 'listed'), False),
                            (('lifecycle', 'matches'), []),
                            (('family',), 'hardware')):
            tampered = copy.deepcopy(record)
            target = tampered
            for key in path[:-1]:
                target = target[key]
            target[path[-1]] = value
            with self.assertRaises(ValueError):
                validate_record(tampered)

    def test_catalog_listing_flag_is_not_a_date_claim(self):
        """``catalog.listed`` records presence, only the collector can know it.

        Flipping it must never change a milestone: removal from the catalog is
        not an end of life, and the embedded notice evidence still stands.
        """
        lifecycle, _, _ = parse_page(lifecycle_page(hardware=(
            ('OM2200', 'OM2216', '30 Jun 2026', '30 Jun 2031', 'CM8100', 'EoS Notice'),
        )), CHECKED)
        record = parse_catalog(catalog_page('OM2216'), CHECKED, lifecycle)[0][0]
        retained = {**record, 'catalog': {**record['catalog'], 'listed': False}}
        validate_record(retained)
        self.assertEqual(retained['milestones'], record['milestones'])
        self.assertEqual(retained['lifecycle'], {'listed': True, 'matches': [lifecycle[0]['id']]})
        tampered = copy.deepcopy(retained)
        tampered['milestones']['eol'] = None
        with self.assertRaises(ValueError):
            validate_record(tampered)


if __name__ == '__main__':
    unittest.main()
