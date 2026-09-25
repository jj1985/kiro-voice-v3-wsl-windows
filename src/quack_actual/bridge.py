"""The same audio sidecar runs locally on Windows or across WSL interop."""
from __future__ import annotations

import asyncio
import contextlib
import json
import os
from pathlib import Path
import sys
from .process import spawn, terminate


def is_wsl() -> bool:
    return os.name != "nt" and ("WSL_DISTRO_NAME" in os.environ or "WSL_INTEROP" in os.environ)


def audio_command(windows_python=None):
    if is_wsl():
        candidate = windows_python or os.environ.get("QUACK_ACTUAL_WINDOWS_PYTHON")
        if not candidate:
            # Installed wheels have no adjacent source checkout. The Linux venv
            # and Windows venv are siblings created by the provided installers.
            root = Path(sys.prefix).parent if Path(sys.prefix).name == ".venv-wsl" else Path(__file__).resolve().parents[2]
            candidate = root / ".venv/Scripts/python.exe"
        candidate = Path(candidate).expanduser()
        if not Path(candidate).is_file():
            raise RuntimeError("WSL needs the Windows audio environment. Run install.ps1 in the same shared checkout or pass --windows-python /mnt/c/.../.venv/Scripts/python.exe.")
        return [str(candidate), "-X", "utf8", "-u", "-m", "quack_actual.audio"]
    return [sys.executable, "-X", "utf8", "-u", "-m", "quack_actual.audio"]


class AudioBridge:
    def __init__(self, cfg, windows_python=None):
        self.cfg, self.windows_python = cfg, windows_python
        self.proc = None
        self.events = asyncio.Queue()
        self.pending = {}
        self.next_id = 0
        self.reader = None
        self.ready = None
        self.lock = asyncio.Lock()

    async def start(self):
        self.ready = asyncio.get_running_loop().create_future()
        self.proc = await spawn(audio_command(self.windows_python))
        self.reader = asyncio.create_task(self._read())
        try:
            await self.request("configure", config=self.cfg)
            return await asyncio.wait_for(self.ready, 30)
        except BaseException:
            await self.close()
            raise

    async def request(self, op, **payload):
        if not self.proc or self.proc.returncode is not None:
            raise RuntimeError("Audio process is not running")
        self.next_id += 1
        rid = self.next_id
        future = asyncio.get_running_loop().create_future()
        self.pending[rid] = future
        try:
            async with self.lock:
                self.proc.stdin.write((json.dumps({"id": rid, "op": op, **payload}) + "\n").encode())
                await self.proc.stdin.drain()
            return await asyncio.wait_for(future, 15)
        finally:
            self.pending.pop(rid, None)

    async def _read(self):
        error = RuntimeError("Audio process closed")
        try:
            while raw := await self.proc.stdout.readline():
                msg = json.loads(raw)
                if "id" in msg and "ok" in msg:
                    future = self.pending.get(msg["id"])
                    if future and not future.done():
                        if msg["ok"]:
                            future.set_result(msg)
                        else:
                            future.set_exception(RuntimeError(msg.get("error", "Audio error")))
                elif msg.get("event") == "ready":
                    if not self.ready.done():
                        self.ready.set_result(msg)
                elif msg.get("event") == "fatal":
                    error = RuntimeError(msg.get("error", "Audio failed"))
                    break
                else:
                    await self.events.put(msg)
        except Exception as exc:
            error = exc
        finally:
            for future in list(self.pending.values()):
                if not future.done():
                    future.set_exception(error)
            if self.ready and not self.ready.done():
                self.ready.set_exception(error)
            await self.events.put({"event": "fatal", "error": str(error)})

    async def close(self):
        if self.proc and self.proc.returncode is None:
            with contextlib.suppress(Exception):
                await asyncio.wait_for(self.request("quit"), 2)
            await terminate(self.proc)
        if self.reader:
            self.reader.cancel()
            await asyncio.gather(self.reader, return_exceptions=True)
        if self.ready and self.ready.done() and not self.ready.cancelled():
            self.ready.exception()  # retrieve startup errors even when configure failed first
