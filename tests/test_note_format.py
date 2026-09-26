import json
import os
import unittest
from unittest.mock import patch

import paper_digest as digest


class NoteFormatTests(unittest.TestCase):
    def test_bilingual_connected_sections_numbered_innovations_and_path_last(self):
        paper = digest.work_from_record({
            'title': 'Sparse terrain reconstruction', 'journal': 'Example', 'source_type': 'journal',
            'publication_date': '2024-03-01', 'categories': ['03_缺失地形恢复_空洞填补'],
            'reading_scope': '摘要，未核读全文', 'summary': {
                **{field: '中文内容' for field in digest.NOTE_FIELDS},
                'innovations': [{'claim': '结构约束辅助恢复', 'analysis': '本文将地形结构参与恢复。'}]},
        }, r'E:\论文\test.pdf')
        text = digest.render_markdown([paper], '2026-09-26')
        self.assertIn('1. **结构约束辅助恢复**', text)
        self.assertIn('**核心创新概括：', text)
        self.assertIn('**大白话概括：', text)
        self.assertTrue(text.strip().endswith('`E:\\论文\\test.pdf`'))
        self.assertNotIn('03_', text)
        self.assertNotIn('https://', text)

    def test_incomplete_notes_cannot_be_published_as_finished_chinese_notes(self):
        self.assertFalse(digest.summary_complete({field: '摘要未说明' for field in digest.NOTE_FIELDS}))
        complete = {field: '中文内容' for field in digest.NOTE_FIELDS}
        self.assertTrue(digest.summary_complete(complete))
        del complete['method_plain']
        self.assertFalse(digest.summary_complete(complete))

    def test_malformed_innovations_and_invented_numbers_are_rejected(self):
        work = digest.work_from_record({'title': 'Sparse terrain reconstruction', 'abstract': 'We reconstruct terrain with interpolation.'})
        data = {'innovations': {'not': 'an array'},
                'results': {'text': '精度提高90%。', 'evidence': 'We reconstruct terrain with interpolation.'}}
        with patch.dict(os.environ, {'SUMMARY_API_KEY': 'test'}), patch.object(digest.requests, 'post') as post:
            post.return_value.json.return_value = {'choices': [{'message': {'content': json.dumps(data)}}]}
            result = digest.summarize_from_abstract(work)
        self.assertEqual(result['innovations'], [])
        self.assertNotIn('results', result)
