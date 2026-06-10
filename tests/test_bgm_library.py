import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from workflow.bgm_library import bgm_source_catalog, download_bgm_from_url


class FakeResponse:
    def __init__(self, body: bytes, content_type: str = "audio/mpeg"):
        self.body = body
        self.headers = {"Content-Type": content_type}

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self, _limit: int):
        return self.body


class BgmLibraryTest(unittest.TestCase):
    def test_bgm_source_catalog_lists_chinese_free_sources_only(self):
        catalog = bgm_source_catalog()

        self.assertGreaterEqual(len(catalog), 4)
        keys = {source["key"] for source in catalog}
        self.assertIn("aigei", keys)
        self.assertIn("ear0", keys)
        self.assertIn("tosound", keys)
        self.assertIn("freesound_cn", keys)
        legacy_foreign_keys = {"opengameart", "fma", "ccmixter", "wikimedia_commons"}
        self.assertFalse(keys & legacy_foreign_keys)
        self.assertTrue(all("网" in source["name"] or "声" in source["name"] for source in catalog))
        self.assertTrue(all(source["license_note"] for source in catalog))
        self.assertTrue(all(source["caution"] for source in catalog))

    def test_download_bgm_from_url_saves_audio_to_library_uploads(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            with patch("workflow.bgm_library.open_without_proxy", return_value=FakeResponse(b"mp3-data")):
                result = download_bgm_from_url(
                    root,
                    {"url": "https://example.com/music/demo.mp3", "source": "aigei"},
                )

            self.assertTrue(result["ok"])
            saved = Path(result["files"][0]["path"])
            self.assertTrue(saved.exists())
            self.assertEqual(saved.read_bytes(), b"mp3-data")
            self.assertIn("/uploads/bgm-library/aigei/", str(saved))
            self.assertTrue(saved.with_name(f"{saved.name}.source.json").exists())

    def test_download_bgm_from_url_rejects_non_audio_extension(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            with patch("workflow.bgm_library.open_without_proxy", return_value=FakeResponse(b"text", "text/plain")):
                result = download_bgm_from_url(
                    root,
                    {"url": "https://example.com/readme.txt", "source": "aigei"},
                )

            self.assertFalse(result["ok"])
            self.assertIn("不像音频文件", result["error"])

    def test_download_bgm_from_url_rejects_unknown_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            result = download_bgm_from_url(
                root,
                {"url": "https://example.com/music/demo.mp3", "source": "unknown"},
            )

            self.assertFalse(result["ok"])
            self.assertIn("中文免费 BGM 素材库", result["error"])


if __name__ == "__main__":
    unittest.main()
