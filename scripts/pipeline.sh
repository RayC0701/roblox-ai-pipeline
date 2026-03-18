#!/usr/bin/env bash
# pipeline.sh — End-to-end Roblox AI Pipeline Orchestrator
#
# Runs the full flow:
#   1. Generate a 3D asset from a prompt (Meshy.ai)
#   2. Upload the asset to Roblox (Open Cloud)
#   3. Regenerate src/shared/AssetIds.luau from the registry
#   4. Generate Luau game code using those asset constants (Anthropic)
#
# Usage:
#   ./scripts/pipeline.sh \
#       --prompt "Low-poly medieval sword" \
#       --name "Medieval Sword" \
#       --spec prompts/templates/combat-system.md \
#       [--output src/server/CombatSystem.server.luau] \
#       [--art-style cartoon] \
#       [--preview-only] \
#       [--asset-type Model] \
#       [--dry-run]
#
# Environment variables required (or set in .env):
#   MESHY_API_KEY      — Meshy.ai API key
#   ROBLOX_API_KEY     — Roblox Open Cloud API key
#   ROBLOX_CREATOR_ID  — Roblox user/group ID
#   ANTHROPIC_API_KEY  — Anthropic API key
#
# --dry-run skips all real API calls (useful for CI).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Load .env if present
if [[ -f "$PROJECT_ROOT/.env" ]]; then
    set -a
    # shellcheck disable=SC1091
    source "$PROJECT_ROOT/.env"
    set +a
fi

# --------------------------------------------------------------------------
# Defaults
# --------------------------------------------------------------------------
PROMPT=""
ASSET_NAME=""
SPEC_FILE=""
OUTPUT_FILE=""
ART_STYLE="cartoon"
PREVIEW_ONLY=""
ASSET_TYPE="Model"
DRY_RUN=""

# --------------------------------------------------------------------------
# Parse arguments
# --------------------------------------------------------------------------
while [[ $# -gt 0 ]]; do
    case "$1" in
        --prompt)       PROMPT="$2";       shift 2 ;;
        --name)         ASSET_NAME="$2";   shift 2 ;;
        --spec)         SPEC_FILE="$2";    shift 2 ;;
        --output)       OUTPUT_FILE="$2";  shift 2 ;;
        --art-style)    ART_STYLE="$2";    shift 2 ;;
        --asset-type)   ASSET_TYPE="$2";   shift 2 ;;
        --preview-only) PREVIEW_ONLY="--preview-only"; shift ;;
        --dry-run)      DRY_RUN="1";       shift ;;
        *)
            echo "Unknown argument: $1" >&2
            exit 1
            ;;
    esac
done

# --------------------------------------------------------------------------
# Validate required args
# --------------------------------------------------------------------------
if [[ -z "$PROMPT" ]]; then
    echo "Error: --prompt is required." >&2
    echo "Usage: $0 --prompt <text> --name <name> --spec <file>" >&2
    exit 1
fi
if [[ -z "$ASSET_NAME" ]]; then
    echo "Error: --name is required." >&2
    exit 1
fi
if [[ -z "$SPEC_FILE" ]]; then
    echo "Error: --spec is required." >&2
    exit 1
fi

# Derive output path if not provided
if [[ -z "$OUTPUT_FILE" ]]; then
    SLUG="${ASSET_NAME// /_}"
    SLUG=$(echo "$SLUG" | tr '[:upper:]' '[:lower:]')
    OUTPUT_FILE="$PROJECT_ROOT/src/server/${SLUG}.server.luau"
fi

# Derive model output path from name
MODEL_SLUG="${ASSET_NAME// /_}"
MODEL_SLUG=$(echo "$MODEL_SLUG" | tr '[:upper:]' '[:lower:]')
MODEL_FILE="$PROJECT_ROOT/assets/models/${MODEL_SLUG}.fbx"

# --------------------------------------------------------------------------
# Banner
# --------------------------------------------------------------------------
echo "============================================================"
echo " Roblox AI Pipeline"
echo "============================================================"
echo " Prompt     : $PROMPT"
echo " Asset Name : $ASSET_NAME"
echo " Art Style  : $ART_STYLE"
echo " Spec File  : $SPEC_FILE"
echo " Output     : $OUTPUT_FILE"
if [[ -n "$DRY_RUN" ]]; then
    echo " Mode       : DRY RUN (no real API calls)"
fi
echo "============================================================"
echo ""

# --------------------------------------------------------------------------
# Step 1: Generate 3D Asset
# --------------------------------------------------------------------------
echo "► Step 1/4: Generating 3D asset..."

if [[ -n "$DRY_RUN" ]]; then
    echo "  [DRY RUN] Would call: python scripts/generate_3d_asset.py \"$PROMPT\" \\"
    echo "            --output \"$MODEL_FILE\" --art-style $ART_STYLE $PREVIEW_ONLY"
    mkdir -p "$(dirname "$MODEL_FILE")"
    echo "DRYRUN_PLACEHOLDER" > "$MODEL_FILE"
    echo "  [DRY RUN] Created placeholder: $MODEL_FILE"
