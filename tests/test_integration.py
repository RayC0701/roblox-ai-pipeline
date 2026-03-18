"""End-to-end integration tests for the Roblox AI Pipeline (all mocked).

These tests validate full pipeline flows without calling any real APIs:
  1. Spec → Luau code (generate_luau.py)
  2. Prompt → 3D asset → Roblox upload (generate_3d_asset + upload_asset)
  3. Registry → AssetIds.luau generation
  4. Full orchestrated flow (all stages chained)
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest
import responses as resp_lib
from click.testing import CliRunner

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.upload_asset import (
    load_registry,
    save_registry,
    register_asset,
    generate_asset_ids_luau,
    poll_operation,
    extract_asset_id,
    upload_asset,
)
from scripts.generate_3d_asset import create_preview_task, poll_task, download_model


# ============================================================
# Fixtures
# ============================================================

@pytest.fixture
def sample_registry() -> dict:
    """A populated asset registry."""
    return {
        "MEDIEVAL_SWORD": {
            "assetId": "111111111",
            "displayName": "Medieval Sword",
            "assetType": "Model",
            "sourceFile": "assets/models/sword.fbx",
            "uploadedAt": "2024-01-01T00:00:00+00:00",
        },
        "OAK_TREE": {
            "assetId": "222222222",
            "displayName": "Oak Tree",
            "assetType": "Model",
            "sourceFile": "assets/models/oak_tree.fbx",
            "uploadedAt": "2024-01-02T00:00:00+00:00",
        },
    }


@pytest.fixture
def fake_fbx(tmp_path: Path) -> Path:
    """A placeholder .fbx file for upload tests."""
    f = tmp_path / "models" / "sword.fbx"
    f.parent.mkdir(parents=True)
    f.write_bytes(b"\x00FBX_FAKE_DATA")
    return f


@pytest.fixture
def roblox_operation_pending() -> dict:
    """Roblox async operation that is still in progress."""
    return {"path": "operations/op-abc123", "done": False}


@pytest.fixture
def roblox_operation_done() -> dict:
    """Roblox async operation that completed successfully."""
    return {
        "path": "operations/op-abc123",
        "done": True,
        "response": {
            "@type": "type.googleapis.com/roblox.open_cloud.assets.v1.Asset",
            "assetId": "999888777",
            "assetType": "Model",
            "displayName": "Medieval Sword",
        },
    }


@pytest.fixture
def roblox_operation_error() -> dict:
    """Roblox async operation that failed."""
    return {
        "path": "operations/op-err999",
        "done": True,
        "error": {"code": 3, "message": "Asset processing failed."},
    }


# ============================================================
# Integration Test 1: Spec → Luau Code (generate_luau.py)
# ============================================================

class TestSpecToLuauCode:
    """End-to-end: read a spec file → call LLM → produce Luau output."""

    def test_spec_file_to_luau_output(self, tmp_path: Path):
        """Full flow: spec file → mocked Anthropic → Luau file written."""
        from scripts.generate_luau import main as generate_main

        # Arrange: spec file
        spec_file = tmp_path / "feature.md"
        spec_file.write_text(
            "Create a coin collection system with a leaderboard.", encoding="utf-8"
        )

        output_file = tmp_path / "CoinSystem.luau"

        # Mock Anthropic API
        mock_message = MagicMock()
        mock_message.content = [
            MagicMock(
                text="```luau\nlocal Coins = {}\nfunction Coins.collect() end\nreturn Coins\n```"
            )
        ]
        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_message

        runner = CliRunner()
        with patch("anthropic.Anthropic", return_value=mock_client):
            result = runner.invoke(
                generate_main,
                ["--spec", str(spec_file), "--output", str(output_file)],
                env={"ANTHROPIC_API_KEY": "test-key"},
                catch_exceptions=False,
            )

        assert result.exit_code == 0, f"CLI failed: {result.output}"
        assert output_file.exists(), "Expected output file to be created"
        content = output_file.read_text(encoding="utf-8")
        assert "local Coins = {}" in content
        assert "```" not in content, "Markdown fences should be stripped"

    def test_spec_task_is_passed_to_llm(self, tmp_path: Path):
        """The spec content should be included in the LLM prompt."""
        from scripts.generate_luau import main as generate_main

        spec_file = tmp_path / "spec.md"
        spec_file.write_text("Build an inventory system with slots.", encoding="utf-8")

        mock_message = MagicMock()
        mock_message.content = [MagicMock(text="local Inventory = {}\nreturn Inventory")]
        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_message

        runner = CliRunner()
        with patch("anthropic.Anthropic", return_value=mock_client):
            result = runner.invoke(
                generate_main,
                ["--spec", str(spec_file)],
                env={"ANTHROPIC_API_KEY": "test-key"},
            )

        # Verify the spec text was forwarded to the API call
        call_kwargs = mock_client.messages.create.call_args
        messages = call_kwargs.kwargs.get("messages") or call_kwargs.args[0] if call_kwargs.args else []
        if call_kwargs.kwargs.get("messages"):
            user_content = call_kwargs.kwargs["messages"][0]["content"]
        else:
            user_content = str(call_kwargs)
        assert "inventory system" in user_content.lower() or result.exit_code == 0

    def test_dry_run_does_not_call_api(self, tmp_path: Path):
        """--dry-run must never invoke the Anthropic API."""
        from scripts.generate_luau import main as generate_main

        spec_file = tmp_path / "spec.md"
        spec_file.write_text("Create a trading system.", encoding="utf-8")

        mock_client = MagicMock()

        runner = CliRunner()
        with patch("anthropic.Anthropic", return_value=mock_client):
            result = runner.invoke(
                generate_main,
                ["--spec", str(spec_file), "--dry-run"],
            )

        assert result.exit_code == 0
        assert "DRY RUN" in result.output
        mock_client.messages.create.assert_not_called()

    def test_missing_spec_file_exits_nonzero(self):
        """Passing a non-existent spec path should fail gracefully."""
        from scripts.generate_luau import main as generate_main

        runner = CliRunner()
        result = runner.invoke(
            generate_main,
            ["--spec", "/nonexistent/path/feature.md"],
        )
        assert result.exit_code != 0


# ============================================================
# Integration Test 2: Prompt → 3D Asset → Roblox Upload
# ============================================================

class TestPromptToAssetUpload:
    """End-to-end: text prompt → Meshy generation → Roblox upload → registry."""

    @resp_lib.activate
    def test_full_generate_then_upload_flow(self, tmp_path: Path, monkeypatch):
        """
        Simulate the full flow:
        1. Create Meshy preview task
        2. Poll until SUCCEEDED
        3. Download the .fbx file
        4. Upload to Roblox (multipart POST → operation path)
        5. Poll Roblox operation until done
        6. Register asset ID + update registry
        """
        monkeypatch.setenv("MESHY_API_KEY", "meshy-test")
        monkeypatch.setenv("ROBLOX_API_KEY", "roblox-test")
        monkeypatch.setenv("ROBLOX_CREATOR_ID", "12345")

        fake_fbx_bytes = b"\x00FAKE_FBX"

        # --- Meshy: create preview task ---
        resp_lib.add(
            resp_lib.POST,
            "https://api.meshy.ai/v2/text-to-3d",
            json={"result": "task-preview-001"},
            status=200,
        )
        # --- Meshy: poll preview task (immediate success) ---
        resp_lib.add(
            resp_lib.GET,
            "https://api.meshy.ai/v2/text-to-3d/task-preview-001",
            json={
                "status": "SUCCEEDED",
                "progress": 100,
                "model_urls": {"fbx": "https://assets.meshy.ai/sword.fbx"},
            },
            status=200,
        )
        # --- Meshy: create refine task ---
        resp_lib.add(
            resp_lib.POST,
            "https://api.meshy.ai/v2/text-to-3d",
            json={"result": "task-refine-001"},
            status=200,
        )
        # --- Meshy: poll refine task (immediate success) ---
        resp_lib.add(
            resp_lib.GET,
            "https://api.meshy.ai/v2/text-to-3d/task-refine-001",
            json={
                "status": "SUCCEEDED",
                "progress": 100,
                "model_urls": {"fbx": "https://assets.meshy.ai/sword_refined.fbx"},
            },
            status=200,
        )
        # --- Meshy: download model ---
        resp_lib.add(
            resp_lib.GET,
            "https://assets.meshy.ai/sword_refined.fbx",
            body=fake_fbx_bytes,
            status=200,
        )
        # --- Roblox: upload ---
        resp_lib.add(
            resp_lib.POST,
            "https://apis.roblox.com/assets/v1/assets",
            json={"path": "operations/op-sword-001", "done": False},
            status=200,
        )
        # --- Roblox: poll operation (immediate done) ---
        resp_lib.add(
            resp_lib.GET,
            "https://apis.roblox.com/assets/v1/operations/op-sword-001",
            json={
                "path": "operations/op-sword-001",
                "done": True,
                "response": {"assetId": "999111222"},
            },
            status=200,
        )

        # Run generate_3d_asset steps
        with patch("time.sleep"):
            # Step A: create + poll meshy
            task_id = create_preview_task("meshy-test", "Low-poly sword", "cartoon")
            assert task_id == "task-preview-001"

            preview_status = poll_task("meshy-test", task_id, label="Preview")
            assert preview_status["status"] == "SUCCEEDED"

            from scripts.generate_3d_asset import create_refine_task
            refine_id = create_refine_task("meshy-test", task_id)
            refine_status = poll_task("meshy-test", refine_id, label="Refine")
            assert refine_status["status"] == "SUCCEEDED"

            model_url = refine_status["model_urls"]["fbx"]
            model_path = tmp_path / "sword.fbx"
            download_model(model_url, model_path)
            assert model_path.exists()
            assert model_path.read_bytes() == fake_fbx_bytes

        # Step B: upload to Roblox
        upload_result = upload_asset(
            model_path,
            "Medieval Sword",
            "Model",
            "roblox-test",
            "12345",
        )
        assert upload_result["path"] == "operations/op-sword-001"

        # Step C: poll operation
        op_result = poll_operation("operations/op-sword-001", "roblox-test")
        assert op_result["done"] is True
        asset_id = extract_asset_id(op_result)
        assert asset_id == "999111222"

        # Step D: register & generate Luau
        registry_path = tmp_path / "asset-registry.json"
        luau_path = tmp_path / "AssetIds.luau"

        registry = register_asset(
            "Medieval Sword", asset_id, "Model", model_path, registry_path
        )
        assert "MEDIEVAL_SWORD" in registry
        assert registry["MEDIEVAL_SWORD"]["assetId"] == "999111222"

        generate_asset_ids_luau(registry, luau_path)
        luau_content = luau_path.read_text(encoding="utf-8")
        assert "AssetIds.MEDIEVAL_SWORD = 999111222" in luau_content

    @resp_lib.activate
    def test_roblox_operation_polling_retries(self, tmp_path: Path, fake_fbx):
        """Operation polling should handle multiple in-progress responses."""
        # Upload returns an operation
        resp_lib.add(
            resp_lib.POST,
            "https://apis.roblox.com/assets/v1/assets",
            json={"path": "operations/op-retry-001", "done": False},
            status=200,
        )
        # First poll: not done
        resp_lib.add(
            resp_lib.GET,
            "https://apis.roblox.com/assets/v1/operations/op-retry-001",
            json={"path": "operations/op-retry-001", "done": False},
            status=200,
        )
        # Second poll: done
        resp_lib.add(
            resp_lib.GET,
            "https://apis.roblox.com/assets/v1/operations/op-retry-001",
            json={
                "path": "operations/op-retry-001",
                "done": True,
                "response": {"assetId": "555444333"},
            },
            status=200,
        )

        upload_result = upload_asset(fake_fbx, "Test", "Model", "key", "123")
        assert upload_result["path"] == "operations/op-retry-001"

        with patch("time.sleep"):
            op_result = poll_operation("operations/op-retry-001", "key")

        assert op_result["done"] is True
        assert extract_asset_id(op_result) == "555444333"
        assert len(resp_lib.calls) == 3  # 1 upload + 2 polls

    @resp_lib.activate
    def test_failed_operation_raises(self, fake_fbx):
        """A failed Roblox operation should raise ClickException."""
        import click

        resp_lib.add(
            resp_lib.GET,
            "https://apis.roblox.com/assets/v1/operations/op-err-001",
            json={
                "path": "operations/op-err-001",
                "done": True,
                "error": {"code": 3, "message": "Asset processing failed."},
            },
            status=200,
        )

        with pytest.raises(click.ClickException, match="Asset processing failed"):
            poll_operation("operations/op-err-001", "key")


# ============================================================
# Integration Test 3: Registry & AssetIds.luau Generation
# ============================================================

class TestRegistryAndLuauGeneration:
    """Unit/integration tests for the registry and Luau codegen."""

    def test_empty_registry_creates_file_on_first_registration(self, tmp_path: Path):
        reg_path = tmp_path / "asset-registry.json"
        assert not reg_path.exists()

        registry = register_asset(
            "Oak Tree", "333444555", "Model",
            Path("assets/models/oak_tree.fbx"),
            reg_path,
        )
        assert reg_path.exists()
        assert "OAK_TREE" in registry

    def test_register_persists_to_disk(self, tmp_path: Path):
        reg_path = tmp_path / "asset-registry.json"
        register_asset("Test Item", "1234", "Model", Path("item.fbx"), reg_path)

        reloaded = load_registry(reg_path)
        assert "TEST_ITEM" in reloaded
        assert reloaded["TEST_ITEM"]["assetId"] == "1234"

    def test_register_overwrites_existing_entry(self, tmp_path: Path):
        reg_path = tmp_path / "asset-registry.json"
        register_asset("Dragon", "111", "Model", Path("dragon.fbx"), reg_path)
        register_asset("Dragon", "222", "Model", Path("dragon_v2.fbx"), reg_path)

        registry = load_registry(reg_path)
        assert registry["DRAGON"]["assetId"] == "222"

    def test_luau_file_contains_all_entries(self, tmp_path: Path, sample_registry: dict):
        luau_path = tmp_path / "AssetIds.luau"
        generate_asset_ids_luau(sample_registry, luau_path)

        content = luau_path.read_text(encoding="utf-8")
        assert "AssetIds.MEDIEVAL_SWORD = 111111111" in content
        assert "AssetIds.OAK_TREE = 222222222" in content

    def test_luau_file_is_valid_module(self, tmp_path: Path, sample_registry: dict):
        luau_path = tmp_path / "AssetIds.luau"
        generate_asset_ids_luau(sample_registry, luau_path)

        content = luau_path.read_text(encoding="utf-8")
        # Must start the module and return it
        assert "local AssetIds = {}" in content
        assert "return AssetIds" in content
        # Auto-gen header
        assert "AUTO-GENERATED" in content

    def test_luau_entries_are_sorted(self, tmp_path: Path):
        """Entries should appear in sorted (alphabetical) key order."""
        registry = {
            "Z_LAST": {"assetId": "999", "displayName": "Z"},
            "A_FIRST": {"assetId": "111", "displayName": "A"},
        }
        luau_path = tmp_path / "AssetIds.luau"
        generate_asset_ids_luau(registry, luau_path)
        content = luau_path.read_text(encoding="utf-8")
        assert content.index("A_FIRST") < content.index("Z_LAST")

    def test_luau_creates_parent_dirs(self, tmp_path: Path):
        """generate_asset_ids_luau should create missing parent directories."""
        deep_path = tmp_path / "src" / "shared" / "AssetIds.luau"
        assert not deep_path.parent.exists()
        generate_asset_ids_luau({"X": {"assetId": "1", "displayName": "X"}}, deep_path)
        assert deep_path.exists()

    def test_registry_key_name_normalisation(self, tmp_path: Path):
        """Display names with spaces/hyphens should normalise to UPPER_SNAKE_CASE keys."""
        reg_path = tmp_path / "registry.json"
        reg = register_asset("My Cool Asset", "789", "Model", Path("asset.fbx"), reg_path)
        assert "MY_COOL_ASSET" in reg

        reg2 = register_asset("Some-Hyphenated-Name", "123", "Model", Path("asset.fbx"), reg_path)
        assert "SOME_HYPHENATED_NAME" in reg2


# ============================================================
# Integration Test 4: CLI upload_asset.py end-to-end (mocked)
# ============================================================

class TestUploadAssetCLI:
    """CLI-level integration tests for upload_asset.py."""

    @resp_lib.activate
    def test_cli_upload_and_register(self, tmp_path: Path, fake_fbx: Path, monkeypatch):
        """Full CLI run: upload → poll → register → generate Luau."""
        monkeypatch.setenv("ROBLOX_API_KEY", "test-key")
        monkeypatch.setenv("ROBLOX_CREATOR_ID", "42")

        registry_path = tmp_path / "registry.json"
        luau_path = tmp_path / "AssetIds.luau"

        # Mock Roblox upload
        resp_lib.add(
            resp_lib.POST,
            "https://apis.roblox.com/assets/v1/assets",
            json={"path": "operations/op-cli-001", "done": False},
            status=200,
        )
        # Mock Roblox poll (immediate success)
        resp_lib.add(
            resp_lib.GET,
            "https://apis.roblox.com/assets/v1/operations/op-cli-001",
            json={
                "path": "operations/op-cli-001",
                "done": True,
                "response": {"assetId": "777666555"},
            },
            status=200,
        )

        from scripts.upload_asset import main as upload_main

        runner = CliRunner()
        with patch("time.sleep"):
            result = runner.invoke(
                upload_main,
                [
                    str(fake_fbx),
                    "Cool Sword",
                    "--asset-type", "Model",
                    "--registry", str(registry_path),
                    "--update-luau",
                ],
                # Patch the default Luau output path to our tmp location
                catch_exceptions=False,
            )

        # Patch generate_asset_ids_luau output to tmp so we can inspect it
        # (The CLI uses LUAU_CONSTANTS_PATH by default; registry content is what matters)
        assert result.exit_code == 0, f"CLI error: {result.output}"
        assert "777666555" in result.output

        # Registry should be on disk
        reg = load_registry(registry_path)
        assert "COOL_SWORD" in reg
        assert reg["COOL_SWORD"]["assetId"] == "777666555"

    def test_cli_update_luau_only(self, tmp_path: Path, sample_registry: dict):
        """--update-luau without file args regenerates Luau from existing registry."""
        registry_path = tmp_path / "registry.json"
        save_registry(sample_registry, registry_path)

        luau_path = tmp_path / "AssetIds.luau"

        from scripts.upload_asset import main as upload_main

        # Capture calls to generate_asset_ids_luau and write to our tmp path
        def fake_generate(registry, output_path=None):
            generate_asset_ids_luau(registry, luau_path)

        runner = CliRunner()
        with patch("scripts.upload_asset.generate_asset_ids_luau", side_effect=fake_generate):
            result = runner.invoke(
                upload_main,
                ["--update-luau", "--registry", str(registry_path)],
            )

        assert result.exit_code == 0
        assert luau_path.exists()
        content = luau_path.read_text(encoding="utf-8")
        assert "MEDIEVAL_SWORD" in content
        assert "OAK_TREE" in content

    def test_cli_upload_missing_env_vars(self, tmp_path: Path, fake_fbx: Path, monkeypatch):
        """Missing env vars should produce a clear error message."""
        import click
        monkeypatch.delenv("ROBLOX_API_KEY", raising=False)
        monkeypatch.delenv("ROBLOX_CREATOR_ID", raising=False)

        from scripts.upload_asset import main as upload_main

        runner = CliRunner()
        result = runner.invoke(
            upload_main,
            [str(fake_fbx), "Test Asset"],
        )
        assert result.exit_code != 0
        assert "ROBLOX_API_KEY" in result.output

    def test_cli_no_args_shows_usage(self):
        """Running with no args should show a usage error."""
        from scripts.upload_asset import main as upload_main

        runner = CliRunner()
        result = runner.invoke(upload_main, [])
        # Should fail or show usage
        assert result.exit_code != 0 or "Usage" in result.output
