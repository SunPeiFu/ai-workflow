import json
import tempfile
import unittest
from pathlib import Path

from workflow.content_pipeline import (
    add_pool_links,
    audit_pool_item,
    batch_rewrite_items,
    list_pool_items,
    score_product,
    update_image_arrangement,
    update_pool_item,
)


class ContentPipelineTest(unittest.TestCase):
    def test_add_pool_links_deduplicates_urls_and_persists_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = add_pool_links(
                root,
                "复制打开 https://v.douyin.com/demo/ 另一个 https://xhslink.com/o/note\nhttps://v.douyin.com/demo/",
            )

            self.assertEqual(result["added"], 2)
            items = list_pool_items(root)["items"]
            self.assertEqual(len(items), 2)
            self.assertEqual({item["status"] for item in items}, {"pending"})
            self.assertTrue((root / "uploads" / "content-pipeline.json").exists())

    def test_pool_listing_merges_existing_remix_packages(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            package_dir = root / "remix_packages" / "remix" / "demo"
            package_dir.mkdir(parents=True)
            analysis = {
                "url": "https://v.douyin.com/from-package/",
                "platform": "douyin",
                "copywriting": {"title": "速干短裤", "body": "适合训练。", "tags": ["短裤"]},
                "images": [{"url": "/tmp/a.jpg"}],
            }
            (package_dir / "analysis.json").write_text(json.dumps(analysis, ensure_ascii=False), encoding="utf-8")

            item = list_pool_items(root)["items"][0]

            self.assertEqual(item["title"], "速干短裤")
            self.assertEqual(item["status"], "analyzed")
            self.assertEqual(item["image_count"], 1)

    def test_product_score_rewards_conversion_and_penalizes_refunds(self):
        strong = score_product(
            {
                "price": 59,
                "commission_rate": 30,
                "monthly_sales": 5000,
                "rating": 4.9,
                "store_score": 4.8,
                "refund_rate": 4,
                "has_coupon": True,
                "asset_completeness": 90,
            }
        )
        weak = score_product(
            {
                "price": 59,
                "commission_rate": 5,
                "monthly_sales": 20,
                "rating": 4.1,
                "store_score": 4.0,
                "refund_rate": 35,
                "has_coupon": False,
                "asset_completeness": 20,
            }
        )

        self.assertGreater(strong["score"], weak["score"])
        self.assertEqual(strong["grade"], "优先测试")
        self.assertIn("commission", strong["breakdown"])

    def test_batch_rewrite_creates_distinct_platform_drafts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            added = add_pool_links(root, "https://xhslink.com/o/rewrite")
            item_id = added["items"][0]["id"]
            update_pool_item(
                root,
                item_id,
                {
                    "title": "柠檬水怎么选？一篇帮你讲清楚",
                    "body": "小白瓶适合日常，绿瓶适合运动后。",
                    "tags": ["柠檬水", "饮料"],
                    "status": "analyzed",
                },
            )

            result = batch_rewrite_items(root, [item_id], "deep")
            item = result["items"][0]

            self.assertNotEqual(item["drafts"]["xiaohongshu"]["title"], item["drafts"]["douyin"]["title"])
            self.assertIn("#", item["drafts"]["xiaohongshu"]["tags"])
            self.assertIn("#", item["drafts"]["douyin"]["tags"])
            self.assertEqual(item["status"], "rewritten")

    def test_image_arrangement_persists_order_cover_and_deletion(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            item_id = add_pool_links(root, "https://v.douyin.com/images/")["items"][0]["id"]
            update_pool_item(root, item_id, {"images": ["a.jpg", "b.jpg", "c.jpg"]})

            item = update_image_arrangement(root, item_id, ["c.jpg", "a.jpg"], "c.jpg")

            self.assertEqual(item["images"], ["c.jpg", "a.jpg"])
            self.assertEqual(item["cover_image"], "c.jpg")
            self.assertEqual(item["status"], "arranged")

    def test_quality_audit_blocks_risky_or_incomplete_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            item_id = add_pool_links(root, "https://v.douyin.com/audit/")["items"][0]["id"]
            update_pool_item(
                root,
                item_id,
                {
                    "title": "全网最好绝对有效的产品",
                    "body": "保证治疗所有问题",
                    "images": [],
                    "product": {},
                },
            )

            blocked = audit_pool_item(root, item_id)
            self.assertFalse(blocked["ready_to_publish"])
            self.assertLess(blocked["score"], 60)
            self.assertTrue(any(issue["severity"] == "blocker" for issue in blocked["issues"]))

            update_pool_item(
                root,
                item_id,
                {
                    "title": "训练短裤怎么选",
                    "body": "对比面料、版型和日常使用场景。",
                    "images": ["a.jpg", "b.jpg"],
                    "cover_image": "a.jpg",
                    "product": {
                        "name": "训练短裤",
                        "price": 59,
                        "commission_rate": 25,
                        "rating": 4.8,
                    },
                },
            )
            ready = audit_pool_item(root, item_id)
            self.assertTrue(ready["ready_to_publish"])
            self.assertGreaterEqual(ready["score"], 70)


if __name__ == "__main__":
    unittest.main()
