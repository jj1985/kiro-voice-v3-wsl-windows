# Architecture

Quack Actual has one platform-neutral controller and a separate audio process.

```text
microphone -> local speech segmentation -> local Whisper -> activated command
                                                            |
                                         Quack Actual controller
                                         /       |       |     \
                                     Copilot   Claude   Codex  Kiro
                                                            |
terminal streaming <- response text -> filtered local text-to-speech
```

Native Windows runs both processes with the same uv-managed Windows environment.
WSL uses a Linux environment for the controller and Windows interop for the audio
process. The controller sends validated configuration over JSONL, so environment
variable forwarding and WSL path translation are not needed for configuration.

`config.py`: configuration validation and user-specific locations.
`process.py`: executable discovery, npm shim resolution, OS-specific child cleanup.
`rpc.py`: concurrent requests/notifications, permission callbacks, timeouts, EOF handling.
`backends.py`: ACP adapters and streaming JSONL parsers.
`bridge.py`: audio process lifecycle with startup and request deadlines.
`audio.py`: bounded microphone and transcription queues, state epochs, interruptible TTS.
`speech.py`: anchored wake matching, local controls, speech filtering.
`app.py`: session cache, one keyboard reader, approval routing, turn cancellation.
`cli.py`: launch, diagnostics, configuration, device listing, and model download commands.

The audio state epoch drops stale work after a control-state change. A single STT
worker replaces unbounded transcription threads. Turn generations reject stale
TTS completions. The keyboard has exactly one reader: a permission callback never
starts a second `input()` that could steal an approval or hang interpreter shutdown.

Active turns have a configurable deadline (default 900 seconds). An uncooperative
ACP cancellation closes that backend instead of mixing late updates into a new
turn. Cooperative cancellation can preserve the session. Idle backend sessions
remain cached until `/new`, application exit, or a transport failure.

## Scope and testing

The test suite uses synthetic protocol peers, mocked speech recognition, temporary
files, and owned child processes. It does not validate speech accuracy, hardware,
provider billing, real authentication, or the semantics of tools launched by an
agent. Run the manual installation checklist in README on your target machine.
The release workflow checks Windows and Ubuntu before publishing a preview release.
