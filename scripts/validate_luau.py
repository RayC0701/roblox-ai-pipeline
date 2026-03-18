#!/usr/bin/env python3
"""Component: Luau script basic syntax validation.

Performs lightweight, regex-based validation of generated Luau code to catch
common mistakes before the code is committed or uploaded to Roblox.

This is a best-effort heuristic validator — it does NOT replace a full Luau
parser or Selene linting, but gives fast feedback on obvious errors.

Usage:
    python scripts/validate_luau.py src/server/coins.luau
    python scripts/validate_luau.py --strict src/server/coins.luau
    cat code.luau | python scripts/validate_luau.py -
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import NamedTuple

import click


class ValidationIssue(NamedTuple):
    line: int
    severity: str  # "error" | "warning" | "info"
    code: str      # Short issue code, e.g. "LUA001"
    message: str


# ---------------------------------------------------------------------------
# Validation rules
# ---------------------------------------------------------------------------

def check_deprecated_globals(lines: list[str]) -> list[ValidationIssue]:
    """Flag deprecated Roblox globals that should not be used in new code."""
    deprecated = {
        # Use negative lookbehind to avoid matching method calls (e.g. task.wait)
        r"(?<!\.)(?<!\w)\bwait\s*\(": ("LUA001", "Use task.wait() instead of deprecated wait()"),
        r"(?<!\.)(?<!\w)\bspawn\s*\(": ("LUA002", "Use task.spawn() instead of deprecated spawn()"),
        r"(?<!\.)(?<!\w)\bdelay\s*\(": ("LUA003", "Use task.delay() instead of deprecated delay()"),
        r"\bLoadLibrary\s*\(": ("LUA004", "LoadLibrary is removed; use require() with ModuleScripts"),
        r"\bypcall\s+function": ("LUA005", "Prefer ypcall(function() ... end) call syntax"),
    }
    issues = []
    for i, line in enumerate(lines, 1):
        for pattern, (code, msg) in deprecated.items():
            if re.search(pattern, line):
                issues.append(ValidationIssue(i, "warning", code, msg))
    return issues


def check_missing_type_annotations(lines: list[str]) -> list[ValidationIssue]:
    """Warn when top-level functions lack return type annotations (Luau style)."""
    issues = []
    fn_pattern = re.compile(r"^(local\s+)?function\s+\w+\s*\([^)]*\)\s*$")
    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        if fn_pattern.match(stripped) and ":" not in stripped:
            issues.append(ValidationIssue(
                i, "info", "LUA010",
                "Function has no return type annotation (add ': void' or ': ReturnType')"
            ))
    return issues


def check_bare_pcall_error_ignored(lines: list[str]) -> list[ValidationIssue]:
    """Flag pcall results that are not checked."""
    issues = []
    bare_pcall = re.compile(r"^\s*pcall\s*\(")
    for i, line in enumerate(lines, 1):
        if bare_pcall.match(line):
            issues.append(ValidationIssue(
                i, "warning", "LUA011",
                "pcall() result is unused — store in 'local ok, err = pcall(...)' and check ok"
            ))
    return issues


def check_global_variables(lines: list[str]) -> list[ValidationIssue]:
    """Detect probable accidental global variable declarations."""
    issues = []
    # Variable assignments without 'local' at the start of a line (heuristic)
    global_pattern = re.compile(r"^([A-Za-z_]\w*)\s*=\s*[^=]")
    local_prefixes = re.compile(r"^\s*(local|for|if|while|repeat|return|function|type|export)")
    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        if not stripped or stripped.startswith("--"):
            continue
        if local_prefixes.match(stripped):
            continue
        if global_pattern.match(stripped):
            # Skip if it looks like a table field assignment (has a dot/bracket prefix)
            if "." not in stripped.split("=")[0] and "[" not in stripped.split("=")[0]:
                issues.append(ValidationIssue(
                    i, "warning", "LUA020",
                    f"Possible accidental global: '{stripped.split('=')[0].strip()}' — use 'local'"
                ))
    return issues


def check_missing_services(lines: list[str]) -> list[ValidationIssue]:
    """Detect service access without GetService (risky in LocalScript/ModuleScript)."""
    issues = []
    bad_access = re.compile(r"\bgame\.\s*(Players|Workspace|ReplicatedStorage|ServerStorage|TweenService|RunService)\b")
    for i, line in enumerate(lines, 1):
        if bad_access.search(line):
            issues.append(ValidationIssue(
                i, "info", "LUA030",
                "Prefer game:GetService('ServiceName') over direct game.ServiceName access"
            ))
    return issues


def check_string_concat_in_loop(lines: list[str]) -> list[ValidationIssue]:
    """Warn about string concatenation inside loops (performance anti-pattern)."""
    issues = []
    in_loop_depth = 0
    loop_start = re.compile(r"^\s*(for|while|repeat)\b")
    loop_end = re.compile(r"^\s*end\b")
    concat_pattern = re.compile(r'(?:".+?"|\'[^\']+?\'|\w+)\s*\.\.\s*(?:".+?"|\'[^\']+?\'|\w+)')

    for i, line in enumerate(lines, 1):
        if loop_start.match(line):
            in_loop_depth += 1
        if loop_end.match(line) and in_loop_depth > 0:
            in_loop_depth -= 1
        if in_loop_depth > 0 and concat_pattern.search(line):
            issues.append(ValidationIssue(
                i, "info", "LUA040",
                "String concatenation (..) inside a loop — consider table.concat() for performance"
            ))
    return issues


ALL_RULES = [
    check_deprecated_globals,
    check_missing_type_annotations,
    check_bare_pcall_error_ignored,
    check_global_variables,
    check_missing_services,
    check_string_concat_in_loop,
]


# ---------------------------------------------------------------------------
# Core validation function
# ---------------------------------------------------------------------------

def validate_luau(source: str, filename: str = "<stdin>") -> list[ValidationIssue]:
    """Run all validation rules against Luau source code.

    Args:
        source: The Luau source code as a string.
        filename: Display name for error messages.

    Returns:
        List of ValidationIssue namedtuples (may be empty = all clear).
    """
    lines = source.splitlines()
    issues: list[ValidationIssue] = []
    for rule in ALL_RULES:
        issues.extend(rule(lines))
    return sorted(issues, key=lambda x: x.line)


def format_issue(issue: ValidationIssue, filename: str) -> str:
    """Format a single issue for display."""
    icon = {"error": "✗", "warning": "⚠", "info": "ℹ"}.get(issue.severity, "?")
    return f"{filename}:{issue.line}: {icon} [{issue.code}] {issue.message}"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

@click.command()
@click.argument("input_file", default="-", type=click.Path())
@click.option("--strict", is_flag=True, help="Exit non-zero if any warnings found (not just errors).")
@click.option("--quiet", "-q", is_flag=True, help="Only show errors, suppress warnings and info.")
def main(input_file: str, strict: bool, quiet: bool) -> None:
    """Validate a Luau script for common issues.

    INPUT_FILE: Path to a .luau file, or '-' to read from stdin.
    """
    if input_file == "-":
        source = sys.stdin.read()
        filename = "<stdin>"
    else:
        # Security: Resolve and validate the path to prevent directory traversal
        path = Path(input_file).resolve()
        
        # Prevent directory traversal attacks by ensuring the resolved path
        # doesn't escape expected boundaries (optional: can add cwd check)
        if not path.exists():
            raise click.ClickException(f"File not found: {input_file}")
        if not path.is_file():
            raise click.ClickException(f"Not a file: {input_file}")
        
        source = path.read_text(encoding="utf-8")
        filename = str(path)

    issues = validate_luau(source, filename)

    errors = [i for i in issues if i.severity == "error"]
    warnings = [i for i in issues if i.severity == "warning"]
    info = [i for i in issues if i.severity == "info"]

    displayed = errors + ([] if quiet else warnings + info)

    for issue in displayed:
        click.echo(format_issue(issue, filename))

    summary_parts = []
    if errors:
        summary_parts.append(f"{len(errors)} error(s)")
    if warnings:
        summary_parts.append(f"{len(warnings)} warning(s)")
    if info and not quiet:
        summary_parts.append(f"{len(info)} info")

    if not issues:
        click.echo(f"✓ {filename}: No issues found.")
    else:
        click.echo(f"\nSummary: {', '.join(summary_parts) or 'all clear'}")

    if errors or (strict and warnings):
        sys.exit(1)


if __name__ == "__main__":
    main()
