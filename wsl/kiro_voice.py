#!/usr/bin/env python3
from __future__ import annotations

import argparse, asyncio, contextlib, json, os, shutil, subprocess
from pathlib import Path
from typing import Any, Optional

from acp import PROTOCOL_VERSION, Client, RequestError, connect_to_agent
from acp.schema import (
    AgentMessageChunk, AllowedOutcome, ClientCapabilities,
    DeclineElicitationResponse, DeniedOutcome, Implementation,
    RequestPermissionResponse, TextContentBlock,
)


def wsl_to_windows(path: Path) -> str:
    return subprocess.run(['wslpath','-w',str(path)], check=True, text=True, capture_output=True).stdout.strip()


class WindowsAudioBridge:
    def __init__(self, windows_python: str, sidecar: Path):
        self.windows_python = windows_python
        self.sidecar = sidecar
        self.proc: Optional[asyncio.subprocess.Process] = None
        self.events: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self.pending: dict[int, asyncio.Future] = {}
        self.next_id = 1
        self.reader_task = None

    async def start(self):
        self.proc = await asyncio.create_subprocess_exec(
            self.windows_python, '-u', wsl_to_windows(self.sidecar.resolve()),
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=None,
        )
        self.reader_task = asyncio.create_task(self._reader())
        while True:
            event = await self.events.get()
            if event.get('event') == 'ready':
                return event

    async def _reader(self):
        assert self.proc and self.proc.stdout
        while True:
            raw = await self.proc.stdout.readline()
            if not raw:
                await self.events.put({'event':'sidecar_exit'})
                return
            try: msg = json.loads(raw)
            except json.JSONDecodeError: continue
            rid = msg.get('id')
            if rid in self.pending and 'ok' in msg:
                fut = self.pending.pop(rid)
                if msg.get('ok'): fut.set_result(msg)
                else: fut.set_exception(RuntimeError(msg.get('error','sidecar error')))
            else:
                await self.events.put(msg)

    async def request(self, op: str, **payload):
        assert self.proc and self.proc.stdin
        rid = self.next_id; self.next_id += 1
        fut = asyncio.get_running_loop().create_future()
        self.pending[rid] = fut
        self.proc.stdin.write((json.dumps({'id':rid,'op':op,**payload})+'\n').encode())
        await self.proc.stdin.drain()
        return await fut

    async def close(self):
        if not self.proc: return
        with contextlib.suppress(Exception): await self.request('quit')
        if self.proc.returncode is None: self.proc.terminate()
        with contextlib.suppress(Exception): await self.proc.wait()
        if self.reader_task: self.reader_task.cancel()


