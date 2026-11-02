"""Unit test for tools/make_context_pack.py."""

from __future__ import annotations

import unittest
from pathlib import Path

# Add project root to path if needed
from tools.make_context_pack import generate_context_pack


class TestContextPackGenerator(unittest.TestCase):
    def test_generate_context_pack(self) -> None:
        root_dir = Path(__file__).resolve().parent.parent
        output_file = root_dir / "output" / "test_context_pack_output.md"

        try:
            generated_path = generate_context_pack(root_dir=root_dir, output_path=output_file)
            self.assertTrue(generated_path.exists())
            self.assertGreater(generated_path.stat().st_size, 0)

            with open(generated_path, "r", encoding="utf-8") as f:
                content = f.read()

            # Verify presence of section headings
            self.assertIn("# AI AFFILIATE CONTENT FACTORY — CONTEXT PACK", content)
            self.assertIn("## 1. AGENTS.md", content)
            self.assertIn("## 2. docs/HANDOFF.md", content)
            self.assertIn("## 3. Last 40 lines of docs/VERIFICATION_LOG.md", content)
            self.assertIn("## 4. Git Log (Last 10 commits)", content)

        finally:
            if output_file.exists():
                output_file.unlink()


if __name__ == "__main__":
    unittest.main()
