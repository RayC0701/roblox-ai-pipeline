# Roblox AI Pipeline

End-to-end AI-assisted Roblox game development: Luau code generation and 3D asset creation.

## Quick Start

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure API keys

```bash
cp .env.example .env
# Edit .env with your API keys
```

### 3. (Optional) Scrape Roblox docs for knowledge base

```bash
bash docs/scrape-roblox-docs.sh
```

## Components

### Component 1: Luau Code Generation (Claude)

Generate Luau scripts from natural language using Claude API.

```bash
# From a task description
python scripts/generate_luau.py "Create a coin collection system with scoring"

# From a spec file
python scripts/generate_luau.py --spec specs/feature.md

# Use a different model
python scripts/generate_luau.py "task" --model claude-opus-4-6

# Write output to a file
python scripts/generate_luau.py "task" --output src/server/feature.luau

# Dry run (see what would be sent without calling the API)
python scripts/generate_luau.py "task" --dry-run
```

### Component 2: Luau Code Generation (OpenAI)

Alternative generator using OpenAI Assistants API with file search.

```bash
# First, create the assistant (one-time setup)
python scripts/generate_luau_openai.py create-assistant

# Generate code
python scripts/generate_luau_openai.py generate "Create a leaderboard system"

# Generate from spec file
python scripts/generate_luau_openai.py generate --spec specs/feature.md

# Write output to file
python scripts/generate_luau_openai.py generate "task" --output src/server/feature.luau
```

### Component 3: 3D Asset Generation

Two generators are available for creating 3D assets:

#### Option A: Meshy.ai (default)

Cloud-based AI generation. Best for organic, detailed, or textured assets.

```bash
# Single asset
python scripts/generate_3d_asset.py "Low-poly cartoon sword" --output assets/models/sword.fbx

# Choose art style
python scripts/generate_3d_asset.py "Medieval castle tower" --art-style realistic

# Preview only (faster, lower quality)
python scripts/generate_3d_asset.py "Simple wooden crate" --preview-only

# Batch generation from YAML
python scripts/batch_generate_assets.py assets/prompts/environment.yaml assets/models/
python scripts/batch_generate_assets.py assets/prompts/weapons.yaml assets/models/ --preview-only
```

#### Option B: Blender (free, procedural)

Uses Claude AI to generate a Blender Python script, then executes it in Blender's
headless mode. Best for simple geometric assets (coins, crates, platforms, gems).

**Prerequisites:** Install Blender 4.0+:
```bash
# macOS
brew install --cask blender

# Linux (Ubuntu/Debian)
sudo apt install blender
# or: sudo snap install blender --classic

# Windows
winget install BlenderFoundation.Blender
```

```bash
# Single asset
python scripts/generate_blender_asset.py "Low-poly gold coin" --output assets/models/coin.fbx

# Choose art style
python scripts/generate_blender_asset.py "Cartoon tree" --art-style cartoon
```

#### When to use which?

| Feature | Meshy.ai | Blender (procedural) |
|---|---|---|
| Cost | Credits (~$0.10-$0.30/asset) | Free (only Claude API ~$0.01) |
| Quality | High (AI-generated textures) | Good for geometric shapes |
| Speed | 1-5 min (cloud processing) | 10-30 sec (local) |
| Best for | Characters, organic shapes, textured models | Coins, crates, platforms, gems, primitives |
| Requires | `MESHY_API_KEY` | Blender installed locally |

#### Using generators with the pipeline

Pass `--generator blender` or `--generator meshy` (default) to `pipeline.sh`:

```bash
# Use Blender for a simple coin asset
./scripts/pipeline.sh \
    --prompt "Low-poly gold coin" \
    --name "Gold Coin" \
    --spec specs/coin.md \
    --generator blender

# Use Meshy for a detailed character (default)
./scripts/pipeline.sh \
    --prompt "Low-poly medieval knight" \
    --name "Knight" \
    --spec specs/combat.md
```

### Upload to Roblox

Upload generated assets via Roblox Open Cloud API.

```bash
python scripts/upload_asset.py assets/models/sword.fbx "Medieval Sword"
python scripts/upload_asset.py assets/models/tree.fbx "Oak Tree" --asset-type Model
```

## Testing

### Run the test suite

```bash
# Install test dependencies (included in requirements.txt)
pip install -r requirements.txt

# Run all tests
pytest tests/ -v

# Run with coverage report
pytest tests/ --cov=scripts --cov-report=term

# Run specific test file
pytest tests/test_generate_luau.py -v
pytest tests/test_generate_3d_asset.py -v
pytest tests/test_validate_luau.py -v
```

**Target:** ≥60% coverage | **Runtime:** <5 seconds (all tests use mocks, no real API calls)

### Luau Validation

Validate generated Luau scripts for common issues before use:

```bash
# Validate a file
python scripts/validate_luau.py src/server/coins.luau

# Strict mode (fail on warnings too)
python scripts/validate_luau.py --strict src/server/coins.luau

# Quiet mode (errors only)
python scripts/validate_luau.py --quiet src/server/coins.luau

# From stdin
cat generated.luau | python scripts/validate_luau.py -
```

Detected issues include:
- Deprecated globals (`wait()`, `spawn()`, `delay()`) → use `task.*` equivalents
- Missing service access via `GetService()`
- Bare `pcall()` with ignored result
- String concatenation inside loops (performance)
- Accidental global variable declarations

## Rojo Integration

Sync generated Luau scripts to Roblox Studio:

```bash
# Install Rojo: https://rojo.space
rojo serve    # Live sync
rojo build -o game.rbxl  # Build place file
```

## Project Structure

```
roblox-ai-pipeline/
├── scripts/           # Pipeline scripts (Claude, OpenAI, Meshy)
├── prompts/           # System prompts and templates
├── assets/prompts/    # 3D asset generation prompts (YAML)
├── assets/models/     # Generated 3D models (.fbx)
├── docs/              # Knowledge base and scraping scripts
├── src/               # Luau source (server/client/shared)
└── default.project.json  # Rojo config
```

## API Keys Required

| Key | Service | Get it at |
|---|---|---|
| `ANTHROPIC_API_KEY` | Claude API | https://console.anthropic.com |
| `OPENAI_API_KEY` | OpenAI API | https://platform.openai.com |
| `MESHY_API_KEY` | Meshy.ai | https://app.meshy.ai |
| `ROBLOX_API_KEY` | Roblox Open Cloud | https://create.roblox.com/credentials |
