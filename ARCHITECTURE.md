# Roblox AI Pipeline Architecture

> End-to-end strategy for AI-assisted Roblox game development: from Luau code generation to 3D asset creation.

---

## Table of Contents

1. [Overview](#overview)
2. [Pipeline Components](#pipeline-components)
3. [Component 1: Claude Project for Luau Code Generation](#component-1-claude-project-for-luau-code-generation)
4. [Component 2: CustomGPT for Luau Code Generation (Alternative)](#component-2-customgpt-for-luau-code-generation-alternative)
5. [Component 3: AI 3D Asset Generation](#component-3-ai-3d-asset-generation)
6. [Component 4: Asset-to-Roblox Import Pipeline](#component-4-asset-to-roblox-import-pipeline)
7. [Component 5: CI/CD & Automation](#component-5-cicd--automation)
8. [Prompt Engineering Strategy](#prompt-engineering-strategy)
9. [Knowledge Base Curation](#knowledge-base-curation)
10. [Directory Structure](#directory-structure)
11. [Workflow Diagrams](#workflow-diagrams)
12. [Risk & Limitations](#risk--limitations)

---

## Overview

This pipeline eliminates two major bottlenecks in Roblox game development:

| Bottleneck | Traditional Approach | AI Pipeline Approach |
|---|---|---|
| **Scripting** | Manually write Luau from scratch | Claude/CustomGPT generates production-ready Luau from natural language specs |
| **3D Modeling** | Manual modeling in Blender/Maya | AI generators (UGCraft.ai, Meshy, Tripo3D) produce game-ready meshes from text/image prompts |

### High-Level Flow

```
[Game Design Doc] ──> [AI Code Gen] ──> [Luau Scripts] ──> [Roblox Studio]
                                                                  ^
[Art Direction]   ──> [AI 3D Gen]  ──> [.fbx/.obj]   ──────────--|
```

---

## Pipeline Components

```
┌─────────────────────────────────────────────────────────────┐
│                    ROBLOX AI PIPELINE                        │
│                                                             │
│  ┌──────────────┐   ┌──────────────┐   ┌────────────────┐  │
│  │ Knowledge     │   │ AI Code Gen  │   │ AI 3D Asset    │  │
│  │ Base          │──>│ (Claude /    │   │ Gen (UGCraft / │  │
│  │ (Roblox API   │   │  CustomGPT)  │   │  Meshy / Tripo)│  │
│  │  Docs + Luau) │   └──────┬───────┘   └───────┬────────┘  │
│  └──────────────┘          │                    │           │
│                            v                    v           │
│                   ┌──────────────────────────────────┐      │
│                   │       Roblox Studio Integration   │      │
│                   │  (Rojo sync / manual import)      │      │
│                   └──────────────────────────────────┘      │
└─────────────────────────────────────────────────────────────┘
```

---

## Component 1: Claude Project for Luau Code Generation

### Why Claude

- Large context window (200k tokens) allows uploading entire API reference sections as project knowledge
- Claude Projects support persistent uploaded files that inform every conversation
- Superior at following complex system prompts and coding conventions
- Claude API enables programmatic integration into automation scripts

### Setup: Claude Project (claude.ai)

#### Step 1: Create the Project

1. Go to **claude.ai** > **Projects** > **Create Project**
2. Name: `Roblox Luau Generator`
3. Set the project instructions (system prompt) — see [Prompt Engineering Strategy](#prompt-engineering-strategy)

#### Step 2: Upload Knowledge Base Files

Upload these documents to the project's knowledge base:

| File | Source | Purpose |
|---|---|---|
| `roblox-api-reference.md` | Scraped from [create.roblox.com/docs](https://create.roblox.com/docs) | Core API: Instance, Workspace, Players, etc. |
| `luau-language-reference.md` | From [luau-lang.org/reference](https://luau-lang.org) | Luau syntax, types, standard library |
| `roblox-services-reference.md` | Scraped from API docs | DataStoreService, ReplicatedStorage, TweenService, etc. |
| `luau-style-guide.md` | Custom or from Roblox community | Naming conventions, patterns, anti-patterns |
| `game-design-doc.md` | Your own | Game-specific mechanics, entity names, config |
| `existing-codebase-patterns.md` | Extracted from your repo | Patterns the AI should follow for consistency |

#### Step 3: Scraping the Docs

Use a scraping script to pull Roblox API docs into markdown:

```bash
# docs/scrape-roblox-docs.sh
# Scrapes key Roblox API pages into markdown for Claude Project upload

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
  # Use a tool like trafilatura, markdownify, or jina reader
  curl -s "https://r.jina.ai/$url" > "docs/roblox-api/$filename"
done
```

Alternatively, download the **Roblox API dump** (machine-readable JSON):
```bash
curl -s "https://raw.githubusercontent.com/MaximumADHD/Roblox-Client-Tracker/roblox/Full-API-Dump.json" \
  > docs/roblox-api/full-api-dump.json
```

#### Step 4: API-Driven Usage (Programmatic)

For automation, use the Claude API directly:

```python
# scripts/generate_luau.py
import anthropic
import json
from pathlib import Path

client = anthropic.Anthropic()  # Uses ANTHROPIC_API_KEY env var

# Load knowledge base context
knowledge_files = list(Path("docs/roblox-api").glob("*.md"))
knowledge_context = ""
for f in knowledge_files:
    knowledge_context += f"\n\n--- {f.name} ---\n{f.read_text()}"

SYSTEM_PROMPT = Path("prompts/luau-system-prompt.md").read_text()

def generate_luau(task_description: str) -> str:
    """Generate Luau code from a natural language task description."""
    message = client.messages.create(
        model="claude-sonnet-4-6",  # or claude-opus-4-6 for complex tasks
        max_tokens=8192,
        system=SYSTEM_PROMPT + "\n\n# Reference Documentation\n" + knowledge_context,
        messages=[
            {"role": "user", "content": task_description}
        ]
    )
    return message.content[0].text

if __name__ == "__main__":
    import sys
    task = sys.argv[1] if len(sys.argv) > 1 else "Create a basic coin collection system"
    code = generate_luau(task)
    print(code)
```

---

## Component 2: CustomGPT for Luau Code Generation (Alternative)

### Setup: OpenAI CustomGPT

Use this as a secondary/alternative generator or for team members who prefer ChatGPT.

#### Step 1: Create the GPT

1. Go to **chatgpt.com** > **Explore GPTs** > **Create**
2. Name: `Roblox Luau Coder`
3. Description: `Generates production-ready Roblox Luau code from natural language descriptions`

#### Step 2: Configure Instructions

Paste your system prompt (same core prompt as Claude, adapted for GPT — see [Prompt Engineering Strategy](#prompt-engineering-strategy)).

#### Step 3: Upload Knowledge Files

Upload the same scraped documentation files listed in Component 1. GPT supports:
- Up to 20 files
- PDF, TXT, MD, JSON, CSV formats
- Files are indexed via retrieval (RAG)

#### Step 4: API Usage (OpenAI Assistants API)

```python
# scripts/generate_luau_openai.py
from openai import OpenAI
from pathlib import Path

client = OpenAI()  # Uses OPENAI_API_KEY env var

# Create assistant once, reuse the ID
def create_assistant():
    # Upload knowledge files
    file_ids = []
    for f in Path("docs/roblox-api").glob("*.md"):
        uploaded = client.files.create(file=open(f, "rb"), purpose="assistants")
        file_ids.append(uploaded.id)

    assistant = client.beta.assistants.create(
        name="Roblox Luau Coder",
        instructions=Path("prompts/luau-system-prompt.md").read_text(),
        model="gpt-4o",
        tools=[{"type": "file_search"}],
        tool_resources={"file_search": {"vector_stores": [
            {"file_ids": file_ids}
        ]}}
    )
    return assistant.id

def generate_luau(assistant_id: str, task: str) -> str:
    thread = client.beta.threads.create()
    client.beta.threads.messages.create(
        thread_id=thread.id, role="user", content=task
    )
    run = client.beta.threads.runs.create_and_poll(
        thread_id=thread.id, assistant_id=assistant_id
    )
    messages = client.beta.threads.messages.list(thread_id=thread.id)
    return messages.data[0].content[0].text.value
```

### Claude vs CustomGPT: When to Use Which

| Scenario | Recommended | Reason |
|---|---|---|
| Complex multi-script systems | Claude | Larger context window, better at multi-file coherence |
| Quick single-script generation | Either | Both handle isolated tasks well |
| Automated CI pipeline | Claude API | More predictable structured output |
| Team exploration / chat | CustomGPT | Familiar ChatGPT UI, easy sharing |
| Type-safe Luau with generics | Claude | Stronger at Luau type annotations |

---

## Component 3: AI 3D Asset Generation

### Tool Comparison

| Tool | Input | Output | Best For | Pricing |
|---|---|---|---|---|
| **UGCraft.ai** | Text/Image | .fbx, .obj (Roblox-optimized) | UGC items, avatars, accessories | Freemium |
| **Meshy.ai** | Text/Image | .fbx, .obj, .glb | Environment props, detailed meshes | Freemium / $20/mo |
| **Tripo3D** | Text/Image | .fbx, .obj, .glb | Characters, organic shapes | Freemium |
| **Luma Genie** | Text | .glb, .obj | Stylized/artistic assets | API access |
| **Rodin (Hyper3D)** | Text/Image | .fbx, .glb | High-detail game assets | API access |

### UGCraft.ai Pipeline (Primary)

UGCraft.ai is purpose-built for Roblox assets, making it the primary choice.

#### Workflow

```
[Text Prompt / Reference Image]
        │
        v
  ┌─────────────┐
  │ UGCraft.ai   │
  │ Generation   │
  └──────┬──────┘
         │
         v
  ┌─────────────┐     ┌──────────────┐
  │ Download     │────>│ Post-Process  │
  │ .fbx / .obj │     │ (if needed)   │
  └─────────────┘     └──────┬───────┘
                             │
                             v
                    ┌──────────────┐
                    │ Import to     │
                    │ Roblox Studio │
                    └──────────────┘
```

#### Asset Generation Prompts (Examples)

```yaml
# assets/prompts/environment.yaml
assets:
  - name: "medieval_torch"
    prompt: "Low-poly medieval wall torch with flame, game-ready, Roblox style, under 5000 tris"
    style: "stylized"

  - name: "treasure_chest"
    prompt: "Cartoon treasure chest, open lid, gold coins visible, Roblox-compatible, low-poly"
    style: "stylized"

  - name: "sci_fi_door"
    prompt: "Futuristic sliding door, sci-fi, metallic, Roblox game asset, clean geometry"
    style: "stylized"
```

### Meshy.ai Pipeline (Secondary)

For assets requiring more geometric detail or when UGCraft doesn't support the style.

#### API Integration

```python
# scripts/generate_3d_asset.py
import requests
import time
from pathlib import Path

MESHY_API_KEY = "your_meshy_api_key"
BASE_URL = "https://api.meshy.ai/v2"

def generate_asset(prompt: str, output_path: str, art_style: str = "cartoon"):
    """Generate a 3D asset from a text prompt using Meshy.ai."""
    # Step 1: Create generation task
    resp = requests.post(
        f"{BASE_URL}/text-to-3d",
        headers={"Authorization": f"Bearer {MESHY_API_KEY}"},
        json={
            "mode": "preview",
            "prompt": prompt,
            "art_style": art_style,
            "negative_prompt": "high-poly, realistic, ugly, blurry"
        }
    )
    task_id = resp.json()["result"]

    # Step 2: Poll for completion
    while True:
        status = requests.get(
            f"{BASE_URL}/text-to-3d/{task_id}",
            headers={"Authorization": f"Bearer {MESHY_API_KEY}"}
        ).json()

        if status["status"] == "SUCCEEDED":
            model_url = status["model_urls"]["fbx"]
            break
        elif status["status"] == "FAILED":
            raise RuntimeError(f"Generation failed: {status}")
        time.sleep(10)

    # Step 3: Download the model
    model_data = requests.get(model_url).content
    Path(output_path).write_bytes(model_data)
    print(f"Asset saved to {output_path}")

if __name__ == "__main__":
    generate_asset(
        prompt="Cartoon medieval sword, game-ready, low poly, Roblox style",
        output_path="assets/models/medieval_sword.fbx"
    )
```

### Post-Processing Checklist

Before importing AI-generated assets into Roblox Studio:

- [ ] **Triangle count**: Keep under 10,000 tris (ideally under 5,000 for props)
- [ ] **Scale**: Roblox uses studs (1 stud ~= 0.28m). Resize in Blender if needed
- [ ] **Origin point**: Center the origin at the base of the model
- [ ] **UV mapping**: Verify UVs are clean (AI tools sometimes produce artifacts)
- [ ] **Texture resolution**: 512x512 or 1024x1024 max for game performance
- [ ] **File format**: .fbx is preferred for Roblox Studio import
- [ ] **Collision mesh**: Simplify or create a separate low-poly collision mesh

---

## Component 4: Asset-to-Roblox Import Pipeline

### Option A: Manual Studio Import

1. Open Roblox Studio
2. **File > Import 3D** (or drag .fbx into viewport)
3. Configure import settings (scale, collision)
4. Place in `Workspace` or `ReplicatedStorage`

### Option B: Rojo-Based Sync (Recommended for Teams)

[Rojo](https://rojo.space) syncs files from your filesystem into Roblox Studio.

```
project/
├── src/
│   ├── server/          # ServerScriptService
│   ├── client/          # StarterPlayerScripts
│   ├── shared/          # ReplicatedStorage
│   └── assets/          # Generated 3D assets (referenced via AssetId after upload)
├── default.project.json # Rojo project config
```

```json
// default.project.json
{
  "name": "AI-Pipeline-Game",
  "tree": {
    "$className": "DataModel",
    "ServerScriptService": {
      "$path": "src/server"
    },
    "StarterPlayer": {
      "StarterPlayerScripts": {
        "$path": "src/client"
      }
    },
    "ReplicatedStorage": {
      "$path": "src/shared"
    }
  }
}
```

### Option C: Roblox Open Cloud API (Asset Upload)

```python
# scripts/upload_asset.py
import requests

ROBLOX_API_KEY = "your_open_cloud_api_key"
CREATOR_ID = "your_user_or_group_id"

def upload_asset(file_path: str, asset_name: str, asset_type: str = "Model"):
    """Upload a 3D asset to Roblox via Open Cloud API."""
    with open(file_path, "rb") as f:
        resp = requests.post(
            "https://apis.roblox.com/assets/v1/assets",
            headers={
                "x-api-key": ROBLOX_API_KEY,
            },
            data={
                "request": f'{{"assetType":"{asset_type}","displayName":"{asset_name}","description":"AI-generated asset","creationContext":{{"creator":{{"userId":"{CREATOR_ID}"}}}}}}'
            },
            files={"fileContent": (file_path, f, "application/octet-stream")}
        )
    return resp.json()
```

---

## Component 5: CI/CD & Automation

### End-to-End Automation Script

```bash
#!/usr/bin/env bash
# scripts/pipeline.sh — Full AI pipeline run

set -euo pipefail

echo "=== ROBLOX AI PIPELINE ==="

# Step 1: Scrape/update docs (weekly)
echo "[1/4] Updating knowledge base..."
bash docs/scrape-roblox-docs.sh

# Step 2: Generate Luau code from task specs
echo "[2/4] Generating Luau scripts..."
for spec in specs/*.md; do
  name=$(basename "$spec" .md)
  python scripts/generate_luau.py "$(cat "$spec")" > "src/server/${name}.luau"
  echo "  Generated: src/server/${name}.luau"
done

# Step 3: Generate 3D assets from prompts
echo "[3/4] Generating 3D assets..."
python scripts/batch_generate_assets.py assets/prompts/environment.yaml assets/models/

# Step 4: Sync to Roblox Studio via Rojo
echo "[4/4] Syncing to Roblox Studio..."
rojo build -o game.rbxl

echo "=== PIPELINE COMPLETE ==="
```

### GitHub Actions Workflow

```yaml
# .github/workflows/ai-pipeline.yml
name: Roblox AI Pipeline

on:
  push:
    paths:
      - 'specs/**'
      - 'assets/prompts/**'
  workflow_dispatch:

jobs:
  generate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'

      - name: Install dependencies
        run: pip install anthropic openai requests pyyaml

      - name: Generate Luau scripts
        env:
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
        run: |
          for spec in specs/*.md; do
            name=$(basename "$spec" .md)
            python scripts/generate_luau.py "$(cat "$spec")" > "src/server/${name}.luau"
          done

      - name: Generate 3D assets
        env:
          MESHY_API_KEY: ${{ secrets.MESHY_API_KEY }}
        run: python scripts/batch_generate_assets.py assets/prompts/environment.yaml assets/models/

      - name: Upload artifacts
        uses: actions/upload-artifact@v4
        with:
          name: generated-assets
          path: |
            src/**/*.luau
            assets/models/**
```

---

## Prompt Engineering Strategy

### Core System Prompt for Luau Generation

Save this as `prompts/luau-system-prompt.md`:

```markdown
You are an expert Roblox game developer who writes production-ready Luau code.

## Rules

1. **Always use Luau** (not Lua 5.1). Use Luau-specific features:
   - Type annotations: `function foo(x: number): string`
   - String interpolation: `` `Hello {name}` ``
   - `if/then` expressions (ternary): `local x = if cond then a else b`
   - Generalized iteration: `for k, v in dict do`
   - `continue` keyword in loops
   - `type` aliases and `export type`
   - Optional types: `number?`
   - Type casting: `value :: Type`

2. **Follow Roblox conventions:**
   - Use PascalCase for classes and services
   - Use camelCase for variables and functions
   - Use UPPER_SNAKE_CASE for constants
   - Get services via `game:GetService("ServiceName")`
   - Never use `wait()` — use `task.wait()`, `task.spawn()`, `task.defer()`
   - Never use `Instance.new("Part", parent)` — set Parent last after configuring
   - Use `:Connect()` for events, clean up with `:Disconnect()`

3. **Structure:**
   - Server scripts go in ServerScriptService
   - Client scripts go in StarterPlayerScripts or StarterGui
   - Shared modules go in ReplicatedStorage
   - Always separate server/client concerns
   - Use RemoteEvents/RemoteFunctions for client-server communication

4. **Safety:**
   - Never trust the client — validate everything on the server
   - Sanitize DataStore keys
   - Rate-limit remote calls
   - Use pcall/xpcall for operations that can fail (DataStore, HTTP)

5. **Output format:**
   - Output ONLY the Luau code in a single fenced code block
   - Include a brief comment header describing the script's purpose
   - Include type annotations on function signatures
   - Do not include explanatory text outside the code block unless asked
```

### Prompt Templates for Common Tasks

```markdown
## Combat System
Generate a Roblox Luau server script for a combat system with:
- Melee attacks with hitbox detection using Touched events
- A cooldown system (1.5 second cooldown between attacks)
- Health reduction with damage numbers shown via BillboardGui
- Death handling with respawn after 5 seconds

## Inventory System
Generate a Roblox Luau module for an inventory system with:
- Add/remove/stack items
- Maximum inventory slots (configurable)
- DataStore persistence (save/load)
- Type definitions for Item and Inventory

## NPC Dialog
Generate a Roblox Luau client script for an NPC dialog system with:
- ProximityPrompt to start conversation
- Dialog UI with typewriter text effect
- Multiple dialog options (branching)
- Quest acceptance integration
```

---

## Knowledge Base Curation

### What to Include

| Category | Files | Update Frequency |
|---|---|---|
| **API Reference** | Core classes (Workspace, Players, Lighting, etc.) | Monthly |
| **Service Docs** | DataStoreService, MessagingService, MarketplaceService | Monthly |
| **Luau Language** | Type system, stdlib, string/table/math libraries | Quarterly |
| **Best Practices** | Security, performance, networking patterns | Quarterly |
| **Your Game Design** | GDD, entity specs, feature requirements | Per sprint |
| **Your Code Patterns** | Extracted patterns from existing codebase | Per sprint |

### Maintenance Script

```bash
# docs/update-knowledge-base.sh
#!/usr/bin/env bash
# Run monthly to keep knowledge base current

set -euo pipefail

echo "Updating Roblox API knowledge base..."

# Update API dump
curl -s "https://raw.githubusercontent.com/MaximumADHD/Roblox-Client-Tracker/roblox/Full-API-Dump.json" \
  > docs/roblox-api/full-api-dump.json

# Re-scrape key doc pages
bash docs/scrape-roblox-docs.sh

# Generate a summary of changes
echo "Knowledge base updated at $(date)"
echo "Files in docs/roblox-api/:"
ls -la docs/roblox-api/
```

---

## Directory Structure

```
roblox-ai-pipeline/
├── ARCHITECTURE.md              # This document
├── default.project.json         # Rojo project config
│
├── docs/
│   ├── roblox-api/              # Scraped API docs (knowledge base)
│   │   ├── full-api-dump.json
│   │   ├── Workspace.md
│   │   ├── Players.md
│   │   └── ...
│   ├── scrape-roblox-docs.sh
│   └── update-knowledge-base.sh
│
├── prompts/
│   ├── luau-system-prompt.md    # Core system prompt for code gen
│   └── templates/               # Task-specific prompt templates
│       ├── combat-system.md
│       ├── inventory-system.md
│       └── npc-dialog.md
│
├── specs/                       # Feature specs (input to code gen)
│   ├── coin-collection.md
│   └── leaderboard.md
│
├── scripts/
│   ├── generate_luau.py         # Claude API code generation
│   ├── generate_luau_openai.py  # OpenAI alternative
│   ├── generate_3d_asset.py     # Single asset generation (Meshy)
│   ├── batch_generate_assets.py # Batch asset generation
│   ├── upload_asset.py          # Roblox Open Cloud upload
│   └── pipeline.sh              # Full pipeline orchestrator
│
├── assets/
│   ├── prompts/                 # 3D generation prompts (YAML)
│   │   ├── environment.yaml
│   │   ├── characters.yaml
│   │   └── weapons.yaml
│   └── models/                  # Generated .fbx/.obj files
│       └── .gitkeep
│
├── src/                         # Generated + hand-written Luau
│   ├── server/                  # ServerScriptService
│   ├── client/                  # StarterPlayerScripts
│   └── shared/                  # ReplicatedStorage modules
│
└── .github/
    └── workflows/
        └── ai-pipeline.yml      # CI/CD automation
```

---

## Workflow Diagrams

### Developer Workflow

```
Developer writes feature spec (natural language)
        │
        v
  ┌─────────────────────────┐
  │  Run: python scripts/    │
  │  generate_luau.py        │
  │  "$(cat specs/feature.md)"│
  └───────────┬─────────────┘
              │
              v
  ┌─────────────────────────┐
  │  Review generated code   │ <── Human review is REQUIRED
  │  Edit/fix if needed      │     AI output is a draft, not final
  └───────────┬─────────────┘
              │
              v
  ┌─────────────────────────┐
  │  Place in src/server or  │
  │  src/client, commit      │
  └───────────┬─────────────┘
              │
              v
  ┌─────────────────────────┐
  │  rojo serve              │ <── Live sync to Studio
  │  (or rojo build)         │
  └───────────┬─────────────┘
              │
              v
  ┌─────────────────────────┐
  │  Test in Roblox Studio   │
  │  Iterate                 │
  └─────────────────────────┘
```

### Asset Generation Workflow

```
Artist/Designer writes asset prompt
        │
        v
  ┌────────────────────────────────┐
  │  UGCraft.ai (web) or           │
  │  Meshy API (scripted)          │
  │  Generate 3D model from prompt │
  └───────────┬────────────────────┘
              │
              v
  ┌────────────────────────────────┐
  │  Download .fbx/.obj            │
  │  Check: tri count, scale, UVs  │
  └───────────┬────────────────────┘
              │
              v
  ┌────────────────────────────────┐
  │  (Optional) Post-process in    │
  │  Blender: decimate, retopo,    │
  │  fix normals, bake textures    │
  └───────────┬────────────────────┘
              │
              v
  ┌────────────────────────────────┐
  │  Import to Roblox Studio       │
  │  OR upload via Open Cloud API  │
  └────────────────────────────────┘
```

---

## Risk & Limitations

| Risk | Mitigation |
|---|---|
| **AI generates incorrect Luau** | Always human-review. Run Selene linter. Test in Studio before shipping. |
| **API docs become stale** | Monthly refresh via scrape scripts. Pin to Roblox API version. |
| **3D assets have bad geometry** | Post-processing checklist. Blender cleanup pass for hero assets. |
| **AI hallucates non-existent APIs** | Knowledge base grounds the model. Validate against API dump JSON. |
| **Cost overruns** | Use Claude Sonnet for routine tasks, Opus only for complex generation. Batch asset gen. |
| **IP/copyright concerns** | AI-generated assets are typically owned by the creator. Review ToS of each tool. |
| **Rate limits** | Implement retry with exponential backoff. Queue large batch jobs. |
| **Vendor lock-in** | Dual-provider strategy (Claude + CustomGPT). Standard .fbx format for assets. |

### Validation Tooling

- **Selene**: Luau linter — catches deprecated APIs, style issues
  ```bash
  # Install: cargo install selene
  selene src/
  ```
- **Roblox LSP**: Type checking for Luau in VS Code
- **Rojo**: Catches structural issues during sync
- **Studio Playtesting**: Final validation — no substitute for running the game
