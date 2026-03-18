#!/usr/bin/env python3
"""Component 3: AI 3D asset generation via Meshy.ai API.

Generates 3D models from text prompts using the Meshy.ai v2 API.
Supports preview-only mode (fast) and full refine mode (higher quality).

Usage:
    python scripts/generate_3d_asset.py "Low-poly sword" --output assets/models/sword.fbx
    python scripts/generate_3d_asset.py "Cartoon tree" --art-style cartoon --preview-only
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import click
import requests
from dotenv import load_dotenv

load_dotenv()

BASE_URL = "https://api.meshy.ai/v2"
MAX_RETRIES = 3
POLL_INTERVAL = 10  # seconds


def get_api_key() -> str:
    """Get the Meshy API key from environment.

    Returns:
        The API key string.

    Raises:
        click.ClickException: If the key is not set.
    """
    key = os.environ.get("MESHY_API_KEY", "")
    if not key:
        raise click.ClickException(
            "MESHY_API_KEY not set. Add it to your .env file or environment."
        )
    return key


def get_headers(api_key: str) -> dict[str, str]:
    """Build authorization headers for the Meshy API.

    Args:
        api_key: The Meshy API key.

    Returns:
        Headers dict with Authorization.
    """
    return {"Authorization": f"Bearer {api_key}"}


def create_preview_task(
    api_key: str,
    prompt: str,
    art_style: str,
    negative_prompt: str = "high-poly, realistic, ugly, blurry",
) -> str:
    """Create a text-to-3D preview generation task.

    Args:
        api_key: Meshy API key.
        prompt: Text description of the 3D asset.
        art_style: Art style (cartoon, realistic, low-poly).
        negative_prompt: What to avoid in the generation.

    Returns:
        The task ID.

    Raises:
        click.ClickException: On API errors.
    """
    for attempt in range(MAX_RETRIES):
        resp = requests.post(
            f"{BASE_URL}/text-to-3d",
            headers=get_headers(api_key),
            json={
                "mode": "preview",
                "prompt": prompt,
                "art_style": art_style,
                "negative_prompt": negative_prompt,
            },
        )

        if resp.status_code == 429:
            wait_time = 2 ** (attempt + 1)
            click.echo(f"Rate limited. Retrying in {wait_time}s...")
            time.sleep(wait_time)
            continue

        if resp.status_code >= 400:
            raise click.ClickException(
                f"Failed to create preview task: {resp.status_code} {resp.text}"
            )

        return resp.json()["result"]

    raise click.ClickException("Max retries exceeded due to rate limiting.")


def create_refine_task(api_key: str, preview_task_id: str) -> str:
    """Create a refine task from a completed preview.

    Args:
        api_key: Meshy API key.
        preview_task_id: The completed preview task ID.

    Returns:
        The refine task ID.

    Raises:
        click.ClickException: On API errors.
    """
    for attempt in range(MAX_RETRIES):
        resp = requests.post(
            f"{BASE_URL}/text-to-3d",
            headers=get_headers(api_key),
            json={
                "mode": "refine",
                "preview_task_id": preview_task_id,
            },
        )

        if resp.status_code == 429:
            wait_time = 2 ** (attempt + 1)
            click.echo(f"Rate limited. Retrying in {wait_time}s...")
            time.sleep(wait_time)
            continue

        if resp.status_code >= 400:
            raise click.ClickException(
                f"Failed to create refine task: {resp.status_code} {resp.text}"
            )

        return resp.json()["result"]

    raise click.ClickException("Max retries exceeded due to rate limiting.")


def poll_task(api_key: str, task_id: str, label: str = "Task") -> dict:
    """Poll a Meshy task until it completes or fails.

    Args:
        api_key: Meshy API key.
        task_id: The task to poll.
        label: Display label for progress output.

    Returns:
        The completed task status dict.

    Raises:
        click.ClickException: If the task fails.
    """
    spinner = ["|", "/", "-", "\\"]
    tick = 0

    while True:
        resp = requests.get(
            f"{BASE_URL}/text-to-3d/{task_id}",
            headers=get_headers(api_key),
        )

        if resp.status_code >= 400:
            raise click.ClickException(
                f"Failed to poll task: {resp.status_code} {resp.text}"
            )

        status = resp.json()
        state = status.get("status", "UNKNOWN")
        progress = status.get("progress", 0)

        frame = spinner[tick % len(spinner)]
        click.echo(f"\r{frame} {label}: {state} ({progress}%)", nl=False)
        sys.stdout.flush()

        if state == "SUCCEEDED":
            click.echo(f"\r  {label}: SUCCEEDED (100%)  ")
            return status
        elif state == "FAILED":
            click.echo()
            error_msg = status.get("task_error", {}).get("message", "Unknown error")
            raise click.ClickException(f"{label} failed: {error_msg}")

        tick += 1
        time.sleep(POLL_INTERVAL)


def download_model(url: str, output_path: Path) -> None:
    """Download a model file from a URL.

    Args:
        url: The download URL.
        output_path: Where to save the file.
    """
    resp = requests.get(url, stream=True)
    resp.raise_for_status()

    output_path.parent.mkdir(parents=True, exist_ok=True)

    total = int(resp.headers.get("content-length", 0))
    downloaded = 0

    with open(output_path, "wb") as f:
        for chunk in resp.iter_content(chunk_size=8192):
            f.write(chunk)
            downloaded += len(chunk)
            if total > 0:
                pct = int(downloaded / total * 100)
                click.echo(f"\rDownloading: {pct}%", nl=False)

    click.echo(f"\rDownloaded: {output_path}      ")


@click.command()
@click.argument("prompt")
@click.option("--output", "-o", type=click.Path(), default="assets/models/output.fbx", show_default=True, help="Output file path.")
@click.option("--art-style", type=click.Choice(["cartoon", "realistic", "low-poly"], case_sensitive=False), default="cartoon", show_default=True, help="Art style for generation.")
@click.option("--preview-only", is_flag=True, help="Skip refine step (faster, lower quality).")
def main(prompt: str, output: str, art_style: str, preview_only: bool) -> None:
    """Generate a 3D asset from a text prompt using Meshy.ai."""
    api_key = get_api_key()

    click.echo(f"Prompt: {prompt}")
    click.echo(f"Style: {art_style}")
    click.echo(f"Mode: {'preview only' if preview_only else 'preview + refine'}")
    click.echo()

    # Step 1: Preview
    click.echo("Creating preview task...")
    preview_id = create_preview_task(api_key, prompt, art_style)
    click.echo(f"Preview task: {preview_id}")

    preview_status = poll_task(api_key, preview_id, label="Preview")

    if preview_only:
        model_urls = preview_status.get("model_urls", {})
        fbx_url = model_urls.get("fbx") or model_urls.get("glb") or model_urls.get("obj")
        if not fbx_url:
            raise click.ClickException("No model URL found in preview result.")
        download_model(fbx_url, Path(output))
        # Log cost for preview-only
        try:
            from scripts.cost_tracker import log_cost
            log_cost(
                script="generate_3d_asset",
                model="meshy-preview",
                tokens_in=0,
                tokens_out=0,
                cost_usd=0.0,
            )
        except Exception:
            pass
        return

    # Step 2: Refine
    click.echo("\nCreating refine task...")
    refine_id = create_refine_task(api_key, preview_id)
    click.echo(f"Refine task: {refine_id}")

    refine_status = poll_task(api_key, refine_id, label="Refine")

    model_urls = refine_status.get("model_urls", {})
    fbx_url = model_urls.get("fbx") or model_urls.get("glb") or model_urls.get("obj")
    if not fbx_url:
        raise click.ClickException("No model URL found in refine result.")

    download_model(fbx_url, Path(output))

    # Log cost for the Meshy API call (flat-rate, tokens not applicable)
    try:
        from scripts.cost_tracker import log_cost
        log_cost(
            script="generate_3d_asset",
            model="meshy-refine",
            tokens_in=0,
            tokens_out=0,
            cost_usd=0.0,  # Meshy uses credits, not per-token billing
        )
    except Exception:
        pass  # Cost tracking is best-effort

    click.echo("Done!")


if __name__ == "__main__":
    main()
