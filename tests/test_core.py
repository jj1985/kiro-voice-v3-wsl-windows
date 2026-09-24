import asyncio
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from quack_actual import config
from quack_actual.backends import Backend
from quack_actual.process import resolve_command, spawn, terminate
from quack_actual.speech import strip_wake, control, clean_tts

FAKE = Path(__file__).with_name('fake_agent.py').resolve()


class CoreTests(unittest.TestCase):
    def test_wake_prefix_only(self):
        self.assertEqual(strip_wake('Quack Actual, inspect Auth.py!', 'quack actual'), (True, 'inspect Auth.py!'))
        self.assertFalse(strip_wake('please say quack actual', 'quack actual')[0])
        self.assertFalse(strip_wake('quack actually', 'quack actual')[0])
        self.assertEqual(strip_wake('quack actual', 'quack actual'), (True, ''))

    def test_controls(self):
        self.assertEqual(control('Switch to Copilot.'), ('backend', 'copilot'))
        self.assertEqual(control('cancel'), ('cancel', ''))
        self.assertIsNone(control('describe the cancel function'))
        self.assertIsNone(control('allow once'))

    def test_tts_code_and_links(self):
        text = clean_tts('Read [docs](https://example.com). ```python\nsecret_code()\n```')
        self.assertNotIn('secret_code', text)
        self.assertNotIn('https', text)
        self.assertIn('docs', text)
        self.assertNotIn('unterminated', clean_tts('ok ```unterminated'))

    def test_config_preserves_user_file(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'config.json'
            config.init(path)
            values = json.loads(path.read_text())
            values['backend'] = 'claude'
            path.write_text(json.dumps(values))
            config.init(path)
            self.assertEqual(config.load(path)['backend'], 'claude')

    def test_config_validation(self):
        for value in (0, -1, float('nan'), float('inf'), True, 'bad'):
            cfg = copy.deepcopy(config.DEFAULTS)
            cfg['conversation_seconds'] = value
            with self.assertRaises(ValueError):
                config.validate(cfg)

    def test_unknown_config_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'config.json'
            path.write_text('{"typo": 1}')
            with self.assertRaises(ValueError):
                config.load(path)

    def test_npm_shim_uses_node_not_shell(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            shim = root / 'copilot.cmd'
            shim.write_text('@echo off')
            package = root / 'node_modules/@github/copilot'
            package.mkdir(parents=True)
            (package / 'package.json').write_text('{"bin":{"copilot":"index.js"}}')
            (package / 'index.js').write_text('')
            (root / 'node.exe').write_text('')
            with patch('quack_actual.process.shutil.which', return_value=str(shim)):
                argv = resolve_command('copilot')
            self.assertEqual(argv, [str(root / 'node.exe'), str(package / 'index.js')])

    def test_unknown_shim_rejected(self):
        with patch('quack_actual.process.shutil.which', return_value='/missing/copilot.cmd'):
            with self.assertRaises(RuntimeError):
                resolve_command('copilot')

    def test_cli_help_and_version(self):
        from quack_actual.cli import parser
        parsed = parser().parse_args(['start', '--backend', 'copilot', '--text-only'])
        self.assertEqual(parsed.backend, 'copilot')
        self.assertEqual(parsed.codex_sandbox, 'read-only')


class AdapterTests(unittest.IsolatedAsyncioTestCase):
    async def make(self, name, decision=None):
        cfg = copy.deepcopy(config.DEFAULTS)
        cfg['commands'] = {name: [sys.executable, str(FAKE)]}
        async def permission(*args):
            return decision
        backend = Backend(name, FAKE.parent, cfg, permission)
        await backend.start()
        self.addAsyncCleanup(backend.close)
        return backend

    async def test_copilot_acp_roundtrip(self):
        backend = await self.make('copilot')
        chunks = []
        self.assertEqual(await backend.prompt('hello', chunks.append, lambda _: None), 'hello')
        self.assertEqual(chunks, ['hello'])
        self.assertEqual(await backend.prompt('followup', chunks.append, lambda _: None), 'followup')
        self.assertEqual(backend.session_id, 'test-session')

    async def test_kiro_acp_roundtrip(self):
        backend = await self.make('kiro')
        self.assertEqual(await backend.prompt('test', lambda _: None, lambda _: None), 'test')

    async def test_permissions_default_deny(self):
        backend = await self.make('copilot')
        self.assertEqual(await backend.prompt('permission', lambda _: None, lambda _: None), 'cancelled')

    async def test_permission_reject_option_preserved(self):
        backend = await self.make('copilot', 'no')
        self.assertEqual(await backend.prompt('permission', lambda _: None, lambda _: None), 'no')

    async def test_permission_allow_explicit(self):
        backend = await self.make('copilot', 'yes')
        self.assertEqual(await backend.prompt('permission', lambda _: None, lambda _: None), 'yes')

    async def test_permission_invalid_option_denied(self):
        backend = await self.make('copilot', 'injected')
        self.assertEqual(await backend.prompt('permission', lambda _: None, lambda _: None), 'cancelled')

    async def test_cooperative_cancel(self):
        backend = await self.make('copilot')
        task = asyncio.create_task(backend.prompt('hang', lambda _: None, lambda _: None))
        await asyncio.sleep(0.1)
        await backend.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await asyncio.wait_for(task, 2)

    async def test_claude_stdin_and_resume(self):
        backend = await self.make('claude')
        text = 'inspect C:\\A B\\auth.py; $(touch nope) & Unicode café'
        self.assertEqual(await backend.prompt(text, lambda _: None, lambda _: None), text)
        self.assertIn('--resume', backend.headless_command())
        self.assertNotIn(text, backend.headless_command())
        self.assertEqual(await backend.prompt('second', lambda _: None, lambda _: None), 'second')

    async def test_codex_stdin_and_resume_sandbox(self):
        backend = await self.make('codex')
        self.assertEqual(await backend.prompt('one', lambda _: None, lambda _: None), 'one')
        command = backend.headless_command()
        self.assertIn('resume', command)
        self.assertIn('sandbox_mode="read-only"', command)
        self.assertEqual(command[-1], '-')
        self.assertEqual(await backend.prompt('two', lambda _: None, lambda _: None), 'two')

    async def test_headless_errors(self):
        for name in ('claude', 'codex'):
            backend = await self.make(name)
            with self.assertRaisesRegex(RuntimeError, 'fixture failure'):
                await backend.prompt('fail', lambda _: None, lambda _: None)

    async def test_kill_owned_process(self):
        proc = await spawn([sys.executable, '-c', 'import time; time.sleep(30)'])
        await terminate(proc)
        self.assertIsNotNone(proc.returncode)

    async def test_rpc_eof_fails_pending(self):
        from quack_actual.rpc import RPC, RPCError
        async def ignore(*args):
            pass
        rpc = RPC(ignore, ignore)
        await rpc.start([sys.executable, '-c', 'import sys; sys.stdin.readline()'])
        try:
            with self.assertRaises(RPCError):
                await rpc.call('initialize', {}, timeout=2)
        finally:
            await rpc.close()


if __name__ == '__main__':
    unittest.main()
