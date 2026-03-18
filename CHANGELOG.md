# Changelog

All notable changes to the Roblox AI Pipeline are documented here.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

---

## [v0.5] — 2026-03-18 — Phase 1: Foundation

### Added
- **Knowledge Base** (`docs/roblox-api/`): Scraped 8 Roblox API reference pages
  (Workspace, Players, DataStoreService, ReplicatedStorage, TweenService,
  RunService, UserInputService, HttpService) + Full API Dump JSON (~7MB).
  The knowledge base is now loaded automatically by `generate_luau.py`,
  grounding Claude in accurate Roblox API signatures.

- **Test Suite** (`tests/`): 76 unit and integration tests covering:
  - `test_generate_luau.py` — Knowledge base loading, markdown fence stripping,
    system prompt building, CLI dry-run, mocked Anthropic API calls (41 tests)
  - `test_generate_3d_asset.py` — Meshy API integration (mocked HTTP), retry
    logic, batch idempotency, file downloads (18 tests)
  - `test_validate_luau.py` — All validation rules, CLI modes, stdin input (17 tests)
  - `conftest.py` — Shared fixtures (tmp dirs, mock API responses)

- **`scripts/validate_luau.py`**: Lightweight Luau script validator with:
  - Deprecated global detection (`wait()`, `spawn()`, `delay()`)
  - Missing type annotation hints
  - Bare `pcall()` result checking
  - Accidental global variable detection
  - Direct `game.ServiceName` access warnings
  - String concatenation in loops performance hint
  - `--strict` mode (fail on warnings), `--quiet` mode, stdin support

- **`pytest.ini`**: Test configuration with `tests/` path, short tracebacks
- **`requirements.txt`**: Added `pytest`, `pytest-mock`, `responses`, `pytest-cov`

### Changed
- **`README.md`**: Added Testing section with commands, Luau Validation section
  with usage examples and issue descriptions

### Metrics (v0.5)
- Test coverage: **62%** (target: ≥60% ✅)
- Test runtime: **0.28s** (target: <5s ✅)
- Knowledge base docs: **8 markdown + 1 JSON** (target: ≥5 ✅)
- All tests: **76 passed, 0 failed** ✅

---

## [v0.4] — 2026-03-18 — Initial Technical Review

### Added
- `TECHNICAL_REVIEW.md`: Comprehensive technical review identifying gaps,
  priorities, and completion plan

---

## [v0.3] — Initial Development

### Added
- `scripts/generate_luau.py`: Claude-powered Luau code generation
- `scripts/generate_luau_openai.py`: OpenAI Assistants alternative
- `scripts/generate_3d_asset.py`: Meshy.ai 3D asset generation
- `scripts/batch_generate_assets.py`: Batch asset processing with idempotency
- `scripts/upload_asset.py`: Roblox Open Cloud upload (partial)
- `prompts/luau-system-prompt.md`: Expert Luau developer system prompt
- `prompts/templates/`: Combat, inventory, NPC dialog templates
- `docs/scrape-roblox-docs.sh`: Roblox API docs scraper
- `docs/update-knowledge-base.sh`: Knowledge base updater
- `ARCHITECTURE.md`: Full technical architecture documentation
- `.github/workflows/test.yml`: CI with syntax checking and dry-run tests
- `default.project.json`: Rojo project configuration
