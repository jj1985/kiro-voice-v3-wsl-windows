"""Pure text routing, shared by the audio process and tests."""
import re


def normalize(text: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", text.casefold()))


def strip_wake(text: str, phrase: str) -> tuple[bool, str]:
    wanted = re.findall(r"[a-z0-9]+", phrase.casefold())
    found = list(re.finditer(r"[a-z0-9]+", text, flags=re.I))
    if not wanted or len(found) < len(wanted):
        return False, text.strip()
    if [match.group().casefold() for match in found[:len(wanted)]] != wanted:
        return False, text.strip()
    return True, text[found[len(wanted) - 1].end():].lstrip(" ,.!?:;-")


def control(text: str) -> tuple[str, str] | None:
    value = normalize(text)
    commands = {"stop": "cancel", "cancel": "cancel", "go to sleep": "sleep", "sleep": "sleep",
                "mute": "mute", "dont speak": "mute", "stop speaking": "mute",
                "unmute": "unmute", "start speaking": "unmute", "repeat that": "repeat"}
    if value in commands:
        return commands[value], ""
    for name in ("kiro", "claude", "codex", "copilot"):
        if value in {f"switch to {name}", f"use {name}", f"backend {name}"}:
            return "backend", name
    return None


def clean_tts(text: str, limit: int = 2500) -> str:
    text = re.sub(r"```.*?(?:```|$)", " Code is displayed in the terminal. ", text, flags=re.S)
    text = re.sub(r"\[([^]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"https?://\S+", "", text)
    text = re.sub(r"[`*_#>|]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > limit:
        text = text[:limit].rsplit(" ", 1)[0] + ". The rest is in the terminal."
    return text
