#!/usr/bin/env python3
"""Component 3b: AI 3D asset generation via Blender + Anthropic Claude.

Generates 3D models procedurally using Blender's Python API (bpy).
Claude generates a Blender Python script from the text prompt, which is
then executed in Blender's headless mode.

This is a free alternative to Meshy for simple geometric assets.

Usage:
    python scripts/generate_blender_asset.py "Low-poly gold coin" --output assets/models/coin.fbx
    python scripts/generate_blender_asset.py "Cartoon tree" --art-style realistic
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import click
from dotenv import load_dotenv

load_dotenv()

BLENDER_SYSTEM_PROMPT = (
    "You are an expert Blender Python scripter. Write a Blender 4.0+ script "
    "using the bpy module to procedurally create a 3D asset matching the user's "
    "description. Delete the default cube. Set up materials/colors as appropriate. "
    "Export as FBX to the specified path. Output ONLY the raw Python code with no "
    "markdown fences or explanations. "
    "NEVER use os.system, subprocess, eval, exec, or network libraries. "
    "Only use bpy, bmesh, mathutils, and math."
)

DEFAULT_MODEL = "claude-sonnet-4-20250514"

BLOCKED_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("os.system", re.compile(r"\bos\.system\s*\(")),
    ("os.popen", re.compile(r"\bos\.popen\s*\(")),
    ("os.exec*", re.compile(r"\bos\.exec[a-z]*\s*\(")),
    ("os.remove", re.compile(r"\bos\.remove\s*\(")),
    ("os.unlink", re.compile(r"\bos\.unlink\s*\(")),
    ("os.rmdir", re.compile(r"\bos\.rmdir\s*\(")),
    ("shutil.rmtree", re.compile(r"\bshutil\.rmtree\s*\(")),
    ("subprocess", re.compile(r"\bsubprocess\b")),
    ("eval(", re.compile(r"\beval\s*\(")),
    ("exec(", re.compile(r"\bexec\s*\(")),
    ("compile(", re.compile(r"\bcompile\s*\(")),
    ("__import__", re.compile(r"__import__")),
    ("urllib", re.compile(r"\burllib\b")),
    ("http.client", re.compile(r"\bhttp\.client\b")),
    ("socket", re.compile(r"\bsocket\b")),
    ("requests", re.compile(r"\brequests\b")),
    ("ftplib", re.compile(r"\bftplib\b")),
]


def validate_blender_script(script_text: str) -> None:
    """Validate that a generated Blender script contains no dangerous operations.

    Scans each non-comment line for blocked patterns such as shell commands,
    network access, and dynamic code execution.

    Args:
        script_text: The generated Python script to validate.

    Raises:
        click.ClickException: If a blocked pattern is found.
    """
    for line_no, line in enumerate(script_text.splitlines(), start=1):
        stripped = line.strip()
        # Skip comment lines
        if stripped.startswith("#"):
            continue
        for name, pattern in BLOCKED_PATTERNS:
            if pattern.search(line):
                raise click.ClickException(
                    f"Blocked pattern '{name}' found in generated script "
                    f"at line {line_no}: {stripped!r}"
                )


def get_anthropic_key() -> str:
    """Get the Anthropic API key from environment.

    Returns:
        The API key string.

    Raises:
        click.ClickException: If the key is not set.
    """
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not key:
        raise click.ClickException(
            "ANTHROPIC_API_KEY not set. Add it to your .env file or environment."
        )
    return key


def find_blender() -> str:
    """Find the Blender executable.

    Returns:
        Path to the Blender binary.

    Raises:
        click.ClickException: If Blender is not found.
    """
    # Check PATH first
    blender_path = shutil.which("blender")
    if blender_path:
        return blender_path

    # Common macOS locations
    mac_paths = [
        "/Applications/Blender.app/Contents/MacOS/Blender",
        os.path.expanduser("~/Applications/Blender.app/Contents/MacOS/Blender"),
    ]
    for p in mac_paths:
        if os.path.isfile(p):
            return p

    raise click.ClickException(
        "Blender not found. Install it:\n"
        "  macOS:  brew install --cask blender\n"
        "  Linux:  sudo apt install blender  (or snap install blender)\n"
        "  Windows: winget install BlenderFoundation.Blender"
    )


def generate_blender_script(
    api_key: str,
    prompt: str,
    output_path: str,
    art_style: str,
    model: str = DEFAULT_MODEL,
) -> tuple[str, int, int]:
    """Call Claude to generate a Blender Python script.

    Args:
        api_key: Anthropic API key.
        prompt: Text description of the 3D asset.
        output_path: Where the FBX file should be exported.
        art_style: Art style hint (cartoon, realistic, low-poly).
        model: Claude model to use.

    Returns:
        Tuple of (script_text, input_tokens, output_tokens).

    Raises:
        click.ClickException: On API errors.
    """
    import anthropic

    client = anthropic.Anthropic(api_key=api_key)

    user_message = (
        f"Create a 3D asset: {prompt}\n"
        f"Art style: {art_style}\n"
        f"Export the final model as FBX to this exact path: {output_path}\n"
        f"Make sure to:\n"
        f"- Delete the default cube\n"
        f"- Create appropriate geometry\n"
        f"- Add materials with colors matching the art style\n"
        f"- Export as FBX with the correct path"
    )

    try:
        response = client.messages.create(
            model=model,
            max_tokens=4096,
            system=BLENDER_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_message}],
        )
    except anthropic.APIError as e:
        raise click.ClickException(f"Anthropic API error: {e}")

    script_text = response.content[0].text
    tokens_in = response.usage.input_tokens
    tokens_out = response.usage.output_tokens

    # Strip markdown fences if Claude included them despite instructions
    script_text = _strip_code_fences(script_text)

    # Safety: reject scripts with dangerous operations
    validate_blender_script(script_text)

    return script_text, tokens_in, tokens_out


def _strip_code_fences(text: str) -> str:
    """Remove markdown code fences from generated code.

    Args:
        text: Raw text that may contain ```python ... ``` wrappers.

    Returns:
        Clean Python code.
    """
    import re

    # Remove ```python ... ``` or ``` ... ```
    pattern = r"^```(?:python)?\s*\n(.*?)```\s*$"
    match = re.match(pattern, text.strip(), re.DOTALL)
    if match:
        return match.group(1).strip()
    return text.strip()


def execute_blender_script(blender_path: str, script_path: str) -> None:
    """Execute a Python script in Blender's headless mode.

    Args:
        blender_path: Path to Blender executable.
        script_path: Path to the Python script to run.

    Raises:
        click.ClickException: If Blender execution fails.
    """
    try:
        result = subprocess.run(
            [blender_path, "-b", "-P", script_path],
            capture_output=True,
            text=True,
            timeout=120,
        )
    except subprocess.TimeoutExpired:
        raise click.ClickException("Blender execution timed out after 120 seconds.")
    except FileNotFoundError:
        raise click.ClickException(f"Blender not found at: {blender_path}")

    if result.returncode != 0:
        # Extract the most relevant error from Blender's output
        stderr = result.stderr.strip()
        stdout = result.stdout.strip()
        error_detail = stderr if stderr else stdout
        # Truncate to last 500 chars for readability
        if len(error_detail) > 500:
            error_detail = "..." + error_detail[-500:]
        raise click.ClickException(
            f"Blender script failed (exit code {result.returncode}):\n{error_detail}"
        )


@click.command()
@click.argument("prompt")
@click.option(
    "--output", "-o",
    type=click.Path(),
    default="assets/models/output.fbx",
    show_default=True,
    help="Output FBX file path.",
)
@click.option(
    "--art-style",
    type=click.Choice(["cartoon", "realistic", "low-poly"], case_sensitive=False),
    default="cartoon",
    show_default=True,
    help="Art style for generation.",
)
@click.option(
    "--model",
    default=DEFAULT_MODEL,
    show_default=True,
    help="Claude model for script generation.",
)
def main(prompt: str, output: str, art_style: str, model: str) -> None:
    """Generate a 3D asset procedurally using Blender + Claude AI."""
    api_key = get_anthropic_key()
    blender_path = find_blender()

    output_path = Path(output).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    click.echo(f"Prompt     : {prompt}")
    click.echo(f"Style      : {art_style}")
    click.echo(f"Output     : {output_path}")
    click.echo(f"Generator  : Blender (procedural)")
    click.echo(f"Blender    : {blender_path}")
    click.echo()

    # Step 1: Generate Blender script via Claude
    click.echo("Generating Blender script via Claude...")
    script_text, tokens_in, tokens_out = generate_blender_script(
        api_key, prompt, str(output_path), art_style, model
    )
    click.echo(f"  Tokens: {tokens_in} in / {tokens_out} out")

    # Step 2: Write script to temp file and execute
    tmp_script = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", prefix="blender_gen_", delete=False
        ) as f:
            f.write(script_text)
            tmp_script = f.name

        click.echo(f"Running Blender script: {tmp_script}")
        execute_blender_script(blender_path, tmp_script)

    finally:
        # Clean up temp file
        if tmp_script and os.path.exists(tmp_script):
            os.unlink(tmp_script)

    # Verify output was created
    if not output_path.exists():
        raise click.ClickException(
            f"Blender script ran but output file was not created: {output_path}"
        )

    file_size = output_path.stat().st_size
    click.echo(f"Generated: {output_path} ({file_size:,} bytes)")

    # Log cost
    try:
        from scripts.cost_tracker import log_cost, estimate_cost

        cost = estimate_cost(model, tokens_in, tokens_out)
        log_cost(
            script="generate_blender_asset",
            model=model,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost_usd=cost,
        )
        click.echo(f"Cost: ${cost:.4f}")
    except Exception:
        pass  # Cost tracking is best-effort

    click.echo("Done!")


if __name__ == "__main__":
    main()
