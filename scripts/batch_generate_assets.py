#!/usr/bin/env python3
"""Batch 3D asset generation from YAML prompt files.

Loads asset prompts from a YAML file and generates each one via Meshy.ai.
Skips assets that already exist on disk (idempotent).

Usage:
    python scripts/batch_generate_assets.py assets/prompts/environment.yaml assets/models/
    python scripts/batch_generate_assets.py assets/prompts/weapons.yaml assets/models/ --preview-only
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import click
import yaml
from dotenv import load_dotenv

load_dotenv()

# Import generation functions from the single-asset script
sys.path.insert(0, str(Path(__file__).resolve().parent))
from generate_3d_asset import (
    create_preview_task,
    create_refine_task,
    download_model,
    get_api_key,
    poll_task,
)

RATE_LIMIT_DELAY = 5  # seconds between asset generations


def load_asset_prompts(yaml_path: Path) -> list[dict]:
    """Load asset prompts from a YAML file.

    Args:
        yaml_path: Path to the YAML file.

    Returns:
        List of asset dicts with name, prompt, and style keys.

    Raises:
        click.ClickException: If the file is invalid.
    """
    if not yaml_path.exists():
        raise click.ClickException(f"YAML file not found: {yaml_path}")

    try:
        data = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        raise click.ClickException(f"Invalid YAML: {e}")

    assets = data.get("assets", [])
    if not assets:
        raise click.ClickException(f"No assets found in {yaml_path}")

    return assets


@click.command()
@click.argument("yaml_file", type=click.Path(exists=True))
@click.argument("output_dir", type=click.Path())
@click.option("--preview-only", is_flag=True, help="Skip refine step for all assets.")
@click.option("--art-style-override", type=click.Choice(["cartoon", "realistic", "low-poly"], case_sensitive=False), default=None, help="Override art style for all assets.")
def main(
    yaml_file: str,
    output_dir: str,
    preview_only: bool,
    art_style_override: str | None,
) -> None:
    """Batch generate 3D assets from a YAML prompt file."""
    api_key = get_api_key()
    assets = load_asset_prompts(Path(yaml_file))
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    total = len(assets)
    succeeded = 0
    skipped = 0
    failed = 0

    click.echo(f"Loaded {total} assets from {yaml_file}")
    click.echo(f"Output directory: {out_dir}")
    click.echo(f"Mode: {'preview only' if preview_only else 'preview + refine'}")
    click.echo()

    for i, asset in enumerate(assets, 1):
        name = asset.get("name", f"asset_{i}")
        prompt = asset.get("prompt", "")
        style = art_style_override or asset.get("style", "cartoon")

        if not prompt:
            click.echo(f"[{i}/{total}] Skipping {name}: no prompt defined")
            skipped += 1
            continue

        output_path = out_dir / f"{name}.fbx"

        if output_path.exists():
            click.echo(f"[{i}/{total}] Skipping {name}: already exists at {output_path}")
            skipped += 1
            continue

        click.echo(f"[{i}/{total}] Generating: {name}")
        click.echo(f"  Prompt: {prompt}")
        click.echo(f"  Style: {style}")

        try:
            # Preview
            preview_id = create_preview_task(api_key, prompt, style)
            preview_status = poll_task(api_key, preview_id, label=f"  Preview ({name})")

            if preview_only:
                model_urls = preview_status.get("model_urls", {})
                fbx_url = model_urls.get("fbx") or model_urls.get("glb") or model_urls.get("obj")
                if not fbx_url:
                    click.echo(f"  Error: no model URL in preview result")
                    failed += 1
                    continue
                download_model(fbx_url, output_path)
            else:
                # Refine
                refine_id = create_refine_task(api_key, preview_id)
                refine_status = poll_task(api_key, refine_id, label=f"  Refine ({name})")

                model_urls = refine_status.get("model_urls", {})
                fbx_url = model_urls.get("fbx") or model_urls.get("glb") or model_urls.get("obj")
                if not fbx_url:
                    click.echo(f"  Error: no model URL in refine result")
                    failed += 1
                    continue
                download_model(fbx_url, output_path)

            succeeded += 1
            click.echo(f"  Saved: {output_path}")

        except click.ClickException as e:
            click.echo(f"  Failed: {e.message}")
            failed += 1

        # Rate limit between assets
        if i < total:
            click.echo(f"  Waiting {RATE_LIMIT_DELAY}s before next asset...")
            time.sleep(RATE_LIMIT_DELAY)

    click.echo()
    click.echo(f"Batch complete: {succeeded} succeeded, {skipped} skipped, {failed} failed")


if __name__ == "__main__":
    main()
