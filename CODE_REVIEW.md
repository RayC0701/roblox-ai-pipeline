# Expert Code Review: Roblox AI Asset Pipeline

**Reviewer**: Senior Roblox Software Engineer & Digital Asset Creator
**Date**: 2026-03-22
**Scope**: Full pipeline — scripts, tests, CI/CD, Luau output, Rojo config, asset prompts
**Test suite status**: 204/204 passing

---

## Executive Summary

This is a well-architected AI-driven pipeline for generating Roblox game assets (3D models + Luau scripts) using multiple AI backends (Anthropic Claude, OpenAI, Meshy.ai, Blender). The codebase demonstrates solid engineering fundamentals: proper secret management, retry logic, cost tracking, dry-run support, and a comprehensive test suite.

**Overall Rating: B+** — Production-viable with targeted fixes. The architecture is sound, but there are a handful of security, correctness, and robustness issues that should be addressed before shipping to a team.

---

## CRITICAL Issues (Must Fix)

### 1. Arbitrary Code Execution via Blender Script Generation
**File**: `scripts/generate_blender_asset.py:88-196`
**Severity**: HIGH

The pipeline asks Claude to generate a Python script, then executes it in Blender with no sandboxing:

```python
result = subprocess.run(
    [blender_path, "-b", "-P", script_path],  # line 176
    capture_output=True, text=True, timeout=120,
)
```

Claude-generated code runs with full filesystem and network access in Blender's Python environment. A hallucinated `import os; os.system("rm -rf /")` or `urllib.request.urlopen(...)` call would execute unchecked.

**Recommendation**:
- Run Blender in a containerized environment (Docker/Podman) with no network and a read-only filesystem except the output directory.
- At minimum, add a regex allowlist/blocklist to reject scripts containing `os.system`, `subprocess`, `shutil.rmtree`, `urllib`, `socket`, `eval`, `exec`, etc.
- Add `--python-use-system-env` flag awareness and document the risk.

### 2. Asset Registry Contains Hardcoded User Paths
**File**: `assets/asset-registry.json:6,13`

```json
"sourceFile": "/Users/andraia/.openclaw/workspace/projects/roblox-ai-pipeline/assets/models/test_sword.fbx"
```

This is a local macOS path checked into the repo. It will break for every other developer and leaks a username.

**Recommendation**: Store relative paths in the registry (`assets/models/test_sword.fbx`). Update `register_asset()` in `upload_asset.py:296` to use `file_path.relative_to(PROJECT_ROOT)`.

### 3. Registry Key Sanitization Is Insufficient for Luau Identifiers
**File**: `scripts/upload_asset.py:291` and `scripts/upload_asset.py:352`

```python
key = asset_name.upper().replace(" ", "_").replace("-", "_")
# ...
lines.append(f"AssetIds.{key} = {asset_id}")
```

An asset named `"123-sword"` produces `AssetIds.123_SWORD` — an invalid Luau identifier (starts with a digit). An asset named `"sword; print('pwned')"` produces a Luau injection. The `asset_id` is also interpolated without validation; a non-numeric ID would produce invalid Luau.

**Recommendation**:
```python
import re
key = asset_name.upper().replace(" ", "_").replace("-", "_")
key = re.sub(r'[^A-Z0-9_]', '', key)
if key and key[0].isdigit():
    key = f"ASSET_{key}"
# For asset ID:
lines.append(f"AssetIds.{key} = {int(asset_id)}")  # enforce numeric
```

---

## HIGH Issues (Should Fix)

### 4. `e.message` AttributeError in Batch Generator
**File**: `scripts/batch_generate_assets.py:205`

```python
except click.ClickException as e:
    click.echo(f"  Failed: {e.message}")
```

`click.ClickException` uses `.format_message()` not `.message` in newer Click versions. While Click 8.x still has `.message`, this is an implementation detail, not part of the public API. Use `e.format_message()` or `str(e)` for forward compatibility.

### 5. CI Pipeline: Selene Linter Failures Are Non-Blocking
**File**: `.github/workflows/validate.yml:42`

```yaml
selene src/ || echo "Selene found issues (non-blocking for now)"
```

