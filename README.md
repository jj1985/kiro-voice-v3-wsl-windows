# Agent Voice — Kiro + Claude Code + Codex on Windows 11 / WSL2

Always-listening local voice control for coding agents running inside **WSL2 Ubuntu 24.04**.

Supported agent backends:

- **Kiro CLI** via `kiro-cli acp`
- **Claude Code CLI** via supported `claude -p --output-format stream-json`
- **OpenAI Codex CLI** via supported `codex exec --json`

The Windows side owns microphone capture, local Whisper speech-to-text, wake-word detection, and Windows TTS. The coding agents and project files stay inside WSL.

## Features

- Always-listening wake phrase; default: **Hey Kiro**
- Local `faster-whisper` transcription
- Kiro / Claude Code / Codex backend selection
- Voice backend switching: **"switch to Claude"**, **"switch to Codex"**, **"switch to Kiro"**
- Terminal backend switching with `/backend`
- 30-second hands-free follow-up conversation window
- Spoken agent responses
- Barge-in phrases including `Kiro stop`, `Claude stop`, `Codex stop`, and `Agent stop`
- Cancellation of the current agent process/turn
- Windows login auto-start with selectable backend
- Optional openWakeWord custom wake model

## Architecture

```text
Windows 11
  microphone
     |
     +-- speech gate / wake detection
     +-- faster-whisper STT
     +-- cancelable Windows SAPI TTS
              |
              | JSONL over WSL interop
              v
WSL2 Ubuntu 24.04
  kiro_voice.py
       |
       +-- KiroBackend   -> kiro-cli acp
       +-- ClaudeBackend -> claude -p ... stream-json
       `-- CodexBackend  -> codex exec --json
              |
              v
       project / shell / tools / MCP
```

## 1. Windows audio setup

Install **Python 3.12 x64** and allow desktop microphone access:

`Settings -> Privacy & security -> Microphone -> Let desktop apps access your microphone`

From PowerShell:

```powershell
cd C:\path\to\kiro-voice-v3-wsl-windows
Set-ExecutionPolicy -Scope Process Bypass
.\windows\setup.ps1
```

The setup script prints the Windows Python path as seen from WSL. Add it to `~/.bashrc`:

```bash
export AGENT_VOICE_WINDOWS_PY='/mnt/c/.../windows/.venv/Scripts/python.exe'
```

The legacy `KIRO_VOICE_WINDOWS_PY` variable is still supported.

## 2. Install the agent CLIs inside WSL

You only need to install the backends you intend to use.

### Kiro

```bash
curl -fsSL https://cli.kiro.dev/install | bash
kiro-cli
```

### Claude Code

```bash
curl -fsSL https://claude.ai/install.sh | bash
claude
```

Authenticate Claude Code normally before using the voice wrapper.

### Codex

```bash
curl -fsSL https://chatgpt.com/codex/install.sh | sh
codex
```

Authenticate Codex normally before using the voice wrapper.

## 3. Install the WSL voice controller

```bash
cd /mnt/c/path/to/kiro-voice-v3-wsl-windows
bash wsl/setup.sh
```

The setup script reports which of `kiro-cli`, `claude`, and `codex` it can find.

## 4. Choose a default backend

Kiro remains the default for backward compatibility.

```bash
export AGENT_VOICE_PROJECT="$HOME/src/my-project"
export AGENT_VOICE_BACKEND=kiro
./wsl/run.sh
```

Claude Code:

```bash
AGENT_VOICE_BACKEND=claude ./wsl/run.sh
```

Codex:

```bash
AGENT_VOICE_BACKEND=codex ./wsl/run.sh
```

You can also invoke the controller directly:

```bash
python wsl/kiro_voice.py --project ~/src/my-project --backend claude
python wsl/kiro_voice.py --project ~/src/my-project --backend codex
```

## Switch agents while running

Terminal commands:

```text
/backend
/backend kiro
/backend claude
/backend codex
```

Or say during an active voice window:

```text
switch to Claude
switch to Codex
switch to Kiro
```

A backend switch starts that backend's voice-controller session. Switching away and then back currently starts a new wrapper session for that backend rather than automatically restoring the previous wrapper session.

## Claude Code behavior

The Claude backend runs print mode with structured streaming:

```text
claude -p --output-format stream-json --verbose --include-partial-messages
```

Text deltas are streamed to the terminal as Claude generates them. The wrapper captures Claude's `session_id` and uses `--resume <session-id>` for voice follow-ups, so context is preserved throughout the active Claude voice session.

Optional model:

```bash
python wsl/kiro_voice.py --backend claude --claude-model sonnet
```

Optional permission mode passthrough:

```bash
export AGENT_VOICE_CLAUDE_PERMISSION_MODE=plan
```

The wrapper intentionally does **not** enable `--dangerously-skip-permissions`. Claude's normal settings and permission model remain in control.

## Codex behavior

The Codex backend runs:

```text
codex exec --json
```

It captures the `thread.started` thread ID, extracts completed `agent_message` items, and resumes follow-ups with:

```text
codex exec --json resume <THREAD_ID> "follow-up"
```

Optional model:

```bash
python wsl/kiro_voice.py --backend codex --codex-model <model>
```

Optional sandbox policy for the initial Codex thread:

```bash
python wsl/kiro_voice.py \
  --backend codex \
  --codex-sandbox workspace-write
