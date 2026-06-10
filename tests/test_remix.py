import json
import tempfile
import unittest
from pathlib import Path

from workflow.remix import (
    analyze_remix_link,
    create_affiliate_jianying_handoff,
    create_affiliate_remix_plan,
    create_jianying_handoff,
    create_remix_package,
    detect_short_video_platform,
    llmstudio_payload,
    normalize_copy_suggestions,
    parse_llmstudio_suggestions,
    parse_remix_html_metadata,
    preferred_llmstudio_model,
    summarize_llmstudio_models,
)


class RemixWorkflowTest(unittest.TestCase):
    def test_detect_short_video_platform_from_url(self):
        self.assertEqual(detect_short_video_platform("https://v.douyin.com/example/"), "douyin")
        self.assertEqual(detect_short_video_platform("https://www.kuaishou.com/short-video/abc"), "kuaishou")
        self.assertEqual(detect_short_video_platform("https://www.xiaohongshu.com/explore/abc"), "xiaohongshu")

    def test_analyze_remix_link_splits_copyable_text_and_images(self):
        result = analyze_remix_link(
            {
                "url": "https://www.xiaohongshu.com/explore/demo",
                "title": "厨房抹布避坑",
                "body": "洗碗布总是发臭，可以换成一次性抹布。",
                "tags": "#厨房清洁 #家居好物",
                "image_urls": [
                    "https://example.com/one.jpg",
                    "https://example.com/two.jpg",
                ],
            }
        )

        self.assertTrue(result["ok"])
        self.assertEqual(result["platform"], "xiaohongshu")
        self.assertEqual(result["copywriting"]["title"], "厨房抹布避坑")
        self.assertEqual(result["copywriting"]["tags"], ["厨房清洁", "家居好物"])
        self.assertEqual(len(result["images"]), 2)
        self.assertIn("改成原创角度", result["optimization_items"][0])

    def test_analyze_remix_link_extracts_xiaohongshu_share_text(self):
        result = analyze_remix_link(
            {
                "url": "马刺最后时刻问题很大！ 总的来说尼克斯打的确实很好... "
                "http://xhslink.com/o/8efRG7IktVj \n复制文字，打开【小红书】，笔记立刻呈现~",
                "fetch_remote": False,
            }
        )

        self.assertTrue(result["ok"])
        self.assertEqual(result["url"], "http://xhslink.com/o/8efRG7IktVj")
        self.assertEqual(result["platform"], "xiaohongshu")
        self.assertEqual(result["copywriting"]["title"], "马刺最后时刻问题很大！")
        self.assertIn("尼克斯", result["copywriting"]["body"])
        self.assertNotIn("复制文字", result["copywriting"]["body"])

    def test_analyze_remix_link_cleans_douyin_share_noise(self):
        result = analyze_remix_link(
            {
                "url": "3.51 复制打开抖音，看看【罗志布秋的作品】非常百搭好看的运动训练，"
                "日常打球速干短裤 每个颜色... https://v.douyin.com/qu3Aocqmh3o/ 06/12 :9pm k@p.qR Jip:/",
                "fetch_remote": False,
            }
        )

        self.assertEqual(result["platform"], "douyin")
        self.assertEqual(result["copywriting"]["title"], "非常百搭好看的运动训练，日常打球速干短裤")
        self.assertNotIn("复制打开抖音", result["copywriting"]["copy_text"])
        self.assertNotIn("Jip", result["copywriting"]["copy_text"])

    def test_create_affiliate_remix_plan_generates_platform_packages_and_risk_checks(self):
        analysis = analyze_remix_link(
            {
                "url": "https://v.douyin.com/demo/",
                "title": "非常百搭好看的运动训练，日常打球速干短裤",
                "body": "每个颜色都好搭，日常训练打球都能穿。",
                "tags": "#运动短裤 #速干短裤",
            }
        )

        plan = create_affiliate_remix_plan(
            analysis,
            {
                "product_name": "速干运动短裤",
                "product_category": "运动服饰",
                "selling_points": "速干,百搭,打球训练",
            },
        )

        self.assertTrue(plan["ok"])
        self.assertIn("douyin", plan["platform_packages"])
        self.assertIn("xiaohongshu", plan["platform_packages"])
        self.assertIn("剪映", "\n".join(plan["jianying_checklist"]))
        self.assertIn("不复用原视频画面", "\n".join(plan["dedupe_checks"]))

    def test_create_affiliate_jianying_handoff_writes_editing_package(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            analysis = analyze_remix_link(
                {
                    "url": "https://v.douyin.com/demo/",
                    "title": "非常百搭好看的运动训练，日常打球速干短裤",
                    "body": "每个颜色都好搭，日常训练打球都能穿。",
                    "tags": "#运动短裤 #速干短裤",
                }
            )

            result = create_affiliate_jianying_handoff(
                root,
                analysis,
                {
                    "product_name": "速干运动短裤",
                    "product_category": "运动服饰",
                    "selling_points": "速干,百搭,打球训练",
                },
                package_name="shorts-jianying",
                launch=False,
            )

            handoff_dir = Path(result["handoff_dir"])
            self.assertTrue(result["ok"])
            self.assertTrue((handoff_dir / "口播稿.txt").exists())
            self.assertTrue((handoff_dir / "分镜清单.md").exists())
            self.assertTrue((handoff_dir / "抖音橱窗版.md").exists())
            self.assertTrue((handoff_dir / "小红书种草版.md").exists())
            self.assertTrue((handoff_dir / "判重检查.md").exists())
            self.assertIn("剪映", (handoff_dir / "剪映SVIP执行清单.md").read_text(encoding="utf-8"))
            self.assertIn("不复用原视频画面", (handoff_dir / "判重检查.md").read_text(encoding="utf-8"))

    def test_parse_remix_html_metadata_reads_xiaohongshu_meta_fields(self):
        metadata = parse_remix_html_metadata(
            """
            <meta name="og:title" content="马刺最后时刻问题很大！ - 小红书">
            <meta name="description" content="总的来说尼克斯打的确实很好。#NBA #马刺尼克斯G1">
            <meta name="keywords" content="NBA, NBA总决赛, 马刺尼克斯G1">
            <meta name="og:image" content="https://example.com/one.jpg">
            <meta property="og:image" content="https://example.com/two.jpg">
            """
        )

        self.assertEqual(metadata["title"], "马刺最后时刻问题很大！")
        self.assertIn("尼克斯", metadata["body"])
        self.assertNotIn("#NBA", metadata["body"])
        self.assertEqual(metadata["tags"], ["NBA", "NBA总决赛", "马刺尼克斯G1"])
        self.assertEqual(metadata["images"], ["https://example.com/one.jpg", "https://example.com/two.jpg"])

    def test_llmstudio_payload_asks_for_three_original_rewrites(self):
        payload = llmstudio_payload("title", "马刺最后时刻问题很大！")

        text = "\n".join(message["content"] for message in payload["messages"])
        self.assertIn("3", text)
        self.assertIn("防止二次加工平台判重", text)
        self.assertIn("马刺最后时刻问题很大", text)
        self.assertIn("标题里不要带 # 符号", text)
        self.assertIn("不要太 AI 味", text)

    def test_llmstudio_payload_can_request_xiaohongshu_emoji(self):
        payload = llmstudio_payload("body", "这个方法适合自我管理", allow_emoji=True)

        text = "\n".join(message["content"] for message in payload["messages"])
        self.assertIn("可以加入少量小红书主流 emoji", text)
        self.assertIn("正文里不要带 # 符号", text)

    def test_llmstudio_payload_guides_tags_to_same_topic_domain(self):
        payload = llmstudio_payload("tags", "#戒色 #男性成长")

        text = "\n".join(message["content"] for message in payload["messages"])
        self.assertIn("每个标签都必须以 # 开头", text)
        self.assertIn("#男性戒色 #自我提升 #心灵成长", text)

    def test_parse_llmstudio_suggestions_accepts_json_array(self):
        suggestions = parse_llmstudio_suggestions('["标题 A", "标题 B", "标题 C"]')

        self.assertEqual(suggestions, ["标题 A", "标题 B", "标题 C"])

    def test_parse_llmstudio_suggestions_accepts_numbered_lines(self):
        suggestions = parse_llmstudio_suggestions("1. 标题 A\n2. 标题 B\n3. 标题 C")

        self.assertEqual(suggestions, ["标题 A", "标题 B", "标题 C"])

    def test_parse_llmstudio_suggestions_accepts_first_json_array_before_extra_text(self):
        suggestions = parse_llmstudio_suggestions(
            '[\n  "标题 A",\n  "标题 B",\n  "标题 C"\n]<|user|>1. **Analyze [bad]**'
        )

        self.assertEqual(suggestions, ["标题 A", "标题 B", "标题 C"])

    def test_normalize_copy_suggestions_removes_hash_from_title_and_body(self):
        suggestions = normalize_copy_suggestions("title", ["#戒色 这件事别硬扛", "男性成长 #自律"])

        self.assertEqual(suggestions, ["戒色 这件事别硬扛", "男性成长 自律"])

    def test_normalize_copy_suggestions_adds_emoji_when_requested_for_title_and_body(self):
        title_suggestions = normalize_copy_suggestions("title", ["戒色这件事别硬扛"], allow_emoji=True)
        body_suggestions = normalize_copy_suggestions("body", ["这个方法适合自我管理"], allow_emoji=True)

        self.assertIn("✨", title_suggestions[0])
        self.assertIn("📝", body_suggestions[0])

    def test_normalize_copy_suggestions_keeps_source_emoji_for_body(self):
        suggestions = normalize_copy_suggestions(
            "body",
            ["柠檬水怎么选不踩雷？小白瓶适合闭眼囤，小绿瓶适合运动后喝。"],
            source_text="做柠檬，它是真的卷🍃 ✅ 小白瓶闭眼囤，👉 小绿瓶运动党本命。",
        )

        self.assertTrue(any(emoji in suggestions[0] for emoji in ["🍃", "✅", "👉"]))

    def test_optimize_copy_with_llmstudio_backfills_source_emoji_when_model_omits_it(self):
        import workflow.remix as remix

        calls = []
        original_request = remix.local_json_request
        try:
            def fake_request(url, method="GET", payload=None, timeout=30):
                calls.append(payload)
                return {
                    "choices": [
                        {
                            "message": {
                                "content": json.dumps(
                                    [
                                        "柠檬水怎么选不踩雷？小白瓶适合日常，小绿瓶适合运动后。",
                                        "别乱买柠檬水，小白瓶和小绿瓶对应不同场景。",
                                        "想要清爽解腻选小白瓶，运动后想补状态看小绿瓶。",
                                    ],
                                    ensure_ascii=False,
                                )
                            }
                        }
                    ]
                }

            remix.local_json_request = fake_request
            result = remix.optimize_copy_with_llmstudio(
                {
                    "field": "body",
                    "text": "做柠檬，它是真的卷🍃 ✅ 小白瓶闭眼囤，👉 小绿瓶运动党本命。",
                    "model": "fake-model",
                    "base_url": "http://127.0.0.1:1234/v1",
                }
            )
        finally:
            remix.local_json_request = original_request

        self.assertIn("输出必须包含 emoji 表情", calls[0]["messages"][1]["content"])
        self.assertEqual(len(result["suggestions"]), 3)
        for suggestion in result["suggestions"]:
            self.assertTrue(any(emoji in suggestion for emoji in ["🍃", "✅", "👉"]))

    def test_llmstudio_payload_preserves_source_emoji_style(self):
        payload = llmstudio_payload("body", "小白瓶闭眼囤🍋 ✅ 小绿瓶适合运动党👉")

        text = "\n".join(message["content"] for message in payload["messages"])
        self.assertIn("原文带有 emoji", text)
        self.assertIn("输出必须包含 emoji 表情", text)
        self.assertIn("颜色、形状或语义相近", text)

    def test_normalize_copy_suggestions_formats_tag_candidates(self):
        suggestions = normalize_copy_suggestions("tags", ["男性戒色 自我提升 #心灵成长", "#戒色 #男性成长 #戒色"])

        self.assertEqual(suggestions, ["#男性戒色 #自我提升 #心灵成长", "#戒色 #男性成长"])

    def test_preferred_llmstudio_model_chooses_fast_rewrite_model(self):
        model = preferred_llmstudio_model(
            [
                "qwen3.6-27b-ud-mlx",
                "qwen3-coder-next-mlx",
                "zai-org/glm-4.7-flash",
                "text-embedding-nomic-embed-text-v1.5",
            ]
        )

        self.assertEqual(model, "zai-org/glm-4.7-flash")

    def test_summarize_llmstudio_models_filters_embeddings_and_marks_default(self):
        summary = summarize_llmstudio_models(
            {
                "data": [
                    {"id": "qwen3.6-27b-ud-mlx"},
                    {"id": "zai-org/glm-4.7-flash"},
                    {"id": "text-embedding-nomic-embed-text-v1.5"},
                ]
            }
        )

        self.assertTrue(summary["ok"])
        self.assertEqual(summary["default_model"], "zai-org/glm-4.7-flash")
        self.assertEqual([item["id"] for item in summary["models"]], ["zai-org/glm-4.7-flash", "qwen3.6-27b-ud-mlx"])
        self.assertTrue(summary["models"][0]["recommended"])

    def test_create_remix_package_writes_text_and_video_packages(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            analysis = analyze_remix_link(
                {
                    "url": "https://v.douyin.com/demo/",
                    "title": "厨房抹布避坑",
                    "body": "洗碗布总是发臭，可以换成一次性抹布。",
                    "tags": "厨房清洁,家居好物",
                    "image_urls": ["https://example.com/one.jpg"],
                }
            )

            result = create_remix_package(root, analysis, package_name="remix-demo")

            package_dir = Path(result["package_dir"])
            self.assertTrue(result["ok"])
            self.assertTrue((package_dir / "copywriting.md").exists())
            self.assertTrue((package_dir / "video-script.txt").exists())
            self.assertTrue((package_dir / "image-package.md").exists())
            self.assertIn("原创改写", (package_dir / "video-script.txt").read_text(encoding="utf-8"))

    def test_create_remix_package_replaces_old_packages_for_same_link(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            old_dir = root / "remix_packages" / "remix" / "old-title"
            old_dir.mkdir(parents=True)
            source_url = "https://www.xiaohongshu.com/explore/demo"
            (old_dir / "analysis.json").write_text(
                json.dumps(
                    {
                        "url": source_url,
                        "platform": "xiaohongshu",
                        "copywriting": {"title": "旧标题", "body": "旧正文", "tags": ["旧"]},
                        "images": [],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            analysis = analyze_remix_link(
                {
                    "url": source_url,
                    "title": "新标题",
                    "body": "新正文",
                    "tags": "新",
                    "image_urls": ["https://example.com/current.jpg"],
                    "fetch_remote": False,
                }
            )

            result = create_remix_package(root, analysis, package_name="new-title")

            self.assertFalse(old_dir.exists())
            self.assertTrue(Path(result["package_dir"]).exists())
            self.assertEqual(result["package_path"], "remix/new-title")

    def test_create_jianying_handoff_writes_import_readme(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            analysis = analyze_remix_link(
                {
                    "url": "https://v.douyin.com/demo/",
                    "title": "厨房抹布避坑",
                    "body": "洗碗布总是发臭，可以换成一次性抹布。",
                    "tags": "厨房清洁",
                }
            )

            result = create_jianying_handoff(root, analysis, package_name="jianying-demo", launch=False)

            handoff_dir = Path(result["handoff_dir"])
            self.assertTrue(result["ok"])
            self.assertTrue((handoff_dir / "剪映导入说明.md").exists())
            self.assertTrue((handoff_dir / "文案.txt").exists())
            self.assertIn("剪映", (handoff_dir / "剪映导入说明.md").read_text(encoding="utf-8"))
