import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import paper_digest as digest


ROOT = Path(__file__).resolve().parents[1]


def work(title, days=0, doi=None, score=30):
    return {
        'title': title,
        'id': 'https://openalex.org/' + digest.normalize_title(title),
        'doi': doi,
        'publication_date': (datetime.now(timezone.utc).date() - timedelta(days=days)).isoformat(),
        '_score': score,
    }


def inverted_abstract(text):
    inverted = {}
    for position, word in enumerate(text.split()):
        inverted.setdefault(word, []).append(position)
    return inverted


class ExclusionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.library = json.loads((ROOT / 'known_papers.json').read_text(encoding='utf-8'))
        cls.known = digest.load_known(str(ROOT / 'known_papers.json'))

    def test_every_imported_reference_and_alias_is_excluded(self):
        self.assertEqual(self.library['source_entry_count'], 85)
        self.assertEqual(len(self.library['papers']), 83)
        self.assertEqual(sum(len(p['source_sections']) for p in self.library['papers']), 85)
        candidates = []
        for entry in self.library['papers']:
            for title in [entry['title'], *entry['aliases']]:
                candidates.append(work(title))
                variant = title.upper().replace('-', '\u2011').replace(' ', '  ')
                candidates.append(work(variant))
        self.assertEqual(digest.select_papers(candidates, self.known), [])

    def test_known_reference_without_doi_blocks_candidate_with_new_doi(self):
        title = 'Void Filling of Digital Elevation Models Based on Terrain Feature-Guided Diffusion Model'
        candidate = work(title, doi='https://doi.org/10.9999/new-indexed-identifier')
        self.assertEqual(digest.select_papers([candidate], self.known), [])

    def test_old_history_and_new_title_keys_both_work(self):
        candidate = work('A distinct new terrain reconstruction study', doi='http://dx.doi.org/10.1234/EXAMPLE')
        self.assertEqual(digest.select_papers([candidate], {'10.1234/example'}), [])
        seen = digest.paper_keys(candidate)
        other_index = {**candidate, 'id': 'https://openalex.org/another-id', 'doi': None}
        self.assertEqual(digest.select_papers([other_index], seen), [])

    def test_newest_first_without_padding_with_seen_old_or_future_papers(self):
        older = work('Older relevant terrain reconstruction', days=30, score=100)
        newest = work('Newest relevant terrain reconstruction', days=0, score=10)
        middle = work('Other relevant DEM completion study', days=7, score=60)
        too_old = work('Very old terrain reconstruction', days=4000)
        future = work('Future terrain reconstruction', days=-1)
        sent = work('An already sent terrain paper', doi='https://doi.org/10.1234/sent')
        duplicate = {**newest, 'id': 'https://openalex.org/a-different-index'}
        candidates = [older, too_old, sent, middle, future, duplicate, newest]
        selected = digest.select_papers(candidates, self.known | {'10.1234/sent'})
        self.assertEqual([p['title'] for p in selected], [newest['title'], middle['title'], older['title']])

    def test_unseen_older_paper_is_allowed_as_historical_supplement(self):
        old = work('Unseen DEM void filling study', days=900)
        self.assertEqual(digest.select_papers([old], self.known), [old])
        self.assertEqual(digest.discovery_type(old), '历史未收录补充')

    def test_hashed_local_catalog_entry_prevents_repeat(self):
        paper = work('An existing DEM restoration paper', days=500)
        excluded = digest.hashed_keys(digest.paper_keys(paper))
        self.assertEqual(digest.select_papers([paper], excluded), [])

    def test_generic_point_cloud_and_review_reply_are_not_terrain_restoration(self):
        self.assertFalse(digest.is_terrain_relevant(work('Point cloud completion for indoor chairs')))
        self.assertFalse(digest.is_terrain_relevant(work('Reply on terrain reconstruction review')))

    def test_fullwidth_entities_and_punctuation(self):
        left = 'Terrain\u2011Net: A & B Model'
        right = '\uff34\uff45\uff52\uff52\uff41\uff49\uff4e-Net: a &amp; b model.'
        self.assertEqual(digest.normalize_title(left), digest.normalize_title(right))

    def test_different_study_with_similar_words_is_not_excluded(self):
        candidate = work('Terrain-Net V2: Ground filtering with a new data fusion method')
        self.assertEqual(digest.select_papers([candidate], self.known), [candidate])

    def test_dem_does_not_match_demonstrate_or_demographic(self):
        self.assertFalse(digest.is_terrain_relevant({'title': 'We demonstrate reconstruction of demographic trends'}))
        self.assertTrue(digest.is_terrain_relevant({'title': 'Sparse DEM reconstruction and interpolation'}))

    def test_collect_applies_exclusions_with_real_library(self):
        known = work(self.library['papers'][0]['title'])
        known['title'] = 'Void Filling of Digital Elevation Models Based on Terrain Feature-Guided Diffusion Model'
        new = work('A new sparse terrain reconstruction method for forested regions')
        with patch.object(digest, 'search_openalex', return_value=[known, new]):
            self.assertEqual([p['title'] for p in digest.collect_papers(self.known)], [new['title']])

    def test_corrupt_history_does_not_silently_reset_deduplication(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'state.json'
            self.assertEqual(digest.load_seen(str(path)), set())
            path.write_text('{broken', encoding='utf-8')
            with self.assertRaises(json.JSONDecodeError):
                digest.load_seen(str(path))
            path.write_text('{}', encoding='utf-8')
            with self.assertRaises(ValueError):
                digest.load_seen(str(path))

    def test_digest_uses_short_reading_note_structure(self):
        paper = work(
            'Self-supervised DEM reconstruction with terrain-aware diffusion',
            doi='https://doi.org/10.1234/structured',
        )
        paper['authorships'] = [{'author': {'display_name': 'Test Author'}}]
        paper['primary_location'] = {
            'source': {'display_name': 'Journal of Terrain Studies', 'type': 'journal'}
        }
        paper['abstract_inverted_index'] = inverted_abstract(
            'Sparse LiDAR point cloud data with missing ridges make complete DEM labels difficult to obtain. '
            'We propose a novel self-supervised terrain-aware diffusion model for DEM reconstruction. '
            'Results demonstrate improved RMSE on two mountainous datasets.'
        )
        rendered = digest.render_markdown([paper])
        for heading in (
            '### 期刊与论文基本信息',
            '### 研究背景',
            '### 核心方法',
            '### 创新点',
            '### 实验结果',
            '### 结论',
            '一句话理解',
        ):
            self.assertIn(heading, rendered)
        self.assertIn('Journal of Terrain Studies', rendered)
        self.assertIn('JCR 分区未核验；中科院分区未核验', rendered)
        self.assertIn('03\\_缺失地形恢复\\_空洞填补', rendered)
        self.assertIn('07\\_拓扑结构与地形特征', rendered)
        self.assertIn('未核读全文', rendered)
        self.assertIn('LiDAR 点云', rendered)
        self.assertIn('自监督学习', rendered)
        self.assertIn('扩散模型', rendered)

    def test_missing_abstract_marks_unverified_fields(self):
        paper = work('Sparse DEM reconstruction by a new method')
        rendered = digest.render_markdown([paper])
        self.assertIn('摘要缺失', rendered)
        self.assertIn('需阅读全文核实', rendered)
        self.assertIn('摘要未给出可核实的实验结果', rendered)
        self.assertIn('摘要未明确说明相对现有工作的创新差异', rendered)

    def test_preprint_is_not_misreported_as_journal(self):
        paper = work('Terrain point cloud completion with interpolation')
        paper['primary_location'] = {
            'source': {'display_name': 'arXiv', 'type': 'repository'}
        }
        rendered = digest.render_markdown([paper])
        self.assertIn('arXiv（来源类型：repository；不确认为期刊）', rendered)
        self.assertIn('JCR 分区未核验', rendered)

    def test_untrusted_title_cannot_inject_markdown_link(self):
        paper = work('Sparse DEM reconstruction [extra](https://example.com)')
        rendered = digest.render_markdown([paper])
        self.assertIn(r'\[extra\]', rendered)
        self.assertNotIn('[extra](https://example.com)', rendered)

    def test_summary_requires_abstract_evidence_and_does_not_invent_numbers(self):
        paper = work('Sparse DEM reconstruction')
        paper['abstract_inverted_index'] = inverted_abstract(
            'Sparse DEM observations create gaps. We propose interpolation for terrain recovery. '
            'Results show improved accuracy on a test region.'
        )
        sections = {
            field: {'text': '摘要未说明，需阅读全文核实', 'evidence': ''}
            for field in digest.NOTE_FIELDS
        }
        sections['method'] = {'text': '研究采用插值恢复地形。', 'evidence': 'We propose interpolation for terrain recovery.'}
        sections['innovation'] = {'text': '世界首次提出此方法。', 'evidence': 'This sentence is not in the abstract.'}
        sections['results'] = {'text': '误差降低了95%。', 'evidence': 'Results show improved accuracy on a test region.'}
        response = {'choices': [{'message': {'content': json.dumps(sections, ensure_ascii=False)}}]}
        with patch.dict(os.environ, {'SUMMARY_API_KEY': 'test-only', 'SUMMARY_API_BASE_URL': '', 'SUMMARY_MODEL': ''}):
            with patch.object(digest.requests, 'post') as post:
                post.return_value.json.return_value = response
                note = digest.summarize_from_abstract(paper)
        self.assertIn('研究采用插值恢复地形', note['method'])
        self.assertNotIn('innovation', note)
        self.assertNotIn('results', note)
        self.assertEqual(post.call_args.kwargs['json']['model'], digest.SUMMARY_MODEL)
        self.assertEqual(post.call_args.args[0], digest.SUMMARY_API_BASE_URL + '/chat/completions')
        paper['_summary'] = note
        rendered = digest.render_markdown([paper])
        self.assertIn('模型辅助整理', rendered)
        self.assertIn('摘要报告', rendered)
        self.assertNotIn('95%', rendered)

    def test_no_key_or_no_abstract_skips_summary_api(self):
        paper = work('Sparse DEM reconstruction')
        with patch.dict(os.environ, {'SUMMARY_API_KEY': ''}):
            with patch.object(digest.requests, 'post') as post:
                self.assertEqual(digest.summarize_from_abstract(paper), {})
                post.assert_not_called()
        with patch.dict(os.environ, {'SUMMARY_API_KEY': 'test-only'}):
            with patch.object(digest.requests, 'post') as post:
                self.assertEqual(digest.summarize_from_abstract(paper), {})
                post.assert_not_called()

    def test_summary_sections_are_bounded_for_email_readability(self):
        sentence = 'This novel method improves terrain reconstruction accuracy ' + ('substantially ' * 80) + '.'
        paper = work('Terrain reconstruction with an accurate model')
        paper['abstract_inverted_index'] = inverted_abstract(sentence)
        innovation = digest.innovation_summary(paper, digest.abstract_sentences(paper))
        self.assertLessEqual(len(innovation), 343)


if __name__ == '__main__':
    unittest.main()
