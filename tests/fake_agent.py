"""Offline protocol fixture. Never calls a real AI service or executes tools."""
import json
import sys

# Match the UTF-8 wire format of real agent CLIs on Windows as well as Linux.
sys.stdin.reconfigure(encoding="utf-8")
sys.stdout.reconfigure(encoding="utf-8")


def send(value):
    print(json.dumps(value), flush=True)


if '--acp' in sys.argv or 'acp' in sys.argv:
    pending = None
    for line in sys.stdin:
        req = json.loads(line)
        method = req.get('method')
        rid = req.get('id')
        if method == 'initialize':
            send({'id': rid, 'result': {'protocolVersion': 1}})
        elif method == 'session/new':
            send({'id': rid, 'result': {'sessionId': 'test-session'}})
        elif method == 'session/set_model':
            send({'id': rid, 'result': {}})
        elif method == 'session/prompt':
            text = req['params']['prompt'][0]['text']
            if text == 'permission':
                pending = rid
                send({'id': 900, 'method': 'session/request_permission', 'params': {
                    'sessionId': 'test-session', 'toolCall': {'title': 'Fake tool'},
                    'options': [{'optionId': 'no', 'name': 'Reject', 'kind': 'reject_once'},
                                {'optionId': 'yes', 'name': 'Allow once', 'kind': 'allow_once'}],
                }})
                continue
            if text == 'hang':
                pending = rid
                continue
            send({'method': 'session/update', 'params': {'sessionId': 'test-session', 'update': {
                'sessionUpdate': 'agent_message_chunk', 'content': {'type': 'text', 'text': text},
            }}})
            send({'id': rid, 'result': {'stopReason': 'end_turn'}})
        elif method == 'session/cancel' and pending:
            send({'id': pending, 'result': {'stopReason': 'cancelled'}})
            pending = None
        elif rid == 900:
            outcome = req['result']['outcome']
            selected = outcome.get('optionId', 'cancelled')
            send({'method': 'session/update', 'params': {'sessionId': 'test-session', 'update': {
                'sessionUpdate': 'agent_message_chunk', 'content': {'type': 'text', 'text': selected},
            }}})
            send({'id': pending, 'result': {'stopReason': 'end_turn'}})
            pending = None
elif '-p' in sys.argv:
    text = sys.stdin.read().strip()
    if text == 'fail':
        send({'type': 'result', 'is_error': True, 'result': 'fixture failure'})
        sys.exit(1)
    send({'type': 'system', 'session_id': 'claude-session'})
    send({'type': 'stream_event', 'parent_tool_use_id': None, 'event': {
        'type': 'content_block_delta', 'delta': {'type': 'text_delta', 'text': text},
    }})
    send({'type': 'result', 'session_id': 'claude-session', 'result': text, 'is_error': False})
elif 'exec' in sys.argv:
    text = sys.stdin.read().strip()
    send({'type': 'thread.started', 'thread_id': 'codex-thread'})
    if text == 'fail':
        send({'type': 'turn.failed', 'error': {'message': 'fixture failure'}})
        sys.exit(1)
    send({'type': 'item.completed', 'item': {'type': 'agent_message', 'text': text}})
    send({'type': 'turn.completed', 'usage': {}})
