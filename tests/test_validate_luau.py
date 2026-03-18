"""Tests for scripts/validate_luau.py."""
from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.validate_luau import (
    validate_luau,
    check_deprecated_globals,
    check_missing_type_annotations,
    check_bare_pcall_error_ignored,
    check_global_variables,
    check_missing_services,
    check_string_concat_in_loop,
    format_issue,
    ValidationIssue,
    main,
)


# ---------------------------------------------------------------------------
# Unit tests: check_deprecated_globals
# ---------------------------------------------------------------------------

class TestCheckDeprecatedGlobals:
    def test_flags_wait(self):
        issues = check_deprecated_globals(["wait(1)"])
        assert any(i.code == "LUA001" for i in issues)

    def test_flags_spawn(self):
        issues = check_deprecated_globals(["spawn(function() end)"])
        assert any(i.code == "LUA002" for i in issues)

    def test_flags_delay(self):
        issues = check_deprecated_globals(["delay(1, function() end)"])
        assert any(i.code == "LUA003" for i in issues)

    def test_flags_load_library(self):
        issues = check_deprecated_globals(["local m = LoadLibrary('RbxUtility')"])
        assert any(i.code == "LUA004" for i in issues)

    def test_no_issues_for_modern_code(self):
        lines = [
            "task.wait(1)",
            "task.spawn(function() end)",
            "task.delay(1, function() end)",
        ]
        issues = check_deprecated_globals(lines)
        codes = [i.code for i in issues]
        assert "LUA001" not in codes
        assert "LUA002" not in codes
        assert "LUA003" not in codes

    def test_reports_correct_line_number(self):
        lines = ["-- line 1", "-- line 2", "wait(1)"]
        issues = check_deprecated_globals(lines)
        assert issues[0].line == 3


# ---------------------------------------------------------------------------
# Unit tests: check_missing_type_annotations
# ---------------------------------------------------------------------------

class TestCheckMissingTypeAnnotations:
    def test_flags_untyped_function(self):
        issues = check_missing_type_annotations(["function doSomething()"])
        assert any(i.code == "LUA010" for i in issues)

    def test_flags_local_function(self):
        issues = check_missing_type_annotations(["local function helper()"])
        assert any(i.code == "LUA010" for i in issues)

    def test_no_flag_for_typed_function(self):
        issues = check_missing_type_annotations(["function doSomething(): void"])
        assert not any(i.code == "LUA010" for i in issues)

    def test_no_flag_for_function_with_params_typed(self):
        issues = check_missing_type_annotations(["function add(a: number, b: number): number"])
        assert not any(i.code == "LUA010" for i in issues)


# ---------------------------------------------------------------------------
# Unit tests: check_bare_pcall_error_ignored
# ---------------------------------------------------------------------------

class TestCheckBarePcall:
    def test_flags_bare_pcall(self):
        issues = check_bare_pcall_error_ignored(["    pcall(function() end)"])
        assert any(i.code == "LUA011" for i in issues)

    def test_no_flag_for_assigned_pcall(self):
        issues = check_bare_pcall_error_ignored(["local ok, err = pcall(function() end)"])
        assert not any(i.code == "LUA011" for i in issues)


# ---------------------------------------------------------------------------
# Unit tests: check_global_variables
# ---------------------------------------------------------------------------

class TestCheckGlobalVariables:
    def test_flags_global_assignment(self):
        issues = check_global_variables(["MyGlobal = 42"])
        assert any(i.code == "LUA020" for i in issues)

    def test_no_flag_for_local(self):
        issues = check_global_variables(["local x = 42"])
        assert not any(i.code == "LUA020" for i in issues)

    def test_no_flag_for_table_field(self):
        issues = check_global_variables(["self.value = 42"])
        assert not any(i.code == "LUA020" for i in issues)

    def test_no_flag_for_comment(self):
        issues = check_global_variables(["-- x = 42"])
        assert not any(i.code == "LUA020" for i in issues)


# ---------------------------------------------------------------------------
# Unit tests: check_missing_services
# ---------------------------------------------------------------------------

class TestCheckMissingServices:
    def test_flags_direct_game_players(self):
        issues = check_missing_services(["local p = game.Players"])
        assert any(i.code == "LUA030" for i in issues)

    def test_flags_direct_game_workspace(self):
        issues = check_missing_services(["local ws = game.Workspace"])
        assert any(i.code == "LUA030" for i in issues)

    def test_no_flag_for_get_service(self):
        issues = check_missing_services(["local Players = game:GetService('Players')"])
        assert not any(i.code == "LUA030" for i in issues)


# ---------------------------------------------------------------------------
# Unit tests: check_string_concat_in_loop
# ---------------------------------------------------------------------------

