import json
import re
import tempfile
import unittest
from pathlib import Path

from workflow.platforms import (
    PLATFORM_PRESETS,
    hook_analysis,
    monetization_plan,
    normalize_platforms,
    platform_metadata,
    publish_schedule,
    render_cover_svg,
    series_plan,
    title_experiment_rows,
    write_platform_packages,
)


class PlatformPackageTest(unittest.TestCase):
    def test_normalize_platforms_defaults_to_all_known_platforms(self):
        self.assertEqual(normalize_platforms(None), ["bilibili", "xiaohongshu", "douyin"])
        self.assertEqual(normalize_platforms(["unknown"]), ["bilibili", "xiaohongshu", "douyin"])

    def test_platform_metadata_contains_traffic_and_risk_checks(self):
        metadata = platform_metadata(
            PLATFORM_PRESETS["douyin"],
            "为什么看片越多的人会焦虑？这不是绝对结论。",
            duration=30,
        )

        self.assertIn("前三秒", " ".join(metadata["traffic_checklist"]))
        self.assertTrue(metadata["risk_checks"])
        self.assertIn("traffic_score", metadata)
        self.assertTrue(metadata["improvement_suggestions"])
        self.assertEqual(len(metadata["title_variants"]), 5)
        self.assertTrue(metadata["comment_prompt"])
        self.assertIn("转化", metadata["conversion_cta"])
        self.assertLessEqual(len(metadata["title"]), PLATFORM_PRESETS["douyin"].title_limit)

    def test_write_platform_packages_creates_publish_assets(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp) / "projects" / "demo"
            (project_dir / "exports").mkdir(parents=True)

            written = write_platform_packages(project_dir, "第一句提出问题。第二句解释。", 12.3)

            self.assertEqual(len(written), 3)
            metadata_path = project_dir / "exports" / "platforms" / "bilibili" / "metadata.json"
            publish_path = project_dir / "exports" / "platforms" / "xiaohongshu" / "publish.md"
            cover_path = project_dir / "exports" / "platforms" / "douyin" / "cover.svg"
            self.assertTrue(metadata_path.exists())
            self.assertTrue(publish_path.exists())
            self.assertTrue(cover_path.exists())
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            self.assertEqual(metadata["platform"]["name"], "哔哩哔哩")
            publish_text = publish_path.read_text(encoding="utf-8")
            self.assertIn("发布包", publish_text)
            self.assertIn("流量优化评分", publish_text)
            self.assertIn("标题变体", publish_text)
            self.assertIn("转化 CTA", publish_text)
            self.assertIn('width="1080"', cover_path.read_text(encoding="utf-8"))
            title_experiments = project_dir / "exports" / "title-experiments.csv"
            self.assertTrue(title_experiments.exists())
            title_text = title_experiments.read_text(encoding="utf-8")
            self.assertIn("platform,platform_name,variant_index,title,hypothesis,selected", title_text)
            self.assertIn("bilibili,哔哩哔哩,1", title_text)
            hook_path = project_dir / "exports" / "hook-analysis.json"
            self.assertTrue(hook_path.exists())
            self.assertIn("platform_rewrites", hook_path.read_text(encoding="utf-8"))
            monetization_path = project_dir / "exports" / "monetization-plan.json"
            self.assertTrue(monetization_path.exists())
            self.assertIn("platform_routes", monetization_path.read_text(encoding="utf-8"))
            series_path = project_dir / "exports" / "series-plan.json"
            self.assertTrue(series_path.exists())
            self.assertIn("episodes", series_path.read_text(encoding="utf-8"))
            schedule_path = project_dir / "exports" / "publish-schedule.json"
            self.assertTrue(schedule_path.exists())
            self.assertIn("slots", schedule_path.read_text(encoding="utf-8"))

    def test_title_experiment_rows_follow_selected_platforms(self):
        rows = title_experiment_rows("第一句提出问题。第二句解释。", 12.3, ["douyin"])

        self.assertEqual({row["platform"] for row in rows}, {"douyin"})
        self.assertEqual(len(rows), 5)
        self.assertEqual(rows[0]["selected"], "yes")
        self.assertIn("停留", rows[0]["hypothesis"])

    def test_hook_analysis_scores_opening_and_generates_platform_rewrites(self):
        analysis = hook_analysis(
            "为什么很多人发了很多视频却没有流量？真正的问题不是努力，而是前三秒没有钩子。",
            68,
            ["douyin", "xiaohongshu"],
        )

        self.assertGreaterEqual(analysis["score"], 70)
        self.assertIn(analysis["grade"], {"强", "可用"})
        self.assertTrue(analysis["features"]["has_question"])
        self.assertTrue(analysis["features"]["has_contrast"])
        self.assertEqual(set(analysis["platform_rewrites"]), {"douyin", "xiaohongshu"})
        self.assertTrue(analysis["recommendations"])

    def test_monetization_plan_generates_offer_ladder_and_routes(self):
        plan = monetization_plan(
            "为什么很多视频没有流量？这期讲短视频发布、涨粉和变现的工作流。",
            88,
            ["bilibili", "douyin"],
        )

        self.assertIn("primary_offer", plan)
        self.assertEqual(plan["primary_offer"]["level"], "free")
        self.assertEqual(set(plan["platform_routes"]), {"bilibili", "douyin"})
        self.assertIn("清单", plan["platform_routes"]["douyin"]["cta"])
        self.assertTrue(plan["profile_checklist"])
        self.assertTrue(plan["risk_notes"])

    def test_series_plan_generates_follow_up_topics(self):
        plan = series_plan(
            "为什么很多视频没有流量？这期讲短视频发布、涨粉和变现的工作流。",
            88,
            ["bilibili", "douyin"],
        )

        self.assertIn("series_name", plan)
        self.assertEqual(set(plan["platforms"]), {"bilibili", "douyin"})
        self.assertGreaterEqual(len(plan["episodes"]), 6)
        self.assertIn("流量", plan["pillars"][0])
        self.assertTrue(plan["reuse_notes"])

    def test_publish_schedule_generates_platform_slots(self):
        schedule = publish_schedule(
            "为什么很多视频没有流量？这期讲短视频发布、涨粉和变现的工作流。",
            88,
            ["bilibili", "douyin"],
        )

        self.assertIn("slots", schedule)
        self.assertGreaterEqual(len(schedule["slots"]), 6)
        self.assertEqual(schedule["slots"][0]["day"], "D+0")
        self.assertIn(schedule["slots"][0]["platform"], {"bilibili", "douyin"})
        self.assertTrue(schedule["daily_review"])
        self.assertIn("加码", schedule["cadence"])

    def test_vertical_cover_uses_mobile_safe_title_sizing(self):
        metadata = platform_metadata(
            PLATFORM_PRESETS["douyin"],
            "为什么看片越多的人面对真实关系时会焦虑？这期只讲机制。",
            duration=58,
        )

        svg = render_cover_svg(metadata)

        font_sizes = [int(size) for size in re.findall(r'font-size="(\d+)"', svg)]
        self.assertTrue(font_sizes)
        self.assertLessEqual(max(font_sizes), 86)
        title_lines = re.findall(r'data-role="cover-title"[^>]*>([^<]+)</text>', svg)
        self.assertTrue(title_lines)
        self.assertLessEqual(max(len(line) for line in title_lines), 5)
        self.assertEqual(title_lines[-1], "3秒说透")


if __name__ == "__main__":
    unittest.main()
