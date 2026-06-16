import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class FrontendAiCopyTest(unittest.TestCase):
    def test_web_provider_opening_does_not_preopen_blank_tab(self):
        script = (ROOT / "web" / "remix.js").read_text(encoding="utf-8")
        match = re.search(
            r"async function openAiCopyWebProvider\([\s\S]+?\n}\n\nasync function parseAiCopyPastedResult",
            script,
        )
        self.assertIsNotNone(match)
        function_body = match.group(0)

        self.assertNotIn('window.open("about:blank"', function_body)
        self.assertNotIn("window.open('about:blank'", function_body)
        self.assertIn('"/api/remix/ai-copy/open-web"', function_body)
        self.assertNotIn("window.open(", function_body)


if __name__ == "__main__":
    unittest.main()