class VoiceClient(Client):
    def __init__(self):
        self.reply = []

    def begin(self): self.reply.clear()
    def text(self): return ''.join(self.reply).strip()

    async def request_permission(self, session_id, tool_call, options, **kwargs):
        del session_id, kwargs
        title = getattr(tool_call,'title',None) or 'tool action'
        print(f'\n🔐 Permission requested: {title}')
        if not options:
            return RequestPermissionResponse(outcome=DeniedOutcome(outcome='cancelled'))
        for i,opt in enumerate(options,1):
            print(f'  {i}. {getattr(opt,"name","option")} [{getattr(opt,"kind","")}]')
        while True:
            choice = (await asyncio.to_thread(input,'Permission> ')).strip()
            if choice.isdigit() and 1 <= int(choice) <= len(options):
                opt = options[int(choice)-1]
                kind = str(getattr(opt,'kind','')).lower()
                if 'deny' in kind or 'cancel' in kind:
                    return RequestPermissionResponse(outcome=DeniedOutcome(outcome='cancelled'))
                return RequestPermissionResponse(outcome=AllowedOutcome(option_id=opt.option_id,outcome='selected'))
            print('Choose one of the displayed numbers.')

    async def session_update(self, session_id, update, **kwargs):
        del session_id, kwargs
        if isinstance(update, AgentMessageChunk) and isinstance(update.content, TextContentBlock):
            self.reply.append(update.content.text)
            print(update.content.text, end='', flush=True)
            return
        title, status = getattr(update,'title',None), getattr(update,'status',None)
        if title and status: print(f'\n🛠 {title}: {status}', flush=True)

    async def create_elicitation(self, message, mode, **kwargs):
        del mode, kwargs
        print(f'\nℹ Kiro requested structured input: {message}')
        return DeclineElicitationResponse(action='decline')
    async def complete_elicitation(self, *args, **kwargs): pass
    async def ext_notification(self, *args, **kwargs): pass
    async def ext_method(self, method, params): raise RequestError.method_not_found(method)
    async def write_text_file(self,*a,**k): raise RequestError.method_not_found('fs/write_text_file')
    async def read_text_file(self,*a,**k): raise RequestError.method_not_found('fs/read_text_file')
    async def create_terminal(self,*a,**k): raise RequestError.method_not_found('terminal/create')
    async def terminal_output(self,*a,**k): raise RequestError.method_not_found('terminal/output')
    async def release_terminal(self,*a,**k): raise RequestError.method_not_found('terminal/release')
    async def wait_for_terminal_exit(self,*a,**k): raise RequestError.method_not_found('terminal/wait_for_exit')
    async def kill_terminal(self,*a,**k): raise RequestError.method_not_found('terminal/kill')


