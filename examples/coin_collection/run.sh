#!/usr/bin/env bash
# Run the coin collection example through the full pipeline.
#
# Usage:
#   ./examples/coin_collection/run.sh [--dry-run]
#
# Use the free Blender generator (no Meshy API key needed):
#   ./examples/coin_collection/run.sh --generator blender [--dry-run]

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

exec "$PROJECT_ROOT/scripts/pipeline.sh" \
    --prompt "Low-poly gold coin with embossed star, cartoon style, shiny metallic surface" \
    --name "Gold Coin" \
    --spec "$SCRIPT_DIR/spec.md" \
    --output "$PROJECT_ROOT/src/server/CoinCollection.server.luau" \
    --art-style cartoon \
    --asset-type Model \
    "$@"
