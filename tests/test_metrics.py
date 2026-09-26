import unittest
from unittest.mock import patch

import journal_metrics as metrics


class MetricsTests(unittest.TestCase):
    def test_incomplete_or_stale_metrics_are_refreshed(self):
        entry = {'checked_at': '2026-09-26', 'indexing': 'SCIE', 'if_value': 4.3,
                 'if_year': 2025, 'cas': '地球科学大类2区', 'jcr': 'Q1'}
        self.assertFalse(metrics.needs_refresh(entry, '2026-09-26'))
        self.assertTrue(metrics.needs_refresh(entry, '2026-09-27'))
        del entry['jcr']
        self.assertTrue(metrics.needs_refresh(entry, '2026-09-26'))

    def test_refresh_clears_old_failure_and_preserves_evidence(self):
        value = metrics.merge_metrics({'failure': 'old', 'sources': ['a']}, {'if_value': 4.3, 'sources': ['b']})
        self.assertNotIn('failure', value)
        self.assertEqual(value['sources'], ['a', 'b'])
        value = metrics.merge_metrics(value, {'failure': 'offline'})
        self.assertEqual(value['if_value'], 4.3)
        self.assertNotIn('failure', value)
        self.assertEqual(value['refresh_failure'], 'offline')

    def test_subject_specific_quartiles_and_years_are_not_conflated(self):
        entry = {'indexing': 'SCIE', 'jcr_subjects': [
            {'quartile': 'Q1', 'subject': 'Geosciences'},
            {'quartile': 'Q2', 'subject': 'Remote Sensing'}],
            'jcr_year_label': 'current publisher display', 'cas': '地球科学大类2区',
            'cas_year': 2025, 'if_value': 4.3, 'if_year': 2025, 'if_release_year': 2026}
        text = metrics.display(entry)
        self.assertIn('Q1（Geosciences）', text)
        self.assertIn('Q2（Remote Sensing）', text)
        self.assertIn('2025年度；2026发布', text)
        self.assertIn('2025版', text)
        self.assertIn('不适用', metrics.display(entry, 'repository'))

    def test_hidden_values_never_become_metric_evidence(self):
        page = metrics.visible_page('<div>IF: 4.3<span style="display:none">99.9</span><script>Q1</script></div>')
        self.assertEqual(page.text_content(), 'IF: 4.3')

    def test_mdpi_statistics_keeps_all_jcr_subjects_not_citescore(self):
        home = metrics.visible_page('<div>Impact Factor: 4.3 (2025) SCIE (Web of Science)</div>')
        stats = metrics.visible_page('<div>JCR category rank\nQ1: Geosciences\nQ2: Remote Sensing\nCiteScore category rank\nQ1: Everything</div>')
        with patch.object(metrics, 'fetch_page', side_effect=[home, stats]):
            result = metrics.publisher_metrics('Remote Sensing')
        self.assertEqual(len(result['jcr_subjects']), 2)
        self.assertEqual(result['if_year'], 2025)
        self.assertNotIn('Everything', metrics.jcr_display(result))
