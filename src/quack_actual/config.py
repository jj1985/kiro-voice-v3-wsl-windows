"""User-owned configuration; no credentials or transcripts are persisted."""
from __future__ import annotations

import copy
import json
import math
import os
from pathlib import Path

DEFAULTS = {
    "backend": "copilot",
    "wake_phrase": "quack actual",
    "conversation_seconds": 30.0,
    "arm_seconds": 10.0,
    "wake_model": "tiny.en",
    "command_model": "small.en",
    "device": "cpu",
    "compute_type": "int8",
    "microphone": None,
    "rms_threshold": 0.012,
    "silence_seconds": 0.85,
    "max_utterance_seconds": 30.0,
    "barge_in": True,
    "tts": True,
    "tts_rate": 190,
    "tts_max_chars": 2500,
    "activation_sound": True,
    "windows_python": "",
    "commands": {},
}
BACKENDS = ("copilot", "claude", "codex", "kiro")


def default_path() -> Path:
    if os.name == "nt":
        return Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local")) / "QuackActual/config.json"
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "quack-actual/config.json"


def load(path: str | Path | None = None) -> dict:
    file = Path(path or os.environ.get("QUACK_ACTUAL_CONFIG") or default_path()).expanduser()
    result = copy.deepcopy(DEFAULTS)
    if file.exists():
        values = json.loads(file.read_text(encoding="utf-8-sig"))
        if not isinstance(values, dict):
            raise ValueError("Configuration must be a JSON object")
        unknown = set(values) - set(DEFAULTS)
        if unknown:
            raise ValueError(f"Unknown configuration keys: {', '.join(sorted(unknown))}")
        result.update(values)
    validate(result)
    return result


def validate(cfg: dict) -> None:
    if cfg["backend"] not in BACKENDS:
        raise ValueError("backend must be copilot, claude, codex, or kiro")
    if not isinstance(cfg["wake_phrase"], str) or not cfg["wake_phrase"].strip():
        raise ValueError("wake_phrase cannot be empty")
    for key in ("conversation_seconds", "arm_seconds", "rms_threshold", "silence_seconds", "max_utterance_seconds"):
        value = cfg[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
            raise ValueError(f"{key} must be a finite positive number")
    if cfg["max_utterance_seconds"] > 120 or cfg["rms_threshold"] >= 1:
        raise ValueError("max_utterance_seconds must be <=120 and rms_threshold <1")
    for key in ("tts", "activation_sound", "barge_in"):
        if not isinstance(cfg[key], bool):
            raise ValueError(f"{key} must be true or false")
    for key in ("tts_rate", "tts_max_chars"):
        if not isinstance(cfg[key], int) or isinstance(cfg[key], bool) or cfg[key] <= 0:
            raise ValueError(f"{key} must be a positive integer")
    if cfg["microphone"] is not None and not isinstance(cfg["microphone"], (int, str)):
        raise ValueError("microphone must be null, an index, or a device-name substring")
    if not isinstance(cfg["commands"], dict):
        raise ValueError("commands must be a mapping of backend names to argument lists")
    for name, command in cfg["commands"].items():
        if name not in BACKENDS or not isinstance(command, list) or not command:
            raise ValueError("Each command override must be a nonempty argument list for a supported backend")
        if any(not isinstance(arg, str) or not arg or "\x00" in arg for arg in command):
            raise ValueError("Command arguments must be nonempty strings without NUL characters")


def init(path: str | Path | None = None) -> Path:
    file = Path(path or os.environ.get("QUACK_ACTUAL_CONFIG") or default_path()).expanduser()
    file.parent.mkdir(parents=True, exist_ok=True)
    if not file.exists():
        with file.open("x", encoding="utf-8") as out:
            json.dump(DEFAULTS, out, indent=2)
            out.write("\n")
    return file
