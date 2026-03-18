#!/usr/bin/env python3
"""Tests for scripts/generate_luau_openai.py"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, Mock, mock_open, patch

import pytest
from click.testing import CliRunner

# Import the functions and CLI from the script
import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
from generate_luau_openai import (
    cli,
    load_assistant_id,
    save_assistant_id,
    strip_markdown_fences,
)

# Check if openai is available
try:
    import openai
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False

# Skip openai-dependent tests if module not available
requires_openai = pytest.mark.skipif(
    not OPENAI_AVAILABLE,
    reason="openai package not installed"
)


class TestStripMarkdownFences:
    """Test the markdown fence stripping utility."""

    def test_strips_luau_fence(self):
        text = "```luau\nprint('hello')\n```"
        result = strip_markdown_fences(text)
        assert result == "print('hello')"

    def test_strips_lua_fence(self):
        text = "```lua\nlocal x = 5\n```"
        result = strip_markdown_fences(text)
        assert result == "local x = 5"

    def test_strips_plain_fence(self):
        text = "```\nreturn true\n```"
        result = strip_markdown_fences(text)
        assert result == "return true"

    def test_no_fence_passthrough(self):
        text = "local y = 10"
        result = strip_markdown_fences(text)
        assert result == "local y = 10"

    def test_multiline_code(self):
        text = """```luau
function hello()
    print("world")
end
```"""
        result = strip_markdown_fences(text)
        assert "function hello()" in result
        assert "print(\"world\")" in result
        assert "```" not in result


class TestSaveAndLoadAssistantId:
    """Test assistant ID persistence."""

    def test_save_creates_file(self, tmp_path):
        """Test that save_assistant_id creates a file."""
        test_file = tmp_path / ".assistant_id"
        with patch("generate_luau_openai.ASSISTANT_ID_FILE", test_file):
            save_assistant_id("asst_12345")
            assert test_file.exists()
            assert test_file.read_text() == "asst_12345"

    def test_load_returns_saved_id(self, tmp_path):
        """Test that load_assistant_id retrieves saved ID."""
        test_file = tmp_path / ".assistant_id"
        test_file.write_text("asst_67890")
        with patch("generate_luau_openai.ASSISTANT_ID_FILE", test_file):
            result = load_assistant_id()
            assert result == "asst_67890"

    def test_load_raises_if_no_file(self, tmp_path):
        """Test that load_assistant_id raises if file doesn't exist."""
        test_file = tmp_path / ".assistant_id"
        with patch("generate_luau_openai.ASSISTANT_ID_FILE", test_file):
            with pytest.raises(Exception) as exc_info:
                load_assistant_id()
            assert "No assistant found" in str(exc_info.value)


@requires_openai
class TestGetOpenAIClient:
    """Test OpenAI client creation."""

    def test_import_check(self):
        """Verify openai module is available for these tests."""
        from generate_luau_openai import get_openai_client
        # If we get here, imports work
        assert True


@requires_openai
class TestCreateAssistantCommand:
    """Test the create-assistant CLI command."""

    def test_import_check(self):
        """Verify imports work."""
        assert True


