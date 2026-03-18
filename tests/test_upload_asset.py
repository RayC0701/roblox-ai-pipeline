#!/usr/bin/env python3
"""Tests for scripts/upload_asset.py"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import Mock, call, mock_open, patch

import pytest
import requests
from click.testing import CliRunner

# Import functions from the script
import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
from upload_asset import (
    extract_asset_id,
    generate_asset_ids_luau,
    get_roblox_config,
    load_registry,
    main,
    poll_operation,
    register_asset,
    save_registry,
    upload_asset,
)


class TestGetRobloxConfig:
    """Test configuration loading from environment."""

    @patch.dict("os.environ", {"ROBLOX_API_KEY": "test_key", "ROBLOX_CREATOR_ID": "12345"})
    def test_returns_valid_config(self):
        """Test successful config retrieval."""
        api_key, creator_id = get_roblox_config()
        assert api_key == "test_key"
        assert creator_id == "12345"

    @patch.dict("os.environ", {"ROBLOX_CREATOR_ID": "12345"}, clear=True)
    def test_raises_on_missing_api_key(self):
        """Test that missing API key raises error."""
        with pytest.raises(Exception) as exc_info:
            get_roblox_config()
        assert "ROBLOX_API_KEY" in str(exc_info.value)

    @patch.dict("os.environ", {"ROBLOX_API_KEY": "test_key"}, clear=True)
    def test_raises_on_missing_creator_id(self):
        """Test that missing creator ID raises error."""
        with pytest.raises(Exception) as exc_info:
            get_roblox_config()
        assert "ROBLOX_CREATOR_ID" in str(exc_info.value)


class TestUploadAsset:
    """Test asset upload functionality."""

    @patch("upload_asset.requests.post")
    def test_uploads_file_successfully(self, mock_post, tmp_path):
        """Test successful asset upload."""
        # Create a test file
        test_file = tmp_path / "model.fbx"
        test_file.write_bytes(b"fake fbx data")
        
        # Mock successful response
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"path": "operations/test123"}
        mock_post.return_value = mock_response
        
        result = upload_asset(
            test_file,
            "Test Model",
            "Model",
            "api_key",
            "creator123"
        )
        
        assert result["path"] == "operations/test123"
        mock_post.assert_called_once()

    def test_raises_on_missing_file(self):
        """Test that upload raises error for non-existent file."""
        fake_path = Path("/nonexistent/file.fbx")
        
        with pytest.raises(Exception) as exc_info:
            upload_asset(fake_path, "Test", "Model", "key", "id")
        assert "File not found" in str(exc_info.value)

    @patch("upload_asset.requests.post")
    def test_raises_on_api_error(self, mock_post, tmp_path):
        """Test handling of API errors during upload."""
        test_file = tmp_path / "model.fbx"
        test_file.write_bytes(b"data")
        
        mock_response = Mock()
        mock_response.status_code = 400
        mock_response.text = "Invalid request"
        mock_post.return_value = mock_response
        
        with pytest.raises(Exception) as exc_info:
            upload_asset(test_file, "Test", "Model", "key", "id")
        assert "400" in str(exc_info.value)

    @patch("upload_asset.requests.post")
    def test_handles_request_exception(self, mock_post, tmp_path):
        """Test handling of network errors."""
        test_file = tmp_path / "model.fbx"
        test_file.write_bytes(b"data")
        
        mock_post.side_effect = requests.RequestException("Network error")
        
        with pytest.raises(Exception) as exc_info:
            upload_asset(test_file, "Test", "Model", "key", "id")
        assert "Upload request failed" in str(exc_info.value)


class TestPollOperation:
    """Test operation polling functionality."""

    @patch("upload_asset.requests.get")
    @patch("upload_asset.time.sleep")
    def test_returns_completed_operation(self, mock_sleep, mock_get):
        """Test successful polling of completed operation."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "done": True,
            "response": {"assetId": "987654321"}
        }
        mock_get.return_value = mock_response
        
        result = poll_operation("operations/test", "api_key")
        
        assert result["done"] is True
        assert result["response"]["assetId"] == "987654321"

    @patch("upload_asset.requests.get")
    @patch("upload_asset.time.sleep")
    def test_polls_multiple_times(self, mock_sleep, mock_get):
        """Test that polling retries for pending operations."""
        # First two calls return pending, third returns done
        mock_responses = [
            Mock(status_code=200, json=lambda: {"done": False}),
            Mock(status_code=200, json=lambda: {"done": False}),
            Mock(status_code=200, json=lambda: {"done": True, "response": {"assetId": "123"}}),
        ]
        mock_get.side_effect = mock_responses
        
        result = poll_operation("operations/test", "api_key")
        
        assert mock_get.call_count == 3
        assert result["done"] is True

    @patch("upload_asset.requests.get")
    @patch("upload_asset.time.sleep")
    def test_raises_on_operation_error(self, mock_sleep, mock_get):
        """Test handling of operation errors."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "done": True,
            "error": {"message": "Processing failed"}
        }
        mock_get.return_value = mock_response
        
        with pytest.raises(Exception) as exc_info:
            poll_operation("operations/test", "api_key")
        assert "Processing failed" in str(exc_info.value)

    @patch("upload_asset.requests.get")
    @patch("upload_asset.time.sleep")
    def test_raises_on_timeout(self, mock_sleep, mock_get):
        """Test timeout after max polling attempts."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"done": False}
        mock_get.return_value = mock_response
        
        with pytest.raises(Exception) as exc_info:
            poll_operation("operations/test", "api_key")
        assert "Timed out" in str(exc_info.value)

    @patch("upload_asset.requests.get")
    def test_raises_on_api_error(self, mock_get):
        """Test handling of API errors during polling."""
        mock_response = Mock()
        mock_response.status_code = 403
        mock_response.text = "Forbidden"
        mock_get.return_value = mock_response
        
        with pytest.raises(Exception) as exc_info:
            poll_operation("operations/test", "api_key")
        assert "403" in str(exc_info.value)


