import tempfile
import unittest
from pathlib import Path

import local_sync


class LocalSyncTests(unittest.TestCase):
    def test_safe_english_title_and_invalid_path_chars(self):
        self.assertEqual(local_sync.safe_filename('DEM: Sparse / Reconstruction?', 'doi'), 'DEM_ Sparse _ Reconstruction_.pdf')

    def test_docx_uses_real_hyperlinks_not_markdown_syntax(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'brief.docx'
            local_sync.build_docx('# Brief\n## 1. [DEM study](<https://doi.org/10.1234/example>)\n**Conclusion:** abstract only.', target)
            from docx import Document
            doc = Document(target)
            self.assertEqual(doc.paragraphs[1].text, '1. DEM study')
            self.assertIn('https://doi.org/10.1234/example', [rel.target_ref for rel in doc.part.rels.values()])
            self.assertNotIn('[DEM study]', '\n'.join(p.text for p in doc.paragraphs))

    def test_report_rows_keep_release_and_collection_dates_distinct(self):
        reports = [({'date': '2026-09-26', 'papers': [{
            'title': 'Sparse DEM reconstruction', 'publication_date': '2022-01-02',
            'doi': 'https://doi.org/10.1/test', 'journal': 'Journal', 'categories': ['03'],
        }]}, {})]
        rows = local_sync.rows_from_reports(reports)
        self.assertEqual(rows[0]['date'], '2022-01-02')
        self.assertEqual(rows[0]['collected'], '2026-09-26')


if __name__ == '__main__':
    unittest.main()
