import copy
import time
import unittest
from unittest.mock import MagicMock, patch
from quack_actual.audio import Monitor
from quack_actual.config import DEFAULTS


class AudioRoutingTests(unittest.TestCase):
    def make(self, transcript, speaking=False):
        cfg = copy.deepcopy(DEFAULTS)
        cfg['activation_sound'] = False
        speaker = MagicMock()
        speaker.active.return_value = speaking
        monitor = Monitor(cfg, speaker)
        monitor.transcribe = MagicMock(return_value=transcript)
        return monitor

    def messages(self, monitor):
        with patch('quack_actual.audio.emit') as output:
            monitor.handle(None, monitor.snapshot(), time.monotonic())
        return [call.kwargs for call in output.call_args_list]

    def test_background_speech_not_forwarded(self):
        self.assertEqual(self.messages(self.make('what is for dinner')), [])

    def test_wake_arms_without_empty_prompt(self):
        monitor = self.make('quack actual')
        messages = self.messages(monitor)
        self.assertTrue(any(m['event'] == 'wake' for m in messages))
        self.assertFalse(any(m['event'] == 'utterance' for m in messages))
        self.assertGreater(monitor.armed_until, time.monotonic())

    def test_combined_wake_command(self):
        messages = self.messages(self.make('Quack Actual, inspect Auth.py'))
        commands = [m['text'] for m in messages if m['event'] == 'utterance']
        self.assertEqual(commands, ['inspect Auth.py'])

    def test_followup_needs_no_wake(self):
        monitor = self.make('inspect Auth.py')
        monitor.state('followup')
        messages = self.messages(monitor)
        self.assertEqual([m['text'] for m in messages if m['event'] == 'utterance'], ['inspect Auth.py'])

    def test_speaker_echo_ignored(self):
        messages = self.messages(self.make('here are your results', speaking=True))
        self.assertEqual(messages, [])

    def test_barge_uses_configured_phrase(self):
        monitor = self.make('Quack Actual cancel', speaking=True)
        messages = self.messages(monitor)
        monitor.speaker.stop.assert_called_once()
        self.assertTrue(any(m['event'] == 'interrupt' for m in messages))
        self.assertTrue(any(m.get('text') == 'cancel' for m in messages))

    def test_barge_disabled(self):
        monitor = self.make('quack actual cancel', speaking=True)
        monitor.cfg['barge_in'] = False
        self.assertEqual(self.messages(monitor), [])
        monitor.transcribe.assert_not_called()

    def test_stale_audio_discarded(self):
        monitor = self.make('quack actual delete a file')
        state = monitor.snapshot()
        monitor.state('sleep')
        with patch('quack_actual.audio.emit') as output:
            monitor.handle(None, state, time.monotonic())
        output.assert_not_called()
        monitor.transcribe.assert_not_called()

    def test_busy_state_requires_wake(self):
        monitor = self.make('ordinary conversation')
        monitor.state('busy')
        self.assertEqual(self.messages(monitor), [])
