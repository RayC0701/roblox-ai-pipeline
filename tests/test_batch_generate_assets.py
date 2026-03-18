#!/usr/bin/env python3
"""Tests for scripts/batch_generate_assets.py"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import Mock, patch

import pytest
from click.testing import CliRunner

# Import functions from the script
import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
from batch_generate_assets import (
    load_asset_prompts,
    load_progress,
    main,
    save_progress,
)


class TestLoadAssetPrompts:
    """Test YAML asset prompt loading."""

    def test_loads_valid_yaml(self, tmp_path):
        """Test loading a valid YAML file."""
        yaml_file = tmp_path / "assets.yaml"
        yaml_content = """
assets:
  - name: sword
    prompt: A medieval sword
    style: realistic
  - name: shield
    prompt: A wooden shield
    style: low-poly
"""
        yaml_file.write_text(yaml_content)
        
        result = load_asset_prompts(yaml_file)
        
        assert len(result) == 2
        assert result[0]["name"] == "sword"
        assert result[0]["prompt"] == "A medieval sword"
        assert result[1]["name"] == "shield"

    def test_raises_on_missing_file(self):
        """Test error when YAML file doesn't exist."""
        fake_path = Path("/nonexistent/file.yaml")
        
        with pytest.raises(Exception) as exc_info:
            load_asset_prompts(fake_path)
        assert "not found" in str(exc_info.value)

    def test_raises_on_invalid_yaml(self, tmp_path):
        """Test error on malformed YAML."""
        yaml_file = tmp_path / "bad.yaml"
        yaml_file.write_text("invalid: yaml: content: [")
        
        with pytest.raises(Exception) as exc_info:
            load_asset_prompts(yaml_file)
        assert "Invalid YAML" in str(exc_info.value)

    def test_raises_on_empty_assets(self, tmp_path):
        """Test error when YAML has no assets."""
        yaml_file = tmp_path / "empty.yaml"
        yaml_file.write_text("assets: []")
        
        with pytest.raises(Exception) as exc_info:
            load_asset_prompts(yaml_file)
        assert "No assets found" in str(exc_info.value)


class TestProgressTracking:
    """Test progress save/load functionality."""

    def test_load_progress_returns_default_if_missing(self, tmp_path):
        """Test loading progress from non-existent file."""
        progress_file = tmp_path / ".progress.json"
        
        result = load_progress(progress_file)
        
        assert result == {"completed": [], "failed": []}

    def test_load_progress_returns_saved_data(self, tmp_path):
        """Test loading existing progress data."""
        progress_file = tmp_path / ".progress.json"
        test_data = {
            "completed": ["asset1", "asset2"],
            "failed": ["asset3"]
        }
        progress_file.write_text(json.dumps(test_data))
        
        result = load_progress(progress_file)
        
        assert result == test_data

    def test_load_progress_handles_corrupted_file(self, tmp_path):
        """Test handling of corrupted progress file."""
        progress_file = tmp_path / ".progress.json"
        progress_file.write_text("{ invalid json")
        
        result = load_progress(progress_file)
        
        # Should return default on corruption
        assert result == {"completed": [], "failed": []}

    def test_save_progress_creates_file(self, tmp_path):
        """Test saving progress data."""
        progress_file = tmp_path / ".progress.json"
        test_data = {
            "completed": ["asset1"],
            "failed": []
        }
        
        save_progress(progress_file, test_data)
        
        assert progress_file.exists()
        saved_data = json.loads(progress_file.read_text())
        assert saved_data == test_data


