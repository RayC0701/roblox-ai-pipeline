#!/usr/bin/env python3
"""API cost tracking for the Roblox AI Pipeline.

Logs token usage and estimated costs to logs/costs.csv.
Used by generate_luau.py, generate_luau_openai.py, and generate_3d_asset.py.

Usage (as a library):
    from scripts.cost_tracker import log_cost
    log_cost("generate_luau", tokens_in=1500, tokens_out=3000, cost_usd=0.045)
"""

from __future__ import annotations

import csv
import os
from datetime import datetime, timezone
from pathlib import Path

# Default costs per 1K tokens (approximate, as of early 2025)
MODEL_COSTS: dict[str, dict[str, float]] = {
    # Anthropic
    "claude-sonnet-4-6": {"input": 0.003, "output": 0.015},
    "claude-opus-4-6": {"input": 0.015, "output": 0.075},
    "claude-sonnet-4-20250514": {"input": 0.003, "output": 0.015},
    "claude-haiku-3-5": {"input": 0.0008, "output": 0.004},
    # OpenAI
    "gpt-4o": {"input": 0.0025, "output": 0.01},
    "gpt-4o-mini": {"input": 0.00015, "output": 0.0006},
    "gpt-4-turbo": {"input": 0.01, "output": 0.03},
    # Meshy (flat rate per task, not per-token)
    # Preview costs ~1 credit ($0.10), refine ~3 credits ($0.30)
    "meshy-preview": {"flat": 0.10},
    "meshy-refine": {"flat": 0.30},
}

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CSV_PATH = PROJECT_ROOT / "logs" / "costs.csv"

CSV_HEADER = ["Timestamp", "Script", "Model", "TokensIn", "TokensOut", "CostUSD"]


def estimate_cost(model: str, tokens_in: int, tokens_out: int) -> float:
    """Estimate the cost in USD for a given model and token counts.

    For flat-rate models (e.g. Meshy), the flat fee is returned regardless
    of token counts.

    Args:
        model: Model identifier (e.g. 'claude-sonnet-4-6').
        tokens_in: Number of input tokens.
        tokens_out: Number of output tokens.

    Returns:
        Estimated cost in USD.
    """
    costs = MODEL_COSTS.get(model, {"input": 0.003, "output": 0.015})
    if "flat" in costs:
        return costs["flat"]
    return (tokens_in / 1000 * costs["input"]) + (tokens_out / 1000 * costs["output"])


def log_cost(
    script: str,
    model: str = "",
    tokens_in: int = 0,
    tokens_out: int = 0,
    cost_usd: float | None = None,
    csv_path: Path | None = None,
) -> None:
    """Append a cost record to the CSV log.

    Args:
        script: Name of the script (e.g. 'generate_luau').
        model: Model used.
        tokens_in: Input token count.
        tokens_out: Output token count.
        cost_usd: Explicit cost. If None, estimated from model + tokens.
        csv_path: Path to the CSV file. Defaults to logs/costs.csv.
    """
    if csv_path is None:
        csv_path = DEFAULT_CSV_PATH

    if cost_usd is None:
        cost_usd = estimate_cost(model, tokens_in, tokens_out)

    csv_path.parent.mkdir(parents=True, exist_ok=True)

    file_exists = csv_path.exists() and csv_path.stat().st_size > 0
    with open(csv_path, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(CSV_HEADER)
        writer.writerow([
            datetime.now(timezone.utc).isoformat(),
            script,
            model,
            tokens_in,
            tokens_out,
            f"{cost_usd:.6f}",
        ])


def summarize_costs(csv_path: Path | None = None) -> dict:
    """Parse the costs CSV and return a summary.

    Args:
        csv_path: Path to costs.csv. Defaults to logs/costs.csv.

    Returns:
        Dict with total_cost, total_tokens_in, total_tokens_out, run_count.
    """
    if csv_path is None:
        csv_path = DEFAULT_CSV_PATH

    if not csv_path.exists():
        return {"total_cost": 0.0, "total_tokens_in": 0, "total_tokens_out": 0, "run_count": 0}

    total_cost = 0.0
    total_in = 0
    total_out = 0
    count = 0

    with open(csv_path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            total_cost += float(row.get("CostUSD", 0))
            total_in += int(row.get("TokensIn", 0))
            total_out += int(row.get("TokensOut", 0))
            count += 1

    return {
        "total_cost": total_cost,
        "total_tokens_in": total_in,
        "total_tokens_out": total_out,
        "run_count": count,
    }
