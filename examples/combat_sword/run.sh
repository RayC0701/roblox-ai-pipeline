#!/usr/bin/env bash
# Run the combat sword example through the full pipeline.
#
# Usage:
#   ./examples/combat_sword/run.sh [--dry-run]

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

exec "$PROJECT_ROOT/scripts/pipeline.sh" \
    --prompt "Low-poly medieval broadsword with leather-wrapped handle, cartoon style" \
    --name "Medieval Sword" \
    --spec "$SCRIPT_DIR/spec.md" \
    --output "$PROJECT_ROOT/src/server/CombatSword.server.luau" \
    --art-style cartoon \
    --asset-type Model \
    "$@"
