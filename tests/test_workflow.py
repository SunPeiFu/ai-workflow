import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from workflow.core import (
    build_project,
    estimate_voice_timeline,
    load_text_document,
    render_srt,
    scale_segments_to_duration,
    select_assets,
    voice_command,
)


class WorkflowTest(unittest.TestCase):
    def test_load_text_document_reads_txt_and_normalizes_spacing(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "script.txt"
            source.write_text("第一段。\r\n\r\n第二段很长，需要继续口播。", encoding="utf-8")

            result = load_text_document(source)

        self.assertEqual(result, "第一段。\n\n第二段很长，需要继续口播。")

    def test_load_text_document_reads_docx_body_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "script.docx"
            document_xml = (
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                "<w:body>"
                "<w:p><w:r><w:t>第一段。</w:t></w:r></w:p>"
                "<w:p><w:r><w:t>第二段。</w:t></w:r></w:p>"
                "</w:body></w:document>"
            )
            with zipfile.ZipFile(source, "w") as archive:
                archive.writestr("word/document.xml", document_xml)

            result = load_text_document(source)

        self.assertEqual(result, "第一段。\n第二段。")

    def test_estimate_voice_timeline_splits_text_into_srt_ready_segments(self):
        text = "第一句介绍问题。第二句给出转折！第三句收束观点？"

        segments = estimate_voice_timeline(text, chars_per_second=5)

        self.assertEqual(
            [segment.text for segment in segments],
            ["第一句介绍问题。", "第二句给出转折！", "第三句收束观点？"],
        )
        self.assertEqual(segments[0].start_seconds, 0)
        self.assertGreater(segments[0].end_seconds, segments[0].start_seconds)
        self.assertEqual(segments[1].start_seconds, segments[0].end_seconds)

    def test_render_srt_matches_voice_timeline(self):
        segments = estimate_voice_timeline("第一句。第二句。", chars_per_second=3)

        srt = render_srt(segments)

        self.assertIn("1\n00:00:00,000 --> 00:00:01,334\n第一句。", srt)
        self.assertIn("2\n00:00:01,334 --> 00:00:02,667\n第二句。", srt)

    def test_scale_segments_to_duration_keeps_text_and_matches_audio_length(self):
        segments = estimate_voice_timeline("第一句。第二句。", chars_per_second=3)

        scaled = scale_segments_to_duration(segments, duration_seconds=10)

        self.assertEqual([segment.text for segment in scaled], ["第一句。", "第二句。"])
        self.assertEqual(scaled[0].start_seconds, 0)
        self.assertEqual(scaled[-1].end_seconds, 10)

    def test_voice_command_uses_selected_macos_voice(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "voice.aiff"

            command = voice_command("你好，开始口播。", voice="Tingting", output=out)

        self.assertEqual(
            command,
            ["say", "-v", "Tingting", "-o", str(out), "你好，开始口播。"],
        )

    def test_select_assets_keeps_custom_bgm_and_images(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            bgm = tmp_path / "bgm.mp3"
            image = tmp_path / "cover.png"
            bgm.write_bytes(b"music")
            image.write_bytes(b"image")

            assets = select_assets(bgm=bgm, images=[image])

        self.assertEqual(assets.bgm, bgm)
        self.assertEqual(assets.images, [image])

    def test_build_project_writes_script_srt_manifest_and_asset_links(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            script = tmp_path / "input.txt"
            bgm = tmp_path / "bgm.mp3"
            image = tmp_path / "image.png"
            script.write_text("这是第一句。这里是第二句。", encoding="utf-8")
            bgm.write_bytes(b"music")
            bgm.with_name(f"{bgm.name}.source.json").write_text(
                json.dumps({"source": "aigei", "source_url": "https://www.aigei.com/music/demo.mp3"}),
                encoding="utf-8",
            )
            image.write_bytes(b"image")

            project = build_project(
                root=tmp_path,
                project_id="demo",
                script_path=script,
                voice="Tingting",
                bgm=bgm,
                images=[image],
            )

            self.assertEqual(project.project_dir, tmp_path / "projects" / "demo")
            self.assertEqual(
                (project.project_dir / "script.txt").read_text(encoding="utf-8"),
                "这是第一句。这里是第二句。",
            )
            self.assertIn("Tingting", (project.project_dir / "episode.yaml").read_text(encoding="utf-8"))
            self.assertIn(
                "00:00:00,000 -->",
                (project.project_dir / "exports" / "subtitles.srt").read_text(encoding="utf-8"),
            )
            self.assertTrue((project.project_dir / "assets" / "bgm" / "bgm.mp3").exists())
            self.assertTrue((project.project_dir / "assets" / "images" / "image.png").exists())
            license_ledger = project.project_dir / "assets" / "licenses.md"
            self.assertTrue(license_ledger.exists())
            license_text = license_ledger.read_text(encoding="utf-8")
            self.assertIn("bgm.mp3", license_text)
            self.assertIn("image.png", license_text)
            self.assertIn("https://www.aigei.com/music/demo.mp3", license_text)
            self.assertIn("待补充授权来源", license_text)
            checklist = project.project_dir / "exports" / "publish-checklist.md"
            self.assertTrue(checklist.exists())
            checklist_text = checklist.read_text(encoding="utf-8")
            self.assertIn("哔哩哔哩", checklist_text)
            self.assertIn("小红书", checklist_text)
            self.assertIn("抖音", checklist_text)
            self.assertTrue((project.project_dir / "exports" / "platforms" / "bilibili" / "publish.md").exists())
            self.assertTrue((project.project_dir / "exports" / "platforms" / "xiaohongshu" / "metadata.json").exists())
            self.assertTrue((project.project_dir / "exports" / "platforms" / "douyin" / "publish.md").exists())
            performance = project.project_dir / "exports" / "performance.csv"
            self.assertTrue(performance.exists())
            performance_text = performance.read_text(encoding="utf-8")
            self.assertIn("platform,status,publish_url,views", performance_text)
            self.assertIn("bilibili,planned", performance_text)
            title_experiments = project.project_dir / "exports" / "title-experiments.csv"
            self.assertTrue(title_experiments.exists())
            self.assertIn("hypothesis", title_experiments.read_text(encoding="utf-8"))
            hook_analysis = project.project_dir / "exports" / "hook-analysis.json"
            self.assertTrue(hook_analysis.exists())
            self.assertIn("hook_text", hook_analysis.read_text(encoding="utf-8"))
            monetization_plan = project.project_dir / "exports" / "monetization-plan.json"
            self.assertTrue(monetization_plan.exists())
            self.assertIn("primary_offer", monetization_plan.read_text(encoding="utf-8"))
            series_plan = project.project_dir / "exports" / "series-plan.json"
            self.assertTrue(series_plan.exists())
            self.assertIn("series_name", series_plan.read_text(encoding="utf-8"))
            publish_schedule = project.project_dir / "exports" / "publish-schedule.json"
            self.assertTrue(publish_schedule.exists())
            self.assertIn("slots", publish_schedule.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
