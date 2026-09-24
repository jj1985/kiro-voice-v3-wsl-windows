"""Native ACP (Copilot/Kiro) and documented JSONL CLI (Claude/Codex) adapters."""
from __future__ import annotations

import asyncio
import contextlib
import json
from pathlib import Path
from . import __version__
from .process import resolve_command, spawn, terminate
from .rpc import RPC


class Backend:
    def __init__(self, name, project, config, permission, model=None, sandbox="read-only", agent=None):
        self.name, self.project, self.config = name, Path(project), config
        self.permission, self.model, self.sandbox, self.agent = permission, model, sandbox, agent
        self.command = None
        self.session_id = None
        self.proc = None
        self.rpc = None
        self.text = lambda text: None
        self.status = lambda text: None
        self.chunks = []
        self.cancelled = False

    async def start(self):
        self.command = resolve_command(self.name, self.config.get("commands", {}).get(self.name))
        if self.name not in {"kiro", "copilot"}:
            return
        command = self.command + (["--acp", "--stdio"] if self.name == "copilot" else ["acp"])
        if self.name == "copilot" and self.model:
            command += ["--model", self.model]
        if self.name == "kiro" and self.agent:
            command += ["--agent", self.agent]
        self.rpc = RPC(self._notification, self._request)
        try:
            await self.rpc.start(command, self.project)
            await self.rpc.call("initialize", {
                "protocolVersion": 1,
                "clientCapabilities": {"fs": {"readTextFile": False, "writeTextFile": False}, "terminal": False},
                "clientInfo": {"name": "quack-actual", "title": "Quack Actual", "version": __version__},
            })
            session = await self.rpc.call("session/new", {"cwd": str(self.project), "mcpServers": []})
            self.session_id = session["sessionId"]
            if self.name == "kiro" and self.model:
                await self.rpc.call("session/set_model", {"sessionId": self.session_id, "modelId": self.model})
        except BaseException:
            await self.close()
            raise

    async def _notification(self, method, params):
        if method != "session/update" or params.get("sessionId") != self.session_id:
            return
        update = params.get("update", {})
        kind = update.get("sessionUpdate")
        if kind == "agent_message_chunk" and not self.cancelled:
            content = update.get("content", {})
            if content.get("type") == "text":
                chunk = str(content.get("text", ""))
                self.chunks.append(chunk)
                self.text(chunk)
        elif kind in {"tool_call", "tool_call_update"}:
            self.status(f"{update.get('title', 'Tool')}: {update.get('status', 'pending')}")

    async def _request(self, method, params):
        if method != "session/request_permission":
            raise NotImplementedError(method)
        if self.cancelled or params.get("sessionId") != self.session_id:
            return {"outcome": {"outcome": "cancelled"}}
        selected = await self.permission(
            self.name, params.get("toolCall", {}), params.get("options", []),
        )
        valid = {option.get("optionId") for option in params.get("options", [])}
        if self.cancelled or selected is None or selected not in valid:
            return {"outcome": {"outcome": "cancelled"}}
        # Reject options are selections too; do not mislabel them as approvals.
        return {"outcome": {"outcome": "selected", "optionId": selected}}

    def headless_command(self):
        if self.name == "claude":
            command = self.command + ["-p", "--output-format", "stream-json", "--verbose", "--include-partial-messages"]
            if self.session_id:
                command += ["--resume", self.session_id]
            if self.model:
                command += ["--model", self.model]
            return command
        if self.name == "codex":
            # Global config applies equally to new and resumed exec sessions.
            command = self.command + ["-c", f'sandbox_mode="{self.sandbox}"', "exec", "--json"]
            if self.model:
                command += ["--model", self.model]
            if self.session_id:
                command += ["resume", self.session_id]
            return command + ["-"]
        raise ValueError("This backend uses ACP, not a headless command")

    async def prompt(self, text, on_text, on_status):
        self.text, self.status, self.chunks, self.cancelled = on_text, on_status, [], False
        if self.rpc:
            result = await self.rpc.call("session/prompt", {
                "sessionId": self.session_id,
                "prompt": [{"type": "text", "text": text}],
            }, timeout=None)
            if result.get("stopReason") == "cancelled":
                raise asyncio.CancelledError()
            return "".join(self.chunks).strip()
        proc = self.proc = await spawn(self.headless_command(), self.project)
        result, error, completed = "", "", False
        try:
            proc.stdin.write((text + "\n").encode("utf-8"))
            await proc.stdin.drain()
            proc.stdin.close()
            while raw := await proc.stdout.readline():
                event = json.loads(raw)
                if self.name == "claude":
                    if event.get("session_id"):
                        self.session_id = str(event["session_id"])
                    kind = event.get("type")
                    if kind == "stream_event" and not event.get("parent_tool_use_id"):
                        inner = event.get("event", {})
                        delta = inner.get("delta", {})
                        if inner.get("type") == "content_block_delta" and delta.get("type") == "text_delta":
                            chunk = str(delta.get("text", ""))
                            self.chunks.append(chunk)
                            on_text(chunk)
                    elif kind == "result":
                        completed = True
                        result = str(event.get("result", ""))
                        if event.get("is_error"):
                            error = result or str(event.get("errors", "Claude failed"))
                        if event.get("permission_denials"):
                            on_status("Claude denied tools that require permission; approve them in the native CLI, then retry. No approval was bypassed.")
                else:
                    kind = event.get("type")
                    if kind == "thread.started":
                        self.session_id = event["thread_id"]
                    elif kind == "item.completed" and event.get("item", {}).get("type") == "agent_message":
                        chunk = str(event["item"].get("text", ""))
                        self.chunks.append(chunk)
                        on_text(chunk + "\n")
                    elif kind == "item.started":
                        item = event.get("item", {})
                        if item.get("type") in {"command_execution", "mcp_tool_call", "file_change"}:
                            on_status(f"Codex: {item.get('type')}")
                    elif kind == "turn.completed":
                        completed = True
                    elif kind == "turn.failed":
                        error = str(event.get("error", {}).get("message", "Codex failed"))
                    elif kind == "error":
                        on_status(str(event.get("message", "Codex error")))
            code = await proc.wait()
            if code or error or not completed:
                raise RuntimeError(error or f"{self.name} exited {code} without a successful final result; check authentication and stderr.")
            response = result or ("\n" if self.name == "codex" else "").join(self.chunks)
            if not self.chunks and response:
                on_text(response)
            return response.strip()
        finally:
            await terminate(proc)
            if self.proc is proc:
                self.proc = None

    async def cancel(self):
        self.cancelled = True
        if self.rpc and self.session_id:
            with contextlib.suppress(Exception):
                await self.rpc.notify("session/cancel", {"sessionId": self.session_id})
        await terminate(self.proc)

    async def close(self):
        await self.cancel()
        if self.rpc:
            await self.rpc.close()
