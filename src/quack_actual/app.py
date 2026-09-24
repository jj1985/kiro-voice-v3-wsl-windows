"""One controller and one keyboard reader for Windows, Linux, and WSL."""
from __future__ import annotations

import asyncio
import contextlib
import json
import sys
import threading
from .backends import Backend
from .bridge import AudioBridge
from .config import BACKENDS
from .speech import control


class App:
    def __init__(self, args, cfg):
        self.args, self.cfg = args, cfg
        self.sessions = {}
        self.selected = args.backend or cfg["backend"]
        self.audio = None
        self.turn = None
        self.generation = 0
        self.stopping = asyncio.Event()
        self.permission_future = None
        self.permission_options = []
        self.permission_lock = asyncio.Lock()
        self.lines = asyncio.Queue()
        self.speaking = cfg["tts"]
        self.last_reply = ""

    async def audio_op(self, op, **params):
        if self.audio:
            await self.audio.request(op, **params)

    async def permission(self, backend, call, options):
        async with self.permission_lock:
            if self.stopping.is_set() or not options:
                return None
            self.permission_options = options
            future = self.permission_future = asyncio.get_running_loop().create_future()
            print(f"\n[{backend}] Permission requested: {call.get('title', 'Tool action')}")
            # Show full tool details in the terminal, not just a misleading label.
            print(json.dumps(call, indent=2, ensure_ascii=True))
            for index, option in enumerate(options, 1):
                print(f"  {index}: {option.get('name')} ({option.get('kind')})")
            print("Type /approve N to select that option, or /deny. Voice never grants permission.")
            try:
                return await asyncio.wait_for(future, 120)
            except asyncio.TimeoutError:
                print("Permission request timed out; denied.")
                return None
            finally:
                if self.permission_future is future:
                    self.permission_future = None
                    self.permission_options = []

    async def switch(self, name):
        if name not in BACKENDS:
            raise ValueError(f"Choose one of: {', '.join(BACKENDS)}")
        await self.cancel()
        if name not in self.sessions:
            backend = Backend(
                name, self.args.project, self.cfg, self.permission,
                model=self.args.model if name == (self.args.backend or self.cfg["backend"]) else None,
                sandbox=self.args.codex_sandbox, agent=self.args.kiro_agent,
            )
            try:
                await backend.start()
            except BaseException:
                await backend.close()
                raise
            self.sessions[name] = backend
        self.selected = name
        print(f"\nQuack Actual | {name} | {self.args.project}")
        await self.audio_op("state", mode="followup")

    async def cancel(self):
        self.generation += 1
        if self.permission_future and not self.permission_future.done():
            self.permission_future.set_result(None)
        await self.audio_op("stop_speaking")
        task = self.turn
        backend = self.sessions.get(self.selected)
        if task and not task.done() and backend:
            await backend.cancel()
            try:
                await asyncio.wait_for(asyncio.shield(task), 3)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
                # An uncooperative agent cannot leak late chunks into a new turn.
                await backend.close()
                self.sessions.pop(self.selected, None)
        self.turn = None

    async def prompt(self, text):
        if self.permission_future:
            print("Resolve the pending permission in the terminal, or say the wake phrase and cancel.")
            return
        await self.cancel()
        if self.selected not in self.sessions:
            await self.switch(self.selected)
        backend = self.sessions[self.selected]
        token = self.generation
        await self.audio_op("state", mode="busy")

        async def run():
            print(f"\nYou> {text}\n{backend.name}> ", end="", flush=True)
            try:
                response = await asyncio.wait_for(backend.prompt(
                    text,
                    lambda part: print(part.replace("\x1b", ""), end="", flush=True),
                    lambda status: print(f"\n[{status}]", flush=True),
                ), self.args.turn_timeout)
                if token != self.generation:
                    return
                print()
                self.last_reply = response
                if self.speaking and response and self.audio:
                    await self.audio_op("speak", text=response, token=token)
                else:
                    await self.audio_op("state", mode="followup")
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                if token == self.generation:
                    print(f"\n{backend.name}: {exc}")
                    await backend.close()
                    self.sessions.pop(backend.name, None)
                    await self.audio_op("state", mode="followup")
        self.turn = asyncio.create_task(run())

    async def command(self, text, voice=False):
        if voice:
            match = control(text)
            if match:
                text = "/" + match[0] + (" " + match[1] if match[1] else "")
            elif text.startswith("/"):
                print("Slash commands require keyboard input.")
                return
        word, _, value = text.partition(" ")
        if word == "/quit":
            self.stopping.set()
        elif word == "/help":
            print("/backend NAME /new /listen /sleep /mute /unmute /repeat /cancel /status /quit\n"
                  "/approve N /deny (keyboard only); other text is a prompt")
        elif word == "/backend":
            if value.strip():
                await self.switch(value.strip().lower())
            else:
                print(f"Selected: {self.selected}; cached sessions: {', '.join(self.sessions)}")
        elif word in {"/approve", "/deny"}:
            if voice or not self.permission_future or self.permission_future.done():
                print("No keyboard permission request is pending.")
            elif word == "/deny":
                self.permission_future.set_result(None)
            elif value.strip().isdigit() and 1 <= int(value) <= len(self.permission_options):
                self.permission_future.set_result(self.permission_options[int(value) - 1]["optionId"])
            else:
                print("Use /approve followed by a displayed option number, or /deny.")
        elif word == "/cancel":
            await self.cancel()
            await self.audio_op("state", mode="followup")
        elif word == "/new":
            await self.cancel()
            backend = self.sessions.pop(self.selected, None)
            if backend:
                await backend.close()
            await self.switch(self.selected)
        elif word in {"/sleep", "/listen"}:
            await self.cancel()
            await self.audio_op("state", mode=word[1:])
        elif word == "/mute":
            self.speaking = False
            await self.audio_op("stop_speaking")
            await self.audio_op("state", mode="followup")
        elif word == "/unmute":
            self.speaking = True
            await self.audio_op("state", mode="followup")
        elif word == "/repeat":
            if self.last_reply and self.speaking:
                await self.audio_op("speak", text=self.last_reply, token=self.generation)
        elif word == "/status":
            print(json.dumps({"backend": self.selected, "sessions": list(self.sessions), "audio": bool(self.audio),
                              "turn_active": bool(self.turn and not self.turn.done()), "tts": self.speaking}, indent=2))
        elif word.startswith("/"):
            print("Unknown local command. Type /help.")
        elif text.strip():
            await self.prompt(text)

    async def events(self):
        while not self.stopping.is_set():
            event = await self.audio.events.get()
            kind = event.get("event")
            try:
                if kind == "utterance":
                    await self.command(event["text"], voice=True)
                elif kind == "interrupt":
                    await self.cancel()
                elif kind == "tts_finished" and event.get("token") == self.generation:
                    await self.audio_op("state", mode="followup")
                    print(f"\nListening for a follow-up ({self.cfg['conversation_seconds']:g}s).")
                elif kind == "fatal":
                    print(f"\nAudio stopped: {event.get('error')}")
                    self.stopping.set()
                elif kind in {"warning", "status"}:
                    print(f"\nAudio: {event.get('error') or event.get('text')}")
                elif kind == "wake":
                    print("\nRadio check. Listening.")
            except Exception as exc:
                print(f"\nVoice command failed: {exc}")
                with contextlib.suppress(Exception):
                    await self.audio_op("state", mode="sleep")

    def start_keyboard(self):
        loop = asyncio.get_running_loop()

        def read():
            while not loop.is_closed():
                line = sys.stdin.readline()
                try:
                    loop.call_soon_threadsafe(self.lines.put_nowait, line if line else None)
                except RuntimeError:
                    return
                if not line:
                    return
        # Unlike asyncio.to_thread(input), this cannot block interpreter shutdown.
        threading.Thread(target=read, daemon=True).start()

    async def keyboard(self):
        while not self.stopping.is_set():
            line = await self.lines.get()
            if line is None:
                self.stopping.set()
                return
            try:
                await self.command(line.strip())
            except Exception as exc:
                print(f"\nCommand failed: {exc}")

    async def run(self):
        tasks = []
        try:
            # Resolve/authenticate the agent before enabling an always-on microphone.
            await self.switch(self.selected)
            if not self.args.text_only:
                self.audio = AudioBridge(self.cfg, self.args.windows_python or self.cfg["windows_python"])
                ready = await self.audio.start()
                print(f"Microphone: {ready['microphone']} | Wake phrase: {self.cfg['wake_phrase']!r}")
                tasks.append(asyncio.create_task(self.events()))
            print("Type /help for commands. Permissions require the keyboard. Ctrl+C exits.")
            self.start_keyboard()
            tasks.append(asyncio.create_task(self.keyboard()))
            await self.stopping.wait()
        finally:
            self.stopping.set()
            with contextlib.suppress(Exception):
                await self.cancel()
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            for backend in list(self.sessions.values()):
                with contextlib.suppress(Exception):
                    await backend.close()
            if self.audio:
                await self.audio.close()
