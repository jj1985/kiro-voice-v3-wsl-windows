#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import contextlib
import json
import os
import shutil
import signal
from pathlib import Path
from typing import Callable, Optional

TextCallback = Callable[[str], None]
StatusCallback = Callable[[str], None]


class BackendError(RuntimeError):
    pass


class AgentBackend:
    name = "base"
    label = "Agent"

    def __init__(self, *, model: Optional[str] = None):
        self.model = model
        self.project: Optional[Path] = None

    async def start(self, project: Path) -> None:
        self.project = project

    async def prompt(self, text: str, on_text: TextCallback, on_status: StatusCallback) -> str:
        raise NotImplementedError

    async def cancel(self) -> None:
        pass

    async def close(self) -> None:
        await self.cancel()


def _require_binary(binary: str, label: str) -> str:
    resolved = shutil.which(binary)
    if resolved is None:
        raise BackendError(f"{label} binary {binary!r} was not found in WSL PATH")
    return resolved


async def _terminate_process(proc: Optional[asyncio.subprocess.Process]) -> None:
    if not proc or proc.returncode is not None:
        return
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        proc.terminate()
    try:
        await asyncio.wait_for(proc.wait(), timeout=2.0)
    except asyncio.TimeoutError:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            proc.kill()
        with contextlib.suppress(Exception):
            await proc.wait()


class KiroBackend(AgentBackend):
    name = "kiro"
    label = "Kiro"

    def __init__(self, *, model: Optional[str] = None, agent: Optional[str] = None):
        super().__init__(model=model)
        self.agent = agent
        self.proc = None
        self.conn = None
        self.session_id = None
        self.client = None

    async def start(self, project: Path) -> None:
        await super().start(project)
        try:
            from acp import PROTOCOL_VERSION, connect_to_agent
            from acp.schema import ClientCapabilities, Implementation
        except ImportError as exc:
            raise BackendError("Kiro backend requires agent-client-protocol; run wsl/setup.sh") from exc
        binary = _require_binary(
            os.getenv("AGENT_VOICE_KIRO_BIN", os.getenv("KIRO_VOICE_KIRO_BIN", "kiro-cli")),
            "Kiro CLI",
        )
        self.client = _make_kiro_client()
        cmd = [binary, "acp"] + (["--agent", self.agent] if self.agent else [])
        self.proc = await asyncio.create_subprocess_exec(
            *cmd, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=None, cwd=str(project), start_new_session=True
        )
        assert self.proc.stdin and self.proc.stdout
        self.conn = connect_to_agent(self.client, self.proc.stdin, self.proc.stdout)
        await self.conn.initialize(
            protocol_version=PROTOCOL_VERSION,
            client_capabilities=ClientCapabilities(),
            client_info=Implementation(name="agent-voice", title="Agent Voice", version="0.4.0"),
        )
        session = await self.conn.new_session(mcp_servers=[], cwd=str(project))
        self.session_id = session.session_id

    async def prompt(self, text, on_text, on_status):
        from acp.schema import TextContentBlock
        assert self.conn and self.session_id and self.client
        self.client.begin(on_text, on_status)
        await self.conn.prompt(session_id=self.session_id, prompt=[TextContentBlock(text=text)])
        return self.client.response_text()

    async def cancel(self):
        if self.conn and self.session_id:
            with contextlib.suppress(Exception):
                await self.conn.cancel(session_id=self.session_id)

    async def close(self):
        await self.cancel()
        await _terminate_process(self.proc)
        self.proc = None


