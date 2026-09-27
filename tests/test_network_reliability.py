import unittest
from unittest.mock import Mock, patch

import requests
import paper_digest as digest


def response(status, results=None, retry_after=None):
    value = Mock(status_code=status, headers={})
    value.json.return_value = {"results": results or []}
    if retry_after is not None:
        value.headers["Retry-After"] = retry_after
    if status >= 400:
        value.raise_for_status.side_effect = requests.HTTPError(response=value)
    return value


class NetworkReliabilityTests(unittest.TestCase):
    @patch.object(digest.time, "sleep")
    def test_503_is_retried_before_success(self, sleep):
        session = Mock()
        session.get.side_effect = [response(503), response(200, [{"title": "Terrain"}])]
        self.assertEqual(digest.search_openalex(session, "terrain", "2025-01-01"), [{"title": "Terrain"}])
        self.assertEqual(session.get.call_count, 2)
        sleep.assert_called_once_with(2)

    @patch.object(digest.time, "sleep")
    def test_retry_after_is_capped(self, sleep):
        send = Mock(side_effect=[response(429, retry_after="999"), response(200)])
        digest.request_with_retry(send)
        sleep.assert_called_once_with(30)

    @patch.object(digest.time, "sleep")
    def test_timeout_recovers_but_401_is_not_retried(self, sleep):
        send = Mock(side_effect=[requests.Timeout(), response(200)])
        digest.request_with_retry(send)
        self.assertEqual(send.call_count, 2)
        denied = Mock(return_value=response(401))
        with self.assertRaises(requests.HTTPError):
            digest.request_with_retry(denied)
        self.assertEqual(denied.call_count, 1)

    @patch.object(digest.time, "sleep")
    def test_exhausted_retries_raise_instead_of_empty_results(self, sleep):
        send = Mock(return_value=response(503))
        with self.assertRaises(requests.HTTPError):
            digest.request_with_retry(send)
        self.assertEqual(send.call_count, 3)

    def test_one_failed_query_does_not_abort_collection(self):
        paper = {"id": "https://openalex.org/W123", "title": "Sparse DEM terrain reconstruction", "publication_date": "2025-01-01"}
        coverage = {}
        with patch.object(digest, "search_openalex", side_effect=[requests.HTTPError(), [paper]] + [[]] * 10) as search:
            found = digest.collect_papers(set(), coverage)
        self.assertEqual(len(found), 1)
        self.assertEqual(search.call_count, 12)
        self.assertEqual(coverage["successful_queries"], 11)
        self.assertEqual(len(coverage["failed_queries"]), 1)

    def test_total_outage_is_not_reported_as_no_new_papers(self):
        with patch.object(digest, "search_openalex", side_effect=requests.ConnectionError()):
            with self.assertRaisesRegex(RuntimeError, "All OpenAlex queries failed"):
                digest.collect_papers(set())

    def test_english_damaged_and_double_escaped_text_cannot_be_published(self):
        summary = {field: "根据摘要说明中文内容。" for field in digest.NOTE_FIELDS}
        self.assertTrue(digest.summary_complete(summary))
        for invalid in ("This is an untranslated abstract.", "中文\ufffd损坏", r"\u4e2d\u6587", "中文锟斤拷", "中文\ud800"):
            self.assertFalse(digest.summary_complete({**summary, "background": invalid}), repr(invalid))
        self.assertFalse(digest.summary_complete({**summary, "innovations": [{"claim": "New method", "analysis": "English explanation"}]}))
        self.assertTrue(digest.valid_chinese_text("采用数字高程模型（DEM）进行地形补全。"))


if __name__ == "__main__":
    unittest.main()
