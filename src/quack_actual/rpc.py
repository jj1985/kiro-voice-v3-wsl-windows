"""Bounded, asynchronous JSON-RPC 2.0 over the ACP NDJSON transport."""
from __future__ import annotations

import asyncio
import contextlib
import json
from .process import spawn, terminate


class RPCError(RuntimeError):
    pass


class RPC:
    def __init__(self, notification, request):
        self.notification, self.request = notification, request
        self.proc = None
        self.pending = {}
        self.next_id = 0
        self.reader = None
        self.handlers = set()
        self.write_lock = asyncio.Lock()

    async def start(self, command, cwd=None):
        self.proc = await spawn(command, cwd)
        self.reader = asyncio.create_task(self._read())

    async def send(self, message):
        if not self.proc or self.proc.returncode is not None:
            raise RPCError("Agent transport is closed")
        async with self.write_lock:
            self.proc.stdin.write((json.dumps(message, ensure_ascii=False) + "\n").encode("utf-8"))
            await self.proc.stdin.drain()

    async def notify(self, method, params):
        await self.send({"jsonrpc": "2.0", "method": method, "params": params})

    async def call(self, method, params, timeout=60):
        self.next_id += 1
        rid = self.next_id
        future = asyncio.get_running_loop().create_future()
        self.pending[rid] = future
        try:
            await self.send({"jsonrpc": "2.0", "id": rid, "method": method, "params": params})
            return await asyncio.wait_for(future, timeout)
        finally:
            self.pending.pop(rid, None)

    async def _answer(self, message):
        result = {"jsonrpc": "2.0", "id": message["id"]}
        try:
            value = await self.request(message["method"], message.get("params", {}))
            result["result"] = value
        except NotImplementedError:
            result["error"] = {"code": -32601, "message": "Client capability not supported"}
        except Exception:
            result["error"] = {"code": -32603, "message": "Client request failed"}
        with contextlib.suppress(Exception):
            await self.send(result)

    async def _read(self):
        error = RPCError("Agent closed its output. Check CLI authentication and version.")
        try:
            while line := await self.proc.stdout.readline():
                message = json.loads(line)
                if not isinstance(message, dict):
                    raise RPCError("Agent returned a non-object protocol message")
                if "method" in message:
                    if "id" in message:
                        task = asyncio.create_task(self._answer(message))
                        self.handlers.add(task)
                        task.add_done_callback(self.handlers.discard)
                    else:
                        await self.notification(message["method"], message.get("params", {}))
                elif (future := self.pending.get(message.get("id"))) is not None and not future.done():
                    if "error" in message:
                        future.set_exception(RPCError(str(message["error"])))
                    else:
                        future.set_result(message.get("result", {}))
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            error = RPCError(f"Agent protocol failure: {exc}")
        finally:
            for future in list(self.pending.values()):
                if not future.done():
                    future.set_exception(error)

    async def close(self):
        for task in list(self.handlers):
            task.cancel()
        if self.handlers:
            await asyncio.gather(*self.handlers, return_exceptions=True)
        await terminate(self.proc)
        if self.reader:
            self.reader.cancel()
            await asyncio.gather(self.reader, return_exceptions=True)
