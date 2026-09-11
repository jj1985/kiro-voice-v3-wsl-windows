#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any, Optional

from backends import BACKENDS, AgentBackend, BackendError, create_backend


def wsl_to_windows(path: Path) -> str:
    return subprocess.run(
        ["wslpath", "-w", str(path)],
        check=True, text=True, capture_output=True
    ).stdout.strip()


class WindowsAudioBridge:
    def __init__(self, windows_python: str, sidecar: Path):
        self.windows_python = windows_python
        self.sidecar = sidecar
        self.proc: Optional[asyncio.subprocess.Process] = None
        self.events: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self.pending: dict[int, asyncio.Future] = {}
        self.next_id = 1
        self.reader_task: Optional[asyncio.Task] = None

    async def start(self):
        self.proc = await asyncio.create_subprocess_exec(
            self.windows_python, "-u", wsl_to_windows(self.sidecar.resolve()),
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=None
        )
        self.reader_task = asyncio.create_task(self._reader())
        while True:
            event = await self.events.get()
            if event.get("event") == "ready":
                return event

    async def _reader(self):
        assert self.proc and self.proc.stdout
        while True:
            raw = await self.proc.stdout.readline()
            if not raw:
                for fut in list(self.pending.values()):
                    if not fut.done():
                        fut.set_exception(RuntimeError("Windows audio sidecar exited"))
                await self.events.put({"event":"sidecar_exit"})
                return
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue
            rid = msg.get("id")
            if rid in self.pending and "ok" in msg:
                fut = self.pending.pop(rid)
                if msg.get("ok"):
                    fut.set_result(msg)
                else:
                    fut.set_exception(RuntimeError(msg.get("error","sidecar error")))
            else:
                await self.events.put(msg)

    async def request(self, op: str, **payload):
        assert self.proc and self.proc.stdin
        rid = self.next_id
        self.next_id += 1
        fut = asyncio.get_running_loop().create_future()
        self.pending[rid] = fut
        self.proc.stdin.write((json.dumps({"id":rid,"op":op,**payload})+"\n").encode())
        await self.proc.stdin.drain()
        return await fut

    async def close(self):
        if not self.proc:
            return
        with contextlib.suppress(Exception):
            await self.request("quit")
        if self.proc.returncode is None:
            self.proc.terminate()
        with contextlib.suppress(Exception):
            await self.proc.wait()
        if self.reader_task:
            self.reader_task.cancel()