Luau linting errors should block PRs. If the intent is to phase this in, use a separate status check marked as "informational" rather than silently swallowing errors in the main validation job.

### 6. No Python Linting in CI
**File**: `.github/workflows/validate.yml`

Only `py_compile` syntax checks are run. No `ruff`, `flake8`, `mypy`, or `black` formatting enforcement. For a pipeline that generates and executes code, static analysis is important.

**Recommendation**: Add at minimum `ruff check scripts/ tests/` to the CI pipeline.

### 7. FBX Vertex Count Estimation Is Too Rough for Roblox Limits
**File**: `scripts/validate_fbx.py:100-103`

The validator estimates vertices by dividing file size by 150 bytes/vertex. This heuristic can be off by 10x for textured models (where textures dominate file size) or dense mesh models.

For Roblox's 100K vertex import limit, this matters. The validator may either:
- Pass a 200K vertex model because its texture data inflates file size
- Warn about a 5K vertex model with large embedded textures

**Recommendation**: Use `struct.unpack` to parse the FBX node tree and read the actual `Vertices` array count from the binary FBX structure, or shell out to a lightweight FBX parser.

### 8. Meshy Cost Tracking Logs $0.00 For All Generations
**File**: `scripts/generate_3d_asset.py:264-298`

```python
log_cost("generate_3d_asset", "meshy-preview", 0, 0, cost_usd=0.0)
```

Every Meshy generation is logged with zero cost. The cost tracker has flat-rate pricing for Meshy (`meshy-preview: $0.10`, `meshy-refine: $0.50`) but it's never used because `cost_usd=0.0` overrides estimation.

**Recommendation**: Remove the explicit `cost_usd=0.0` override, or pass `cost_usd=None` and let `estimate_cost()` provide the flat rate.

---

## MEDIUM Issues (Nice to Fix)

### 9. Model Reference Hardcoded to Deprecated Version
**File**: `scripts/generate_blender_asset.py:37`

```python
DEFAULT_MODEL = "claude-sonnet-4-20250514"
```

This references a dated snapshot. The `generate_luau.py` correctly uses `"claude-sonnet-4-6"`. Be consistent across all scripts.

### 10. OpenAI Assistant Lifecycle Not Managed
**File**: `scripts/generate_luau_openai.py`

The `create-assistant` command creates an assistant and stores its ID in `.assistant_id`, but there's no `delete-assistant` command. Orphaned assistants accumulate on the OpenAI account. Also, no mechanism to detect when the assistant's model or instructions are stale.

### 11. Duplicate `strip_markdown_fences` Implementations
**Files**: `scripts/utils.py:9-20`, `scripts/generate_blender_asset.py:145-161`

Two separate implementations of fence-stripping exist. The one in `generate_blender_asset.py` handles `python` fences; the one in `utils.py` handles `luau`/`lua` fences. These should be unified into a single function in `utils.py` that accepts any language tag.

### 12. `validate_and_report()` Silently Swallows ImportError
**File**: `scripts/utils.py:46-47`

```python
except ImportError:
    pass
```

If `validate_luau` fails to import (e.g., a broken refactor), all Luau validation silently stops. This should at minimum log a warning.

### 13. No Rate Limit Handling in Upload Polling
**File**: `scripts/upload_asset.py:158-213`

The upload function retries on HTTP 429 and 5xx, which is good. But `poll_operation()` does NOT handle 429 responses — a rate limit during polling will crash the upload flow.

### 14. `generate_asset_ids_luau` Doesn't Validate Key Uniqueness
**File**: `scripts/upload_asset.py:314-362`

If two assets normalize to the same key (e.g., "Cool Sword" and "Cool-Sword" both become `COOL_SWORD`), the second silently overwrites the first in the registry AND in the Luau output. No warning is emitted.

---

## LOW Issues (Consider)

### 15. Cost Tracker Model Pricing Will Drift
**File**: `scripts/cost_tracker.py:20-34`

Hardcoded pricing as of early 2025. Consider fetching from a config file or at minimum logging a warning when an unknown model is encountered (currently returns 0 silently).

### 16. No `.env.example` File
New developers must read the README to discover which environment variables are required. A `.env.example` with placeholder values is standard practice.

