#!/usr/bin/env bash
# Run monthly to keep knowledge base current

set -euo pipefail

echo "Updating Roblox API knowledge base..."

mkdir -p docs/roblox-api

# Update API dump
curl -s "https://raw.githubusercontent.com/MaximumADHD/Roblox-Client-Tracker/roblox/Full-API-Dump.json" \
  > docs/roblox-api/full-api-dump.json

# Re-scrape key doc pages
bash docs/scrape-roblox-docs.sh

# Generate a summary of changes
echo "Knowledge base updated at $(date)"
echo "Files in docs/roblox-api/:"
ls -la docs/roblox-api/
