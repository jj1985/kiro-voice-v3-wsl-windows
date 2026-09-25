"""User-facing commands; diagnostics work without audio dependencies."""
from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
from . import __version__
from . import config
from .bridge import audio_command, is_wsl
from .process import resolve_command


def doctor(cfg, backend=None, text_only=False):
    backend = backend or cfg["backend"]
    print(f"Quack Actual {__version__}\nPlatform: {platform.system()} {platform.release()} ({platform.machine()})")
    print(f"Python: {sys.version.split()[0]}\nInterpreter: {sys.executable}")
    venv = sys.prefix != sys.base_prefix
    print(f"Virtual environment: {'yes' if venv else 'NO - use the installer or uv run'}")
    print(f"uv: {shutil.which('uv') or 'not on PATH (launchers can still use the installed venv)'}")
    failed = not venv
    for name in config.BACKENDS:
        try:
            command = resolve_command(name, cfg["commands"].get(name))
            response = subprocess.run(command + ["--version"], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=10)
            if response.returncode:
                raise RuntimeError(f"version probe returned {response.returncode}")
            print(f"{name}: {(response.stdout or response.stderr).strip()[:150]}")
        except (RuntimeError, OSError, subprocess.TimeoutExpired) as exc:
            print(f"{name}: unavailable ({exc})")
            failed |= name == backend
    if not text_only:
        if is_wsl():
            try:
                command = audio_command(cfg.get("windows_python"))
                print(f"WSL Windows-audio interpreter: {command[0]}")
            except RuntimeError as exc:
                print(exc)
                failed = True
        else:
            for module in ("sounddevice", "numpy", "faster_whisper", "pyttsx3"):
                installed = importlib.util.find_spec(module) is not None
                print(f"{module}: {'installed' if installed else 'MISSING; rerun install with voice enabled'}")
                failed |= not installed
    print("No login or microphone capture was performed. Run devices, then a live voice smoke test.")
    return int(failed)


def parser():
    ap = argparse.ArgumentParser(description="Quack Actual - One voice. Every agent.")
    ap.add_argument("--version", action="version", version=__version__)
    subs = ap.add_subparsers(dest="command", required=True)
    start = subs.add_parser("start", help="Start the voice or text console")
    start.add_argument("--backend", choices=config.BACKENDS, default=os.environ.get("QUACK_ACTUAL_BACKEND"))
    start.add_argument("--project", type=Path, default=Path.cwd())
    start.add_argument("--text-only", action="store_true")
    start.add_argument("--windows-python", help="WSL path to the Windows .venv/Scripts/python.exe")
    start.add_argument("--model", help="Model for the initially selected backend")
    start.add_argument("--kiro-agent")
    start.add_argument("--codex-sandbox", choices=("read-only", "workspace-write"), default="read-only")
    start.add_argument("--turn-timeout", type=float, default=900)
    diag = subs.add_parser("doctor", help="Check interpreters, environments, and installed CLIs")
    diag.add_argument("--backend", choices=config.BACKENDS)
    diag.add_argument("--text-only", action="store_true")
    settings = subs.add_parser("config", help="Create or locate your configuration without overwriting it")
    settings.add_argument("action", choices=("init", "path"), default="path", nargs="?")
    subs.add_parser("devices", help="List input/output devices in this operating system")
    subs.add_parser("download-models", help="Download the configured local speech models")
    for sub in subs.choices.values():
        sub.add_argument("--config", dest="config_path")
    return ap


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        if args.command == "config":
            print(config.init(args.config_path) if args.action == "init" else config.resolve_path(args.config_path))
            return 0
        cfg = config.load(args.config_path)
        if args.command == "doctor":
            return doctor(cfg, args.backend, args.text_only)
        if args.command == "devices":
            import sounddevice as sd
            print(sd.query_devices())
            return 0
        if args.command == "download-models":
            from .audio import download_models
            download_models(cfg)
            return 0
        args.project = args.project.expanduser().resolve()
        if not args.project.is_dir():
            raise ValueError(f"Project directory does not exist: {args.project}")
        if not 0 < args.turn_timeout < float("inf"):
            raise ValueError("turn-timeout must be a finite positive number")
        from .app import App
        asyncio.run(App(args, cfg).run())
        return 0
    except KeyboardInterrupt:
        print("\nQuack Actual: off the air.")
        return 130
    except (OSError, RuntimeError, ValueError, ImportError, TimeoutError) as exc:
        print(f"Quack Actual: {exc}", file=sys.stderr)
        return 1