### 17. Test Suite: Overly Permissive Assertions
Multiple tests check `result.exit_code in (0, 1)` or use `"keyword" in result.output`. These are fragile and may mask regressions. Prefer exact exit code assertions and structured output validation.

### 18. Missing `pytest-timeout` in Requirements
**File**: `pytest.ini` references `timeout = 30` but `pytest-timeout` is not in `requirements.txt`. The pytest warning `Unknown config option: timeout` confirms this.

### 19. Batch Generator Doesn't Validate YAML Schema
**File**: `scripts/batch_generate_assets.py:43-67`

The YAML loader checks for the `assets` key but doesn't validate individual asset entries have `name` and `prompt` fields. A missing `prompt` key produces a confusing `KeyError` at generation time.

---

## Architecture & Design Observations

### What's Done Well

1. **Clean separation of concerns**: Each script is a focused CLI tool composable via `pipeline.sh`. This is textbook Unix philosophy applied to an AI pipeline.

2. **Dual AI backend support**: Claude (via Anthropic) and OpenAI with file-search assistants. The Blender fallback for users without Meshy API access is excellent for accessibility.

3. **Dry-run mode throughout**: Every stage supports `--dry-run`, making the pipeline safe to test without API costs. The `_dryrun_registry.py` helper is a nice touch.

4. **Cost tracking**: The CSV-based cost logger with per-model pricing is practical. It enables budget monitoring for teams using expensive AI APIs.

5. **Progressive validation**: Luau validation catches Roblox anti-patterns (deprecated `wait()`, missing `GetService()`, string concat in loops). FBX validation catches oversized or malformed models before upload.

6. **Resume capability in batch generation**: The progress file pattern in `batch_generate_assets.py` is essential for long-running batch jobs against rate-limited APIs.

7. **Rojo integration**: The `default.project.json` correctly maps the Roblox game tree. Generated `AssetIds.luau` in `ReplicatedStorage` is the right location for shared constants.

8. **Test coverage**: 204 tests with good mock coverage of all external APIs. The integration tests verify end-to-end flows.

### Architectural Recommendations

1. **Add a schema layer**: Define JSON Schema or Pydantic models for the asset registry, YAML prompts, and API responses. This would catch the key sanitization and missing-field issues statically.

2. **Centralize retry logic**: Retry/backoff is implemented independently in `generate_3d_asset.py`, `upload_asset.py`, and `pipeline.sh`. Extract a shared `retry_with_backoff()` utility.

3. **Add structured logging**: The pipeline uses `click.echo()` throughout. For a production pipeline, structured JSON logging with severity levels would improve observability.

4. **Consider a pipeline state machine**: The bash orchestrator (`pipeline.sh`) works but becomes brittle as stages increase. A Python-based orchestrator with explicit state transitions would be more maintainable.

---

## Roblox-Specific Correctness

| Area | Status | Notes |
|------|--------|-------|
| Luau syntax validation | Good | Catches deprecated APIs, enforces `GetService()` |
| Asset upload flow | Good | Correct Open Cloud API usage with async polling |
| FBX format handling | Adequate | Basic validation; vertex estimation is rough |
| Rojo project structure | Correct | Proper ServerScriptService/ReplicatedStorage mapping |
| Asset ID management | Good with caveats | Key collision risk; no numeric validation on IDs |
| Modern Luau patterns | Good | Validates `task.*` usage over deprecated `wait()`/`spawn()` |
| Type annotations | Encouraged | Validator flags untyped functions (good practice) |

---

## Summary of Action Items

| Priority | Count | Items |
|----------|-------|-------|
| CRITICAL | 3 | Blender sandbox, registry paths, Luau injection via key/ID |
| HIGH | 5 | `e.message` compat, Selene blocking, Python linting, FBX vertex estimation, Meshy cost tracking |
| MEDIUM | 6 | Model version, assistant lifecycle, duplicate code, silent ImportError, poll rate limits, key uniqueness |
| LOW | 5 | Pricing drift, .env.example, test assertions, pytest-timeout, YAML schema |

The pipeline is a strong foundation. Addressing the 3 critical issues and the top HIGH items would make this production-ready for a Roblox development team.
