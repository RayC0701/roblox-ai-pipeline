#!/usr/bin/env python3
"""Autonomous pipeline watcher — polls an input queue directory for new specs.

Designed to work with a Claude Max subscription via the `claude` CLI,
eliminating the need for an ANTHROPIC_API_KEY.

Usage:
    # Watch for new specs (default: every 30s)
    python scripts/watch_queue.py

    # Custom interval and generator
    python scripts/watch_queue.py --interval 60 --generator blender

    # One-shot: process queue once and exit
    python scripts/watch_queue.py --once

Queue directory structure (queue/):
    queue/
      pending/       <- Drop .yaml job files here
      processing/    <- Jobs move here while running
      done/          <- Completed jobs land here
      failed/        <- Failed jobs land here

Job file format (.yaml):
    prompt: "Low-poly medieval sword"
    name: "Medieval Sword"
    spec: prompts/templates/combat-system.md
    output: src/server/CombatSystem.server.luau   # optional
    generator: meshy                                # optional (meshy|blender)
    art_style: cartoon                              # optional
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import click
import yaml
from dotenv import load_dotenv

load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parent.parent
QUEUE_DIR = PROJECT_ROOT / "queue"
PENDING = QUEUE_DIR / "pending"
PROCESSING = QUEUE_DIR / "processing"
DONE = QUEUE_DIR / "done"
FAILED = QUEUE_DIR / "failed"
LOG_FILE = PROJECT_ROOT / "logs" / "watcher.log"


def ensure_queue_dirs() -> None:
    """Create queue subdirectories if they don't exist."""
    for d in (PENDING, PROCESSING, DONE, FAILED):
        d.mkdir(parents=True, exist_ok=True)
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)


def log(msg: str) -> None:
    """Log to both stdout and the watcher log file."""
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    click.echo(line)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


def process_job(job_path: Path, generator: str, use_claude_cli: bool) -> bool:
    """Process a single job file through the pipeline.

    Args:
        job_path: Path to the .yaml job file (in processing/).
        generator: Default 3D generator (meshy or blender).
        use_claude_cli: If True, pass --claude-cli to generate_luau.py.

    Returns:
        True if the job succeeded.
    """
    try:
        job = yaml.safe_load(job_path.read_text(encoding="utf-8"))
    except Exception as e:
        log(f"  ERROR: Failed to parse {job_path.name}: {e}")
        return False

    prompt = job.get("prompt", "")
    name = job.get("name", "")
    spec = job.get("spec", "")

    if not prompt or not name or not spec:
        log(f"  ERROR: Job {job_path.name} missing required fields (prompt, name, spec)")
        return False

    # Build pipeline command
    cmd = [
        str(PROJECT_ROOT / "scripts" / "pipeline.sh"),
        "--prompt", prompt,
        "--name", name,
        "--spec", str(PROJECT_ROOT / spec),
        "--generator", job.get("generator", generator),
    ]

    if job.get("output"):
        cmd += ["--output", str(PROJECT_ROOT / job["output"])]
    if job.get("art_style"):
        cmd += ["--art-style", job["art_style"]]

    # Set env var so pipeline.sh passes --claude-cli to generate_luau.py
    env = None
    if use_claude_cli:
        import os
        env = {**os.environ, "USE_CLAUDE_CLI": "1"}

    log(f"  Running: {' '.join(cmd)}")

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=600,  # 10 minute timeout per job
            env=env,
        )

        if result.returncode != 0:
            log(f"  FAILED (exit {result.returncode})")
            if result.stderr:
                log(f"  stderr: {result.stderr[:500]}")
            return False

        log(f"  SUCCESS")
        if result.stdout:
            # Log last few lines of output
            lines = result.stdout.strip().split("\n")
            for line in lines[-5:]:
                log(f"    {line}")
        return True

    except subprocess.TimeoutExpired:
        log(f"  ERROR: Job timed out after 600s")
        return False
    except Exception as e:
        log(f"  ERROR: {e}")
        return False


def process_queue(generator: str, use_claude_cli: bool) -> int:
    """Process all pending jobs in the queue.

    Returns:
        Number of jobs processed.
    """
    pending_jobs = sorted(PENDING.glob("*.yaml")) + sorted(PENDING.glob("*.yml"))

    if not pending_jobs:
        return 0

    log(f"Found {len(pending_jobs)} pending job(s)")
    processed = 0

    for job_file in pending_jobs:
        job_name = job_file.name
        log(f"Processing: {job_name}")

        # Move to processing/
        processing_path = PROCESSING / job_name
        shutil.move(str(job_file), str(processing_path))

        success = process_job(processing_path, generator, use_claude_cli)
        processed += 1

        # Move to done/ or failed/
        dest = DONE if success else FAILED
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        final_name = f"{ts}_{job_name}"
        shutil.move(str(processing_path), str(dest / final_name))

    return processed


@click.command()
@click.option("--interval", default=30, show_default=True, help="Polling interval in seconds.")
@click.option("--generator", default="blender", show_default=True, help="Default 3D generator (meshy|blender).")
@click.option("--claude-cli", "use_claude_cli", is_flag=True, default=True,
              help="Use claude CLI instead of API (default, works with Max subscription).")
@click.option("--api", "use_api", is_flag=True, help="Use Anthropic API directly instead of claude CLI.")
@click.option("--once", is_flag=True, help="Process queue once and exit (no polling).")
def main(interval: int, generator: str, use_claude_cli: bool, use_api: bool, once: bool) -> None:
    """Watch the queue/ directory for new pipeline jobs and process them.

    Drop .yaml job files into queue/pending/ and this watcher will
    automatically run the full pipeline for each one.

    Works with Claude Max subscription — no API key needed.
    """
    if use_api:
        use_claude_cli = False

    ensure_queue_dirs()

    log("Pipeline watcher started")
    log(f"  Queue dir : {QUEUE_DIR}")
    log(f"  Generator : {generator}")
    log(f"  Mode      : {'claude CLI (Max subscription)' if use_claude_cli else 'Anthropic API'}")
    log(f"  Interval  : {'one-shot' if once else f'{interval}s'}")

    if once:
        n = process_queue(generator, use_claude_cli)
        log(f"Processed {n} job(s). Exiting.")
        return

    try:
        while True:
            process_queue(generator, use_claude_cli)
            time.sleep(interval)
    except KeyboardInterrupt:
        log("Watcher stopped (Ctrl+C)")


if __name__ == "__main__":
    main()
