"""Integration tests for scripts/generate_3d_asset.py."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest
import responses as resp_lib

# Import module under test
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.generate_3d_asset import (
    get_api_key,
    get_headers,
    create_preview_task,
    create_refine_task,
    poll_task,
    download_model,
)
import scripts.generate_3d_asset as asset_module


# ---------------------------------------------------------------------------
# Unit tests: get_api_key / get_headers
# ---------------------------------------------------------------------------

class TestApiKey:
    def test_get_api_key_from_env(self, monkeypatch):
        monkeypatch.setenv("MESHY_API_KEY", "test-key-123")
        assert get_api_key() == "test-key-123"

    def test_get_api_key_missing_raises(self, monkeypatch):
        import click
        monkeypatch.delenv("MESHY_API_KEY", raising=False)
        with pytest.raises(click.ClickException, match="MESHY_API_KEY"):
            get_api_key()

    def test_get_headers_format(self):
        headers = get_headers("my-secret-key")
        assert headers == {"Authorization": "Bearer my-secret-key"}


# ---------------------------------------------------------------------------
# Unit tests: create_preview_task (mocked HTTP)
# ---------------------------------------------------------------------------

class TestCreatePreviewTask:
    @resp_lib.activate
    def test_creates_task_successfully(self):
        resp_lib.add(
            resp_lib.POST,
            "https://api.meshy.ai/v2/text-to-3d",
            json={"result": "task-preview-001"},
            status=200,
        )
        task_id = create_preview_task("test-key", "Low-poly sword", "cartoon")
        assert task_id == "task-preview-001"

    @resp_lib.activate
    def test_raises_on_api_error(self):
        import click
        resp_lib.add(
            resp_lib.POST,
            "https://api.meshy.ai/v2/text-to-3d",
            json={"error": "Unauthorized"},
            status=401,
        )
        with pytest.raises(click.ClickException, match="Failed to create preview task"):
            create_preview_task("bad-key", "test prompt", "cartoon")

    @resp_lib.activate
    def test_retries_on_rate_limit_then_succeeds(self):
        # First call: 429, second call: 200
        resp_lib.add(
            resp_lib.POST,
            "https://api.meshy.ai/v2/text-to-3d",
            json={"error": "Rate limited"},
            status=429,
        )
        resp_lib.add(
            resp_lib.POST,
            "https://api.meshy.ai/v2/text-to-3d",
            json={"result": "task-retry-001"},
            status=200,
        )
        with patch("time.sleep"):  # Don't actually sleep in tests
            task_id = create_preview_task("test-key", "test prompt", "cartoon")
        assert task_id == "task-retry-001"

    @resp_lib.activate
    def test_raises_after_max_retries(self):
        import click
        # All retries fail with 429
        for _ in range(asset_module.MAX_RETRIES):
            resp_lib.add(
                resp_lib.POST,
                "https://api.meshy.ai/v2/text-to-3d",
                json={"error": "Rate limited"},
                status=429,
            )
        with patch("time.sleep"):
            with pytest.raises(click.ClickException, match="Max retries exceeded"):
                create_preview_task("test-key", "test prompt", "cartoon")

    @resp_lib.activate
    def test_sends_correct_payload(self):
        resp_lib.add(
            resp_lib.POST,
            "https://api.meshy.ai/v2/text-to-3d",
            json={"result": "task-001"},
            status=200,
        )
        create_preview_task("test-key", "A cartoon mushroom", "cartoon")
        body = resp_lib.calls[0].request.body
        import json
        payload = json.loads(body)
        assert payload["mode"] == "preview"
        assert payload["prompt"] == "A cartoon mushroom"
        assert payload["art_style"] == "cartoon"


# ---------------------------------------------------------------------------
# Unit tests: create_refine_task (mocked HTTP)
# ---------------------------------------------------------------------------

class TestCreateRefineTask:
    @resp_lib.activate
    def test_creates_refine_successfully(self):
        resp_lib.add(
            resp_lib.POST,
            "https://api.meshy.ai/v2/text-to-3d",
            json={"result": "task-refine-001"},
            status=200,
        )
        task_id = create_refine_task("test-key", "task-preview-001")
        assert task_id == "task-refine-001"

    @resp_lib.activate
    def test_sends_correct_refine_payload(self):
        resp_lib.add(
            resp_lib.POST,
            "https://api.meshy.ai/v2/text-to-3d",
            json={"result": "task-refine-001"},
            status=200,
        )
        create_refine_task("test-key", "task-preview-001")
        body = resp_lib.calls[0].request.body
        import json
        payload = json.loads(body)
        assert payload["mode"] == "refine"
        assert payload["preview_task_id"] == "task-preview-001"


# ---------------------------------------------------------------------------
# Unit tests: poll_task
# ---------------------------------------------------------------------------

class TestPollTask:
    @resp_lib.activate
    def test_returns_immediately_on_succeeded(self, meshy_task_succeeded):
        resp_lib.add(
            resp_lib.GET,
            "https://api.meshy.ai/v2/text-to-3d/task-abc123",
            json=meshy_task_succeeded,
            status=200,
        )
        result = poll_task("test-key", "task-abc123")
        assert result["status"] == "SUCCEEDED"
        assert result["model_urls"]["fbx"] == "https://assets.meshy.ai/models/output.fbx"

    @resp_lib.activate
    def test_raises_on_failed_task(self, meshy_task_failed):
        import click
        resp_lib.add(
            resp_lib.GET,
            "https://api.meshy.ai/v2/text-to-3d/task-abc123",
            json=meshy_task_failed,
            status=200,
        )
        with pytest.raises(click.ClickException, match="Generation failed due to content policy"):
            poll_task("test-key", "task-abc123")

    @resp_lib.activate
    def test_polls_multiple_times_then_succeeds(self, meshy_task_pending, meshy_task_succeeded):
        """Simulate task that transitions PENDING -> SUCCEEDED."""
        resp_lib.add(
            resp_lib.GET,
            "https://api.meshy.ai/v2/text-to-3d/task-abc123",
            json=meshy_task_pending,
            status=200,
        )
        resp_lib.add(
            resp_lib.GET,
            "https://api.meshy.ai/v2/text-to-3d/task-abc123",
            json=meshy_task_succeeded,
            status=200,
        )
        with patch("time.sleep"):
            result = poll_task("test-key", "task-abc123")
        assert result["status"] == "SUCCEEDED"
        assert len(resp_lib.calls) == 2  # Two polls before success

    @resp_lib.activate
    def test_raises_on_api_error(self):
        import click
        resp_lib.add(
            resp_lib.GET,
            "https://api.meshy.ai/v2/text-to-3d/task-abc123",
            json={"error": "Not found"},
            status=404,
        )
        with pytest.raises(click.ClickException, match="Failed to poll task"):
            poll_task("test-key", "task-abc123")

    def test_raises_on_timeout(self, meshy_task_pending):
        """poll_task should raise after the timeout expires."""
        import click
        with patch("time.sleep"), \
             patch("time.time") as mock_time, \
             patch("requests.get") as mock_get:
            # Simulate time progressing past the deadline
            mock_time.side_effect = [0, 0, 999]  # start=0, deadline check=0, then 999 > timeout
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = meshy_task_pending
            mock_get.return_value = mock_resp

            with pytest.raises(click.ClickException, match="timed out"):
                poll_task("test-key", "task-abc123", timeout=10)


# ---------------------------------------------------------------------------
# Unit tests: download_model
# ---------------------------------------------------------------------------

class TestDownloadModel:
    @resp_lib.activate
    def test_downloads_and_writes_file(self, tmp_path: Path):
        fake_fbx_data = b"\x00\x01\x02\x03FAKE_FBX_DATA"
        resp_lib.add(
            resp_lib.GET,
            "https://assets.meshy.ai/models/output.fbx",
            body=fake_fbx_data,
            status=200,
            headers={"content-length": str(len(fake_fbx_data))},
        )
        output_path = tmp_path / "models" / "output.fbx"
        download_model("https://assets.meshy.ai/models/output.fbx", output_path)
        assert output_path.exists()
        assert output_path.read_bytes() == fake_fbx_data

    @resp_lib.activate
    def test_creates_parent_directories(self, tmp_path: Path):
        resp_lib.add(
            resp_lib.GET,
            "https://example.com/model.fbx",
            body=b"data",
            status=200,
        )
        deeply_nested = tmp_path / "a" / "b" / "c" / "model.fbx"
        download_model("https://example.com/model.fbx", deeply_nested)
        assert deeply_nested.exists()


# ---------------------------------------------------------------------------
# Idempotency tests: batch_generate_assets logic
# ---------------------------------------------------------------------------

class TestIdempotency:
    def test_skip_existing_model(self, tmp_path: Path, monkeypatch):
        """Verify that batch logic skips already-generated models."""
        from scripts.batch_generate_assets import main as batch_main
        from click.testing import CliRunner

        # Mock the API key so get_api_key() doesn't raise
        monkeypatch.setenv("MESHY_API_KEY", "test-key-123")

        # Create a dummy batch-prompts.yaml
        prompts_dir = tmp_path / "assets"
        prompts_dir.mkdir()
        yaml_file = prompts_dir / "batch-prompts.yaml"
        yaml_file.write_text(
            "assets:\n  - name: test_sword\n    prompt: Low-poly sword\n    style: cartoon\n",
            encoding="utf-8",
        )

        # Pre-create output file to simulate already-generated asset
        output_dir = tmp_path / "assets" / "models"
        output_dir.mkdir(parents=True)
        existing_file = output_dir / "test_sword.fbx"
        existing_file.write_text("fake fbx data", encoding="utf-8")

        runner = CliRunner()
        result = runner.invoke(
            batch_main,
            [str(yaml_file), str(output_dir)],
        )
        # Should exit 0 and show skip message
        assert result.exit_code == 0
        assert "already exists" in result.output or "Skipping test_sword" in result.output

    def test_batch_processes_missing_models(self, tmp_path: Path, monkeypatch):
        """Batch skips existing, processes new assets."""
        monkeypatch.setenv("MESHY_API_KEY", "test-key-123")

        yaml_file = tmp_path / "prompts.yaml"
        yaml_file.write_text(
            "assets:\n"
            "  - name: existing_item\n    prompt: Already done\n    style: cartoon\n"
            "  - name: new_item\n    prompt: New asset to generate\n    style: cartoon\n",
            encoding="utf-8",
        )

        output_dir = tmp_path / "models"
        output_dir.mkdir()

        # Pre-create only first item
        (output_dir / "existing_item.fbx").write_text("existing", encoding="utf-8")

        # Mock API calls so new_item triggers generation path
        from click.testing import CliRunner
        from scripts.batch_generate_assets import main as batch_main

        with resp_lib.RequestsMock() as rsps:
            rsps.add(
                resp_lib.POST,
                "https://api.meshy.ai/v2/text-to-3d",
                json={"result": "task-preview-new"},
                status=200,
            )
            rsps.add(
                resp_lib.GET,
                "https://api.meshy.ai/v2/text-to-3d/task-preview-new",
                json={
                    "status": "SUCCEEDED",
                    "progress": 100,
                    "model_urls": {"fbx": "https://example.com/new_item.fbx"},
                },
                status=200,
            )
            rsps.add(
                resp_lib.POST,
                "https://api.meshy.ai/v2/text-to-3d",
                json={"result": "task-refine-new"},
                status=200,
            )
            rsps.add(
                resp_lib.GET,
                "https://api.meshy.ai/v2/text-to-3d/task-refine-new",
                json={
                    "status": "SUCCEEDED",
                    "progress": 100,
                    "model_urls": {"fbx": "https://example.com/new_item_refined.fbx"},
                },
                status=200,
            )
            rsps.add(
                resp_lib.GET,
                "https://example.com/new_item_refined.fbx",
                body=b"FAKE_FBX",
                status=200,
            )
            with patch("time.sleep"):
                runner = CliRunner()
                result = runner.invoke(
                    batch_main,
                    [str(yaml_file), str(output_dir)],
                )

        assert result.exit_code == 0
        # existing_item should be skipped
        assert "Skipping existing_item" in result.output
