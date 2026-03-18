"""Tests for scripts/generate_blender_asset.py."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.generate_blender_asset import (
    get_anthropic_key,
    find_blender,
    generate_blender_script,
    _strip_code_fences,
    execute_blender_script,
)


# ---------------------------------------------------------------------------
# get_anthropic_key
# ---------------------------------------------------------------------------

class TestGetAnthropicKey:
    def test_returns_key_from_env(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-key-123")
        assert get_anthropic_key() == "sk-test-key-123"

    def test_raises_when_missing(self, monkeypatch):
        import click
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        with pytest.raises(click.ClickException, match="ANTHROPIC_API_KEY"):
            get_anthropic_key()


# ---------------------------------------------------------------------------
# find_blender
# ---------------------------------------------------------------------------

class TestFindBlender:
    def test_finds_blender_in_path(self, monkeypatch):
        monkeypatch.setattr("shutil.which", lambda _: "/usr/local/bin/blender")
        assert find_blender() == "/usr/local/bin/blender"

    def test_finds_blender_in_applications(self, monkeypatch):
        monkeypatch.setattr("shutil.which", lambda _: None)
        mac_path = "/Applications/Blender.app/Contents/MacOS/Blender"
        monkeypatch.setattr("os.path.isfile", lambda p: p == mac_path)
        assert find_blender() == mac_path

    def test_raises_when_not_found(self, monkeypatch):
        import click
        monkeypatch.setattr("shutil.which", lambda _: None)
        monkeypatch.setattr("os.path.isfile", lambda _: False)
        with pytest.raises(click.ClickException, match="Blender not found"):
            find_blender()


# ---------------------------------------------------------------------------
# _strip_code_fences
# ---------------------------------------------------------------------------

class TestStripCodeFences:
    def test_strips_python_fences(self):
        code = "```python\nimport bpy\nbpy.ops.mesh.primitive_cube_add()\n```"
        result = _strip_code_fences(code)
        assert result == "import bpy\nbpy.ops.mesh.primitive_cube_add()"

    def test_strips_plain_fences(self):
        code = "```\nimport bpy\n```"
        result = _strip_code_fences(code)
        assert result == "import bpy"

    def test_no_fences_unchanged(self):
        code = "import bpy\nbpy.ops.mesh.primitive_cube_add()"
        result = _strip_code_fences(code)
        assert result == code

    def test_handles_whitespace(self):
        code = "  ```python\nimport bpy\n```  "
        result = _strip_code_fences(code)
        assert result == "import bpy"


# ---------------------------------------------------------------------------
# generate_blender_script
# ---------------------------------------------------------------------------

class TestGenerateBlenderScript:
    def test_generates_script_successfully(self):
        mock_anthropic = MagicMock()
        mock_client = MagicMock()
        mock_anthropic.Anthropic.return_value = mock_client

        mock_response = MagicMock()
        mock_response.content = [MagicMock(text="import bpy\nbpy.ops.mesh.primitive_cube_add()")]
        mock_response.usage.input_tokens = 150
        mock_response.usage.output_tokens = 200
        mock_client.messages.create.return_value = mock_response

        with patch.dict("sys.modules", {"anthropic": mock_anthropic}):
            script, tokens_in, tokens_out = generate_blender_script(
                "sk-test", "A gold coin", "/tmp/coin.fbx", "cartoon"
            )

        assert "import bpy" in script
        assert tokens_in == 150
        assert tokens_out == 200
        mock_client.messages.create.assert_called_once()

    def test_raises_on_api_error(self):
        import click

        mock_anthropic = MagicMock()
        mock_client = MagicMock()
        mock_anthropic.Anthropic.return_value = mock_client
        mock_anthropic.APIError = type("APIError", (Exception,), {})
        mock_client.messages.create.side_effect = mock_anthropic.APIError("Rate limit")

        with patch.dict("sys.modules", {"anthropic": mock_anthropic}):
            with pytest.raises(click.ClickException, match="Anthropic API error"):
                generate_blender_script("sk-test", "A coin", "/tmp/out.fbx", "cartoon")


# ---------------------------------------------------------------------------
# execute_blender_script
# ---------------------------------------------------------------------------

class TestExecuteBlenderScript:
    @patch("subprocess.run")
    def test_executes_successfully(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stderr="", stdout="")
        execute_blender_script("/usr/bin/blender", "/tmp/script.py")
        mock_run.assert_called_once_with(
            ["/usr/bin/blender", "-b", "-P", "/tmp/script.py"],
            capture_output=True,
            text=True,
            timeout=120,
        )

    @patch("subprocess.run")
    def test_raises_on_nonzero_exit(self, mock_run):
        import click
        mock_run.return_value = MagicMock(
            returncode=1,
            stderr="Error: Python script failed",
            stdout="",
        )
        with pytest.raises(click.ClickException, match="Blender script failed"):
            execute_blender_script("/usr/bin/blender", "/tmp/script.py")

    @patch("subprocess.run")
    def test_raises_on_timeout(self, mock_run):
        import click
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="blender", timeout=120)
        with pytest.raises(click.ClickException, match="timed out"):
            execute_blender_script("/usr/bin/blender", "/tmp/script.py")

    @patch("subprocess.run")
    def test_raises_on_blender_not_found(self, mock_run):
        import click
        mock_run.side_effect = FileNotFoundError()
        with pytest.raises(click.ClickException, match="Blender not found"):
            execute_blender_script("/bad/path/blender", "/tmp/script.py")

    @patch("subprocess.run")
    def test_truncates_long_error_output(self, mock_run):
        import click
        long_error = "X" * 1000
        mock_run.return_value = MagicMock(
            returncode=1,
            stderr=long_error,
            stdout="",
        )
        with pytest.raises(click.ClickException, match=r"\.\.\.X"):
            execute_blender_script("/usr/bin/blender", "/tmp/script.py")


# ---------------------------------------------------------------------------
# CLI integration (main command)
# ---------------------------------------------------------------------------

class TestMainCLI:
    @patch("scripts.generate_blender_asset.execute_blender_script")
    @patch("scripts.generate_blender_asset.generate_blender_script")
    @patch("scripts.generate_blender_asset.find_blender")
    @patch("scripts.generate_blender_asset.get_anthropic_key")
    def test_full_pipeline(self, mock_key, mock_find, mock_gen, mock_exec, tmp_path):
        from click.testing import CliRunner
        from scripts.generate_blender_asset import main

        mock_key.return_value = "sk-test"
        mock_find.return_value = "/usr/bin/blender"
        mock_gen.return_value = ("import bpy\nprint('hello')", 100, 200)

        output_file = tmp_path / "model.fbx"

        # Simulate Blender creating the output file
        def fake_exec(blender, script):
            output_file.write_bytes(b"FAKE_FBX_DATA")

        mock_exec.side_effect = fake_exec

        runner = CliRunner()
        result = runner.invoke(main, ["A gold coin", "--output", str(output_file)])

        assert result.exit_code == 0, result.output
        assert "Generated:" in result.output
        assert "Done!" in result.output

    @patch("scripts.generate_blender_asset.execute_blender_script")
    @patch("scripts.generate_blender_asset.generate_blender_script")
    @patch("scripts.generate_blender_asset.find_blender")
    @patch("scripts.generate_blender_asset.get_anthropic_key")
    def test_fails_when_no_output_created(self, mock_key, mock_find, mock_gen, mock_exec, tmp_path):
        from click.testing import CliRunner
        from scripts.generate_blender_asset import main

        mock_key.return_value = "sk-test"
        mock_find.return_value = "/usr/bin/blender"
        mock_gen.return_value = ("import bpy", 50, 100)
        mock_exec.return_value = None  # Blender "runs" but doesn't create file

        output_file = tmp_path / "missing.fbx"
        runner = CliRunner()
        result = runner.invoke(main, ["A coin", "--output", str(output_file)])

        assert result.exit_code != 0
        assert "output file was not created" in result.output