class TestCheckStringConcatInLoop:
    def test_flags_concat_in_for_loop(self):
        lines = [
            "for i = 1, 10 do",
            '    result = result .. "item"',
            "end",
        ]
        issues = check_string_concat_in_loop(lines)
        assert any(i.code == "LUA040" for i in issues)

    def test_no_flag_outside_loop(self):
        issues = check_string_concat_in_loop(['local s = "hello" .. " world"'])
        assert not any(i.code == "LUA040" for i in issues)


# ---------------------------------------------------------------------------
# Integration tests: validate_luau()
# ---------------------------------------------------------------------------

class TestValidateLuau:
    def test_clean_code_returns_no_issues(self):
        code = """
local Players = game:GetService("Players")
local DataStore = game:GetService("DataStoreService")

local function saveCoins(player: Player, coins: number): boolean
    local ok, err = pcall(function()
        local store = DataStore:GetDataStore("Coins")
        store:SetAsync(tostring(player.UserId), coins)
    end)
    return ok
end
"""
        issues = validate_luau(code)
        # May have info-level issues but no errors/warnings for clean code
        errors_warnings = [i for i in issues if i.severity in ("error", "warning")]
        assert len(errors_warnings) == 0

    def test_deprecated_wait_flagged(self):
        code = "wait(1)\nprint('done')"
        issues = validate_luau(code)
        assert any(i.code == "LUA001" for i in issues)

    def test_multiple_issues_sorted_by_line(self):
        code = "wait(1)\nspawn(function() end)\ndelay(1, f)"
        issues = validate_luau(code)
        lines = [i.line for i in issues]
        assert lines == sorted(lines)

    def test_empty_code_no_issues(self):
        issues = validate_luau("")
        assert issues == []

    def test_comment_only_no_issues(self):
        issues = validate_luau("-- This is a comment\n-- Another comment")
        assert issues == []


# ---------------------------------------------------------------------------
# Unit tests: format_issue
# ---------------------------------------------------------------------------

class TestFormatIssue:
    def test_error_format(self):
        issue = ValidationIssue(5, "error", "LUA001", "Use task.wait()")
        result = format_issue(issue, "test.luau")
        assert "test.luau:5" in result
        assert "LUA001" in result
        assert "task.wait()" in result
        assert "✗" in result

    def test_warning_format(self):
        issue = ValidationIssue(3, "warning", "LUA002", "Use task.spawn()")
        result = format_issue(issue, "test.luau")
        assert "⚠" in result

    def test_info_format(self):
        issue = ValidationIssue(1, "info", "LUA010", "Add type annotation")
        result = format_issue(issue, "test.luau")
        assert "ℹ" in result


# ---------------------------------------------------------------------------
# CLI tests
# ---------------------------------------------------------------------------

class TestValidateLuauCLI:
    def test_clean_file_exits_zero(self, tmp_path: Path):
        luau_file = tmp_path / "clean.luau"
        luau_file.write_text(
            "local Players = game:GetService('Players')\n",
            encoding="utf-8",
        )
        runner = CliRunner()
        result = runner.invoke(main, [str(luau_file)])
        assert result.exit_code == 0
        assert "No issues found" in result.output

    def test_file_with_warnings_exits_zero_by_default(self, tmp_path: Path):
        """Without --strict, warnings should not cause non-zero exit."""
        luau_file = tmp_path / "warn.luau"
        luau_file.write_text("wait(1)\n", encoding="utf-8")
        runner = CliRunner()
        result = runner.invoke(main, [str(luau_file)])
        # exit 0 because warnings don't fail without --strict
        assert result.exit_code == 0

    def test_file_with_warnings_and_strict_exits_one(self, tmp_path: Path):
        """With --strict, warnings should cause exit code 1."""
        luau_file = tmp_path / "warn.luau"
        luau_file.write_text("wait(1)\n", encoding="utf-8")
        runner = CliRunner()
        result = runner.invoke(main, ["--strict", str(luau_file)])
        assert result.exit_code == 1

    def test_missing_file_exits_nonzero(self):
        runner = CliRunner()
        result = runner.invoke(main, ["/does/not/exist.luau"])
        assert result.exit_code != 0

    def test_quiet_mode_suppresses_info(self, tmp_path: Path):
        """--quiet should suppress info-level messages."""
        luau_file = tmp_path / "typed.luau"
        luau_file.write_text("function doSomething()\nend\n", encoding="utf-8")
        runner = CliRunner()
        result_normal = runner.invoke(main, [str(luau_file)])
        result_quiet = runner.invoke(main, ["--quiet", str(luau_file)])
        # Info issues should appear in normal but be suppressed in quiet
        if "LUA010" in result_normal.output:
            assert "LUA010" not in result_quiet.output

    def test_stdin_input(self):
        """Test reading from stdin (- argument)."""
        runner = CliRunner()
        result = runner.invoke(main, ["-"], input="local x = 1\n")
        assert result.exit_code == 0
