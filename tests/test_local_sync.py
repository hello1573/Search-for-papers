import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

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

    @unittest.skipUnless(os.environ.get('TEST_NODE'), 'Requires artifact-tool Node runtime')
    def test_archived_digest_creates_matching_word_excel_and_open_pdf(self):
        report = {'schema_version': 1, 'date': '2026-09-26', 'papers': [{
            'title': 'Sparse DEM terrain reconstruction', 'publication_date': '2025-05-01',
            'doi': 'https://doi.org/10.1234/demo', 'journal': 'Example Journal',
            'relevance': '高', 'categories': ['03_缺失地形恢复_空洞填补'],
            'open_access_pdf_urls': ['https://example.org/full.pdf'],
        }]}
        markdown = '# Daily digest\n## 1. [Sparse DEM terrain reconstruction](<https://doi.org/10.1234/demo>)\n**Method:** abstract only.\n'

        class Response(io.BytesIO):
            def geturl(self):
                return 'https://example.org/full.pdf'

        def source(repo, *args):
            return json.dumps(report) if args[-1].endswith('.json') else markdown

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.object(local_sync, 'report_paths', return_value=['reports/daily/2026-09-26.json']), \
                 patch.object(local_sync, 'git', side_effect=source), \
                 patch.object(local_sync, 'urlopen', side_effect=lambda *a, **kw: Response(b'%PDF-1.4\n' + b'x' * 2048 + b'\n%%EOF')):
                for _ in range(2):
                    local_sync.run(root, root, Path(os.environ['TEST_NODE']), Path(local_sync.__file__).with_name('build_catalog.mjs'))
            self.assertTrue((root / '2026-09-26_稀疏地形重建文献简报.docx').exists())
            self.assertTrue((root / '稀疏地形重建文献总表.xlsx').exists())
            self.assertTrue((root / '论文' / '2026-09-26' / 'Sparse DEM terrain reconstruction.pdf').exists())


if __name__ == '__main__':
    unittest.main()
