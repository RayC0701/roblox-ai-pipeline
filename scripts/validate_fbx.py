#!/usr/bin/env python3
"""Validate FBX files before uploading to Roblox.

Performs lightweight checks on FBX files:
  - File exists and is non-empty
  - File size is under the Roblox 20 MB limit
  - Binary/ASCII FBX header is valid
  - Estimates vertex count from binary FBX (best-effort heuristic)

Usage:
    python scripts/validate_fbx.py assets/models/sword.fbx
    python scripts/validate_fbx.py assets/models/sword.fbx --max-size-mb 10
"""

from __future__ import annotations

import struct
import sys
from pathlib import Path

import click

# Roblox limits
DEFAULT_MAX_SIZE_MB = 20
ROBLOX_MAX_VERTICES = 100_000  # Conservative estimate for mesh imports

# FBX magic bytes
FBX_BINARY_MAGIC = b"Kaydara FBX Binary  \x00"
FBX_ASCII_MAGIC = b"; FBX"


class FBXValidationError(Exception):
    """Raised when an FBX file fails validation."""


def validate_fbx_file(
    file_path: Path,
    max_size_mb: float = DEFAULT_MAX_SIZE_MB,
) -> dict:
    """Validate an FBX file for Roblox compatibility.

    Args:
        file_path: Path to the .fbx file.
        max_size_mb: Maximum allowed file size in megabytes.

    Returns:
        A dict with validation results:
            valid (bool), file_size (int), format (str),
            estimated_vertices (int|None), warnings (list[str])

    Raises:
        FBXValidationError: If a hard validation check fails.
    """
    result: dict = {
        "valid": True,
        "file_size": 0,
        "format": "unknown",
        "estimated_vertices": None,
        "warnings": [],
    }

    # --- Existence ---
    if not file_path.exists():
        raise FBXValidationError(f"File not found: {file_path}")

    if not file_path.is_file():
        raise FBXValidationError(f"Not a file: {file_path}")

    # --- Size checks ---
    file_size = file_path.stat().st_size
    result["file_size"] = file_size

    if file_size == 0:
        raise FBXValidationError(f"File is empty: {file_path}")

    max_bytes = int(max_size_mb * 1024 * 1024)
    if file_size > max_bytes:
        raise FBXValidationError(
            f"File too large: {file_size / (1024*1024):.1f} MB "
            f"(limit: {max_size_mb} MB)"
        )

    # --- Header check ---
    with open(file_path, "rb") as f:
        header = f.read(64)

    if header[:21] == FBX_BINARY_MAGIC:
        result["format"] = "binary"
        # Try to read FBX version from binary header (bytes 23-26, little-endian uint32)
        if len(header) >= 27:
            version = struct.unpack_from("<I", header, 23)[0]
            if version < 5000 or version > 10000:
                result["warnings"].append(
                    f"Unusual FBX version {version}; expected 7100-7700 for modern FBX"
                )
        # Best-effort vertex estimate from file size
        # Rough heuristic: binary FBX ~100-200 bytes per vertex on average
        estimated_verts = file_size // 150
        result["estimated_vertices"] = estimated_verts
        if estimated_verts > ROBLOX_MAX_VERTICES:
            result["warnings"].append(
                f"Estimated ~{estimated_verts:,} vertices (may exceed Roblox limits)"
            )
    elif header[:5] == FBX_ASCII_MAGIC or b"FBXHeaderExtension" in header:
        result["format"] = "ascii"
        # ASCII FBX is less common for production; warn about it
        result["warnings"].append(
            "ASCII FBX detected; binary FBX is preferred for Roblox"
        )
    else:
        # Not a recognizable FBX — could be a placeholder or corrupt file
        result["warnings"].append(
            "File does not start with a recognized FBX header; "
            "it may be corrupt or a placeholder"
        )

    return result


@click.command()
@click.argument("file_path", type=click.Path())
@click.option(
    "--max-size-mb",
    type=float,
    default=DEFAULT_MAX_SIZE_MB,
    show_default=True,
    help="Maximum allowed file size in MB.",
)
@click.option("--json", "as_json", is_flag=True, help="Output results as JSON.")
def main(file_path: str, max_size_mb: float, as_json: bool) -> None:
    """Validate an FBX file for Roblox compatibility."""
    import json

    path = Path(file_path)

    try:
        result = validate_fbx_file(path, max_size_mb)
    except FBXValidationError as e:
        if as_json:
            click.echo(json.dumps({"valid": False, "error": str(e)}))
        else:
            click.echo(f"✗ FAILED: {e}", err=True)
        sys.exit(1)

    if as_json:
        click.echo(json.dumps(result, indent=2))
    else:
        size_mb = result["file_size"] / (1024 * 1024)
        click.echo(f"File: {path}")
        click.echo(f"Size: {size_mb:.2f} MB")
        click.echo(f"Format: {result['format']}")
        if result["estimated_vertices"]:
            click.echo(f"Estimated vertices: ~{result['estimated_vertices']:,}")
        for w in result["warnings"]:
            click.echo(f"⚠ {w}")
        if result["valid"]:
            click.echo("✓ Validation passed")

    if not result["valid"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
