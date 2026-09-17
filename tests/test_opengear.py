import copy
import unittest

from engine.opengear import HEADERS, parse_date, parse_page, validate_record


def page(sale='30 Jun 2026', support='30 Jun 2031'):
    # Representative Opengear lifecycle rows, including HTML-separated part groups.
    return ('<table><tr>' + ''.join(f'<th>{h}</th>' for h in HEADERS['hardware']) +
            '</tr><tr><td>OM2200</td><td>OM2216<br>OM2232</td>' +
            f'<td>{sale}</td><td>{support}</td><td>CM8100</td>' +
            '<td><a href="/notice.pdf">EoS Notice</a></td></tr></table>' +
            '<table><tr>' + ''.join(f'<th>{h}</th>' for h in HEADERS['revision']) +
            '</tr><tr><td>IM7200 Infrastructure Manager</td><td>IM7200 Rev 06</td>' +
            '<td>N/A</td><td>N/A</td><td>N/A</td><td>Revision</td></tr></table>')


class OpengearTests(unittest.TestCase):
    def test_grouped_parts_dates_and_exclusions(self):
        records, excluded = parse_page(page(), '2026-09-17T00:00:00Z')
        self.assertEqual(records[0]['model_number'], 'OM2216 OM2232')
        self.assertEqual(records[0]['milestones'],
                         {'ga': None, 'eos': '2026-06-30', 'eossec': None, 'eol': '2031-06-30'})
        self.assertEqual(records[0]['status'], 'expiring')
        self.assertEqual(excluded[0]['product'], 'IM7200 Infrastructure Manager')
        self.assertIn('https://opengear.com/notice.pdf', records[0]['provenance']['source_urls'])
        validate_record(records[0])

    def test_date_correction_keeps_identity_and_changes_status(self):
        initial = parse_page(page(), '2026-09-17T00:00:00Z')[0][0]
        corrected = parse_page(page('30 Jun 2025', '30 Jun 2026'), '2026-09-17T00:00:00Z')[0][0]
        self.assertEqual(initial['id'], corrected['id'])
        self.assertEqual(corrected['status'], 'eol')
        changed = copy.deepcopy(initial)
        changed['milestones']['eol'] = '2032-06-30'
        with self.assertRaisesRegex(ValueError, 'contradicts'):
            validate_record(changed)

    def test_missing_tables_and_changed_headers_fail(self):
        for html in ['', page().replace('End of Support', 'Maintenance')]:
            with self.assertRaises(ValueError):
                parse_page(html, '2026-09-17T00:00:00Z')

    def test_month_precision_and_impossible_dates_fail(self):
        self.assertEqual(parse_date('1 Sept 2016'), '2016-09-01')
        for value in ['July 2028', '31 Feb 2026', 'true']:
            with self.assertRaises(ValueError):
                parse_date(value)

    def test_duplicate_rows_fail_instead_of_overwriting(self):
        html = page()
        row = html[html.index('<tr><td>OM2200'):html.index('</tr></table>') + 5]
        html = html.replace('</tr></table>', '</tr>' + row + '</table>', 1)
        with self.assertRaisesRegex(ValueError, 'Duplicate'):
            parse_page(html, '2026-09-17T00:00:00Z')
