import json
import subprocess
import time
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from workflow.web_app import (
    CAPCUT_CALM_MALE_LABEL,
    REFERENCE_VOICE_LABEL,
    codex_image_polish_prompt,
    create_project_from_payload,
    default_cover_image,
    delete_remix_content,
    delete_projects,
    export_video_command,
    export_short_clips_command,
    find_ffmpeg_with_subtitles,
    list_voices,
    list_projects,
    list_remix_packages,
    open_douyin_content_folder,
    open_xiaohongshu_content_folder,
    package_platform_publish,
    performance_insights,
    performance_summary,
    prepare_visual_source,
    read_hook_analysis,
    read_monetization_plan,
    read_publish_schedule,
    read_series_plan,
    read_title_experiments,
    read_project_performance,
    read_remix_package_file,
    preview_project,
    parse_byte_range,
    codex_polish_failure_payload,
    polish_remix_images_locally,
    polish_remix_images_with_codex,
    save_uploaded_files,
    save_title_experiments,
    save_project_performance,
    save_remix_package_file,
    selected_platform_presets,
    start_douyin_note_generation,
    start_jianying_automation_job,
    start_jianying_content_generation,
    start_xiaohongshu_note_generation,
    start_xiaohongshu_publish_assistant,
    jianying_automation_job_status,
    video_scale_filter,
    write_ass_subtitles,
)


