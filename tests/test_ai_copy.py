import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from workflow.ai_copy import (
    build_ai_copy_prompt,
    delete_ai_copy_history,
    generate_ai_copy_with_lmstudio,
    list_ai_copy_history,
    parse_ai_copy_candidates,
    save_ai_copy_history,
    web_ai_copy_prompt,
)


class AiCopyTest(unittest.TestCase):
    def test_build_prompt_applies_task_strength_and_emoji_rules(self):
        prompt = build_ai_copy_prompt(
            "这款短裤适合打球，面料速干。",
            task="xiaohongshu",
            strength="deep",
            allow_emoji=True,
            candidate_count=3,
        )

        self.assertIn("小红书", prompt)
        self.assertIn("深度改写", prompt)
        self.assertIn("emoji", prompt)
        self.assertIn("JSON 数组", prompt)
        self.assertIn("不得编造", prompt)
        self.assertIn("这款短裤适合打球", prompt)

    def test_parse_candidates_accepts_json_fence_numbered_and_single_text(self):
        self.assertEqual(
            parse_ai_copy_candidates('```json\n["候选 A", "候选 B"]\n```'),
            ["候选 A", "候选 B"],
        )
        self.assertEqual(
            parse_ai_copy_candidates("1. 候选 A\n2. 候选 B"),
            ["候选 A", "候选 B"],
        )
        self.assertEqual(
            parse_ai_copy_candidates('["正确 A", "正确 B"]<|user|>1. 后续模板噪声 ["噪声"]'),
            ["正确 A", "正确 B"],
        )
        self.assertEqual(parse_ai_copy_candidates("只有一个完整回答"), ["只有一个完整回答"])

    @patch("workflow.ai_copy.subprocess.run")
    def test_lmstudio_generation_sends_json_to_curl_stdin(self, run):
        run.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout=json.dumps(
                {
                    "choices": [
                        {
                            "message": {
                                "content": '["标题 A", "标题 B", "标题 C"]',
                            }
                        }
                    ]
                },
                ensure_ascii=False,
            ),
            stderr="",
        )

        result = generate_ai_copy_with_lmstudio(
            {
                "text": "原始中文\n第二行",
                "task": "title",
                "strength": "standard",
                "allow_emoji": False,
                "candidate_count": 3,
                "model": "qwen-test",
            },
            curl_path="/usr/bin/curl",
        )

        command = run.call_args.args[0]
        request_body = json.loads(run.call_args.kwargs["input"])
        self.assertEqual(command[-1], "http://127.0.0.1:1234/v1/chat/completions")
        self.assertIn("--data-binary", command)
        self.assertIn("@-", command)
        self.assertEqual(request_body["model"], "qwen-test")
        self.assertIn("原始中文\n第二行", request_body["messages"][1]["content"])
        self.assertTrue(request_body["messages"][1]["content"].endswith("/no_think"))
        self.assertEqual(request_body["stop"], ["<|user|>", "<|assistant|>"])
        self.assertLessEqual(request_body["max_tokens"], 2400)
        self.assertEqual(result["suggestions"], ["标题 A", "标题 B", "标题 C"])
        self.assertEqual(result["transport"], "curl")

    def test_web_prompt_returns_provider_url_and_prompt(self):
        gemini = web_ai_copy_prompt(
            {
                "provider": "gemini",
                "text": "原文",
                "task": "body",
                "strength": "standard",
            }
        )
        chatgpt = web_ai_copy_prompt(
            {
                "provider": "chatgpt",
                "text": "原文",
                "task": "title",
                "strength": "light",
            }
        )

        self.assertEqual(gemini["url"], "https://gemini.google.com/app")
        self.assertEqual(chatgpt["url"], "https://chatgpt.com/")
        self.assertIn("原文", gemini["prompt"])
        with self.assertRaises(ValueError):
            web_ai_copy_prompt({"provider": "unknown", "text": "原文"})

    def test_history_save_list_and_delete(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            saved = save_ai_copy_history(
                root,
                {
                    "provider": "lmstudio",
                    "task": "body",
                    "source_text": "原文",
                    "suggestions": ["候选 A"],
                    "selected_text": "候选 A",
                },
            )

            path = root / "uploads" / "ai-copy-history.json"
            self.assertTrue(path.exists())
            entries = list_ai_copy_history(root)["items"]
            self.assertEqual(entries[0]["id"], saved["item"]["id"])
            self.assertEqual(entries[0]["selected_text"], "候选 A")

            result = delete_ai_copy_history(root, saved["item"]["id"])
            self.assertEqual(result["deleted"], 1)
            self.assertEqual(list_ai_copy_history(root)["items"], [])


if __name__ == "__main__":
    unittest.main()