class App:
    def __init__(self,args):
        self.args=args
        self.project=Path(args.project).expanduser().resolve()
        self.audio: Optional[WindowsAudioBridge]=None
        self.backend: Optional[AgentBackend]=None
        self.backend_name=args.backend
        self.prompt_task: Optional[asyncio.Task]=None
        self.stop=asyncio.Event()
        self.speak=os.getenv("AGENT_VOICE_SPEAK", os.getenv("KIRO_VOICE_SPEAK","1"))!="0"

    async def start(self):
        if not self.project.is_dir():
            raise SystemExit(f"Project directory does not exist: {self.project}")
        winpy=(self.args.windows_python or os.getenv("AGENT_VOICE_WINDOWS_PY")
               or os.getenv("KIRO_VOICE_WINDOWS_PY"))
        if not winpy:
            raise SystemExit(
                "Set AGENT_VOICE_WINDOWS_PY (or legacy KIRO_VOICE_WINDOWS_PY) "
                "to the Windows venv python.exe path as seen from WSL"
            )
        sidecar=Path(__file__).resolve().parents[1]/"windows"/"audio_bridge.py"
        self.audio=WindowsAudioBridge(str(Path(winpy).expanduser()),sidecar)
        ready=await self.audio.start()
        dev,cfg=ready.get("device",{}),ready.get("config",{})
        print(f'🎙 Windows microphone: {dev.get("name","<unknown>")}')
        print(f'👂 Wake phrase: {cfg.get("wake_phrase","hey kiro")!r} ({cfg.get("wake_backend","whisper_phrase")})')
        await self.switch_backend(self.backend_name, announce=False)
        print('Always listening. Say the wake phrase, type /help, or say "switch to Claude", "switch to Codex", or "switch to Kiro".')

    def _make_backend(self,name):
        model={"kiro":self.args.kiro_model,"claude":self.args.claude_model,"codex":self.args.codex_model}.get(name)
        return create_backend(
            name, model=model, kiro_agent=self.args.agent,
            claude_permission_mode=self.args.claude_permission_mode,
            codex_sandbox=self.args.codex_sandbox,
            codex_skip_git_check=self.args.codex_skip_git_check
        )

    async def switch_backend(self,name,*,announce=True):
        name=name.lower().strip()
        if name not in BACKENDS:
            print(f"Unknown backend: {name}. Choose: {', '.join(BACKENDS)}")
            return
        if self.backend and self.backend.name==name:
            if announce:
                print(f"✓ Already using {self.backend.label}")
            return
        await self.cancel()
        old=self.backend
        new=self._make_backend(name)
        try:
            await new.start(self.project)
        except Exception:
            with contextlib.suppress(Exception):
                await new.close()
            raise
        if old:
            with contextlib.suppress(Exception):
                await old.close()
        self.backend=new
        self.backend_name=name
        print(f"✓ Backend: {new.label}")
        if announce and self.audio:
            with contextlib.suppress(Exception):
                await self.audio.request("speak",text=f"Switched to {new.label}.",
                                         followup_seconds=self.args.conversation_timeout)

    async def cancel(self):
        if self.backend:
            with contextlib.suppress(Exception):
                await self.backend.cancel()
        if self.prompt_task and not self.prompt_task.done():
            current=asyncio.current_task()
            if self.prompt_task is not current:
                self.prompt_task.cancel()
                with contextlib.suppress(Exception,asyncio.CancelledError):
                    await self.prompt_task

    def _backend_switch_from_text(self,text):
        normalized=re.sub(r"[^a-z0-9 ]+"," ",text.lower())
        normalized=re.sub(r"\s+"," ",normalized).strip()
        aliases={"claude":("claude","claude code"),"codex":("codex","openai codex"),"kiro":("kiro",)}
        for name,names in aliases.items():
            for alias in names:
                if normalized in {f"switch to {alias}",f"use {alias}",f"change to {alias}",f"backend {alias}"}:
                    return name
        return None

    async def handle_prompt(self,text):
        target=self._backend_switch_from_text(text)
        if target:
            try:
                await self.switch_backend(target)
            except BackendError as exc:
                print(f"⚠ Cannot switch backend: {exc}")
            return
        await self.prompt(text)

    async def prompt(self,text):
        if not text.strip() or not self.backend:
            return
        if self.prompt_task and not self.prompt_task.done():
            await self.cancel()
        backend=self.backend
        async def run():
            print(f"\nYou (voice)> {text}\n{backend.label}> ",end="",flush=True)
            printed=False
            def on_text(chunk):
                nonlocal printed
                printed=True
                print(chunk,end="",flush=True)
            def on_status(status):
                print(f"\n🛠 {status}",flush=True)
            try:
                response=await backend.prompt(text,on_text,on_status)
            except asyncio.CancelledError:
                print(f"\n⛔ {backend.label} turn cancelled.")
                raise
            except Exception as exc:
                print(f"\n⚠ {backend.label} prompt failed: {exc}")
                if self.audio:
                    await self.audio.request("arm_followup",seconds=self.args.conversation_timeout)
                return
            if not printed and response:
                print(response,end="",flush=True)
            print()
            assert self.audio
            if self.speak and response:
                await self.audio.request("speak",text=response,followup_seconds=self.args.conversation_timeout)
            else:
                await self.audio.request("arm_followup",seconds=self.args.conversation_timeout)
        self.prompt_task=asyncio.create_task(run())

    async def events(self):
        assert self.audio
        while not self.stop.is_set():
            event=await self.audio.events.get()
            kind=event.get("event")
            if kind=="wake":
                print(f'\n🔔 Wake detected: {event.get("phrase")}')
            elif kind=="utterance":
                await self.handle_prompt(str(event.get("text","")))
            elif kind=="barge_in":
                print(f'\n🛑 Barge-in: {event.get("action")} ({event.get("text","")})')
                if event.get("action") in {"stop","cancel"}:
                    await self.cancel()
                    await self.audio.request("arm_followup",seconds=self.args.conversation_timeout)
            elif kind=="tts_started":
                print("\n🔊 Speaking…")
            elif kind=="tts_finished":
                secs=float(event.get("followup_seconds",self.args.conversation_timeout))
                await self.audio.request("arm_followup",seconds=secs)
                print(f"👂 Follow-up window open for {secs:.0f}s")
            elif kind=="sleep":
                print("\n💤 Wake-word mode.")
            elif kind=="sidecar_exit":
                print("\n⚠ Windows audio sidecar exited.")
                self.stop.set()

    async def console(self):
        assert self.audio
        while not self.stop.is_set():
            try:
                line=(await asyncio.to_thread(input," ")).strip()
            except (EOFError,KeyboardInterrupt):
                self.stop.set(); return
            if not line:
                continue
            if line=="/quit":
                self.stop.set()
            elif line=="/help":
                print("/listen /sleep /mute /unmute /cancel /status /quit\n"
                      "/backend                       show current backend\n"
                      "/backend kiro|claude|codex     switch backend")
            elif line=="/listen":
                await self.audio.request("force_listen")
            elif line=="/sleep":
                await self.audio.request("sleep")
            elif line=="/mute":
                self.speak=False
                await self.audio.request("stop_speaking")
                print("🔇 TTS muted.")
            elif line=="/unmute":
                self.speak=True
                print("🔊 TTS enabled.")
            elif line=="/cancel":
                await self.audio.request("stop_speaking")
                await self.cancel()
            elif line=="/status":
                status=(await self.audio.request("status")).get("result",{})
                status["backend"]=self.backend.name if self.backend else None
                print(json.dumps(status,indent=2))
            elif line=="/backend":
                print(f"Backend: {self.backend.label if self.backend else 'none'}")
            elif line.startswith("/backend "):
                target=line.split(maxsplit=1)[1].strip().lower()
                try:
                    await self.switch_backend(target)
                except BackendError as exc:
                    print(f"⚠ Cannot switch backend: {exc}")
            elif line.startswith("/"):
                print("Unknown command. Type /help.")
            else:
                await self.handle_prompt(line)

    async def run(self):
        await self.start()
        et=asyncio.create_task(self.events())
        ct=asyncio.create_task(self.console())
        try:
            await self.stop.wait()
        finally:
            et.cancel(); ct.cancel()
            await self.cancel()
            if self.backend:
                with contextlib.suppress(Exception):
                    await self.backend.close()
            if self.audio:
                await self.audio.close()