def _make_kiro_client():
    from acp import Client, RequestError
    from acp.schema import (
        AgentMessageChunk, AllowedOutcome, DeclineElicitationResponse,
        DeniedOutcome, RequestPermissionResponse, TextContentBlock,
    )

    class KiroClient(Client):
        def __init__(self):
            self.reply = []
            self.on_text = lambda _s: None
            self.on_status = lambda _s: None

        def begin(self, on_text, on_status):
            self.reply.clear()
            self.on_text = on_text
            self.on_status = on_status

        def response_text(self):
            return "".join(self.reply).strip()

        async def request_permission(self, session_id, tool_call, options, **kwargs):
            del session_id, kwargs
            title = getattr(tool_call, "title", None) or "tool action"
            print(f"\n🔐 Kiro permission requested: {title}")
            if not options:
                return RequestPermissionResponse(outcome=DeniedOutcome(outcome="cancelled"))
            for i, opt in enumerate(options, 1):
                print(f"  {i}. {getattr(opt, 'name', 'option')} [{getattr(opt, 'kind', '')}]")
            while True:
                choice = (await asyncio.to_thread(input, "Permission> ")).strip()
                if choice.isdigit() and 1 <= int(choice) <= len(options):
                    opt = options[int(choice) - 1]
                    kind = str(getattr(opt, "kind", "")).lower()
                    if "deny" in kind or "cancel" in kind:
                        return RequestPermissionResponse(outcome=DeniedOutcome(outcome="cancelled"))
                    return RequestPermissionResponse(
                        outcome=AllowedOutcome(option_id=opt.option_id, outcome="selected")
                    )
                print("Choose one of the displayed numbers.")

        async def session_update(self, session_id, update, **kwargs):
            del session_id, kwargs
            if isinstance(update, AgentMessageChunk) and isinstance(update.content, TextContentBlock):
                chunk = update.content.text
                self.reply.append(chunk)
                self.on_text(chunk)
                return
            title = getattr(update, "title", None)
            status = getattr(update, "status", None)
            if title:
                self.on_status(f"{title}: {status}" if status else str(title))

        async def create_elicitation(self, message, mode, **kwargs):
            del mode, kwargs
            self.on_status(f"structured input requested: {message}")
            return DeclineElicitationResponse(action="decline")

        async def complete_elicitation(self, *a, **k): pass
        async def ext_notification(self, *a, **k): pass
        async def ext_method(self, method, params):
            del params
            raise RequestError.method_not_found(method)
        async def write_text_file(self,*a,**k): raise RequestError.method_not_found("fs/write_text_file")
        async def read_text_file(self,*a,**k): raise RequestError.method_not_found("fs/read_text_file")
        async def create_terminal(self,*a,**k): raise RequestError.method_not_found("terminal/create")
        async def terminal_output(self,*a,**k): raise RequestError.method_not_found("terminal/output")
        async def release_terminal(self,*a,**k): raise RequestError.method_not_found("terminal/release")
        async def wait_for_terminal_exit(self,*a,**k): raise RequestError.method_not_found("terminal/wait_for_exit")
        async def kill_terminal(self,*a,**k): raise RequestError.method_not_found("terminal/kill")

    return KiroClient()


class ClaudeBackend(AgentBackend):
    name = "claude"
    label = "Claude Code"

    def __init__(self, *, model=None, permission_mode=None):
        super().__init__(model=model)
        self.permission_mode = permission_mode
        self.binary = None
        self.session_id = None
        self.proc = None

    async def start(self, project):
        await super().start(project)
        self.binary = _require_binary(os.getenv("AGENT_VOICE_CLAUDE_BIN", "claude"), "Claude Code")

    async def prompt(self, text, on_text, on_status):
        assert self.binary and self.project
        cmd = [self.binary, "-p", "--output-format", "stream-json", "--verbose", "--include-partial-messages"]
        if self.session_id: cmd += ["--resume", self.session_id]
        if self.model: cmd += ["--model", self.model]
        if self.permission_mode: cmd += ["--permission-mode", self.permission_mode]
        cmd.append(text)
        self.proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=None,
            cwd=str(self.project), start_new_session=True
        )
        assert self.proc.stdout
        chunks, result_text, error_text = [], "", ""
        while True:
            raw = await self.proc.stdout.readline()
            if not raw: break
            try: event = json.loads(raw)
            except json.JSONDecodeError: continue
            if event.get("session_id"): self.session_id = str(event["session_id"])
            etype = event.get("type")
            if etype == "stream_event" and not event.get("parent_tool_use_id"):
                inner = event.get("event") or {}
                delta = inner.get("delta") or {}
                if inner.get("type") == "content_block_delta" and delta.get("type") == "text_delta":
                    chunk = str(delta.get("text", ""))
                    if chunk:
                        chunks.append(chunk); on_text(chunk)
                elif inner.get("type") == "content_block_start":
                    block = inner.get("content_block") or {}
                    if block.get("type") == "tool_use":
                        on_status(f"Claude tool: {block.get('name', 'tool')}")
            elif etype == "system" and event.get("subtype") == "api_retry":
                on_status(f"Claude retry {event.get('attempt','?')}/{event.get('max_retries','?')}")
            elif etype == "result":
                if event.get("session_id"): self.session_id = str(event["session_id"])
                if isinstance(event.get("result"), str): result_text = event["result"]
                if event.get("is_error"): error_text = result_text or str(event.get("error","Claude failed"))
        rc = await self.proc.wait()
        self.proc = None
        if rc != 0 or error_text:
            raise BackendError(error_text or f"Claude Code exited with status {rc}")
        return (result_text or "".join(chunks)).strip()

    async def cancel(self):
        await _terminate_process(self.proc); self.proc = None


