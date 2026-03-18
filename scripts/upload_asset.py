#!/usr/bin/env python3
"""Upload 3D assets to Roblox via the Open Cloud API.

The Roblox Assets API is asynchronous: an upload returns an Operation path
that must be polled until the asset finishes processing.  Once complete, the
asset ID is stored in ``assets/asset-registry.json`` and the shared Luau
constants file can be regenerated with ``--update-luau``.

Usage:
    python scripts/upload_asset.py assets/models/sword.fbx "Medieval Sword"
    python scripts/upload_asset.py assets/models/tree.fbx "Oak Tree" \\
        --asset-type Model --update-luau
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import click
import requests
from dotenv import load_dotenv

load_dotenv()

ROBLOX_ASSETS_URL = "https://apis.roblox.com/assets/v1/assets"
ROBLOX_OPERATIONS_URL = "https://apis.roblox.com/assets/v1"
POLL_INTERVAL = 5       # seconds between status checks
MAX_POLL_ATTEMPTS = 60  # 5 min total at 5s intervals

# Paths relative to the project root
PROJECT_ROOT = Path(__file__).parent.parent
ASSET_REGISTRY_PATH = PROJECT_ROOT / "assets" / "asset-registry.json"
LUAU_CONSTANTS_PATH = PROJECT_ROOT / "src" / "shared" / "AssetIds.luau"


# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Upload
# ---------------------------------------------------------------------------

UPLOAD_MAX_RETRIES = 3  # retry transient failures


def upload_asset(
    file_path: Path,
    asset_name: str,
    asset_type: str,
    api_key: str,
    creator_id: str,
) -> dict:
    """Upload a 3D asset to Roblox via Open Cloud API.

    Retries transient errors (429 / 5xx) with exponential backoff.

    Args:
        file_path: Path to the asset file (.fbx, .obj, etc.).
        asset_name: Display name for the asset in Roblox.
        asset_type: Roblox asset type (Model, Decal, Audio, etc.).
        api_key: Roblox Open Cloud API key.
        creator_id: Roblox user or group ID.

    Returns:
        API response as a dict (contains an ``path`` operation key).

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

    last_error: Exception | None = None
    for attempt in range(UPLOAD_MAX_RETRIES):
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
            last_error = e
            wait_time = 2 ** (attempt + 1)
            click.echo(f"Upload request failed ({e}). Retrying in {wait_time}s...")
            time.sleep(wait_time)
            continue

        if resp.status_code == 429 or resp.status_code >= 500:
            wait_time = 2 ** (attempt + 1)
            click.echo(
                f"Upload returned {resp.status_code}. Retrying in {wait_time}s..."
            )
            time.sleep(wait_time)
            continue

        if resp.status_code >= 400:
            raise click.ClickException(
                f"Upload failed ({resp.status_code}): {resp.text}"
            )

        return resp.json()

    if last_error:
        raise click.ClickException(f"Upload request failed after {UPLOAD_MAX_RETRIES} retries: {last_error}")
    raise click.ClickException(
        f"Upload failed after {UPLOAD_MAX_RETRIES} retries (last status: {resp.status_code})"
    )


# ---------------------------------------------------------------------------
# Status polling
# ---------------------------------------------------------------------------

def poll_operation(operation_path: str, api_key: str) -> dict:
    """Poll a Roblox long-running operation until it completes.

    Roblox uploads are asynchronous.  The initial upload response returns an
    operation path like ``"operations/abc123"``.  This function polls that
    path until the operation is ``done``.

    Args:
        operation_path: Relative operation path from the upload response,
            e.g. ``"operations/abc123"``.
        api_key: Roblox Open Cloud API key.

    Returns:
        The final operation response dict, which contains the asset ID under
        ``response.assetId``.

    Raises:
        click.ClickException: If polling fails or the operation errors out.
    """
    url = f"{ROBLOX_OPERATIONS_URL}/{operation_path}"
    spinner = ["|", "/", "-", "\\"]
    tick = 0

    for attempt in range(MAX_POLL_ATTEMPTS):
        try:
            resp = requests.get(url, headers={"x-api-key": api_key})
        except requests.RequestException as e:
            raise click.ClickException(f"Poll request failed: {e}")

        if resp.status_code >= 400:
            raise click.ClickException(
                f"Poll failed ({resp.status_code}): {resp.text}"
            )

        data = resp.json()

        done = data.get("done", False)
        frame = spinner[tick % len(spinner)]
        click.echo(f"\r{frame} Processing asset... (attempt {attempt + 1}/{MAX_POLL_ATTEMPTS})", nl=False)
        sys.stdout.flush()

        if done:
            click.echo("\r  Processing complete.                                   ")
            if "error" in data:
                err = data["error"]
                raise click.ClickException(
                    f"Asset processing failed: {err.get('message', err)}"
                )
            return data

        tick += 1
        time.sleep(POLL_INTERVAL)

    raise click.ClickException(
        f"Timed out waiting for asset to process after {MAX_POLL_ATTEMPTS} attempts."
    )


def extract_asset_id(operation_result: dict) -> str:
    """Extract the asset ID from a completed operation response.

    Args:
        operation_result: The completed operation dict from ``poll_operation``.

    Returns:
        Asset ID string.

    Raises:
        click.ClickException: If the asset ID cannot be found.
    """
    response = operation_result.get("response", {})
    asset_id = response.get("assetId")
    if not asset_id:
        raise click.ClickException(
            f"Could not find assetId in operation response: {operation_result}"
        )
    return str(asset_id)


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