```

Or:

```bash
export AGENT_VOICE_CODEX_SANDBOX=workspace-write
```

Available values are `read-only`, `workspace-write`, and `danger-full-access`. No override is applied by default, so your Codex configuration remains authoritative.

For a non-Git working directory:

```bash
export AGENT_VOICE_CODEX_SKIP_GIT_CHECK=1
```

## Kiro behavior

Kiro continues to use its ACP server:

```text
kiro-cli acp
```

Kiro ACP permission requests remain interactive in the terminal. You can also select a Kiro custom agent:

```bash
python wsl/kiro_voice.py --backend kiro --agent my-agent
```

## Voice workflow

Example:

```text
You:   Hey Kiro, inspect the authentication code.
Claude Code: ...

You:   Fix the token expiration problem.
Claude Code: ...

You:   switch to Codex
Agent Voice: Switched to Codex.

You:   Review the current changes for regressions.
Codex: ...
```

The wake phrase is independent of the selected coding backend. You can change `wake_phrase` in `windows/config.json`; for a multi-agent setup, `hey agent` may feel more natural than `hey kiro`.

## Barge-in / cancellation

While TTS is speaking, these default phrases stop/cancel it:

```text
Kiro stop
Claude stop
Codex stop
Agent stop

Kiro cancel
Claude cancel
Codex cancel
Agent cancel
```

The active CLI process or ACP turn is then cancelled where supported.

## Terminal controls

```text
/help
/listen
/sleep
/mute
/unmute
/cancel
/status
/backend
/backend kiro|claude|codex
/quit
```

## Windows auto-start

Choose the backend when installing the startup entry:

```powershell
cd C:\path\to\kiro-voice-v3-wsl-windows\windows

.\install-autostart.ps1 `
    -Distro "Ubuntu-24.04" `
    -Project "~/src/my-project" `
    -Backend "claude"
```

Valid backend values are `kiro`, `claude`, and `codex`.

Remove the startup entry with:

```powershell
.\install-autostart.ps1 -Remove
```

## Wake-word configuration

The default `whisper_phrase` backend works immediately with arbitrary phrases because only detected speech segments are sent through a small local Whisper model for wake-phrase matching.

Edit `windows/config.json` after Windows setup:

```json
{
  "wake_backend": "whisper_phrase",
  "wake_phrase": "hey agent"
}
```

For a lower-power dedicated wake model, point `wake_model` at an openWakeWord ONNX model and set `wake_backend` to `openwakeword`.

## Privacy

Microphone audio and Whisper transcription remain local to the Windows machine. The voice wrapper sends **transcribed command text**, not raw microphone audio, to the selected coding CLI.

Each agent CLI retains its own authentication, account, network behavior, configuration, permission rules, telemetry policy, and tool access.

## Notes on output streaming

- **Kiro:** ACP message chunks stream directly.
- **Claude Code:** token-level text deltas stream from `stream-json`.
- **Codex:** `codex exec --json` emits structured JSONL events; agent messages are surfaced when its `agent_message` item completes.

This project intentionally uses documented/programmatic CLI interfaces rather than scraping interactive terminal UIs.
