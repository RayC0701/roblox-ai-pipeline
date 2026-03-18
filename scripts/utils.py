"""Shared utilities for the Roblox AI Pipeline scripts."""
from __future__ import annotations

import re

import click


def strip_markdown_fences(text: str) -> str:
    """Remove markdown code fences from generated output.

    Args:
        text: Raw text that may contain ```luau ... ``` fences.

    Returns:
        Clean code without fences.
    """
    text = re.sub(r"^```(?:luau|lua)?\s*\n", "", text.strip())
    text = re.sub(r"\n```\s*$", "", text)
    return text.strip()


def validate_and_report(code: str) -> None:
    """Run Luau validation on generated code and print warnings/errors.

    This is a best-effort helper: if the validate_luau module is not
    available, validation is silently skipped.

    Args:
        code: The generated Luau source code to validate.
    """
    try:
        from scripts.validate_luau import validate_luau as run_validation, format_issue

        issues = run_validation(code)
        errors = [i for i in issues if i.severity == "error"]
        warnings = [i for i in issues if i.severity == "warning"]
        if errors:
            click.echo(f"⚠ Generated code has {len(errors)} error(s):", err=True)
            for issue in errors:
                click.echo(f"  {format_issue(issue, '<generated>')}", err=True)
        if warnings:
            click.echo(f"ℹ Generated code has {len(warnings)} warning(s):", err=True)
            for issue in warnings:
                click.echo(f"  {format_issue(issue, '<generated>')}", err=True)
    except ImportError:
        pass  # validate_luau not available; skip