class TestBatchGenerationFlow:
    """Test batch generation CLI."""

    @patch("batch_generate_assets.get_api_key")
    @patch("batch_generate_assets.create_preview_task")
    @patch("batch_generate_assets.poll_task")
    @patch("batch_generate_assets.download_model")
    @patch("batch_generate_assets.time.sleep")
    def test_generates_all_assets(
        self,
        mock_sleep,
        mock_download,
        mock_poll,
        mock_create,
        mock_get_key,
        tmp_path
    ):
        """Test successful batch generation."""
        mock_get_key.return_value = "test_key"
        mock_create.return_value = "preview_123"
        mock_poll.return_value = {
            "model_urls": {"fbx": "https://example.com/model.fbx"}
        }
        
        yaml_file = tmp_path / "assets.yaml"
        yaml_file.write_text("""
assets:
  - name: test_asset
    prompt: A test asset
    style: cartoon
""")
        
        output_dir = tmp_path / "models"
        
        runner = CliRunner()
        result = runner.invoke(main, [str(yaml_file), str(output_dir), "--preview-only"])
        
        assert result.exit_code == 0
        assert "1 succeeded" in result.output
        mock_create.assert_called_once()
        mock_download.assert_called_once()

    @patch("batch_generate_assets.get_api_key")
    def test_skips_existing_assets(self, mock_get_key, tmp_path):
        """Test that existing assets are skipped."""
        mock_get_key.return_value = "test_key"
        
        yaml_file = tmp_path / "assets.yaml"
        yaml_file.write_text("""
assets:
  - name: existing_asset
    prompt: Test
""")
        
        output_dir = tmp_path / "models"
        output_dir.mkdir()
        (output_dir / "existing_asset.fbx").write_bytes(b"existing")
        
        runner = CliRunner()
        result = runner.invoke(main, [str(yaml_file), str(output_dir)])
        
        assert result.exit_code == 0
        assert "1 skipped" in result.output

    @patch("batch_generate_assets.get_api_key")
    def test_skips_assets_without_prompt(self, mock_get_key, tmp_path):
        """Test that assets without prompts are skipped."""
        mock_get_key.return_value = "test_key"
        
        yaml_file = tmp_path / "assets.yaml"
        yaml_file.write_text("""
assets:
  - name: no_prompt_asset
    style: cartoon
""")
        
        output_dir = tmp_path / "models"
        
        runner = CliRunner()
        result = runner.invoke(main, [str(yaml_file), str(output_dir)])
        
        assert result.exit_code == 0
        assert "no prompt defined" in result.output

    @patch("batch_generate_assets.get_api_key")
    @patch("batch_generate_assets.create_preview_task")
    @patch("batch_generate_assets.poll_task")
    @patch("batch_generate_assets.time.sleep")
    def test_tracks_failures(
        self,
        mock_sleep,
        mock_poll,
        mock_create,
        mock_get_key,
        tmp_path
    ):
        """Test that failures are tracked."""
        mock_get_key.return_value = "test_key"
        mock_create.return_value = "preview_123"
        # Return empty model_urls to trigger failure
        mock_poll.return_value = {"model_urls": {}}
        
        yaml_file = tmp_path / "assets.yaml"
        yaml_file.write_text("""
assets:
  - name: fail_asset
    prompt: Will fail
""")
        
        output_dir = tmp_path / "models"
        
        runner = CliRunner()
        result = runner.invoke(main, [str(yaml_file), str(output_dir), "--preview-only"])
        
        assert result.exit_code == 0
        assert "1 failed" in result.output