class CodexBackend(AgentBackend):
    name = "codex"
    label = "Codex"

    def __init__(self, *, model=None, sandbox=None, skip_git_check=False):
        super().__init__(model=model)
        self.sandbox = sandbox
        self.skip_git_check = skip_git_check
        self.binary = None
        self.thread_id = None
        self.proc = None

    async def start(self, project):
        await super().start(project)
        self.binary = _require_binary(os.getenv("AGENT_VOICE_CODEX_BIN", "codex"), "Codex CLI")

    def _command(self, text):
        cmd = [self.binary, "exec", "--json"]
        if self.model: cmd += ["--model", self.model]
        if self.skip_git_check: cmd += ["--skip-git-repo-check"]
        if self.sandbox and not self.thread_id: cmd += ["--sandbox", self.sandbox]
        if self.thread_id: cmd += ["resume", self.thread_id, text]
        else: cmd.append(text)
        return cmd

    async def prompt(self, text, on_text, on_status):
        assert self.project
        self.proc = await asyncio.create_subprocess_exec(
            *self._command(text), stdout=asyncio.subprocess.PIPE, stderr=None,
            cwd=str(self.project), start_new_session=True
        )
        assert self.proc.stdout
        replies, error_text = [], ""
        while True:
            raw = await self.proc.stdout.readline()
            if not raw: break
            try: event = json.loads(raw)
            except json.JSONDecodeError: continue
            etype = event.get("type")
            if etype == "thread.started" and event.get("thread_id"):
                self.thread_id = str(event["thread_id"])
            elif etype in {"item.started", "item.updated", "item.completed"}:
                item = event.get("item") or {}
                item_type = item.get("type")
                if etype == "item.completed" and item_type == "agent_message":
                    chunk = str(item.get("text", ""))
                    if chunk:
                        replies.append(chunk); on_text(chunk)
                elif etype == "item.started":
                    if item_type == "command_execution":
                        on_status(f"Codex command: {item.get('command','')}")
                    elif item_type == "mcp_tool_call":
                        on_status(f"Codex MCP: {item.get('server','')}/{item.get('tool','')}")
                    elif item_type == "web_search":
                        on_status(f"Codex web search: {item.get('query','')}")
                    elif item_type == "collab_tool_call":
                        on_status(f"Codex collaboration: {item.get('tool','tool')}")
            elif etype == "turn.failed":
                err = event.get("error") or {}; error_text = str(err.get("message", err))
            elif etype == "error":
                error_text = str(event.get("message", "Codex failed"))
        rc = await self.proc.wait()
        self.proc = None
        if rc != 0 or error_text:
            raise BackendError(error_text or f"Codex exited with status {rc}")
        return "\n".join(replies).strip()

    async def cancel(self):
        await _terminate_process(self.proc); self.proc = None


def create_backend(name, *, model=None, kiro_agent=None, claude_permission_mode=None,
                   codex_sandbox=None, codex_skip_git_check=False):
    normalized = name.strip().lower()
    if normalized == "kiro":
        return KiroBackend(model=model, agent=kiro_agent)
    if normalized == "claude":
        return ClaudeBackend(model=model, permission_mode=claude_permission_mode)
    if normalized == "codex":
        return CodexBackend(model=model, sandbox=codex_sandbox, skip_git_check=codex_skip_git_check)
    raise BackendError(f"Unknown backend {name!r}; expected one of: kiro, claude, codex")


BACKENDS = ("kiro", "claude", "codex")