class WebAppTest(unittest.TestCase):
    def test_open_douyin_content_folder_prefers_generated_note_package(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_url = "https://v.douyin.com/open-note/"
            remix_dir = root / "remix_packages" / "remix" / "source"
            note_dir = root / "remix_packages" / "douyin-note" / "note"
            remix_dir.mkdir(parents=True)
            note_dir.mkdir(parents=True)
            analysis = {
                "url": source_url,
                "platform": "douyin",
                "copywriting": {"title": "打开抖音图文包"},
            }
            for package_dir in (remix_dir, note_dir):
                (package_dir / "analysis.json").write_text(json.dumps(analysis, ensure_ascii=False), encoding="utf-8")

            content_id = list_remix_packages(root)["contents"][0]["id"]
            with patch("workflow.web_app.subprocess.run") as run:
                run.return_value.returncode = 0
                result = open_douyin_content_folder(root, content_id)

            self.assertTrue(result["opened_folder"])
            self.assertEqual(result["package_group"], "douyin-note")
            self.assertEqual(Path(result["folder"]), note_dir.resolve())

    def test_open_douyin_content_folder_falls_back_to_xiaohongshu_materials(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            xhs_dir = root / "remix_packages" / "xiaohongshu-note" / "source"
            xhs_dir.mkdir(parents=True)
            analysis = {
                "url": "https://www.xiaohongshu.com/explore/douyin-folder",
                "platform": "xiaohongshu",
                "copywriting": {"title": "尚未生成抖音包"},
            }
            (xhs_dir / "analysis.json").write_text(json.dumps(analysis, ensure_ascii=False), encoding="utf-8")

            content_id = list_remix_packages(root)["contents"][0]["id"]
            with patch("workflow.web_app.subprocess.run") as run:
                run.return_value.returncode = 0
                result = open_douyin_content_folder(root, content_id)

            self.assertTrue(result["opened_folder"])
            self.assertEqual(result["package_group"], "xiaohongshu-note")
            self.assertEqual(Path(result["folder"]), xhs_dir.resolve())

    def test_start_douyin_note_generation_creates_platform_package_from_xiaohongshu_materials(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_url = "https://www.xiaohongshu.com/explore/douyin-package"
            remix_dir = root / "remix_packages" / "remix" / "source"
            xhs_dir = root / "remix_packages" / "xiaohongshu-note" / "xhs-note"
            remix_dir.mkdir(parents=True)
            (xhs_dir / "images").mkdir(parents=True)
            source_image = remix_dir / "old.jpg"
            xhs_image = xhs_dir / "images" / "01-current.jpg"
            source_image.write_bytes(b"old")
            xhs_image.write_bytes(b"current")
            source_analysis = {
                "url": source_url,
                "platform": "xiaohongshu",
                "copywriting": {
                    "title": "柠檬水怎么选？一篇帮你讲清楚🍋",
                    "body": "原始长正文。",
                    "tags": ["柠檬水"],
                },
                "images": [{"url": str(source_image)}],
            }
            xhs_analysis = {
                "url": source_url,
                "platform": "xiaohongshu",
                "copywriting": {
                    "title": "柠檬水怎么选？一篇帮你讲清楚🍋",
                    "body": "先说结论。小白瓶适合日常，绿色瓶适合运动后，粉色瓶适合关注轻负担的人群。",
                    "tags": ["柠檬水", "运动饮品", "好物分享", "日常饮品"],
                },
                "images": [{"url": str(xhs_image)}],
            }
            (remix_dir / "analysis.json").write_text(json.dumps(source_analysis, ensure_ascii=False), encoding="utf-8")
            (xhs_dir / "analysis.json").write_text(json.dumps(xhs_analysis, ensure_ascii=False), encoding="utf-8")

            content_id = list_remix_packages(root)["contents"][0]["id"]
            result = start_douyin_note_generation(root, content_id)

            note_dir = Path(result["note_dir"])
            self.assertTrue((note_dir / "抖音图文.md").exists())
            self.assertTrue((note_dir / "图片顺序.md").exists())
            self.assertTrue((note_dir / "发布清单.md").exists())
            self.assertEqual(result["package_group"], "douyin-note")
            self.assertEqual(result["source_package_group"], "xiaohongshu-note")
            self.assertEqual(result["image_count"], 1)
            self.assertIn("current", next((note_dir / "images").iterdir()).name)
            note_text = (note_dir / "抖音图文.md").read_text(encoding="utf-8")
            self.assertIn("## 标题", note_text)
            self.assertIn("## 正文", note_text)
            self.assertIn("## 标签", note_text)
            self.assertNotIn("一篇帮你讲清楚", note_text.split("## 正文", 1)[0])
            self.assertIn("#柠檬水", note_text)

    def test_start_douyin_note_generation_replaces_previous_package_for_same_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_url = "https://v.douyin.com/replace-package/"
            remix_dir = root / "remix_packages" / "remix" / "source"
            stale_dir = root / "remix_packages" / "douyin-note" / "old-package"
            remix_dir.mkdir(parents=True)
            stale_dir.mkdir(parents=True)
            analysis = {
                "url": source_url,
                "platform": "douyin",
                "copywriting": {"title": "速干短裤", "body": "训练和日常都能穿。", "tags": ["运动短裤"]},
                "images": [],
            }
            for package_dir in (remix_dir, stale_dir):
                (package_dir / "analysis.json").write_text(json.dumps(analysis, ensure_ascii=False), encoding="utf-8")

            content_id = list_remix_packages(root)["contents"][0]["id"]
            result = start_douyin_note_generation(root, content_id)
            content = next(item for item in list_remix_packages(root)["contents"] if item["id"] == content_id)
            douyin_packages = [package for package in content["packages"] if package["group"] == "douyin-note"]

            self.assertFalse(stale_dir.exists())
            self.assertEqual(len(douyin_packages), 1)
            self.assertEqual(Path(result["note_dir"]).name, douyin_packages[0]["name"])

    def test_open_xiaohongshu_content_folder_prefers_generated_note_package(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_url = "https://www.xiaohongshu.com/explore/open-folder"
            remix_dir = root / "remix_packages" / "remix" / "source"
            note_dir = root / "remix_packages" / "xiaohongshu-note" / "note"
            remix_dir.mkdir(parents=True)
            note_dir.mkdir(parents=True)
            analysis = {
                "url": source_url,
                "platform": "xiaohongshu",
                "copywriting": {"title": "打开当前素材文件夹"},
            }
            for package_dir in (remix_dir, note_dir):
                (package_dir / "analysis.json").write_text(json.dumps(analysis, ensure_ascii=False), encoding="utf-8")

            content_id = list_remix_packages(root)["contents"][0]["id"]
            with patch("workflow.web_app.subprocess.run") as run:
                run.return_value.returncode = 0
                result = open_xiaohongshu_content_folder(root, content_id)

            self.assertTrue(result["opened_folder"])
            self.assertEqual(result["package_group"], "xiaohongshu-note")
            self.assertEqual(Path(result["folder"]), note_dir.resolve())
            run.assert_called_once_with(["open", str(note_dir.resolve())], text=True, capture_output=True, check=False)

    def test_open_xiaohongshu_content_folder_falls_back_to_source_package(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            remix_dir = root / "remix_packages" / "remix" / "source"
            remix_dir.mkdir(parents=True)
            analysis = {
                "url": "https://www.xiaohongshu.com/explore/source-folder",
                "platform": "xiaohongshu",
                "copywriting": {"title": "尚未生成图文包"},
            }
            (remix_dir / "analysis.json").write_text(json.dumps(analysis, ensure_ascii=False), encoding="utf-8")

            content_id = list_remix_packages(root)["contents"][0]["id"]
            with patch("workflow.web_app.subprocess.run") as run:
                run.return_value.returncode = 0
                result = open_xiaohongshu_content_folder(root, content_id)

            self.assertTrue(result["opened_folder"])
            self.assertEqual(result["package_group"], "remix")
            self.assertEqual(Path(result["folder"]), remix_dir.resolve())

    def test_list_read_and_save_remix_package_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            package_dir = root / "remix_packages" / "jianying" / "demo"
            package_dir.mkdir(parents=True)
            target = package_dir / "文案.txt"
            target.write_text("原文案", encoding="utf-8")
            (package_dir / "analysis.json").write_text("{}", encoding="utf-8")

            packages = list_remix_packages(root)["packages"]
            self.assertEqual(packages[0]["name"], "demo")
            self.assertEqual(packages[0]["group"], "jianying")
            self.assertIn("文案.txt", [file["name"] for file in packages[0]["files"]])

            file_info = read_remix_package_file(root, "jianying/demo/文案.txt")
            self.assertEqual(file_info["content"], "原文案")
            self.assertTrue(file_info["editable"])

            saved = save_remix_package_file(root, "jianying/demo/文案.txt", "新文案")
            self.assertTrue(saved["ok"])
            self.assertEqual(target.read_text(encoding="utf-8"), "新文案")

            with self.assertRaises(ValueError):
                read_remix_package_file(root, "../escape.txt")

    def test_list_remix_packages_groups_by_source_link_and_deletes_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            remix_dir = root / "remix_packages" / "remix" / "demo-remix"
            jianying_dir = root / "remix_packages" / "jianying" / "demo-jianying"
            other_dir = root / "remix_packages" / "jianying" / "other"
            remix_dir.mkdir(parents=True)
            jianying_dir.mkdir(parents=True)
            other_dir.mkdir(parents=True)
            analysis = {
                "url": "https://v.douyin.com/demo/",
                "platform": "douyin",
                "copywriting": {"title": "速干短裤"},
            }
            (remix_dir / "analysis.json").write_text(json.dumps(analysis, ensure_ascii=False), encoding="utf-8")
            (remix_dir / "copywriting.md").write_text("文案", encoding="utf-8")
            (jianying_dir / "analysis.json").write_text(json.dumps(analysis, ensure_ascii=False), encoding="utf-8")
            (jianying_dir / "文案.txt").write_text("剪映文案", encoding="utf-8")
            (other_dir / "analysis.json").write_text(
                json.dumps({"url": "https://v.douyin.com/other/", "copywriting": {"title": "另一个"}}, ensure_ascii=False),
                encoding="utf-8",
            )

            result = list_remix_packages(root)

            content = next(item for item in result["contents"] if item["source_url"] == "https://v.douyin.com/demo/")
            self.assertEqual(content["title"], "速干短裤")
            self.assertEqual(content["package_count"], 2)
            self.assertEqual({package["group"] for package in content["packages"]}, {"remix", "jianying"})

            deleted = delete_remix_content(root, content["id"])
            self.assertTrue(deleted["ok"])
            self.assertFalse(remix_dir.exists())
            self.assertFalse(jianying_dir.exists())
            self.assertTrue(other_dir.exists())

    def test_list_remix_packages_prunes_stale_remix_and_xiaohongshu_note_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_url = "https://www.xiaohongshu.com/explore/demo"
            old_remix = root / "remix_packages" / "remix" / "old-remix"
            latest_remix = root / "remix_packages" / "remix" / "latest-remix"
            old_note = root / "remix_packages" / "xiaohongshu-note" / "old-note"
            latest_note = root / "remix_packages" / "xiaohongshu-note" / "latest-note"
            for package_dir in [old_remix, latest_remix, old_note, latest_note]:
                package_dir.mkdir(parents=True)
                (package_dir / "analysis.json").write_text(
                    json.dumps(
                        {
                            "url": source_url,
                            "platform": "xiaohongshu",
                            "copywriting": {"title": package_dir.name},
                        },
                        ensure_ascii=False,
                    ),
                    encoding="utf-8",
                )
                time.sleep(0.01)

            result = list_remix_packages(root)
            paths = {package["path"] for package in result["packages"]}

            self.assertFalse(old_remix.exists())
            self.assertFalse(old_note.exists())
            self.assertTrue(latest_remix.exists())
            self.assertTrue(latest_note.exists())
            self.assertEqual(paths, {"remix/latest-remix", "xiaohongshu-note/latest-note"})

    def test_start_jianying_content_generation_prefers_affiliate_handoff(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_url = "https://v.douyin.com/demo/"
            remix_dir = root / "remix_packages" / "remix" / "demo-remix"
            affiliate_dir = root / "remix_packages" / "affiliate-jianying" / "demo-affiliate"
            remix_dir.mkdir(parents=True)
            affiliate_dir.mkdir(parents=True)
            analysis = {
                "analysis": {
                    "url": source_url,
                    "platform": "douyin",
                    "copywriting": {"title": "速干短裤"},
                }
            }
            (remix_dir / "analysis.json").write_text(json.dumps(analysis, ensure_ascii=False), encoding="utf-8")
            (affiliate_dir / "analysis.json").write_text(json.dumps(analysis, ensure_ascii=False), encoding="utf-8")
            (affiliate_dir / "口播稿.txt").write_text("口播内容", encoding="utf-8")
            (affiliate_dir / "分镜清单.md").write_text("分镜内容", encoding="utf-8")

            content_id = list_remix_packages(root)["contents"][0]["id"]
            result = start_jianying_content_generation(root, content_id, launch=False)

            self.assertTrue(result["ok"])
            self.assertEqual(result["status"], "ready_for_jianying")
            self.assertFalse(result["launched"])
            self.assertEqual(Path(result["package_dir"]).resolve(), affiliate_dir.resolve())
            task_text = Path(result["task_file"]).read_text(encoding="utf-8")
            self.assertIn("剪映生成任务", task_text)
            self.assertIn("口播稿.txt", task_text)
            self.assertIn("分镜清单.md", task_text)

    def test_start_jianying_automation_job_prepares_payload_and_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            package_dir = root / "remix_packages" / "affiliate-jianying" / "demo-affiliate"
            package_dir.mkdir(parents=True)
            (package_dir / "analysis.json").write_text(
                json.dumps(
                    {
                        "analysis": {
                            "url": "https://v.douyin.com/demo/",
                            "platform": "douyin",
                            "copywriting": {"title": "速干短裤"},
                        }
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (package_dir / "口播稿.txt").write_text("第一句口播。\n第二句口播。", encoding="utf-8")
            (package_dir / "分镜清单.md").write_text("# 分镜\n- 商品特写", encoding="utf-8")

            content_id = list_remix_packages(root)["contents"][0]["id"]
            result = start_jianying_automation_job(root, content_id, launch=False)
            status = jianying_automation_job_status(result["job_id"])

            self.assertTrue(result["ok"])
            self.assertEqual(status["state"], "completed")
            self.assertEqual(status["progress"], 100)
            self.assertTrue((package_dir / "jianying_automation_payload.json").exists())
            self.assertTrue((package_dir / "剪映UI自动化.applescript").exists())
            payload = json.loads((package_dir / "jianying_automation_payload.json").read_text(encoding="utf-8"))
            self.assertEqual(payload["script_text"], "第一句口播。\n第二句口播。")
            self.assertIn("launch_jianying", [step["id"] for step in status["steps"]])
            self.assertIn("enter_creation", [step["id"] for step in status["steps"]])

    def test_start_xiaohongshu_note_generation_creates_image_note_package(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            package_dir = root / "remix_packages" / "affiliate-jianying" / "demo-affiliate"
            package_dir.mkdir(parents=True)
            local_image = package_dir / "local-cover.jpg"
            local_image.write_bytes(b"fake-image")
            analysis = {
                "analysis": {
                    "url": "https://v.douyin.com/demo/",
                    "platform": "douyin",
                    "copywriting": {
                        "title": "速干短裤",
                        "body": "适合训练和日常打球。",
                        "tags": ["运动穿搭", "短裤"],
                    },
                    "images": [{"url": str(local_image)}],
                }
            }
            (package_dir / "analysis.json").write_text(json.dumps(analysis, ensure_ascii=False), encoding="utf-8")
            (package_dir / "小红书种草版.md").write_text("小红书正文候选", encoding="utf-8")

            content_id = list_remix_packages(root)["contents"][0]["id"]
            result = start_xiaohongshu_note_generation(root, content_id)

            self.assertTrue(result["ok"])
            note_dir = Path(result["note_dir"])
            self.assertTrue((note_dir / "小红书笔记.md").exists())
            self.assertTrue((note_dir / "图片笔记分镜.md").exists())
            self.assertTrue((note_dir / "发布清单.md").exists())
            self.assertTrue((note_dir / "images").is_dir())
            self.assertTrue(list((note_dir / "images").glob("*.jpg")))
            note_text = (note_dir / "小红书笔记.md").read_text(encoding="utf-8")
            storyboard_text = (note_dir / "图片笔记分镜.md").read_text(encoding="utf-8")
            self.assertIn("小红书正文候选", note_text)
            self.assertIn("带货承接", note_text)
            self.assertIn("/images/", storyboard_text)
            self.assertEqual(result["image_count"], 1)
            self.assertEqual(result["package_group"], "xiaohongshu-note")

    def test_start_xiaohongshu_note_generation_adds_affiliate_bridge_for_non_product_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            package_dir = root / "remix_packages" / "jianying" / "spurs-jianying"
            package_dir.mkdir(parents=True)
            image_path = package_dir / "cover.jpg"
            image_path.write_bytes(b"fake-image")
            (package_dir / "analysis.json").write_text(
                json.dumps(
                    {
                        "url": "http://xhslink.com/o/demo",
                        "platform": "xiaohongshu",
                        "copywriting": {
                            "title": "马刺最后时刻问题很大！",
                            "body": "这是一条比赛复盘。",
                            "tags": ["NBA", "马刺"],
                        },
                        "images": [{"url": str(image_path)}],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (package_dir / "文案.txt").write_text("比赛复盘正文", encoding="utf-8")

            content_id = list_remix_packages(root)["contents"][0]["id"]
            result = start_xiaohongshu_note_generation(root, content_id)

            note_text = (Path(result["note_dir"]) / "小红书笔记.md").read_text(encoding="utf-8")
            checklist_text = (Path(result["note_dir"]) / "发布清单.md").read_text(encoding="utf-8")
            self.assertIn("带货承接", note_text)
            self.assertIn("商品承接", checklist_text)
            self.assertIn("#好物分享", note_text)

    def test_start_xiaohongshu_note_generation_replaces_old_images(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            package_dir = root / "remix_packages" / "remix" / "same-title"
            package_dir.mkdir(parents=True)
            first = package_dir / "first.jpg"
            second = package_dir / "second.jpg"
            latest = package_dir / "latest.jpg"
            first.write_bytes(b"first")
            second.write_bytes(b"second")
            latest.write_bytes(b"latest")
            analysis = {
                "url": "http://xhslink.com/o/demo",
                "platform": "xiaohongshu",
                "copywriting": {"title": "同一个标题", "body": "正文", "tags": ["测试"]},
                "images": [{"url": str(first)}, {"url": str(second)}],
            }
            (package_dir / "analysis.json").write_text(json.dumps(analysis, ensure_ascii=False), encoding="utf-8")
            content_id = list_remix_packages(root)["contents"][0]["id"]
            first_result = start_xiaohongshu_note_generation(root, content_id)
            self.assertEqual(first_result["image_count"], 2)

            analysis["images"] = [{"url": str(latest)}]
            (package_dir / "analysis.json").write_text(json.dumps(analysis, ensure_ascii=False), encoding="utf-8")
            second_result = start_xiaohongshu_note_generation(root, content_id)
            note_dir = Path(second_result["note_dir"])
            images = sorted((note_dir / "images").iterdir())

            self.assertEqual(second_result["image_count"], 1)
            self.assertEqual(len(images), 1)
            self.assertIn("latest", images[0].name)
            storyboard = (note_dir / "图片笔记分镜.md").read_text(encoding="utf-8")
            self.assertIn("latest", storyboard)
            self.assertNotIn("first", storyboard)
            self.assertNotIn("second", storyboard)

    def test_xiaohongshu_generation_prefers_latest_remix_images_over_old_jianying_package(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            old_package = root / "remix_packages" / "jianying" / "old-jianying"
            latest_package = root / "remix_packages" / "remix" / "latest-remix"
            old_package.mkdir(parents=True)
            latest_package.mkdir(parents=True)
            image_c = latest_package / "image-c.jpg"
            image_c.write_bytes(b"image-c")
            source_url = "http://xhslink.com/o/same-content"
            old_analysis = {
                "url": source_url,
                "platform": "xiaohongshu",
                "copywriting": {"title": "同一个内容", "body": "旧剪映包没有图片", "tags": ["旧"]},
                "images": [],
            }
            latest_analysis = {
                "url": source_url,
                "platform": "xiaohongshu",
                "copywriting": {"title": "同一个内容", "body": "只保留新上传图片 C", "tags": ["新"]},
                "images": [{"url": str(image_c)}],
            }
            (old_package / "analysis.json").write_text(json.dumps(old_analysis, ensure_ascii=False), encoding="utf-8")
            (old_package / "文案.txt").write_text("旧剪映包文案", encoding="utf-8")
            (latest_package / "analysis.json").write_text(json.dumps(latest_analysis, ensure_ascii=False), encoding="utf-8")
            (latest_package / "copywriting.md").write_text("最新基础包文案", encoding="utf-8")
            time.sleep(0.01)

            content_id = list_remix_packages(root)["contents"][0]["id"]
            result = start_xiaohongshu_note_generation(root, content_id)
            publish = start_xiaohongshu_publish_assistant(root, content_id, launch=False)
            note_dir = Path(result["note_dir"])
            images = sorted((note_dir / "images").iterdir())

            self.assertEqual(result["source_package_group"], "remix")
            self.assertEqual(result["image_count"], 1)
            self.assertEqual(publish["image_count"], 1)
            self.assertEqual(Path(publish["opened_dir"]).name, "同一个内容-小红书图文包")
            self.assertEqual(len(images), 1)
            self.assertIn("image-c", images[0].name)

    def test_xiaohongshu_generation_can_use_explicit_source_package_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            older_package = root / "remix_packages" / "remix" / "older-remix"
            selected_package = root / "remix_packages" / "remix" / "selected-remix"
            older_package.mkdir(parents=True)
            selected_package.mkdir(parents=True)
            old_image = older_package / "old.jpg"
            selected_image = selected_package / "selected-c.jpg"
            old_image.write_bytes(b"old")
            selected_image.write_bytes(b"selected")
            source_url = "http://xhslink.com/o/explicit-source"
            for package_dir, image_path in [(older_package, old_image), (selected_package, selected_image)]:
                (package_dir / "analysis.json").write_text(
                    json.dumps(
                        {
                            "url": source_url,
                            "platform": "xiaohongshu",
                            "copywriting": {"title": "显式源包", "body": "正文", "tags": ["测试"]},
                            "images": [{"url": str(image_path)}],
                        },
                        ensure_ascii=False,
                    ),
                    encoding="utf-8",
                )
            content_id = list_remix_packages(root)["contents"][0]["id"]

            result = start_xiaohongshu_note_generation(root, content_id, "remix/selected-remix")
            images = sorted((Path(result["note_dir"]) / "images").iterdir())

            self.assertEqual(result["source_package_path"], "remix/selected-remix")
            self.assertEqual(len(images), 1)
            self.assertIn("selected-c", images[0].name)
            self.assertNotIn("old", images[0].name)

    def test_xiaohongshu_generation_removes_stale_note_packages_for_same_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            remix_dir = root / "remix_packages" / "remix" / "current-remix"
            stale_note_dir = root / "remix_packages" / "xiaohongshu-note" / "old-note"
            remix_dir.mkdir(parents=True)
            stale_note_dir.mkdir(parents=True)
            image = remix_dir / "current.jpg"
            image.write_bytes(b"current")
            source_url = "http://xhslink.com/o/stale-note"
            (remix_dir / "analysis.json").write_text(
                json.dumps(
                    {
                        "url": source_url,
                        "platform": "xiaohongshu",
                        "copywriting": {"title": "当前图文", "body": "正文", "tags": ["测试"]},
                        "images": [{"url": str(image)}],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (stale_note_dir / "analysis.json").write_text(
                json.dumps(
                    {
                        "url": source_url,
                        "platform": "xiaohongshu",
                        "copywriting": {"title": "旧图文", "body": "旧正文", "tags": ["旧"]},
                        "images": [],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            content_id = list_remix_packages(root)["contents"][0]["id"]
            result = start_xiaohongshu_note_generation(root, content_id)
            content = next(item for item in list_remix_packages(root)["contents"] if item["id"] == content_id)
            note_packages = [package for package in content["packages"] if package["group"] == "xiaohongshu-note"]

            self.assertFalse(stale_note_dir.exists())
            self.assertEqual(len(note_packages), 1)
            self.assertEqual(Path(result["note_dir"]).name, note_packages[0]["name"])

    def test_xiaohongshu_publish_assistant_opens_project_folder_after_automation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            package_dir = root / "remix_packages" / "remix" / "publish-open-folder"
            package_dir.mkdir(parents=True)
            image_path = package_dir / "cover.jpg"
            image_path.write_bytes(b"fake-image")
            (package_dir / "analysis.json").write_text(
                json.dumps(
                    {
                        "url": "http://xhslink.com/o/open-folder",
                        "platform": "xiaohongshu",
                        "copywriting": {"title": "打开图片目录", "body": "正文", "tags": ["测试"]},
                        "images": [{"url": str(image_path)}],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            content_id = list_remix_packages(root)["contents"][0]["id"]
            start_xiaohongshu_note_generation(root, content_id)

            with patch("workflow.web_app.subprocess.run") as run:
                run.return_value.returncode = 0
                run.return_value.stdout = "ok"
                run.return_value.stderr = ""
                result = start_xiaohongshu_publish_assistant(root, content_id, launch=True)

            self.assertTrue(result["opened_folder"])
            self.assertEqual(run.call_args_list[0].args[0][0], "osascript")
            self.assertEqual(run.call_args_list[1].args[0][0], "open")
            self.assertEqual(Path(run.call_args_list[1].args[0][1]).name, "打开图片目录-小红书图文包")
            self.assertNotIn("/images", run.call_args_list[1].args[0][1])

    def test_start_xiaohongshu_publish_assistant_prepares_clipboard_and_script(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            package_dir = root / "remix_packages" / "jianying" / "spurs-jianying"
            package_dir.mkdir(parents=True)
            image_path = package_dir / "cover.jpg"
            image_path.write_bytes(b"fake-image")
            (package_dir / "analysis.json").write_text(
                json.dumps(
                    {
                        "url": "http://xhslink.com/o/demo",
                        "platform": "xiaohongshu",
                        "copywriting": {
                            "title": "马刺最后时刻问题很大！",
                            "body": "比赛复盘正文",
                            "tags": ["NBA", "马刺"],
                        },
                        "images": [{"url": str(image_path)}],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            content_id = list_remix_packages(root)["contents"][0]["id"]
            start_xiaohongshu_note_generation(root, content_id)

            result = start_xiaohongshu_publish_assistant(root, content_id, launch=False)
            note_dir = Path(result["note_dir"])
            payload = json.loads((note_dir / "xiaohongshu_publish_payload.json").read_text(encoding="utf-8"))
            script_text = (note_dir / "小红书发布助手.applescript").read_text(encoding="utf-8")

            self.assertTrue(result["ok"])
            self.assertEqual(result["status"], "ready_for_rednote")
            self.assertIn("马刺最后时刻问题很大", payload["clipboard_text"])
            self.assertEqual(payload["title"], "马刺最后时刻问题很大！")
            self.assertIn("比赛复盘正文", payload["body"])
            self.assertIn("#NBA", payload["tags"])
            self.assertEqual(payload["image_count"], 1)
            self.assertEqual(result["image_count"], 1)
            self.assertEqual(Path(result["opened_dir"]).name, "马刺最后时刻问题很大--小红书图文包")
            self.assertEqual(payload["publish_intent"], "draft")
            self.assertEqual(payload["draft_intent"], "image_note")
            self.assertEqual(payload["automation_level"], "fill_draft_until_final_publish")
            self.assertIn("com.xingin.discover", script_text)
            self.assertIn("the clipboard", script_text)
            self.assertIn("draft_entry", script_text)
            self.assertIn("pasteIntoMatchingInput", script_text)
            self.assertIn("clickWindowRatio", script_text)
            self.assertIn("opened_dir=", script_text)
            self.assertNotIn('do shell script "open " & quoted form', script_text)
            self.assertIn("final_publish=manual", script_text)
            self.assertNotIn('clickFirstMatchingControl({"发布"', script_text)

    def test_create_project_from_inline_text_payload(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            payload = {
                "project_id": "web-demo",
                "script_text": "第一句。第二句。",
                "voice": "Tingting",
                "bgm": "",
                "images": [],
            }

            result = create_project_from_payload(root, payload)

            self.assertTrue(result["ok"])
            self.assertEqual(result["project_id"], "web-demo")
            self.assertTrue((root / "projects" / "web-demo" / "script.txt").exists())
            self.assertTrue((root / "projects" / "web-demo" / "exports" / "subtitles.srt").exists())

    def test_create_project_can_scale_subtitles_to_target_duration(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            payload = {
                "project_id": "duration-demo",
                "script_text": "第一句。第二句。",
                "voice": "Tingting",
                "target_duration_seconds": 42,
            }

            create_project_from_payload(root, payload)

            manifest = (root / "projects" / "duration-demo" / "episode.yaml").read_text(encoding="utf-8")
            self.assertIn("estimated_duration_seconds: 42.000", manifest)

    def test_create_project_respects_selected_platforms(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            payload = {
                "project_id": "platform-demo",
                "script_text": "第一句。第二句。",
                "voice": "Tingting",
                "platforms": ["douyin"],
            }

            create_project_from_payload(root, payload)

            platforms_dir = root / "projects" / "platform-demo" / "exports" / "platforms"
            self.assertTrue((platforms_dir / "douyin" / "metadata.json").exists())
            self.assertFalse((platforms_dir / "bilibili").exists())
            self.assertFalse((platforms_dir / "xiaohongshu").exists())

    def test_list_projects_returns_generated_content_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project_dir = root / "projects" / "demo"
            project_dir.mkdir(parents=True)
            (project_dir / "voice").mkdir()
            (project_dir / "exports").mkdir()
            (project_dir / "assets" / "images").mkdir(parents=True)
            (project_dir / "assets" / "bgm").mkdir(parents=True)
            (project_dir / "exports" / "platforms" / "douyin").mkdir(parents=True)
            (project_dir / "episode.yaml").write_text("voice: Tingting\n", encoding="utf-8")
            (project_dir / "script.txt").write_text("文案", encoding="utf-8")
            (project_dir / "voice" / "voice.aiff").write_bytes(b"audio")
            (project_dir / "exports" / "subtitles.srt").write_text("字幕", encoding="utf-8")
            (project_dir / "exports" / "performance.csv").write_text(
                "platform,status,publish_url,views,likes,comments,favorites,shares,followers_delta,conversion_notes,review_notes\n"
                "douyin,published,https://example.com,100,12,3,8,2,5,私信 1 个,标题不错\n",
                encoding="utf-8",
            )
            (project_dir / "exports" / "title-experiments.csv").write_text(
                "platform,platform_name,variant_index,title,hypothesis,selected,publish_url,views,click_rate,notes\n"
                "douyin,抖音,1,标题 A,测试停留,yes,https://example.com,100,3.2,首版\n",
                encoding="utf-8",
            )
            (project_dir / "exports" / "hook-analysis.json").write_text(
                json.dumps({"hook_text": "为什么没有流量？", "score": 78, "grade": "可用"}, ensure_ascii=False),
                encoding="utf-8",
            )
            (project_dir / "exports" / "monetization-plan.json").write_text(
                json.dumps({"primary_offer": {"name": "流量清单"}, "platform_routes": {"douyin": {}}}, ensure_ascii=False),
                encoding="utf-8",
            )
            (project_dir / "exports" / "series-plan.json").write_text(
                json.dumps({"series_name": "流量系列", "episodes": [{"title": "下一条"}]}, ensure_ascii=False),
                encoding="utf-8",
            )
            (project_dir / "exports" / "publish-schedule.json").write_text(
                json.dumps({"slots": [{"day": "D+0", "platform": "douyin", "title": "发布标题"}]}, ensure_ascii=False),
                encoding="utf-8",
            )
            (project_dir / "exports" / "preview.mp4").write_bytes(b"video")
            (project_dir / "exports" / "platforms" / "douyin" / "video.mp4").write_bytes(b"video")
            (project_dir / "exports" / "platforms" / "douyin" / "cover.png").write_bytes(b"cover")
            (project_dir / "exports" / "platforms" / "douyin" / "metadata.json").write_text(
                json.dumps(
                    {
                        "platform": {"name": "抖音", "aspect_ratio": "9:16"},
                        "title": "测试标题",
                        "title_variants": ["标题 A", "标题 B"],
                        "hashtags": ["情绪", "成长"],
                        "comment_prompt": "评论区说一个关键词",
                        "conversion_cta": "关注下一条",
                        "description": "简介",
                        "traffic_score": 76,
                        "technical_checklist": ["字幕已硬烧"],
                        "traffic_checklist": ["前三秒直接抛冲突"],
                        "risk_checks": [{"type": "none", "hits": [], "action": "人工复核"}],
                        "improvement_suggestions": ["封面再压短"],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (project_dir / "assets" / "images" / "one.png").write_bytes(b"image")
            (project_dir / "assets" / "bgm" / "music.mp3").write_bytes(b"music")

            projects = list_projects(root)

            self.assertEqual(projects[0]["id"], "demo")
            self.assertEqual(projects[0]["manifest"], "voice: Tingting\n")
            self.assertTrue(projects[0]["has_audio"])
            self.assertTrue(projects[0]["has_subtitles"])
            self.assertTrue(projects[0]["has_video"])
            self.assertTrue(projects[0]["can_preview"])
            self.assertEqual(projects[0]["image_count"], 1)
            self.assertEqual(projects[0]["bgm_count"], 1)
            self.assertEqual(projects[0]["script"], "projects/demo/script.txt")
            self.assertEqual(projects[0]["audio"], "projects/demo/voice/voice.aiff")
            self.assertEqual(projects[0]["subtitles"], "projects/demo/exports/subtitles.srt")
            self.assertEqual(projects[0]["video"], "projects/demo/exports/preview.mp4")
            self.assertEqual(projects[0]["platform_packages"][0]["name"], "抖音")
            self.assertEqual(projects[0]["platform_packages"][0]["score"], 76)
            self.assertEqual(projects[0]["platform_packages"][0]["video"], "/media/demo/exports/platforms/douyin/video.mp4")
            self.assertEqual(projects[0]["platform_packages"][0]["cover"], "/media/demo/exports/platforms/douyin/cover.png")
            self.assertEqual(projects[0]["platform_packages"][0]["technical_checklist"], ["字幕已硬烧"])
            self.assertEqual(projects[0]["platform_packages"][0]["traffic_checklist"], ["前三秒直接抛冲突"])
            self.assertEqual(projects[0]["platform_packages"][0]["improvement_suggestions"], ["封面再压短"])
            self.assertEqual(projects[0]["platform_packages"][0]["title_variants"], ["标题 A", "标题 B"])
            self.assertEqual(projects[0]["platform_packages"][0]["hashtags"], ["情绪", "成长"])
            self.assertEqual(projects[0]["platform_packages"][0]["comment_prompt"], "评论区说一个关键词")
            self.assertEqual(projects[0]["platform_packages"][0]["conversion_cta"], "关注下一条")
            self.assertEqual(projects[0]["performance"][0]["platform"], "douyin")
            self.assertEqual(projects[0]["performance"][0]["views"], 100)
            self.assertEqual(projects[0]["performance_insights"]["best_platform"], "douyin")
            self.assertGreater(projects[0]["performance_insights"]["rows"][0]["engagement_rate"], 0)
            self.assertEqual(projects[0]["title_experiments"][0]["title"], "标题 A")
            self.assertEqual(projects[0]["title_experiments"][0]["click_rate"], "3.2")
            self.assertEqual(projects[0]["hook_analysis"]["score"], 78)
            self.assertEqual(projects[0]["monetization_plan"]["primary_offer"]["name"], "流量清单")
            self.assertEqual(projects[0]["series_plan"]["series_name"], "流量系列")
            self.assertEqual(projects[0]["publish_schedule"]["slots"][0]["day"], "D+0")

    def test_delete_projects_removes_selected_project_dirs_safely(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            keep = root / "projects" / "keep"
            first = root / "projects" / "first"
            second = root / "projects" / "second"
            keep.mkdir(parents=True)
            first.mkdir()
            second.mkdir()

            result = delete_projects(root, ["first", "second", "../escape", "missing"])

            self.assertTrue(result["ok"])
            self.assertEqual(result["deleted"], ["first", "second"])
            self.assertEqual(result["invalid"], ["../escape"])
            self.assertEqual(result["missing"], ["missing"])
            self.assertTrue(keep.exists())
            self.assertFalse(first.exists())
            self.assertFalse(second.exists())

    def test_parse_byte_range_supports_video_seeking_headers(self):
        self.assertEqual(parse_byte_range("bytes=100-199", 1000), (100, 199))
        self.assertEqual(parse_byte_range("bytes=100-", 1000), (100, 999))
        self.assertEqual(parse_byte_range("bytes=-200", 1000), (800, 999))
        self.assertEqual(parse_byte_range("", 1000), None)
        self.assertEqual(parse_byte_range("bytes=1000-", 1000), "invalid")
        self.assertEqual(parse_byte_range("items=0-1", 1000), "invalid")

    def test_read_and_save_project_performance_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project_dir = root / "projects" / "demo"
            (project_dir / "exports").mkdir(parents=True)
            (project_dir / "exports" / "performance.csv").write_text(
                "platform,status,publish_url,views,likes,comments,favorites,shares,followers_delta,conversion_notes,review_notes\n"
                "bilibili,planned,,0,0,0,0,0,0,,\n",
                encoding="utf-8",
            )

            saved = save_project_performance(
                root,
                "demo",
                [
                    {
                        "platform": "bilibili",
                        "status": "published",
                        "publish_url": "https://example.com/video",
                        "views": 2300,
                        "likes": 88,
                        "comments": 19,
                        "favorites": 41,
                        "shares": 7,
                        "followers_delta": 12,
                        "conversion_notes": "主页咨询 2 个",
                        "review_notes": "标题钩子有效",
                    }
                ],
            )

            self.assertTrue(saved["ok"])
            rows = read_project_performance(root, "demo")["performance"]
            self.assertEqual(rows[0]["status"], "published")
            self.assertEqual(rows[0]["views"], 2300)
            self.assertEqual(rows[0]["conversion_notes"], "主页咨询 2 个")

    def test_read_and_save_title_experiments_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project_dir = root / "projects" / "demo"
            (project_dir / "exports").mkdir(parents=True)

            saved = save_title_experiments(
                root,
                "demo",
                [
                    {
                        "platform": "douyin",
                        "platform_name": "抖音",
                        "variant_index": 1,
                        "title": "测试标题",
                        "hypothesis": "验证前三秒停留",
                        "selected": True,
                        "publish_url": "https://example.com/video",
                        "views": 1200,
                        "click_rate": "4.20%",
                        "notes": "首版表现较好",
                    }
                ],
            )

            self.assertTrue(saved["ok"])
            rows = read_title_experiments(root, "demo")["title_experiments"]
            self.assertEqual(rows[0]["platform"], "douyin")
            self.assertEqual(rows[0]["selected"], "yes")
            self.assertEqual(rows[0]["views"], 1200)
            self.assertEqual(rows[0]["click_rate"], "4.2")

    def test_read_title_experiments_backfills_from_platform_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project_dir = root / "projects" / "demo"
            platform_dir = project_dir / "exports" / "platforms" / "douyin"
            platform_dir.mkdir(parents=True)
            (platform_dir / "metadata.json").write_text(
                json.dumps(
                    {
                        "platform": {"name": "抖音"},
                        "title_variants": ["标题 A", "标题 B"],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            result = read_title_experiments(root, "demo")

            self.assertTrue(result["ok"])
            self.assertEqual(len(result["title_experiments"]), 2)
            self.assertEqual(result["title_experiments"][0]["platform"], "douyin")
            self.assertTrue((project_dir / "exports" / "title-experiments.csv").exists())

    def test_read_hook_analysis_backfills_from_script(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project_dir = root / "projects" / "demo"
            platform_dir = project_dir / "exports" / "platforms" / "douyin"
            platform_dir.mkdir(parents=True)
            (project_dir / "script.txt").write_text("为什么很多视频没有流量？真正的问题是前三秒太平。", encoding="utf-8")
            (platform_dir / "metadata.json").write_text(
                json.dumps({"platform": {"name": "抖音"}}, ensure_ascii=False),
                encoding="utf-8",
            )

            result = read_hook_analysis(root, "demo")

            self.assertTrue(result["ok"])
            self.assertIn("hook_text", result["hook_analysis"])
            self.assertIn("douyin", result["hook_analysis"]["platform_rewrites"])
            self.assertTrue((project_dir / "exports" / "hook-analysis.json").exists())

    def test_read_monetization_plan_backfills_from_script(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project_dir = root / "projects" / "demo"
            platform_dir = project_dir / "exports" / "platforms" / "xiaohongshu"
            platform_dir.mkdir(parents=True)
            (project_dir / "script.txt").write_text("为什么视频发了很多还是没有流量？这期讲涨粉和变现。", encoding="utf-8")
            (platform_dir / "metadata.json").write_text(
                json.dumps({"platform": {"name": "小红书"}}, ensure_ascii=False),
                encoding="utf-8",
            )

            result = read_monetization_plan(root, "demo")

            self.assertTrue(result["ok"])
            self.assertIn("primary_offer", result["monetization_plan"])
            self.assertIn("xiaohongshu", result["monetization_plan"]["platform_routes"])
            self.assertTrue((project_dir / "exports" / "monetization-plan.json").exists())

    def test_read_series_plan_backfills_from_script(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project_dir = root / "projects" / "demo"
            platform_dir = project_dir / "exports" / "platforms" / "bilibili"
            platform_dir.mkdir(parents=True)
            (project_dir / "script.txt").write_text("为什么视频发了很多还是没有流量？这期讲涨粉和变现。", encoding="utf-8")
            (platform_dir / "metadata.json").write_text(
                json.dumps({"platform": {"name": "哔哩哔哩"}}, ensure_ascii=False),
                encoding="utf-8",
            )

            result = read_series_plan(root, "demo")

            self.assertTrue(result["ok"])
            self.assertIn("series_name", result["series_plan"])
            self.assertEqual(result["series_plan"]["platforms"], ["bilibili"])
            self.assertTrue((project_dir / "exports" / "series-plan.json").exists())

    def test_read_publish_schedule_backfills_from_script(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project_dir = root / "projects" / "demo"
            platform_dir = project_dir / "exports" / "platforms" / "douyin"
            platform_dir.mkdir(parents=True)
            (project_dir / "script.txt").write_text("为什么视频发了很多还是没有流量？这期讲涨粉和变现。", encoding="utf-8")
            (platform_dir / "metadata.json").write_text(
                json.dumps({"platform": {"name": "抖音"}}, ensure_ascii=False),
                encoding="utf-8",
            )

            result = read_publish_schedule(root, "demo")

            self.assertTrue(result["ok"])
            self.assertTrue(result["publish_schedule"]["slots"])
            self.assertEqual(result["publish_schedule"]["slots"][0]["platform"], "douyin")
            self.assertTrue((project_dir / "exports" / "publish-schedule.json").exists())

    def test_performance_insights_scores_platform_results(self):
        insights = performance_insights(
            [
                {
                    "platform": "bilibili",
                    "views": 1000,
                    "likes": 20,
                    "comments": 5,
                    "favorites": 15,
                    "shares": 3,
                    "followers_delta": 2,
                },
                {
                    "platform": "douyin",
                    "views": 500,
                    "likes": 60,
                    "comments": 20,
                    "favorites": 40,
                    "shares": 10,
                    "followers_delta": 12,
                },
            ]
        )

        self.assertEqual(insights["best_platform"], "douyin")
        douyin = next(row for row in insights["rows"] if row["platform"] == "douyin")
        self.assertAlmostEqual(douyin["engagement_rate"], 0.26)
        self.assertAlmostEqual(douyin["favorite_rate"], 0.08)
        self.assertTrue(insights["suggestions"])

    def test_performance_summary_aggregates_across_projects(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = root / "projects" / "first" / "exports"
            second = root / "projects" / "second" / "exports"
            first.mkdir(parents=True)
            second.mkdir(parents=True)
            header = "platform,status,publish_url,views,likes,comments,favorites,shares,followers_delta,conversion_notes,review_notes\n"
            (first / "performance.csv").write_text(
                header + "douyin,published,,1000,100,20,80,10,30,,爆款钩子\n",
                encoding="utf-8",
            )
            (second / "performance.csv").write_text(
                header + "bilibili,published,,2000,40,10,30,5,5,,长视频一般\n",
                encoding="utf-8",
            )

            summary = performance_summary(root)

            self.assertTrue(summary["ok"])
            self.assertEqual(summary["total_views"], 3000)
            self.assertEqual(summary["best_platform"], "douyin")
            self.assertEqual(summary["best_project"], "first")
            self.assertEqual(summary["platforms"]["douyin"]["views"], 1000)
            self.assertTrue(summary["suggestions"])

    def test_list_projects_sorts_newest_first(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            older = root / "projects" / "aaa-old"
            newer = root / "projects" / "zzz-new"
            older.mkdir(parents=True)
            newer.mkdir(parents=True)
            (older / "script.txt").write_text("old", encoding="utf-8")
            time.sleep(0.01)
            (newer / "script.txt").write_text("new", encoding="utf-8")

            projects = list_projects(root)

            self.assertEqual([project["id"] for project in projects], ["zzz-new", "aaa-old"])

    def test_package_platform_publish_creates_downloadable_zip(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project_dir = root / "projects" / "demo"
            platform_dir = project_dir / "exports" / "platforms" / "douyin"
            platform_dir.mkdir(parents=True)
            (project_dir / "exports").mkdir(exist_ok=True)
            (project_dir / "script.txt").write_text("文案", encoding="utf-8")
            (project_dir / "episode.yaml").write_text("topic: demo\n", encoding="utf-8")
            (project_dir / "assets").mkdir(exist_ok=True)
            (project_dir / "assets" / "licenses.md").write_text("素材授权", encoding="utf-8")
            (project_dir / "exports" / "subtitles.srt").write_text("字幕", encoding="utf-8")
            (project_dir / "exports" / "performance.csv").write_text("platform,status\n", encoding="utf-8")
            (project_dir / "exports" / "title-experiments.csv").write_text("platform,title\n", encoding="utf-8")
            (project_dir / "exports" / "hook-analysis.json").write_text("{}", encoding="utf-8")
            (project_dir / "exports" / "monetization-plan.json").write_text("{}", encoding="utf-8")
            (project_dir / "exports" / "series-plan.json").write_text("{}", encoding="utf-8")
            (project_dir / "exports" / "publish-schedule.json").write_text("{}", encoding="utf-8")
            (platform_dir / "metadata.json").write_text("{}", encoding="utf-8")
            (platform_dir / "publish.md").write_text("发布说明", encoding="utf-8")
            (platform_dir / "cover.png").write_bytes(b"cover")
            (platform_dir / "video.mp4").write_bytes(b"video")

            result = package_platform_publish(root, "demo", "douyin")

            self.assertTrue(result["ok"])
            self.assertEqual(result["package_url"], "/media/demo/exports/platforms/douyin/publish-package.zip")
            package_path = Path(result["package"])
            self.assertTrue(package_path.exists())
            self.assertIn("video.mp4", result["files"])
            self.assertIn("script.txt", result["files"])
            self.assertIn("assets/licenses.md", result["files"])
            self.assertIn("exports/performance.csv", result["files"])
            self.assertIn("exports/title-experiments.csv", result["files"])
            self.assertIn("exports/hook-analysis.json", result["files"])
            self.assertIn("exports/monetization-plan.json", result["files"])
            self.assertIn("exports/series-plan.json", result["files"])
            self.assertIn("exports/publish-schedule.json", result["files"])

    def test_selected_platform_presets_follow_existing_metadata_dirs(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp) / "projects" / "demo"
            self.assertEqual([preset.key for preset in selected_platform_presets(project_dir)], ["bilibili", "xiaohongshu", "douyin"])

            (project_dir / "exports" / "platforms" / "douyin").mkdir(parents=True)
            (project_dir / "exports" / "platforms" / "douyin" / "metadata.json").write_text("{}", encoding="utf-8")

            self.assertEqual([preset.key for preset in selected_platform_presets(project_dir)], ["douyin"])

    def test_create_project_from_uploaded_text_payload(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            upload = root / "upload.txt"
            upload.write_text("上传文案第一句。", encoding="utf-8")
            payload = {
                "project_id": "upload-demo",
                "script_path": str(upload),
                "voice": "Tingting",
                "images": [],
            }

            result = create_project_from_payload(root, payload)

            self.assertTrue(result["ok"])
            self.assertIn("upload-demo", json.dumps(result, ensure_ascii=False))

    def test_voice_list_exposes_capcut_reference_voice_first(self):
        self.assertEqual(list_voices(), [CAPCUT_CALM_MALE_LABEL, REFERENCE_VOICE_LABEL])

    def test_save_uploaded_files_copies_multipart_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            boundary = "----workflow-test"
            body = (
                f"--{boundary}\r\n"
                'Content-Disposition: form-data; name="files"; filename="demo.txt"\r\n'
                "Content-Type: text/plain\r\n\r\n"
                "hello\r\n"
                f"--{boundary}--\r\n"
            ).encode("utf-8")

            result = save_uploaded_files(
                root,
                f"multipart/form-data; boundary={boundary}",
                body,
                kind="scripts",
            )

            self.assertTrue(result["ok"])
            saved = Path(result["files"][0]["path"])
            self.assertTrue(saved.exists())
            self.assertEqual(saved.read_text(encoding="utf-8"), "hello")
            self.assertIn("/uploads/scripts/", str(saved))

    def test_polish_remix_images_with_codex_passes_selected_images_and_prompt(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "uploads" / "remix-images" / "one.png"
            source.parent.mkdir(parents=True)
            source.write_bytes(b"image")

            def fake_run(command, text, capture_output, timeout, check, input=None):
                output_dir = Path(command[command.index("--add-dir") + 1])
                (output_dir / "polished-01.png").write_bytes(b"polished")
                return type("Result", (), {"returncode": 0, "stdout": "ok", "stderr": ""})()

            with patch("workflow.web_app.find_codex_cli", return_value="/usr/local/bin/codex"), patch(
                "workflow.web_app.subprocess.run", side_effect=fake_run
            ) as run:
                result = polish_remix_images_with_codex(
                    root,
                    {
                        "images": [str(source)],
                        "prompt": "改成小红书清爽种草风，提升亮度和质感",
                    },
                )

            self.assertTrue(result["ok"])
            self.assertEqual(len(result["images"]), 1)
            self.assertTrue(result["images"][0]["path"].endswith("polished-01.png"))
            command = run.call_args.args[0]
            self.assertIn("--image", command)
            image_arg = command[command.index("--image") + 1]
            self.assertTrue(image_arg.endswith("01-one.png"))
            self.assertEqual(command[-1], "-")
            prompt_text = run.call_args.kwargs["input"]
            self.assertIn("改成小红书清爽种草风", prompt_text)
            self.assertIn("Use case: ads-marketing / product-mockup", prompt_text)
            self.assertIn("必须调用 Codex 的 imagegen skill", prompt_text)
            self.assertIn("禁止只给原图增加边框", prompt_text)
            self.assertIn("小红书/抖音/电商带货", prompt_text)

    def test_codex_image_polish_prompt_builds_product_ad_brief(self):
        prompt = codex_image_polish_prompt(
            "做成厨房用品带货主图，清爽干净，突出耐用和易清洁",
            Path("/tmp/out"),
            [Path("01-product.png")],
        )

        self.assertIn("产品宣传图", prompt)
        self.assertIn("主体保真", prompt)
        self.assertIn("场景化背景", prompt)
        self.assertIn("摄影级灯光", prompt)
        self.assertIn("禁止只给原图增加边框", prompt)
        self.assertIn("polished-01.png", prompt)

    def test_polish_remix_images_returns_outputs_when_codex_times_out_after_writing_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "uploads" / "remix-images" / "one.png"
            source.parent.mkdir(parents=True)
            source.write_bytes(b"image")

            def fake_run(command, text, capture_output, timeout, check, input=None):
                output_dir = Path(command[command.index("--add-dir") + 1])
                (output_dir / "polished-01.png").write_bytes(b"polished")
                raise subprocess.TimeoutExpired(command, timeout, output="still running", stderr="")

            with patch("workflow.web_app.find_codex_cli", return_value="/usr/local/bin/codex"), patch(
                "workflow.web_app.subprocess.run", side_effect=fake_run
            ):
                result = polish_remix_images_with_codex(
                    root,
                    {"images": [str(source)], "prompt": "生成小红书产品宣传图"},
                )

            self.assertTrue(result["ok"])
            self.assertTrue(result["timed_out"])
            self.assertEqual(len(result["images"]), 1)
            self.assertIn("polished-01.png", result["images"][0]["path"])

    def test_polish_remix_images_requires_prompt_and_images(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            missing_images = polish_remix_images_with_codex(root, {"prompt": "提升质感"})
            missing_prompt = polish_remix_images_with_codex(root, {"images": ["/tmp/a.png"], "prompt": ""})

            self.assertFalse(missing_images["ok"])
            self.assertIn("请选择", missing_images["error"])
            self.assertFalse(missing_prompt["ok"])
            self.assertIn("提示词", missing_prompt["error"])

    def test_polish_remix_images_locally_checks_comfyui_availability(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            with patch("workflow.web_app.urllib.request.urlopen", side_effect=OSError("refused")):
                result = polish_remix_images_locally(
                    root,
                    {"images": ["/tmp/a.png"], "prompt": "生成小红书产品宣传图"},
                )

            self.assertFalse(result["ok"])
            self.assertEqual(result["engine"], "local")
            self.assertIn("ComfyUI", result["error"])
            self.assertIn("127.0.0.1:8188", result["error"])

    def test_codex_polish_failure_payload_reports_stream_disconnect(self):
        with tempfile.TemporaryDirectory() as tmp:
            request_dir = Path(tmp) / "codex-image-polish"
            stderr = (
                "Reading prompt from stdin...\n"
                "OpenAI Codex v0.137.0-alpha.4\n"
                "ERROR: stream disconnected before completion: error sending request for url "
                "(https://chatgpt.com/backend-api/codex/responses)"
            )

            result = codex_polish_failure_payload(request_dir, "", stderr)

            self.assertFalse(result["ok"])
            self.assertTrue(result["retryable"])
            self.assertIn("网络连接中断", result["error"])
            self.assertNotIn("Reading prompt from stdin", result["error"])

    def test_reference_voice_preset_maps_to_local_tts_engine(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            payload = {
                "project_id": "voice-preset-demo",
                "script_text": "参考声音测试。",
                "voice": REFERENCE_VOICE_LABEL,
                "images": [],
            }

            create_project_from_payload(root, payload)

            command = root / "projects" / "voice-preset-demo" / "voice" / "generate_voice.sh"
            self.assertIn("'say' '-v' 'Tingting'", command.read_text(encoding="utf-8"))

    def test_capcut_calm_male_preset_uses_edge_tts_mp3(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            payload = {
                "project_id": "capcut-voice-demo",
                "script_text": "剪映沉稳男声测试。",
                "voice": CAPCUT_CALM_MALE_LABEL,
                "images": [],
            }

            create_project_from_payload(root, payload)

            project_dir = root / "projects" / "capcut-voice-demo"
            command = project_dir / "voice" / "generate_voice.sh"
            self.assertIn("'python3' '-m' 'edge_tts'", command.read_text(encoding="utf-8"))
            self.assertIn("'zh-CN-YunyangNeural'", command.read_text(encoding="utf-8"))
            self.assertIn("'--rate=-6%'", command.read_text(encoding="utf-8"))
            self.assertIn("'--pitch=-2Hz'", command.read_text(encoding="utf-8"))
            self.assertIn("voice.mp3", command.read_text(encoding="utf-8"))
            self.assertIn("voice: jianying-calm-male", (project_dir / "episode.yaml").read_text(encoding="utf-8"))

    def test_preview_project_returns_audio_subtitles_and_images(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project_dir = root / "projects" / "demo"
            (project_dir / "voice").mkdir(parents=True)
            (project_dir / "exports").mkdir()
            (project_dir / "assets" / "images").mkdir(parents=True)
            (project_dir / "voice" / "voice.aiff").write_bytes(b"audio")
            (project_dir / "exports" / "subtitles.srt").write_text(
                "1\n00:00:00,000 --> 00:00:01,200\n第一句。\n",
                encoding="utf-8",
            )
            (project_dir / "assets" / "images" / "one.png").write_bytes(b"image")

            preview = preview_project(root, "demo")

            self.assertTrue(preview["ok"])
            self.assertEqual(preview["audio_url"], "/media/demo/voice/voice.aiff")
            self.assertEqual(preview["video_url"], "")
            self.assertEqual(preview["subtitles"][0]["text"], "第一句。")
            self.assertEqual(preview["images"], ["/media/demo/assets/images/one.png"])

    def test_preview_project_prefers_wav_and_encodes_media_urls(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project_id = "测试第一个项目"
            project_dir = root / "projects" / project_id
            (project_dir / "voice").mkdir(parents=True)
            (project_dir / "exports").mkdir()
            (project_dir / "assets" / "images").mkdir(parents=True)
            (project_dir / "voice" / "voice.aiff").write_bytes(b"aiff")
            (project_dir / "voice" / "voice.wav").write_bytes(b"wav")
            (project_dir / "exports" / "subtitles.srt").write_text(
                "1\n00:00:00,000 --> 00:00:01,200\n第一句。\n",
                encoding="utf-8",
            )
            (project_dir / "assets" / "images" / "封面 图.png").write_bytes(b"image")

            preview = preview_project(root, project_id)

            self.assertEqual(
                preview["audio_url"],
                "/media/%E6%B5%8B%E8%AF%95%E7%AC%AC%E4%B8%80%E4%B8%AA%E9%A1%B9%E7%9B%AE/voice/voice.wav",
            )
            self.assertEqual(
                preview["images"],
                [
                    "/media/%E6%B5%8B%E8%AF%95%E7%AC%AC%E4%B8%80%E4%B8%AA%E9%A1%B9%E7%9B%AE/assets/images/%E5%B0%81%E9%9D%A2%20%E5%9B%BE.png"
                ],
            )

    def test_preview_project_returns_encoded_mp4_when_video_exists(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project_id = "测试第一个项目"
            project_dir = root / "projects" / project_id
            (project_dir / "voice").mkdir(parents=True)
            (project_dir / "exports").mkdir()
            (project_dir / "voice" / "voice.wav").write_bytes(b"wav")
            (project_dir / "exports" / "preview.mp4").write_bytes(b"mp4")
            (project_dir / "exports" / "subtitles.srt").write_text(
                "1\n00:00:00,000 --> 00:00:01,200\n第一句。\n",
                encoding="utf-8",
            )

            preview = preview_project(root, project_id)

            self.assertEqual(
                preview["video_url"],
                "/media/%E6%B5%8B%E8%AF%95%E7%AC%AC%E4%B8%80%E4%B8%AA%E9%A1%B9%E7%9B%AE/exports/preview.mp4",
            )

    def test_export_video_command_uses_ffmpeg_to_create_mp4(self):
        root = Path("/tmp/workflow")
        project_id = "demo"
        project_dir = root / "projects" / project_id
        command = export_video_command(
            ffmpeg="ffmpeg",
            project_dir=project_dir,
            image=project_dir / "assets" / "images" / "one.png",
            audio=project_dir / "voice" / "voice.wav",
            ass=project_dir / "exports" / "subtitles.ass",
            output=project_dir / "exports" / "preview.mp4",
        )

        self.assertEqual(command[0], "ffmpeg")
        self.assertIn("-loop", command)
        self.assertIn("-vf", command)
        video_filter = command[command.index("-vf") + 1]
        self.assertIn("fps=30", video_filter)
        self.assertIn("scale=1280:720:force_original_aspect_ratio=increase", video_filter)
        self.assertIn("crop=1280:720", video_filter)
        self.assertIn("zoompan", video_filter)
        self.assertIn("subtitles=filename=exports/subtitles.ass", video_filter)
        self.assertIn("libx264", command)
        self.assertIn("-b:v", command)
        self.assertEqual(command[command.index("-b:v") + 1], "6000k")
        self.assertIn("-ar", command)
        self.assertEqual(command[command.index("-ar") + 1], "44100")
        self.assertIn("-ac", command)
        self.assertEqual(command[command.index("-ac") + 1], "2")
        self.assertIn("-b:a", command)
        self.assertEqual(command[command.index("-b:a") + 1], "160k")
        self.assertEqual(command[-1], "exports/preview.mp4")

    def test_prepare_visual_source_creates_slideshow_for_multiple_images(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp) / "projects" / "demo"
            image_dir = project_dir / "assets" / "images"
            voice_dir = project_dir / "voice"
            image_dir.mkdir(parents=True)
            voice_dir.mkdir(parents=True)
            first = image_dir / "one.png"
            second = image_dir / "two.png"
            audio = voice_dir / "voice.wav"
            first.write_bytes(b"one")
            second.write_bytes(b"two")
            audio.write_bytes(b"audio")

            source, is_sequence = prepare_visual_source(project_dir, first, audio, target_duration_seconds=12)

            self.assertTrue(is_sequence)
            self.assertEqual(source.name, "slideshow.ffconcat")
            text = source.read_text(encoding="utf-8")
            self.assertIn("ffconcat version 1.0", text)
            self.assertIn(str(first), text)
            self.assertIn(str(second), text)
            self.assertIn("duration 6.000", text)

    def test_export_video_command_allows_default_cover_outside_project(self):
        root = Path("/tmp/workflow")
        project_dir = root / "projects" / "demo"
        image = root / "web" / "default-cover.ppm"

        command = export_video_command(
            ffmpeg="ffmpeg",
            project_dir=project_dir,
            image=image,
            audio=project_dir / "voice" / "voice.wav",
            ass=project_dir / "exports" / "subtitles.ass",
            output=project_dir / "exports" / "preview.mp4",
        )

        self.assertIn(str(image), command)

    def test_export_video_command_can_target_platform_canvas(self):
        root = Path("/tmp/workflow")
        project_dir = root / "projects" / "demo"

        command = export_video_command(
            ffmpeg="ffmpeg",
            project_dir=project_dir,
            image=project_dir / "assets" / "images" / "one.png",
            audio=project_dir / "voice" / "voice.wav",
            ass=project_dir / "exports" / "subtitles.ass",
            output=project_dir / "exports" / "platforms" / "douyin" / "video.mp4",
            target_size="1080x1920",
        )

        video_filter = command[command.index("-vf") + 1]
        self.assertIn("scale=1080:1920:force_original_aspect_ratio=increase", video_filter)
        self.assertIn("crop=1080:1920", video_filter)
        self.assertIn("zoompan", video_filter)
        self.assertEqual(command[-1], "exports/platforms/douyin/video.mp4")

    def test_export_video_command_mixes_bgm_when_available(self):
        root = Path("/tmp/workflow")
        project_dir = root / "projects" / "demo"

        command = export_video_command(
            ffmpeg="ffmpeg",
            project_dir=project_dir,
            image=project_dir / "assets" / "images" / "one.png",
            audio=project_dir / "voice" / "voice.wav",
            ass=project_dir / "exports" / "subtitles.ass",
            output=project_dir / "exports" / "preview.mp4",
            bgm=project_dir / "assets" / "bgm" / "music.mp3",
        )

        self.assertIn("-stream_loop", command)
        self.assertIn("assets/bgm/music.mp3", command)
        self.assertIn("-filter_complex", command)
        self.assertIn("amix=inputs=2:duration=first", command[command.index("-filter_complex") + 1])
        self.assertIn("[aout]", command)

    def test_export_video_command_limits_threads_and_accepts_target_duration(self):
        root = Path("/tmp/workflow")
        project_dir = root / "projects" / "demo"

        command = export_video_command(
            ffmpeg="ffmpeg",
            project_dir=project_dir,
            image=project_dir / "assets" / "images" / "one.png",
            audio=project_dir / "voice" / "voice.wav",
            ass=project_dir / "exports" / "subtitles.ass",
            output=project_dir / "exports" / "preview.mp4",
            target_duration_seconds=30,
        )

        self.assertIn("-threads", command)
        self.assertEqual(command[command.index("-threads") + 1], "2")
        self.assertIn("-filter_threads", command)
        self.assertIn("-t", command)
        self.assertEqual(command[command.index("-t") + 1], "30")
        self.assertNotIn("-shortest", command)

    def test_video_scale_filter_rejects_invalid_target_size(self):
        self.assertIn("scale=1280:720", video_scale_filter())
        self.assertIn("pad=1280:720", video_scale_filter())
        self.assertIn("zoompan", video_scale_filter(motion=True))
        self.assertIn("crop=1280:720", video_scale_filter(motion=True))

    def test_export_short_clips_command_segments_platform_video(self):
        root = Path("/tmp/workflow")
        project_dir = root / "projects" / "demo"

        command = export_short_clips_command(
            "ffmpeg",
            project_dir,
            project_dir / "exports" / "platforms" / "douyin" / "video.mp4",
            project_dir / "exports" / "platforms" / "douyin" / "short-%02d.mp4",
            60,
        )

        self.assertIn("-f", command)
        self.assertIn("segment", command)
        self.assertIn("-segment_time", command)
        self.assertIn("60", command)
        self.assertEqual(command[-1], "exports/platforms/douyin/short-%02d.mp4")

    def test_default_cover_uses_even_dimensions_for_h264(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "web").mkdir()

            cover = default_cover_image(root)
            header = cover.read_bytes().splitlines()[:2]

            self.assertEqual(header[0], b"P6")
            self.assertEqual(header[1], b"1280 720")

    def test_write_ass_subtitles_creates_styled_dialogues(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            srt = root / "subtitles.srt"
            ass = root / "subtitles.ass"
            srt.write_text(
                "1\n00:00:00,000 --> 00:00:01,200\n第一句。\n\n"
                "2\n00:00:01,200 --> 00:00:03,400\n第二句。\n",
                encoding="utf-8",
            )

            write_ass_subtitles(srt, ass)

            text = ass.read_text(encoding="utf-8")
            self.assertIn("[V4+ Styles]", text)
            self.assertIn("Style: Default", text)
            self.assertIn("Dialogue: 0,0:00:00.00,0:00:01.20,Default,,0,0,0,,第一句。", text)
            self.assertIn("Dialogue: 0,0:00:01.20,0:00:03.40,Default,,0,0,0,,第二句。", text)

    def test_export_video_reports_missing_subtitles_filter(self):
        from workflow.web_app import ffmpeg_supports_subtitles_filter

        self.assertFalse(ffmpeg_supports_subtitles_filter("/bin/false"))

    def test_find_ffmpeg_with_subtitles_returns_usable_binary(self):
        ffmpeg = find_ffmpeg_with_subtitles()

        self.assertTrue(ffmpeg)


if __name__ == "__main__":
    unittest.main()