class TestResumeCapability:
    """Test resume functionality for partial failures."""

    @patch("batch_generate_assets.get_api_key")
    @patch("batch_generate_assets.create_preview_task")
    @patch("batch_generate_assets.poll_task")
    @patch("batch_generate_assets.download_model")
    @patch("batch_generate_assets.time.sleep")
    def test_resume_skips_completed_assets(
        self,
        mock_sleep,
        mock_download,
        mock_poll,
        mock_create,
        mock_get_key,
        tmp_path
    ):
        """Test that --resume skips already-completed assets."""
        mock_get_key.return_value = "test_key"
        mock_create.return_value = "preview_123"
        mock_poll.return_value = {
            "model_urls": {"fbx": "https://example.com/model.fbx"}
        }
        
        yaml_file = tmp_path / "assets.yaml"
        yaml_file.write_text("""
assets:
  - name: completed_asset
    prompt: Already done
  - name: new_asset
    prompt: Need to generate
""")
        
        output_dir = tmp_path / "models"
        output_dir.mkdir()
        
        # Create progress file showing first asset completed
        progress_file = output_dir / ".progress.json"
        progress_file.write_text(json.dumps({
            "completed": ["completed_asset"],
            "failed": []
        }))
        
        runner = CliRunner()
        result = runner.invoke(main, [str(yaml_file), str(output_dir), "--resume", "--preview-only"])
        
        assert result.exit_code == 0
        assert "already completed" in result.output
        assert "1 succeeded" in result.output
        # Should only generate the second asset
        assert mock_create.call_count == 1

    @patch("batch_generate_assets.get_api_key")
    @patch("batch_generate_assets.create_preview_task")
    @patch("batch_generate_assets.poll_task")
    @patch("batch_generate_assets.download_model")
    @patch("batch_generate_assets.time.sleep")
    def test_resume_saves_progress_incrementally(
        self,
        mock_sleep,
        mock_download,
        mock_poll,
        mock_create,
        mock_get_key,
        tmp_path
    ):
        """Test that progress is saved after each asset."""
        mock_get_key.return_value = "test_key"
        mock_create.return_value = "preview_123"
        mock_poll.return_value = {
            "model_urls": {"fbx": "https://example.com/model.fbx"}
        }
        
        yaml_file = tmp_path / "assets.yaml"
        yaml_file.write_text("""
assets:
  - name: asset1
    prompt: First
  - name: asset2
    prompt: Second
""")
        
        output_dir = tmp_path / "models"
        
        runner = CliRunner()
        result = runner.invoke(main, [str(yaml_file), str(output_dir), "--resume", "--preview-only"])
        
        assert result.exit_code == 0
        
        # Check progress file exists and contains both assets
        progress_file = output_dir / ".progress.json"
        assert progress_file.exists()
        progress = json.loads(progress_file.read_text())
        assert "asset1" in progress["completed"]
        assert "asset2" in progress["completed"]

    @patch("batch_generate_assets.get_api_key")
    @patch("batch_generate_assets.create_preview_task")
    @patch("batch_generate_assets.poll_task")
    @patch("batch_generate_assets.time.sleep")
    def test_resume_tracks_failures_separately(
        self,
        mock_sleep,
        mock_poll,
        mock_create,
        mock_get_key,
        tmp_path
    ):
        """Test that failed assets are tracked in progress file."""
        mock_get_key.return_value = "test_key"
        mock_create.return_value = "preview_123"
        mock_poll.return_value = {"model_urls": {}}  # Empty = failure
        
        yaml_file = tmp_path / "assets.yaml"
        yaml_file.write_text("""
assets:
  - name: failing_asset
    prompt: Will fail
""")
        
        output_dir = tmp_path / "models"
        
        runner = CliRunner()
        result = runner.invoke(main, [str(yaml_file), str(output_dir), "--resume", "--preview-only"])
        
        assert result.exit_code == 0
        
        progress_file = output_dir / ".progress.json"
        progress = json.loads(progress_file.read_text())
        assert "failing_asset" in progress["failed"]
        assert "failing_asset" not in progress["completed"]

    @patch("batch_generate_assets.get_api_key")
    def test_resume_marks_existing_files_as_completed(self, mock_get_key, tmp_path):
        """Test that existing files are added to progress when resuming."""
        mock_get_key.return_value = "test_key"
        
        yaml_file = tmp_path / "assets.yaml"
        yaml_file.write_text("""
assets:
  - name: existing
    prompt: Already exists
""")
        
        output_dir = tmp_path / "models"
        output_dir.mkdir()
        (output_dir / "existing.fbx").write_bytes(b"data")
        
        runner = CliRunner()
        result = runner.invoke(main, [str(yaml_file), str(output_dir), "--resume"])
        
        assert result.exit_code == 0
        
        # Should update progress file
        progress_file = output_dir / ".progress.json"
        progress = json.loads(progress_file.read_text())
        assert "existing" in progress["completed"]


class TestStyleOverride:
    """Test art style override functionality."""

    @patch("batch_generate_assets.get_api_key")
    @patch("batch_generate_assets.create_preview_task")
    @patch("batch_generate_assets.poll_task")
    @patch("batch_generate_assets.download_model")
    @patch("batch_generate_assets.time.sleep")
    def test_style_override_applies_to_all(
        self,
        mock_sleep,
        mock_download,
        mock_poll,
        mock_create,
        mock_get_key,
        tmp_path
    ):
        """Test that --art-style-override overrides YAML styles."""
        mock_get_key.return_value = "test_key"
        mock_create.return_value = "preview_123"
        mock_poll.return_value = {
            "model_urls": {"fbx": "https://example.com/model.fbx"}
        }
        
        yaml_file = tmp_path / "assets.yaml"
        yaml_file.write_text("""
assets:
  - name: asset1
    prompt: Test 1
    style: cartoon
  - name: asset2
    prompt: Test 2
    style: realistic
""")
        
        output_dir = tmp_path / "models"
        
        runner = CliRunner()
        result = runner.invoke(
            main,
            [str(yaml_file), str(output_dir), "--preview-only", "--art-style-override=low-poly"]
        )
        
        assert result.exit_code == 0
        # Check that low-poly was used (appears in output)
        assert "low-poly" in result.output
