#!/usr/bin/env python3
"""Component 2: Luau code generation via OpenAI Assistants API.

Alternative to the Claude-based generator. Uses OpenAI's Assistants API
with file search to ground responses in Roblox API documentation.

Usage:
    python scripts/generate_luau_openai.py create-assistant
    python scripts/generate_luau_openai.py generate "Create a coin collection system"
    python scripts/generate_luau_openai.py generate --spec specs/feature.md
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import click
from dotenv import load_dotenv

load_dotenv()

ASSISTANT_ID_FILE = Path(__file__).resolve().parent.parent / ".assistant_id"


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


def get_openai_client():
    """Create and return an OpenAI client.

    Returns:
        An authenticated OpenAI client instance.

    Raises:
        click.ClickException: If the API key is not configured.
    """
    from openai import OpenAI

    try:
        client = OpenAI()
    except Exception as e:
        raise click.ClickException(
            f"Failed to create OpenAI client. Is OPENAI_API_KEY set? {e}"
        )
    return client


def save_assistant_id(assistant_id: str) -> None:
    """Save the assistant ID to a file for reuse.

    Args:
        assistant_id: The OpenAI assistant identifier.
    """
    ASSISTANT_ID_FILE.write_text(assistant_id, encoding="utf-8")


def load_assistant_id() -> str:
    """Load a previously saved assistant ID.

    Returns:
        The assistant ID string.

    Raises:
        click.ClickException: If no assistant has been created yet.
    """
    if not ASSISTANT_ID_FILE.exists():
        raise click.ClickException(
            "No assistant found. Run 'create-assistant' first."
        )
    return ASSISTANT_ID_FILE.read_text(encoding="utf-8").strip()


@click.group()
def cli() -> None:
    """Luau code generation using OpenAI Assistants API."""


@cli.command("create-assistant")
@click.option("--model", default="gpt-4o", show_default=True, help="OpenAI model to use.")
def create_assistant(model: str) -> None:
    """Create an OpenAI Assistant with Roblox docs uploaded for file search."""
    from openai import OpenAI

    client = get_openai_client()

    project_root = Path(__file__).resolve().parent.parent
    docs_dir = project_root / "docs" / "roblox-api"
    prompt_path = project_root / "prompts" / "luau-system-prompt.md"

    if not prompt_path.exists():
        raise click.ClickException(f"System prompt not found: {prompt_path}")

    instructions = prompt_path.read_text(encoding="utf-8")

    # Upload knowledge files
    file_ids: list[str] = []
    if docs_dir.exists():
        md_files = sorted(docs_dir.glob("*.md"))
        for f in md_files:
            click.echo(f"Uploading {f.name}...")
            try:
                uploaded = client.files.create(
                    file=open(f, "rb"), purpose="assistants"
                )
                file_ids.append(uploaded.id)
            except Exception as e:
                click.echo(f"  Warning: failed to upload {f.name}: {e}")

    click.echo(f"Uploaded {len(file_ids)} knowledge files.")

    # Build tool resources
    tool_resources = {}
    if file_ids:
        tool_resources = {
            "file_search": {
                "vector_stores": [{"file_ids": file_ids}]
            }
        }

    try:
        assistant = client.beta.assistants.create(
            name="Roblox Luau Coder",
            instructions=instructions,
            model=model,
            tools=[{"type": "file_search"}],
            tool_resources=tool_resources if tool_resources else None,
        )
    except Exception as e:
        raise click.ClickException(f"Failed to create assistant: {e}")

    save_assistant_id(assistant.id)
    click.echo(f"Assistant created: {assistant.id}")
    click.echo(f"Saved to {ASSISTANT_ID_FILE}")


@cli.command("generate")
@click.argument("task", required=False)
@click.option("--spec", type=click.Path(exists=True), help="Read task from a spec file.")
@click.option("--model", default=None, help="Override the assistant's model for this run.")
@click.option("--output", "-o", type=click.Path(), help="Write output to file instead of stdout.")
def generate(
    task: str | None,
    spec: str | None,
    model: str | None,
    output: str | None,
) -> None:
    """Generate Luau code from a task description using an OpenAI Assistant."""
    # Resolve task description
    if spec:
        task_description = Path(spec).read_text(encoding="utf-8")
    elif task:
        task_description = task
    else:
        raise click.ClickException(
            "Provide a task description as an argument or use --spec to read from a file."
        )

    client = get_openai_client()
    assistant_id = load_assistant_id()

    try:
        thread = client.beta.threads.create()
        client.beta.threads.messages.create(
            thread_id=thread.id, role="user", content=task_description
        )

        run_kwargs: dict = {
            "thread_id": thread.id,
            "assistant_id": assistant_id,
        }
        if model:
            run_kwargs["model"] = model

        run = client.beta.threads.runs.create_and_poll(**run_kwargs)

        if run.status != "completed":
            raise click.ClickException(
                f"Run finished with status: {run.status}. "
                f"Last error: {run.last_error}"
            )

        messages = client.beta.threads.messages.list(thread_id=thread.id)
        raw_output = messages.data[0].content[0].text.value
    except click.ClickException:
        raise
    except Exception as e:
        raise click.ClickException(f"OpenAI API error: {e}")

    code = strip_markdown_fences(raw_output)

    if output:
        out_path = Path(output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(code + "\n", encoding="utf-8")
        click.echo(f"Written to {out_path}")
    else:
        click.echo(code)


if __name__ == "__main__":
    cli()
