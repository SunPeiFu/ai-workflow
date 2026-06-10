import tempfile
import unittest
from pathlib import Path

from workflow.product_videos import (
    product_asset_checklist,
    product_compliance_risks,
    product_video_script,
)
from workflow.web_app import create_project_from_payload


class ProductVideoTest(unittest.TestCase):
    def test_product_video_script_builds_platform_specific_sales_script(self):
        script = product_video_script(
            {
                "video_type": "商品种草",
                "product_name": "厨房一次性抹布",
                "product_category": "厨房清洁耗材",
                "price": "19.9",
                "commission": "30%",
                "pain_point": "洗碗布总是油腻发臭",
                "selling_points": "干湿两用、用完即丢、不容易掉絮",
                "target_platform": "douyin",
            }
        )

        self.assertIn("洗碗布总是油腻发臭", script)
        self.assertIn("厨房一次性抹布", script)
        self.assertIn("干湿两用", script)
        self.assertIn("评论区", script)
        self.assertIn("19.9", script)

    def test_product_compliance_risks_flags_absolute_and_health_claims(self):
        risks = product_compliance_risks("这款调味品100%无毒，还能排毒，效果永久。")

        self.assertEqual([risk["term"] for risk in risks], ["100%", "无毒", "排毒", "永久"])
        self.assertTrue(all(risk["suggestion"] for risk in risks))

    def test_product_compliance_risks_does_not_flag_step_order_words(self):
        risks = product_compliance_risks("第一步先展示使用前的问题，第二步展示实际怎么用。")

        self.assertEqual(risks, [])

    def test_product_asset_checklist_includes_conversion_materials(self):
        checklist = product_asset_checklist("厨房清洁耗材")

        self.assertIn("商品主图", checklist)
        self.assertIn("使用前油污/杂乱场景", checklist)
        self.assertIn("使用后对比图", checklist)
        self.assertIn("价格/优惠截图", checklist)

    def test_create_project_from_product_payload_writes_brief_and_risk_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            payload = {
                "project_id": "product-demo",
                "voice": "Tingting",
                "content_mode": "product",
                "video_type": "商品种草",
                "product_name": "厨房一次性抹布",
                "product_category": "厨房清洁耗材",
                "price": "19.9",
                "commission": "30%",
                "pain_point": "洗碗布总是油腻发臭",
                "selling_points": "干湿两用、用完即丢、不容易掉絮",
                "target_platform": "douyin",
                "platforms": ["douyin", "xiaohongshu"],
            }

            result = create_project_from_payload(root, payload)

            project_dir = root / "projects" / "product-demo"
            self.assertTrue(result["ok"])
            self.assertIn("厨房一次性抹布", (project_dir / "script.txt").read_text(encoding="utf-8"))
            self.assertTrue((project_dir / "brief.md").exists())
            self.assertTrue((project_dir / "assets" / "product-shot-list.md").exists())
            self.assertTrue((project_dir / "exports" / "compliance-risks.json").exists())
            self.assertIn("content_mode: product", (project_dir / "episode.yaml").read_text(encoding="utf-8"))