def args():
    p=argparse.ArgumentParser(description="Always-listening voice frontend for Kiro, Claude Code, and Codex CLI on WSL + Windows")
    p.add_argument("--project",default=".")
    p.add_argument("--backend",choices=BACKENDS,
                   default=os.getenv("AGENT_VOICE_BACKEND",os.getenv("KIRO_VOICE_BACKEND","kiro")))
    p.add_argument("--agent",help="Kiro custom agent")
    p.add_argument("--windows-python")
    p.add_argument("--kiro-model")
    p.add_argument("--claude-model")
    p.add_argument("--codex-model")
    p.add_argument("--claude-permission-mode",default=os.getenv("AGENT_VOICE_CLAUDE_PERMISSION_MODE"))
    p.add_argument("--codex-sandbox",choices=("read-only","workspace-write","danger-full-access"),
                   default=os.getenv("AGENT_VOICE_CODEX_SANDBOX"))
    p.add_argument("--codex-skip-git-check",action="store_true",
                   default=os.getenv("AGENT_VOICE_CODEX_SKIP_GIT_CHECK","0")=="1")
    p.add_argument("--conversation-timeout",type=float,
                   default=float(os.getenv("AGENT_VOICE_CONVERSATION_TIMEOUT",
                                           os.getenv("KIRO_VOICE_CONVERSATION_TIMEOUT","30"))))
    return p.parse_args()


if __name__=="__main__":
    asyncio.run(App(args()).run())
