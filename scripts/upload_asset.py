#!/usr/bin/env python3
"""Upload 3D assets to Roblox via the Open Cloud API.

Usage:
    python scripts/upload_asset.py assets/models/sword.fbx "Medieval Sword"
    python scripts/upload_asset.py assets/models/tree.fbx "Oak Tree" --asset-type Model
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import click
import requests
from dotenv import load_dotenv

load_dotenv()

ROBLOX_ASSETS_URL = "https://apis.roblox.com/assets/v1/assets"


def get_roblox_config() -> tuple[str, str]:
    """Get Roblox API key and creator ID from environment.

    Returns:
        Tuple of (api_key, creator_id).

    Raises:
        click.ClickException: If either value is missing.
    """
    api_key = os.environ.get("ROBLOX_API_KEY", "")
    creator_id = os.environ.get("ROBLOX_CREATOR_ID", "")

    if not api_key:
        raise click.ClickException(
            "ROBLOX_API_KEY not set. Add it to your .env file or environment."
        )
    if not creator_id:
        raise click.ClickException(
            "ROBLOX_CREATOR_ID not set. Add it to your .env file or environment."
        )

    return api_key, creator_id


def upload_asset(
    file_path: Path,
    asset_name: str,
    asset_type: str,
    api_key: str,
    creator_id: str,
) -> dict:
    """Upload a 3D asset to Roblox via Open Cloud API.

    Args:
        file_path: Path to the asset file (.fbx, .obj, etc.).
        asset_name: Display name for the asset in Roblox.
        asset_type: Roblox asset type (Model, Decal, Audio, etc.).
        api_key: Roblox Open Cloud API key.
        creator_id: Roblox user or group ID.

    Returns:
        API response as a dict.

    Raises:
        click.ClickException: On upload failure.
    """
    if not file_path.exists():
        raise click.ClickException(f"File not found: {file_path}")

    request_body = json.dumps({
        "assetType": asset_type,
        "displayName": asset_name,
        "description": "AI-generated asset",
        "creationContext": {
            "creator": {
                "userId": creator_id,
            }
        },
    })

    try:
        with open(file_path, "rb") as f:
            resp = requests.post(
                ROBLOX_ASSETS_URL,
                headers={"x-api-key": api_key},
                data={"request": request_body},
                files={
                    "fileContent": (file_path.name, f, "application/octet-stream")
                },
            )
    except requests.RequestException as e:
        raise click.ClickException(f"Upload request failed: {e}")

    if resp.status_code >= 400:
        raise click.ClickException(
            f"Upload failed ({resp.status_code}): {resp.text}"
        )

    return resp.json()


@click.command()
@click.argument("file_path", type=click.Path(exists=True))
@click.argument("asset_name")
@click.option("--asset-type", default="Model", show_default=True, help="Roblox asset type.")
def main(file_path: str, asset_name: str, asset_type: str) -> None:
    """Upload a 3D asset to Roblox via Open Cloud API."""
    api_key, creator_id = get_roblox_config()
    path = Path(file_path)

    click.echo(f"Uploading {path.name} as '{asset_name}' ({asset_type})...")

    result = upload_asset(path, asset_name, asset_type, api_key, creator_id)

    click.echo("Upload successful!")
    click.echo(f"Response: {json.dumps(result, indent=2)}")


if __name__ == "__main__":
    main()
