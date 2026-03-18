"""Shared fixtures for roblox-ai-pipeline tests."""
from __future__ import annotations

import json
from pathlib import Path

import pytest


@pytest.fixture
def tmp_docs_dir(tmp_path: Path) -> Path:
    """Create a temporary docs/roblox-api directory with sample files."""
    docs_dir = tmp_path / "docs" / "roblox-api"
    docs_dir.mkdir(parents=True)
    return docs_dir


@pytest.fixture
def populated_docs_dir(tmp_docs_dir: Path) -> Path:
    """docs/roblox-api with sample markdown files."""
    (tmp_docs_dir / "DataStoreService.md").write_text(
        "# DataStoreService\n\nGetDataStore(name: string): DataStore\n",
        encoding="utf-8",
    )
    (tmp_docs_dir / "Players.md").write_text(
        "# Players\n\nLocalPlayer: Player\nGetPlayers(): {Player}\n",
        encoding="utf-8",
    )
    (tmp_docs_dir / "Workspace.md").write_text(
        "# Workspace\n\nFindFirstChild(name: string): Instance?\n",
        encoding="utf-8",
    )
    return tmp_docs_dir


@pytest.fixture
def sample_system_prompt(tmp_path: Path) -> Path:
    """Create a sample system prompt file."""
    prompt_dir = tmp_path / "prompts"
    prompt_dir.mkdir()
    prompt_file = prompt_dir / "luau-system-prompt.md"
    prompt_file.write_text(
        "You are an expert Roblox Luau developer. Write clean, typed Luau code.",
        encoding="utf-8",
    )
    return prompt_file


@pytest.fixture
def meshy_task_pending() -> dict:
    """Sample Meshy API pending task response."""
    return {
        "id": "task-abc123",
        "status": "PENDING",
        "progress": 0,
        "model_urls": {},
    }


@pytest.fixture
def meshy_task_succeeded() -> dict:
    """Sample Meshy API succeeded task response."""
    return {
        "id": "task-abc123",
        "status": "SUCCEEDED",
        "progress": 100,
        "model_urls": {
            "fbx": "https://assets.meshy.ai/models/output.fbx",
            "glb": "https://assets.meshy.ai/models/output.glb",
        },
    }


@pytest.fixture
def meshy_task_failed() -> dict:
    """Sample Meshy API failed task response."""
    return {
        "id": "task-abc123",
        "status": "FAILED",
        "progress": 10,
        "model_urls": {},
        "task_error": {"message": "Generation failed due to content policy."},
    }