class App:
    def __init__(self,args):
        self.args=args; self.audio=None; self.conn=None; self.proc=None; self.session=None
        self.client=VoiceClient(); self.prompt_task=None; self.stop=asyncio.Event()
        self.speak=os.getenv('KIRO_VOICE_SPEAK','1')!='0'

    async def start(self):
        project=Path(self.args.project).expanduser().resolve()
        if not project.is_dir(): raise SystemExit(f'Project directory does not exist: {project}')
        kiro=os.getenv('KIRO_VOICE_KIRO_BIN','kiro-cli')
        if shutil.which(kiro) is None: raise SystemExit(f'{kiro!r} not found in WSL PATH')
        winpy=self.args.windows_python or os.getenv('KIRO_VOICE_WINDOWS_PY')
        if not winpy: raise SystemExit('Set KIRO_VOICE_WINDOWS_PY to the Windows venv python.exe path as seen from WSL')
        sidecar=Path(__file__).resolve().parents[1]/'windows'/'audio_bridge.py'
        self.audio=WindowsAudioBridge(str(Path(winpy).expanduser()),sidecar)
        ready=await self.audio.start(); dev=ready.get('device',{}); cfg=ready.get('config',{})
        print(f'🎙 Windows microphone: {dev.get("name","<unknown>")}')
        print(f'👂 Wake phrase: {cfg.get("wake_phrase","hey kiro")!r} ({cfg.get("wake_backend","whisper_phrase")})')
        cmd=[kiro,'acp'] + (['--agent',self.args.agent] if self.args.agent else [])
        self.proc=await asyncio.create_subprocess_exec(*cmd,stdin=asyncio.subprocess.PIPE,stdout=asyncio.subprocess.PIPE,stderr=None,cwd=str(project))
        assert self.proc.stdin and self.proc.stdout
        self.conn=connect_to_agent(self.client,self.proc.stdin,self.proc.stdout)
        await self.conn.initialize(protocol_version=PROTOCOL_VERSION,client_capabilities=ClientCapabilities(),client_info=Implementation(name='kiro-voice-v3',title='Kiro Voice V3',version='0.3.0'))
        sess=await self.conn.new_session(mcp_servers=[],cwd=str(project)); self.session=sess.session_id
        print(f'✓ Kiro ACP session: {self.session}')
        print('Always listening. Say the wake phrase, or type /help.')

    async def cancel(self):
        if self.conn and self.session:
            with contextlib.suppress(Exception): await self.conn.cancel(session_id=self.session)
        if self.prompt_task and not self.prompt_task.done():
            self.prompt_task.cancel()
            with contextlib.suppress(Exception,asyncio.CancelledError): await self.prompt_task

    async def prompt(self,text):
        if not text.strip(): return
        if self.prompt_task and not self.prompt_task.done(): await self.cancel()
        async def run():
            self.client.begin(); print(f'\nYou (voice)> {text}\nKiro> ',end='',flush=True)
            try:
                await self.conn.prompt(session_id=self.session,prompt=[TextContentBlock(text=text)])
            except asyncio.CancelledError:
                print('\n⛔ Kiro turn cancelled.'); raise
            except Exception as e:
                print(f'\n⚠ Kiro prompt failed: {e}'); return
            print(); response=self.client.text()
            if self.speak and response:
                await self.audio.request('speak',text=response,followup_seconds=self.args.conversation_timeout)
            else:
                await self.audio.request('arm_followup',seconds=self.args.conversation_timeout)
        self.prompt_task=asyncio.create_task(run())

    async def events(self):
        while not self.stop.is_set():
            e=await self.audio.events.get(); kind=e.get('event')
            if kind=='wake': print(f'\n🔔 Wake detected: {e.get("phrase")}')
            elif kind=='utterance': await self.prompt(str(e.get('text','')))
            elif kind=='barge_in':
                print(f'\n🛑 Barge-in: {e.get("action")} ({e.get("text","")})')
                if e.get('action') in {'stop','cancel'}:
                    await self.cancel(); await self.audio.request('arm_followup',seconds=self.args.conversation_timeout)
            elif kind=='tts_started': print('\n🔊 Speaking…')
            elif kind=='tts_finished':
                secs=float(e.get('followup_seconds',self.args.conversation_timeout)); await self.audio.request('arm_followup',seconds=secs)
                print(f'👂 Follow-up window open for {secs:.0f}s')
            elif kind=='sleep': print('\n💤 Wake-word mode.')
            elif kind=='sidecar_exit': print('\n⚠ Windows audio sidecar exited.'); self.stop.set()

    async def console(self):
        while not self.stop.is_set():
            try: line=(await asyncio.to_thread(input,'')).strip()
            except (EOFError,KeyboardInterrupt): self.stop.set(); return
            if not line: continue
            if line=='/quit': self.stop.set()
            elif line=='/help': print('/listen /sleep /mute /unmute /cancel /status /quit')
            elif line=='/listen': await self.audio.request('force_listen')
            elif line=='/sleep': await self.audio.request('sleep')
            elif line=='/mute': self.speak=False; await self.audio.request('stop_speaking'); print('🔇 TTS muted.')
            elif line=='/unmute': self.speak=True; print('🔊 TTS enabled.')
            elif line=='/cancel': await self.audio.request('stop_speaking'); await self.cancel()
            elif line=='/status': print(json.dumps((await self.audio.request('status')).get('result',{}),indent=2))
            elif line.startswith('/'): print('Unknown command. Type /help.')
            else: await self.prompt(line)

    async def run(self):
        await self.start(); et=asyncio.create_task(self.events()); ct=asyncio.create_task(self.console())
        try: await self.stop.wait()
        finally:
            et.cancel(); ct.cancel(); await self.cancel()
            if self.audio: await self.audio.close()
            if self.proc and self.proc.returncode is None:
                self.proc.terminate();
                with contextlib.suppress(Exception): await self.proc.wait()


def args():
    p=argparse.ArgumentParser(description='Always-listening voice frontend for Kiro CLI on WSL + Windows')
    p.add_argument('--project',default='.'); p.add_argument('--agent'); p.add_argument('--windows-python')
    p.add_argument('--conversation-timeout',type=float,default=float(os.getenv('KIRO_VOICE_CONVERSATION_TIMEOUT','30')))
    return p.parse_args()

if __name__=='__main__': asyncio.run(App(args()).run())