else
    python3 "$SCRIPT_DIR/generate_3d_asset.py" "$PROMPT" \
        --output "$MODEL_FILE" \
        --art-style "$ART_STYLE" \
        ${PREVIEW_ONLY}
fi

echo ""

# --------------------------------------------------------------------------
# Step 1.5: Validate the 3D asset
# --------------------------------------------------------------------------
echo "► Validating 3D asset..."

if [[ -n "$DRY_RUN" ]]; then
    echo "  [DRY RUN] Would validate: $MODEL_FILE"
else
    if ! python3 "$SCRIPT_DIR/validate_fbx.py" "$MODEL_FILE"; then
        echo "ERROR: 3D asset validation failed for $MODEL_FILE" >&2
        exit 1
    fi
fi

echo ""

# --------------------------------------------------------------------------
# Step 2: Upload Asset to Roblox
# --------------------------------------------------------------------------
echo "► Step 2/4: Uploading asset to Roblox..."

if [[ -n "$DRY_RUN" ]]; then
    echo "  [DRY RUN] Would call: python scripts/upload_asset.py \"$MODEL_FILE\" \"$ASSET_NAME\" \\"
    echo "            --asset-type $ASSET_TYPE"

    # Inject a fake entry into the registry so step 3 has something to work with
    REGISTRY="$PROJECT_ROOT/assets/asset-registry.json"
    mkdir -p "$(dirname "$REGISTRY")"
    KEY=$(echo "$ASSET_NAME" | tr '[:lower:]' '[:upper:]')
    KEY="${KEY// /_}"
    KEY="${KEY//-/_}"
    python3 - <<PYEOF
import json, pathlib
reg_path = pathlib.Path("$REGISTRY")
reg = json.loads(reg_path.read_text()) if reg_path.exists() else {}
reg["$KEY"] = {
    "assetId": "000000000",
    "displayName": "$ASSET_NAME",
    "assetType": "$ASSET_TYPE",
    "sourceFile": "$MODEL_FILE",
    "uploadedAt": "1970-01-01T00:00:00+00:00",
}
reg_path.write_text(json.dumps(reg, indent=2))
print(f"  [DRY RUN] Registry updated with placeholder ID 000000000")
PYEOF
else
    python3 "$SCRIPT_DIR/upload_asset.py" "$MODEL_FILE" "$ASSET_NAME" \
        --asset-type "$ASSET_TYPE" \
        --update-luau
fi

echo ""

# --------------------------------------------------------------------------
# Step 3: Regenerate AssetIds.luau
# --------------------------------------------------------------------------
echo "► Step 3/4: Regenerating AssetIds.luau..."

python3 "$SCRIPT_DIR/upload_asset.py" --update-luau

echo ""

# --------------------------------------------------------------------------
# Step 4: Generate Luau Code
# --------------------------------------------------------------------------
echo "► Step 4/4: Generating Luau code..."

GENERATE_ARGS=("--spec" "$SPEC_FILE" "--output" "$OUTPUT_FILE")

if [[ -n "$DRY_RUN" ]]; then
    GENERATE_ARGS+=("--dry-run")
fi

python3 "$SCRIPT_DIR/generate_luau.py" "${GENERATE_ARGS[@]}"

echo ""

# --------------------------------------------------------------------------
# Summary
# --------------------------------------------------------------------------
echo "============================================================"
echo " Pipeline complete!"
echo "============================================================"
if [[ -z "$DRY_RUN" ]]; then
    echo " 3D Model  : $MODEL_FILE"
    echo " AssetIds  : $PROJECT_ROOT/src/shared/AssetIds.luau"
    echo " Luau Code : $OUTPUT_FILE"
fi
echo "============================================================"

# --------------------------------------------------------------------------
# Cost Summary
# --------------------------------------------------------------------------
COSTS_CSV="$PROJECT_ROOT/logs/costs.csv"
if [[ -f "$COSTS_CSV" ]]; then
    echo ""
    echo "💰 API Cost Summary:"
    echo "------------------------------------------------------------"
    # Parse CSV and sum costs (skip header)
    TOTAL_COST=$(tail -n +2 "$COSTS_CSV" | awk -F',' '{sum += $6} END {printf "%.6f", sum}')
    TOTAL_IN=$(tail -n +2 "$COSTS_CSV" | awk -F',' '{sum += $4} END {printf "%d", sum}')
    TOTAL_OUT=$(tail -n +2 "$COSTS_CSV" | awk -F',' '{sum += $5} END {printf "%d", sum}')
    RUN_COUNT=$(tail -n +2 "$COSTS_CSV" | wc -l | tr -d ' ')
    echo " Total API calls : $RUN_COUNT"
    echo " Tokens in       : $TOTAL_IN"
    echo " Tokens out      : $TOTAL_OUT"
    echo " Total cost      : \$$TOTAL_COST"
    echo "------------------------------------------------------------"
fi
