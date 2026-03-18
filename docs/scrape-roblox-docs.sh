#!/usr/bin/env bash
# Scrapes key Roblox API pages into markdown for Claude Project upload

set -euo pipefail

URLS=(
  "https://create.roblox.com/docs/reference/engine/classes/Workspace"
  "https://create.roblox.com/docs/reference/engine/classes/Players"
  "https://create.roblox.com/docs/reference/engine/classes/DataStoreService"
  "https://create.roblox.com/docs/reference/engine/classes/ReplicatedStorage"
  "https://create.roblox.com/docs/reference/engine/classes/TweenService"
  "https://create.roblox.com/docs/reference/engine/classes/RunService"
  "https://create.roblox.com/docs/reference/engine/classes/UserInputService"
  "https://create.roblox.com/docs/reference/engine/classes/HttpService"
)

mkdir -p docs/roblox-api

for url in "${URLS[@]}"; do
  filename=$(echo "$url" | sed 's|.*/||').md
  echo "Scraping $url -> docs/roblox-api/$filename"
  curl -s "https://r.jina.ai/$url" > "docs/roblox-api/$filename"
  sleep 2  # Rate limit courtesy
done

echo "Done. Scraped ${#URLS[@]} pages."
