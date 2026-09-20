import json
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
        too_old = work('Very old terrain reconstruction', days=731)
        future = work('Future terrain reconstruction', days=-1)
        sent = work('An already sent terrain paper', doi='https://doi.org/10.1234/sent')
        duplicate = {**newest, 'id': 'https://openalex.org/a-different-index'}
        candidates = [older, too_old, sent, middle, future, duplicate, newest]
        selected = digest.select_papers(candidates, self.known | {'10.1234/sent'})
        self.assertEqual([p['title'] for p in selected], [newest['title'], middle['title'], older['title']])

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


if __name__ == '__main__':
    unittest.main()