class TestExtractAssetId:
    """Test asset ID extraction."""

    def test_extracts_valid_asset_id(self):
        """Test extraction from valid operation result."""
        operation = {
            "done": True,
            "response": {"assetId": "123456789"}
        }
        
        asset_id = extract_asset_id(operation)
        assert asset_id == "123456789"

    def test_raises_on_missing_asset_id(self):
        """Test error when asset ID is missing."""
        operation = {"done": True, "response": {}}
        
        with pytest.raises(Exception) as exc_info:
            extract_asset_id(operation)
        assert "Could not find assetId" in str(exc_info.value)

    def test_handles_numeric_asset_id(self):
        """Test conversion of numeric asset ID to string."""
        operation = {
            "done": True,
            "response": {"assetId": 987654321}
        }
        
        asset_id = extract_asset_id(operation)
        assert asset_id == "987654321"
        assert isinstance(asset_id, str)


class TestRegistry:
    """Test asset registry operations."""

    def test_load_registry_returns_existing(self, tmp_path):
        """Test loading an existing registry file."""
        registry_path = tmp_path / "registry.json"
        test_data = {"TEST_ASSET": {"assetId": "123"}}
        registry_path.write_text(json.dumps(test_data))
        
        result = load_registry(registry_path)
        assert result == test_data

    def test_load_registry_returns_empty_if_missing(self, tmp_path):
        """Test loading non-existent registry returns empty dict."""
        registry_path = tmp_path / "missing.json"
        
        result = load_registry(registry_path)
        assert result == {}

    def test_save_registry_creates_file(self, tmp_path):
        """Test saving registry creates file with correct content."""
        registry_path = tmp_path / "assets" / "registry.json"
        test_data = {"KEY": {"value": "test"}}
        
        save_registry(test_data, registry_path)
        
        assert registry_path.exists()
        saved_data = json.loads(registry_path.read_text())
        assert saved_data == test_data

    def test_register_asset_adds_entry(self, tmp_path):
        """Test registering a new asset."""
        registry_path = tmp_path / "registry.json"
        file_path = tmp_path / "model.fbx"
        
        with patch("upload_asset._utc_now", return_value="2024-01-01T00:00:00Z"):
            result = register_asset(
                "Test Sword",
                "123456",
                "Model",
                file_path,
                registry_path
            )
        
        assert "TEST_SWORD" in result
        assert result["TEST_SWORD"]["assetId"] == "123456"
        assert result["TEST_SWORD"]["displayName"] == "Test Sword"
        assert result["TEST_SWORD"]["assetType"] == "Model"

    def test_register_asset_updates_existing(self, tmp_path):
        """Test updating an existing asset entry."""
        registry_path = tmp_path / "registry.json"
        existing = {"TEST_SWORD": {"assetId": "old_id"}}
        registry_path.write_text(json.dumps(existing))
        
        file_path = tmp_path / "model.fbx"
        
        with patch("upload_asset._utc_now", return_value="2024-01-01T00:00:00Z"):
            result = register_asset(
                "Test Sword",
                "new_id",
                "Model",
                file_path,
                registry_path
            )
        
        assert result["TEST_SWORD"]["assetId"] == "new_id"


class TestGenerateAssetIdsLuau:
    """Test Luau constants file generation."""

    def test_generates_valid_luau_file(self, tmp_path):
        """Test generation of AssetIds.luau from registry."""
        output_path = tmp_path / "AssetIds.luau"
        registry = {
            "MEDIEVAL_SWORD": {
                "assetId": "123456",
                "displayName": "Medieval Sword"
            },
            "OAK_TREE": {
                "assetId": "789012",
                "displayName": "Oak Tree"
            }
        }
        
        generate_asset_ids_luau(registry, output_path)
        
        assert output_path.exists()
        content = output_path.read_text()
        
        assert "AUTO-GENERATED" in content
        assert "AssetIds.MEDIEVAL_SWORD = 123456" in content
        assert "AssetIds.OAK_TREE = 789012" in content
        assert "return AssetIds" in content

    def test_generates_empty_file_for_empty_registry(self, tmp_path):
        """Test generation with empty registry."""
        output_path = tmp_path / "AssetIds.luau"
        registry = {}
        
        generate_asset_ids_luau(registry, output_path)
        
        assert output_path.exists()
        content = output_path.read_text()
        assert "local AssetIds = {}" in content
        assert "return AssetIds" in content

    def test_creates_parent_directories(self, tmp_path):
        """Test that parent directories are created if needed."""
        output_path = tmp_path / "nested" / "dir" / "AssetIds.luau"
        registry = {"TEST": {"assetId": "123", "displayName": "Test"}}
        
        generate_asset_ids_luau(registry, output_path)
        
        assert output_path.exists()


