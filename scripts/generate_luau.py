#!/usr/bin/env python3
"""Component 1: Luau code generation via Claude API.

Generates production-ready Roblox Luau code from natural language task
descriptions using the Anthropic Claude API with an optional local
knowledge base for grounding.

Usage:
    python scripts/generate_luau.py "Create a coin collection system"
    python scripts/generate_luau.py --spec specs/feature.md
    python scripts/generate_luau.py "task" --model claude-opus-4-6 --output src/server/feature.luau
    python scripts/generate_luau.py "task" --dry-run

    # Use Claude Max subscription via CLI (no API key needed):
    python scripts/generate_luau.py "task" --claude-cli
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import click
from dotenv import load_dotenv

from scripts.utils import strip_markdown_fences, validate_and_report

load_dotenv()


def load_knowledge_base(docs_dir: Path) -> str:
    """Load all markdown files from the knowledge base directory.

    Args:
        docs_dir: Path to the docs/roblox-api directory.

    Returns:
        Concatenated contents of all .md files, or empty string if none found.
    """
    if not docs_dir.exists():
        return ""

    knowledge_files = sorted(docs_dir.glob("*.md"))
    if not knowledge_files:
        return ""

    sections: list[str] = []
    for f in knowledge_files:
        try:
            content = f.read_text(encoding="utf-8")
            sections.append(f"\n\n--- {f.name} ---\n{content}")
        except OSError:
            continue

    return "".join(sections)


def load_system_prompt(prompt_path: Path) -> str:
    """Load the system prompt from a markdown file.

    Args:
        prompt_path: Path to the system prompt file.

    Returns:
        The system prompt text.

    Raises:
        click.ClickException: If the prompt file is not found.
    """
    if not prompt_path.exists():
        raise click.ClickException(f"System prompt not found: {prompt_path}")
    return prompt_path.read_text(encoding="utf-8")


def build_system_message(system_prompt: str, knowledge_context: str) -> str:
    """Combine system prompt with knowledge base context.

    Args:
        system_prompt: The core system prompt.
        knowledge_context: Concatenated knowledge base content.

    Returns:
        Full system message for the API call.
    """
    if knowledge_context:
        return system_prompt + "\n\n# Reference Documentation\n" + knowledge_context
    return system_prompt


def generate_luau(
    task_description: str,
    model: str,
    system_prompt: str,
    knowledge_context: str,
) -> str:
    """Generate Luau code from a natural language task description.

    Args:
        task_description: What the code should do.
        model: Claude model identifier.
        system_prompt: The system prompt text.
        knowledge_context: Knowledge base content.

    Returns:
        Generated Luau code with markdown fences stripped.
    """
    import anthropic

    client = anthropic.Anthropic()

    system_message = build_system_message(system_prompt, knowledge_context)

    try:
        message = client.messages.create(
            model=model,
            max_tokens=8192,
            system=system_message,
            messages=[{"role": "user", "content": task_description}],
        )
    except anthropic.AuthenticationError:
        raise click.ClickException(
            "Invalid ANTHROPIC_API_KEY. Set it in your .env file or environment."
        )
    except anthropic.RateLimitError:
        raise click.ClickException(
            "Rate limited by Anthropic API. Please wait and try again."
        )
    except anthropic.APIError as e:
        raise click.ClickException(f"Anthropic API error: {e}")

    # Log API cost
    try:
        from scripts.cost_tracker import log_cost
        usage = message.usage
        log_cost(
            script="generate_luau",
            model=model,
            tokens_in=usage.input_tokens,
            tokens_out=usage.output_tokens,
        )
    except Exception:
        pass  # Cost tracking is best-effort

    raw_output = message.content[0].text
    return strip_markdown_fences(raw_output)


def generate_luau_cli(
    task_description: str,
    system_prompt: str,
    knowledge_context: str,
) -> str:
    """Generate Luau code using the `claude` CLI (Claude Code).

    Works with a Claude Max subscription — no ANTHROPIC_API_KEY needed.
    Invokes the `claude` command in non-interactive (print) mode.

    Args:
        task_description: What the code should do.
        system_prompt: The system prompt text.
        knowledge_context: Knowledge base content.

    Returns:
        Generated Luau code with markdown fences stripped.
    """
    system_message = build_system_message(system_prompt, knowledge_context)

    # Write system prompt to a temp file so we can pass it via --system-prompt
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".md", delete=False, encoding="utf-8"
    ) as f:
        f.write(system_message)
        system_file = f.name

    try:
        result = subprocess.run(
            [
                "claude",
                "--print",                       # non-interactive, output only
                "--system-prompt", system_file,
                task_description,
            ],
            capture_output=True,
            text=True,
            timeout=300,  # 5 minute timeout
        )
    except FileNotFoundError:
        raise click.ClickException(
            "claude CLI not found. Install Claude Code: npm install -g @anthropic-ai/claude-code"
        )
    except subprocess.TimeoutExpired:
        raise click.ClickException("claude CLI timed out after 300s")
    finally:
        os.unlink(system_file)

    if result.returncode != 0:
        stderr = result.stderr.strip()
        raise click.ClickException(f"claude CLI failed (exit {result.returncode}): {stderr[:500]}")

    return strip_markdown_fences(result.stdout)


@click.command()
@click.argument("task", required=False)
@click.option("--spec", type=click.Path(exists=True), help="Read task from a spec file.")
@click.option("--model", default="claude-sonnet-4-6", show_default=True, help="Claude model to use.")
@click.option("--output", "-o", type=click.Path(), help="Write output to file instead of stdout.")
@click.option("--dry-run", is_flag=True, help="Show what would be sent without calling the API.")
@click.option("--claude-cli", is_flag=True, envvar="USE_CLAUDE_CLI",
              help="Use claude CLI (Claude Max subscription) instead of API.")
def main(
    task: str | None,
    spec: str | None,
    model: str,
    output: str | None,
    dry_run: bool,
    claude_cli: bool,
) -> None:
    """Generate Luau code from a task description using Claude API."""
    # Resolve task description
    if spec:
        task_description = Path(spec).read_text(encoding="utf-8")
    elif task:
        task_description = task
    else:
        raise click.ClickException(
            "Provide a task description as an argument or use --spec to read from a file."
        )

    # Paths relative to project root
    project_root = Path(__file__).resolve().parent.parent
    prompt_path = project_root / "prompts" / "luau-system-prompt.md"
    docs_dir = project_root / "docs" / "roblox-api"

    system_prompt = load_system_prompt(prompt_path)
    knowledge_context = load_knowledge_base(docs_dir)

    if dry_run:
        system_message = build_system_message(system_prompt, knowledge_context)
        click.echo("=== DRY RUN ===")
        click.echo(f"Model: {model}")
        click.echo(f"Max tokens: 8192")
        click.echo(f"System prompt length: {len(system_message)} chars")
        click.echo(f"Knowledge base files: {len(list(docs_dir.glob('*.md'))) if docs_dir.exists() else 0}")
        click.echo(f"\n--- Task ---\n{task_description}")
        click.echo(f"\n--- System prompt (first 500 chars) ---\n{system_message[:500]}...")
        return

    if claude_cli:
        code = generate_luau_cli(task_description, system_prompt, knowledge_context)
    else:
        code = generate_luau(task_description, model, system_prompt, knowledge_context)

    # Run validation on generated code before writing
    validate_and_report(code)

    if output:
        out_path = Path(output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(code + "\n", encoding="utf-8")
        click.echo(f"Written to {out_path}")
    else:
        click.echo(code)


if __name__ == "__main__":
    main()