def load_registry(registry_path: Path) -> dict:
    """Load the asset registry JSON file, returning an empty dict if missing.

    Args:
        registry_path: Path to asset-registry.json.

    Returns:
        Registry dict.
    """
    if registry_path.exists():
        with open(registry_path, encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_registry(registry: dict, registry_path: Path) -> None:
    """Save the asset registry to disk.

    Args:
        registry: Registry dict to persist.
        registry_path: Path to asset-registry.json.
    """
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    with open(registry_path, "w", encoding="utf-8") as f:
        json.dump(registry, f, indent=2)
    click.echo(f"Registry updated: {registry_path}")


def register_asset(
    asset_name: str,
    asset_id: str,
    asset_type: str,
    file_path: Path,
    registry_path: Path = ASSET_REGISTRY_PATH,
) -> dict:
    """Add or update an entry in the asset registry.

    Args:
        asset_name: Human-readable display name.
        asset_id: The Roblox asset ID.
        asset_type: Roblox asset type string.
        file_path: Source file path (stored for reference).
        registry_path: Path to asset-registry.json.

    Returns:
        The updated registry dict.
    """
    registry = load_registry(registry_path)

    # Use a slug derived from the display name as the key
    key = asset_name.upper().replace(" ", "_").replace("-", "_")
    registry[key] = {
        "assetId": asset_id,
        "displayName": asset_name,
        "assetType": asset_type,
        "sourceFile": str(file_path),
        "uploadedAt": _utc_now(),
    }

    save_registry(registry, registry_path)
    return registry


def _utc_now() -> str:
    """Return current UTC time as ISO 8601 string."""
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Luau constants generator
# ---------------------------------------------------------------------------

def generate_asset_ids_luau(
    registry: dict,
    output_path: Path = LUAU_CONSTANTS_PATH,
) -> None:
    """Generate a Luau module with AssetId constants from the registry.

    The generated file looks like::

        -- AUTO-GENERATED by scripts/upload_asset.py — do not edit manually.
        -- Re-generate with: python scripts/upload_asset.py --update-luau

        local AssetIds = {}

        AssetIds.MEDIEVAL_SWORD = 123456789
        AssetIds.OAK_TREE = 987654321

        return AssetIds

    Args:
        registry: The asset registry dict.
        output_path: Where to write the Luau file.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)

    lines = [
        "-- AUTO-GENERATED by scripts/upload_asset.py — do not edit manually.",
        "-- Re-generate with: python scripts/upload_asset.py --update-luau",
        "--",
        "-- AssetIds: constants for all uploaded Roblox assets.",
        "",
        "local AssetIds = {}",
        "",
    ]

    for key, entry in sorted(registry.items()):
        asset_id = entry.get("assetId", "0")
        display_name = entry.get("displayName", key)
        lines.append(f"-- {display_name}")
        lines.append(f"AssetIds.{key} = {asset_id}")
        lines.append("")

    lines.append("return AssetIds")
    lines.append("")

    content = "\n".join(lines)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(content)

    click.echo(f"AssetIds.luau updated: {output_path}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

@click.command()
@click.argument("file_path", type=click.Path(), required=False)
@click.argument("asset_name", required=False)
@click.option("--asset-type", default="Model", show_default=True, help="Roblox asset type.")
@click.option(
    "--no-poll",
    is_flag=True,
    help="Skip operation polling; return immediately after upload.",
)
@click.option(
    "--update-luau",
    is_flag=True,
    help="(Re)generate src/shared/AssetIds.luau from the registry (can be used alone).",
)
@click.option(
    "--registry",
    "registry_path",
    type=click.Path(),
    default=str(ASSET_REGISTRY_PATH),
    show_default=True,
    help="Path to asset-registry.json.",
)
def main(
    file_path: str | None,
    asset_name: str | None,
    asset_type: str,
    no_poll: bool,
    update_luau: bool,
    registry_path: str,
) -> None:
    """Upload a 3D asset to Roblox and track its ID.

    If --update-luau is passed without FILE_PATH/ASSET_NAME, only the Luau
    constants file is regenerated from the existing registry.
    """
    reg_path = Path(registry_path)

    # --update-luau only (no upload)
    if update_luau and not file_path:
        registry = load_registry(reg_path)
        if not registry:
            click.echo("Registry is empty — nothing to generate.", err=True)
            raise SystemExit(1)
        generate_asset_ids_luau(registry)
        return

    # Upload path requires both arguments
    if not file_path or not asset_name:
        raise click.UsageError(
            "FILE_PATH and ASSET_NAME are required when uploading an asset.\n"
            "Use --update-luau alone to regenerate AssetIds.luau."
        )

    api_key, creator_id = get_roblox_config()
    path = Path(file_path)

    click.echo(f"Uploading {path.name} as '{asset_name}' ({asset_type})...")

    result = upload_asset(path, asset_name, asset_type, api_key, creator_id)

    operation_path = result.get("path")
    if not operation_path:
        # Some older API versions return assetId directly
        asset_id = str(result.get("assetId", ""))
        if not asset_id:
            click.echo(f"Unexpected response: {json.dumps(result, indent=2)}")
            raise click.ClickException("Could not determine asset ID from response.")
    elif no_poll:
        click.echo("Upload submitted (polling skipped).")
        click.echo(f"Operation: {operation_path}")
        click.echo(f"Full response:\n{json.dumps(result, indent=2)}")
        return
    else:
        click.echo(f"Upload accepted. Operation: {operation_path}")
        click.echo("Waiting for Roblox to finish processing...")
        op_result = poll_operation(operation_path, api_key)
        asset_id = extract_asset_id(op_result)

    click.echo(f"Asset ID: {asset_id}")

    # Update registry
    registry = register_asset(asset_name, asset_id, asset_type, path, reg_path)

    if update_luau:
        generate_asset_ids_luau(registry)

    click.echo("Done!")


if __name__ == "__main__":
    main()