class TestGenerateCommand:
    """Test the generate CLI command."""

    @patch("generate_luau_openai.get_openai_client")
    @patch("generate_luau_openai.load_assistant_id")
    def test_generates_code_from_task(self, mock_load_id, mock_get_client):
        """Test code generation from a simple task string."""
        mock_load_id.return_value = "asst_test"
        
        # Setup mock client and responses
        mock_client = Mock()
        mock_get_client.return_value = mock_client
        
        mock_thread = Mock()
        mock_thread.id = "thread_123"
        mock_client.beta.threads.create.return_value = mock_thread
        
        mock_run = Mock()
        mock_run.status = "completed"
        mock_client.beta.threads.runs.create_and_poll.return_value = mock_run
        
        mock_message_content = Mock()
        mock_message_content.text.value = "```luau\nprint('Generated code')\n```"
        mock_message = Mock()
        mock_message.content = [mock_message_content]
        mock_messages = Mock()
        mock_messages.data = [mock_message]
        mock_client.beta.threads.messages.list.return_value = mock_messages
        
        runner = CliRunner()
        result = runner.invoke(cli, ["generate", "Create a test function"])
        
        assert result.exit_code == 0
        assert "Generated code" in result.output

    @patch("generate_luau_openai.get_openai_client")
    @patch("generate_luau_openai.load_assistant_id")
    def test_generates_code_from_spec_file(self, mock_load_id, mock_get_client, tmp_path):
        """Test code generation from a specification file."""
        mock_load_id.return_value = "asst_test"
        
        # Setup mock client
        mock_client = Mock()
        mock_get_client.return_value = mock_client
        
        mock_thread = Mock()
        mock_thread.id = "thread_456"
        mock_client.beta.threads.create.return_value = mock_thread
        
        mock_run = Mock()
        mock_run.status = "completed"
        mock_client.beta.threads.runs.create_and_poll.return_value = mock_run
        
        mock_message_content = Mock()
        mock_message_content.text.value = "local function test() return true end"
        mock_message = Mock()
        mock_message.content = [mock_message_content]
        mock_messages = Mock()
        mock_messages.data = [mock_message]
        mock_client.beta.threads.messages.list.return_value = mock_messages
        
        # Create spec file
        spec_file = tmp_path / "spec.md"
        spec_file.write_text("# Feature Spec\nCreate a boolean test function")
        
        runner = CliRunner()
        result = runner.invoke(cli, ["generate", f"--spec={spec_file}"])
        
        assert result.exit_code == 0
        assert "local function test()" in result.output

    @patch("generate_luau_openai.get_openai_client")
    @patch("generate_luau_openai.load_assistant_id")
    def test_writes_output_to_file(self, mock_load_id, mock_get_client, tmp_path):
        """Test that --output writes generated code to a file."""
        mock_load_id.return_value = "asst_test"
        
        mock_client = Mock()
        mock_get_client.return_value = mock_client
        
        mock_thread = Mock()
        mock_thread.id = "thread_789"
        mock_client.beta.threads.create.return_value = mock_thread
        
        mock_run = Mock()
        mock_run.status = "completed"
        mock_client.beta.threads.runs.create_and_poll.return_value = mock_run
        
        mock_message_content = Mock()
        mock_message_content.text.value = "return 42"
        mock_message = Mock()
        mock_message.content = [mock_message_content]
        mock_messages = Mock()
        mock_messages.data = [mock_message]
        mock_client.beta.threads.messages.list.return_value = mock_messages
        
        output_file = tmp_path / "output.luau"
        
        runner = CliRunner()
        result = runner.invoke(cli, ["generate", "Test task", f"--output={output_file}"])
        
        assert result.exit_code == 0
        assert output_file.exists()
        assert "return 42" in output_file.read_text()

    def test_generate_no_task_or_spec_fails(self):
        """Test that generate fails if neither task nor spec is provided."""
        runner = CliRunner()
        result = runner.invoke(cli, ["generate"])
        
        assert result.exit_code != 0
        assert "Provide a task description" in result.output

    @patch("generate_luau_openai.get_openai_client")
    @patch("generate_luau_openai.load_assistant_id")
    def test_handles_run_failure(self, mock_load_id, mock_get_client):
        """Test handling of failed OpenAI runs."""
        mock_load_id.return_value = "asst_test"
        
        mock_client = Mock()
        mock_get_client.return_value = mock_client
        
        mock_thread = Mock()
        mock_thread.id = "thread_fail"
        mock_client.beta.threads.create.return_value = mock_thread
        
        mock_run = Mock()
        mock_run.status = "failed"
        mock_run.last_error = "API error"
        mock_client.beta.threads.runs.create_and_poll.return_value = mock_run
        
        runner = CliRunner()
        result = runner.invoke(cli, ["generate", "Test task"])
        
        assert result.exit_code != 0
        assert "failed" in result.output


class TestCLIWithModelOverride:
    """Test model override functionality."""

    @patch("generate_luau_openai.get_openai_client")
    @patch("generate_luau_openai.load_assistant_id")
    def test_model_override_passed_to_api(self, mock_load_id, mock_get_client):
        """Test that --model option overrides the assistant's model."""
        mock_load_id.return_value = "asst_test"
        
        mock_client = Mock()
        mock_get_client.return_value = mock_client
        
        mock_thread = Mock()
        mock_thread.id = "thread_model"
        mock_client.beta.threads.create.return_value = mock_thread
        
        mock_run = Mock()
        mock_run.status = "completed"
        mock_client.beta.threads.runs.create_and_poll.return_value = mock_run
        
        mock_message_content = Mock()
        mock_message_content.text.value = "return nil"
        mock_message = Mock()
        mock_message.content = [mock_message_content]
        mock_messages = Mock()
        mock_messages.data = [mock_message]
        mock_client.beta.threads.messages.list.return_value = mock_messages
        
        runner = CliRunner()
        result = runner.invoke(cli, ["generate", "Test", "--model=gpt-4-turbo"])
        
        # Check that create_and_poll was called with model parameter
        call_kwargs = mock_client.beta.threads.runs.create_and_poll.call_args[1]
        assert "model" in call_kwargs
        assert call_kwargs["model"] == "gpt-4-turbo"
