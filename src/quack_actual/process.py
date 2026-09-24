"""Cross-platform subprocesses: never interpolate prompts into a shell."""
from __future__ import annotations

import asyncio
import contextlib
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess

PACKAGES = {
    "copilot": "@github/copilot",
    "claude": "@anthropic-ai/claude-code",
    "codex": "@openai/codex",
}


def resolve_command(name: str, override: list[str] | None = None) -> list[str]:
    command = list(override or ["kiro-cli" if name == "kiro" else name])
    executable = shutil.which(command[0])
    if executable is None:
        raise RuntimeError(f"{name}: {command[0]!r} is not on PATH. Install and sign in to that CLI first.")
    path = Path(executable)
    if path.suffix.lower() in {".cmd", ".bat", ".ps1"}:
        # npm's Windows shim is a shell script. Read its package bin metadata and
        # launch Node directly, avoiding cmd.exe quoting and prompt injection.
        package = PACKAGES.get(name)
        metadata = path.parent / "node_modules" / (package or "") / "package.json"
        if not package or not metadata.is_file():
            raise RuntimeError(f"Cannot safely resolve {path}. Install a native binary or set commands.{name} to [executable, script].")
        data = json.loads(metadata.read_text(encoding="utf-8"))
        bins = data.get("bin", {})
        entry = bins if isinstance(bins, str) else bins.get(name)
        if not entry:
            raise RuntimeError(f"No {name} entry in {metadata}")
        script = (metadata.parent / entry).resolve()
        if not script.is_file() or not script.is_relative_to(metadata.parent.resolve()):
            raise RuntimeError(f"Invalid npm entry point: {script}")
        node = path.parent / "node.exe"
        node_executable = str(node) if node.is_file() else shutil.which("node")
        if not node_executable:
            raise RuntimeError("Node.js is required by this npm-installed CLI")
        return [node_executable, str(script), *command[1:]]
    return [str(path), *command[1:]]


async def spawn(command: list[str], cwd: Path | None = None) -> asyncio.subprocess.Process:
    options = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt" else {"start_new_session": True}
    return await asyncio.create_subprocess_exec(
        *command, cwd=cwd, stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE, stderr=None,
        limit=8 * 1024 * 1024, **options,
    )


async def terminate(proc: asyncio.subprocess.Process | None) -> None:
    if proc is None or proc.returncode is not None:
        return
    if os.name == "nt":
        # Only this application's child tree, never unrelated CLI processes.
        killer = await asyncio.create_subprocess_exec(
            "taskkill.exe", "/PID", str(proc.pid), "/T", "/F",
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
        )
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(killer.wait(), 5)
    else:
        with contextlib.suppress(ProcessLookupError):
            os.killpg(proc.pid, signal.SIGTERM)
    try:
        await asyncio.wait_for(proc.wait(), 3)
    except asyncio.TimeoutError:
        with contextlib.suppress(ProcessLookupError):
            if os.name == "nt":
                proc.kill()
            else:
                os.killpg(proc.pid, signal.SIGKILL)
        await asyncio.wait_for(proc.wait(), 3)
