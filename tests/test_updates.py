import unittest
from urllib.error import HTTPError
from unittest.mock import patch
from updates import check_update, release_result, version_tuple, RELEASES_URL


class UpdateTests(unittest.TestCase):
    def test_compares_versions_numerically_and_ignores_remote_links(self):
        result = release_result({"tag_name": "v0.10.0", "body": "Changes", "html_url": "https://evil.test"}, "0.2.0")
        self.assertTrue(result["available"])
        self.assertEqual(result["release_url"], RELEASES_URL)
        self.assertFalse(release_result({"tag_name": "v0.1.0"}, "0.2.0")["available"])
        self.assertFalse(release_result({"tag_name": "v1.0.0", "draft": True}, "0.2.0")["available"])

    def test_rejects_untrusted_versions_and_handles_no_release(self):
        for value in ["1.2", "1.2.3-rc1", "<script>", None]:
            with self.assertRaises(ValueError):
                version_tuple(value)
        with patch("updates.urlopen", side_effect=HTTPError("url", 404, "No release", {}, None)):
            self.assertEqual(check_update("0.2.0")["status"], "unpublished")
        with patch("updates.urlopen", side_effect=OSError("Offline")):
            self.assertEqual(check_update("0.2.0")["status"], "unavailable")