class TestCLI:
    """Test command-line interface."""

    @patch("upload_asset.get_roblox_config")
    @patch("upload_asset.upload_asset")
    @patch("upload_asset.poll_operation")
    @patch("upload_asset.register_asset")
    def test_full_upload_flow(
        self,
        mock_register,
        mock_poll,
        mock_upload,
        mock_config,
        tmp_path
    ):
        """Test complete upload flow from CLI."""
        mock_config.return_value = ("api_key", "creator_id")
        mock_upload.return_value = {"path": "operations/test123"}
        mock_poll.return_value = {
            "done": True,
            "response": {"assetId": "987654"}
        }
        mock_register.return_value = {}
        
        test_file = tmp_path / "model.fbx"
        test_file.write_bytes(b"data")
        
        runner = CliRunner()
        result = runner.invoke(main, [str(test_file), "Test Model"])
        
        assert result.exit_code == 0
        assert "Asset ID: 987654" in result.output
        mock_upload.assert_called_once()
        mock_poll.assert_called_once()

    @patch("upload_asset.load_registry")
    @patch("upload_asset.generate_asset_ids_luau")
    def test_update_luau_only(self, mock_generate, mock_load, tmp_path):
        """Test --update-luau without file upload."""
        mock_load.return_value = {"TEST": {"assetId": "123"}}
        
        runner = CliRunner()
        result = runner.invoke(main, ["--update-luau", "--registry", str(tmp_path / "reg.json")])
        
        assert result.exit_code == 0
        mock_generate.assert_called_once()

    def test_missing_arguments_fails(self):
        """Test that missing required arguments produces error."""
        runner = CliRunner()
        result = runner.invoke(main, [])
        
        assert result.exit_code != 0

    @patch("upload_asset.get_roblox_config")
    @patch("upload_asset.upload_asset")
    def test_no_poll_option(self, mock_upload, mock_config, tmp_path):
        """Test --no-poll skips polling."""
        mock_config.return_value = ("key", "id")
        mock_upload.return_value = {"path": "operations/test"}
        
        test_file = tmp_path / "model.fbx"
        test_file.write_bytes(b"data")
        
        runner = CliRunner()
        result = runner.invoke(main, [str(test_file), "Test", "--no-poll"])
        
        assert result.exit_code == 0
        assert "polling skipped" in result.output

    @patch("upload_asset.get_roblox_config")
    @patch("upload_asset.upload_asset")
    @patch("upload_asset.poll_operation")
    @patch("upload_asset.register_asset")
    @patch("upload_asset.generate_asset_ids_luau")
    def test_update_luau_after_upload(
        self,
        mock_generate,
        mock_register,
        mock_poll,
        mock_upload,
        mock_config,
        tmp_path
    ):
        """Test that --update-luau triggers generation after upload."""
        mock_config.return_value = ("key", "id")
        mock_upload.return_value = {"path": "operations/test"}
        mock_poll.return_value = {"done": True, "response": {"assetId": "123"}}
        mock_register.return_value = {}
        
        test_file = tmp_path / "model.fbx"
        test_file.write_bytes(b"data")
        
        runner = CliRunner()
        result = runner.invoke(main, [str(test_file), "Test", "--update-luau"])
        
        assert result.exit_code == 0
        mock_generate.assert_called_once()


class TestEdgeCases:
    """Test edge cases and error conditions."""

    @patch("upload_asset.get_roblox_config")
    def test_handles_direct_asset_id_response(self, mock_config, tmp_path):
        """Test handling of responses that return assetId directly (no operation path)."""
        # Some older API versions return the asset ID immediately
        mock_config.return_value = ("key", "id")
        
        test_file = tmp_path / "model.fbx"
        test_file.write_bytes(b"data")
        
        with patch("upload_asset.upload_asset") as mock_upload:
            mock_upload.return_value = {"assetId": "123456"}
            
            with patch("upload_asset.register_asset") as mock_register:
                mock_register.return_value = {}
                
                runner = CliRunner()
                result = runner.invoke(main, [str(test_file), "Test"])
                
                assert result.exit_code == 0
                assert "123456" in result.output

    @patch("upload_asset.load_registry")
    def test_empty_registry_update_luau_fails(self, mock_load):
        """Test --update-luau with empty registry."""
        mock_load.return_value = {}
        
        runner = CliRunner()
        result = runner.invoke(main, ["--update-luau"])
        
        assert result.exit_code != 0
        assert "empty" in result.output.lower()
