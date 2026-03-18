"""Tests for scripts/cost_tracker.py."""
from __future__ import annotations

import csv
from pathlib import Path

import pytest

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.cost_tracker import estimate_cost, log_cost, summarize_costs


class TestEstimateCost:
    def test_known_model(self):
        cost = estimate_cost("claude-sonnet-4-6", tokens_in=1000, tokens_out=1000)
        # claude-sonnet-4-6: input=0.003/1K, output=0.015/1K → 0.003 + 0.015 = 0.018
        assert abs(cost - 0.018) < 0.0001

    def test_unknown_model_uses_default(self):
        cost = estimate_cost("unknown-model", tokens_in=1000, tokens_out=1000)
        # Default: input=0.003/1K, output=0.015/1K
        assert abs(cost - 0.018) < 0.0001

    def test_zero_tokens(self):
        cost = estimate_cost("gpt-4o", tokens_in=0, tokens_out=0)
        assert cost == 0.0


class TestLogCost:
    def test_creates_csv_with_header(self, tmp_path: Path):
        csv_path = tmp_path / "costs.csv"
        log_cost("test_script", model="gpt-4o", tokens_in=100, tokens_out=200, csv_path=csv_path)
        assert csv_path.exists()
        lines = csv_path.read_text().strip().split("\n")
        assert len(lines) == 2  # header + 1 data row
        assert "Timestamp" in lines[0]

    def test_appends_to_existing(self, tmp_path: Path):
        csv_path = tmp_path / "costs.csv"
        log_cost("first", model="gpt-4o", tokens_in=100, tokens_out=200, csv_path=csv_path)
        log_cost("second", model="gpt-4o", tokens_in=300, tokens_out=400, csv_path=csv_path)
        lines = csv_path.read_text().strip().split("\n")
        assert len(lines) == 3  # header + 2 data rows

    def test_explicit_cost(self, tmp_path: Path):
        csv_path = tmp_path / "costs.csv"
        log_cost("test", cost_usd=1.23, csv_path=csv_path)
        content = csv_path.read_text()
        assert "1.230000" in content

    def test_creates_parent_dirs(self, tmp_path: Path):
        csv_path = tmp_path / "deep" / "nested" / "costs.csv"
        log_cost("test", csv_path=csv_path)
        assert csv_path.exists()


class TestSummarizeCosts:
    def test_empty_summary(self, tmp_path: Path):
        csv_path = tmp_path / "empty.csv"
        result = summarize_costs(csv_path)
        assert result["total_cost"] == 0.0
        assert result["run_count"] == 0

    def test_sums_correctly(self, tmp_path: Path):
        csv_path = tmp_path / "costs.csv"
        log_cost("a", model="gpt-4o", tokens_in=1000, tokens_out=0, cost_usd=0.01, csv_path=csv_path)
        log_cost("b", model="gpt-4o", tokens_in=0, tokens_out=2000, cost_usd=0.02, csv_path=csv_path)

        result = summarize_costs(csv_path)
        assert result["run_count"] == 2
        assert abs(result["total_cost"] - 0.03) < 0.0001
        assert result["total_tokens_in"] == 1000
        assert result["total_tokens_out"] == 2000
