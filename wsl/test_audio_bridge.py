#!/usr/bin/env python3
import asyncio
import os
from pathlib import Path
from kiro_voice import WindowsAudioBridge

async def main():
    py = os.getenv("KIRO_VOICE_WINDOWS_PY")
    if not py:
        raise SystemExit("Set KIRO_VOICE_WINDOWS_PY first")
    sidecar = Path(__file__).resolve().parents[1] / "windows" / "audio_bridge.py"
    b = WindowsAudioBridge(py, sidecar)
    ready = await b.start()
    print("Ready:", ready)
    print("Say the configured wake phrase. Press Ctrl+C when done.")
    try:
        while True:
            print(await b.events.get())
    finally:
        await b.close()

asyncio.run(main())
