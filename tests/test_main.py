import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from app.main import SurveillanceSync, TelegramUploader, env_bool, parse_suffixes


class TestHelpers(unittest.TestCase):
    def test_parse_suffixes_normalizes(self):
        self.assertEqual(parse_suffixes("mp4,.MKV, avi "), {".mp4", ".mkv", ".avi"})

    def test_env_bool(self):
        with patch("os.getenv", return_value="true"):
            self.assertTrue(env_bool("A", False))
        with patch("os.getenv", return_value="0"):
            self.assertFalse(env_bool("A", True))


class TestSurveillanceSync(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.watch = Path(self.tmpdir.name)
        self.uploader = Mock(spec=TelegramUploader)
        self.sync = SurveillanceSync(
            watch_dir=self.watch,
            uploader=self.uploader,
            polling_interval=1,
            stable_checks_required=2,
            min_file_age_sec=0,
            video_threshold_mb=1,
            archive_dir=None,
        )

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_is_ready_after_stable_size_checks(self):
        p = self.watch / "cam1.mp4"
        p.write_bytes(b"abc")

        now = time.time()
        self.assertFalse(self.sync._is_ready(p, now))
        self.assertFalse(self.sync._is_ready(p, now + 1))
        self.assertTrue(self.sync._is_ready(p, now + 2))

    def test_upload_route_by_size(self):
        small = self.watch / "small.mp4"
        large = self.watch / "large.mp4"
        small.write_bytes(b"x" * 100)
        large.write_bytes(b"x" * (2 * 1024 * 1024))

        self.sync._upload(small)
        self.uploader.upload_as_video.assert_called_once_with(small)

        self.sync._upload(large)
        self.uploader.upload_as_document.assert_called_once_with(large)


class TestTelegramUploader(unittest.TestCase):
    @patch("app.main.requests.get")
    def test_verify_connection_retries_then_success(self, mock_get):
        failure = RuntimeError("network down")
        success_resp = Mock()
        success_resp.raise_for_status.return_value = None
        success_resp.json.return_value = {"ok": True, "result": {"username": "bot_name"}}

        mock_get.side_effect = [failure, success_resp]

        uploader = TelegramUploader("token", "chat", timeout=1, max_retries=2, retry_delay_sec=0)
        uploader.verify_connection()

        self.assertEqual(mock_get.call_count, 2)


if __name__ == "__main__":
    unittest.main()
