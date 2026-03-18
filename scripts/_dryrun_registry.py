#!/usr/bin/env python3
"""Helper for pipeline.sh --dry-run: inject a placeholder registry entry.

This avoids shell-injection risks from interpolating variables into a
Python heredoc.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description="Inject dry-run registry entry")
    parser.add_argument("--registry", required=True, help="Path to asset-registry.json")
    parser.add_argument("--key", required=True, help="Registry key (UPPER_SNAKE_CASE)")
    parser.add_argument("--asset-name", required=True, help="Display name of the asset")
    parser.add_argument("--asset-type", required=True, help="Roblox asset type")
    parser.add_argument("--model-file", required=True, help="Source model file path")
    args = parser.parse_args()

    reg_path = Path(args.registry)
    reg: dict = {}
    if reg_path.exists():
        reg = json.loads(reg_path.read_text(encoding="utf-8"))

    reg[args.key] = {
        "assetId": "000000000",
        "displayName": args.asset_name,
        "assetType": args.asset_type,
        "sourceFile": args.model_file,
        "uploadedAt": "1970-01-01T00:00:00+00:00",
    }

    reg_path.parent.mkdir(parents=True, exist_ok=True)
    reg_path.write_text(json.dumps(reg, indent=2), encoding="utf-8")
    print(f"  [DRY RUN] Registry updated with placeholder ID 000000000")


if __name__ == "__main__":
    main()
