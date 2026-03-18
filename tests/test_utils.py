"""Tests for scripts/utils.py — shared utilities."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.utils import strip_markdown_fences


class TestStripMarkdownFences:
    def test_strips_luau_fence(self):
        assert strip_markdown_fences("```luau\nprint('hi')\n```") == "print('hi')"

    def test_strips_lua_fence(self):
        assert strip_markdown_fences("```lua\nlocal x = 1\n```") == "local x = 1"

    def test_strips_plain_fence(self):
        assert strip_markdown_fences("```\nreturn true\n```") == "return true"

    def test_no_fence_passthrough(self):
        assert strip_markdown_fences("local y = 10") == "local y = 10"

    def test_multiline_code(self):
        text = "```luau\nlocal a = 1\nlocal b = 2\n```"
        result = strip_markdown_fences(text)
        assert "local a = 1" in result
        assert "```" not in result
