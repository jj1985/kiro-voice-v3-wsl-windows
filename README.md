# Quack Actual

**One voice. Every agent.**

A local voice console for GitHub Copilot CLI, Claude Code, Codex CLI, and Kiro CLI.
Say **“Quack Actual”**, give a command, and hear the response. Switch coding agents
without changing your microphone setup.

Version 0.5.0 is a preview release. Native Windows 11 and WSL2 Ubuntu 24.04 are
first-class launch paths. Automated tests use simulated agents; you must perform
the live microphone and authenticated-agent checks described below on your machine.

## Choose your installation

| Mode | Controller and coding agents | Microphone and speech | Environment |
|---|---|---|---|
| Native Windows 11 x64 | Windows; no WSL required | Windows | `.venv` |
| WSL2 Ubuntu 24.04 | Ubuntu | Windows through WSL interop | `.venv-wsl` plus Windows `.venv` |
| Text-only | Windows or Linux | None | Either environment above |

All paths use the same `quack_actual` Python package. No terminal scraping, network
listener, cloud speech API, or credential proxy is involved. Raw microphone audio
stays in local memory. Activated command text and project context are handled by
the selected coding agent under that provider's policies and your configuration.

## Native Windows: setup and first run

Download the setup ZIP from this repository's **Releases**, extract it to a permanent
folder such as `C:\Tools\quack-actual`, and open PowerShell there. Do not install
inside the ZIP viewer or move the folder after creating its virtual environment.

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\install.ps1
```

The installer provisions `uv` when missing, manages Python 3.12, creates `.venv`,
installs the application and speech dependencies, creates user configuration without
overwriting it, and downloads the configured speech models. A release bundle has
`uv.lock`; installation uses `uv sync --locked`. A development checkout without a
lockfile resolves and creates one on its first installation.

An internet connection is required for initial downloads. This is a complete
**online setup bundle**, not an offline bundle of Python, every model, and every
vendor's CLI. Agent accounts and licenses are not included.

Install and authenticate at least one coding CLI **in Windows** before running.
Examples (only run the commands for the tools you choose):

```powershell
# Copilot CLI: official WinGet package
winget install GitHub.Copilot
copilot

# Claude Code: official WinGet package
winget install Anthropic.ClaudeCode
claude

# Codex: with a supported Node.js installation
npm install -g @openai/codex
codex
```

For Kiro, use its official Windows installation instructions linked in
[backend documentation](docs/BACKENDS.md), then authenticate `kiro-cli` normally.
Open a fresh terminal after installing a CLI so PATH changes take effect.
Quack Actual uses each CLI's own authentication; never put tokens in this repo.

Enable **Settings → Privacy & security → Microphone → Let desktop apps access your
microphone**. Then:

```powershell
.\launch.ps1 doctor --backend copilot
.\launch.ps1 devices
.\launch.ps1 start --backend copilot --project C:\src\my-project
```

Say “Quack Actual”, wait for the tone, then ask a question. You can also combine the
wake phrase and command: “Quack Actual, explain this repository.” After a spoken
reply, a 30-second follow-up window opens. Recognition is English in this release.

For a keyboard-only installation and initial agent smoke test:

```powershell
.\install.ps1 -TextOnly
.\launch.ps1 start --backend copilot --project C:\src\my-project --text-only
```

Rerun `install.ps1` without `-TextOnly` to add voice. `-SkipModels` defers model
download until first use; `-NoBootstrap` requires an already installed `uv`.
Launchers use the environment directly, so activation is optional and Python is
never installed into your system environment by these scripts.

## WSL2 Ubuntu 24.04

Run the Windows installer first in a checkout on the Windows filesystem. In Ubuntu,
open **that same checkout**, install/authenticate your preferred coding CLI in Ubuntu,
and create the separate Linux environment:

```bash
cd /mnt/c/Tools/quack-actual
bash install.sh
bash launch.sh start --backend copilot --project "$HOME/src/my-project"
```

The controller automatically finds this checkout's Windows `.venv/Scripts/python.exe`
for the audio process. With separate checkouts, pass the Windows interpreter's WSL path:

```bash
bash launch.sh start --backend kiro --project "$HOME/src/my-project" \
  --windows-python /mnt/c/Tools/quack-actual/.venv/Scripts/python.exe
```

No PulseAudio/WSLg microphone setup is required. Keep your actual Linux development
project in the Linux filesystem. Configuration is loaded by the controller's OS and
sent to the audio process: edit the Ubuntu config when running the Ubuntu controller.
`install.sh --voice` is available for native Linux audio experimentation; it needs
PortAudio and a working platform TTS driver, which are not installed by this script.

## Select and switch agents

```powershell
.\launch.ps1 start --backend claude --project C:\src\my-project
.\launch.ps1 start --backend codex --project C:\src\my-project
.\launch.ps1 start --backend kiro --project C:\src\my-project
```

In the console, type `/backend copilot`, `/backend claude`, `/backend codex`, or
`/backend kiro`. During a listening window, say “switch to Copilot” (or the other
agent name). Idle sessions are retained when switching during the same application
run. Sessions are not automatically restored after restarting Quack Actual.

`--model` selects a model for the initially chosen backend; `--kiro-agent` selects a
Kiro custom agent. Codex is read-only by default. Explicitly opt into workspace writes:

```powershell
.\launch.ps1 start --backend codex --project C:\src\my-project --codex-sandbox workspace-write
```

This program never adds full-access or skip-all-permissions flags. However, an
agent can already have trusted tools or permissive settings configured by you.
Review those settings before enabling always-listening operation.

## Controls and permissions

| Command | Action |
|---|---|
| `/backend NAME` | Switch backend, retaining its idle session |
| `/new` | Reset the selected backend session |
| `/listen`, `/sleep` | Arm one command or return to wake-phrase mode |
| `/cancel` | Stop speech and request cancellation of the active turn |
| `/mute`, `/unmute`, `/repeat` | Control spoken replies |
| `/approve N`, `/deny` | Resolve a displayed ACP permission request; keyboard only |
| `/status`, `/help`, `/quit` | Inspect state, get help, or exit |

Spoken local controls include “cancel”, “go to sleep”, “mute”, “unmute”, and
“repeat that”. While speaking or running an agent turn, prefix your command with
“Quack Actual”, for example **“Quack Actual, cancel.”** Cancellation is best effort:
it stops future work, but cannot undo tools that already ran or remote work they started.

Copilot and Kiro use ACP and display actual permission options in the console.
Claude and Codex use noninteractive JSONL modes: their existing permissions and
sandbox rules apply, but this wrapper does not implement interactive approvals for
those two adapters. Configure approved operations in the native CLI. Voice input
never approves a pending tool action.

## Configuration and audio behavior

```powershell
.\launch.ps1 config path
.\launch.ps1 config init
```

Windows defaults to `%LOCALAPPDATA%\QuackActual\config.json`; Ubuntu defaults to
`~/.config/quack-actual/config.json`. `--config PATH` selects another file. A complete
example is in [config.example.json](config.example.json). Change `wake_phrase`,
`microphone` (device index/name or null), `conversation_seconds`, or `rms_threshold`
as needed. Restart the application after edits.

The default wake mechanism transcribes local speech segments with `tiny.en` and
checks an anchored phrase; commands use `small.en`. This is **not** a dedicated
low-power wake-word model and may transcribe background conversation locally.
Audio is not saved by this application. First model downloads use the model host's
normal network/cache behavior. Agent CLIs may persist command transcripts themselves.

A headset is recommended. There is no acoustic echo cancellation or speaker identity
verification. Barge-in is detected after speech segmentation/transcription, not
instantaneously. Wake phrases are convenience controls, not authentication. Code
blocks and long URLs are filtered from TTS. Replies stream in the terminal; TTS
starts after the agent completes its turn.

## Optional startup at login

This is opt-in and opens a visible console for permissions and diagnostics:

```powershell
.\scripts\autostart.ps1 -Backend copilot -Project C:\src\my-project
# Or start the Ubuntu controller:
.\scripts\autostart.ps1 -Mode wsl -Distro Ubuntu-24.04 -Backend kiro -Project '~/src/my-project'
# Remove only Quack Actual's startup shortcut:
.\scripts\autostart.ps1 -Remove
```

## Verify your installation

Run `doctor`, then `devices`, then a text-only prompt. Test a wake phrase, a spoken
reply, a follow-up, a cancellation, a denied tool request, and backend switching.
Check `git diff` in the target project. Keep the terminal open and use Ctrl+C as an
escape hatch. No live subscription calls or microphone recordings are made by CI.

Developer tests and builds:

```bash
uv sync --python 3.12
uv run python -m unittest discover -s tests -v
uv run python -m compileall -q src tests
uv build
uv run python scripts/build_release.py
```

See [architecture](docs/ARCHITECTURE.md), [backend references](docs/BACKENDS.md),
[security notes](SECURITY.md), and [release notes](RELEASE.md).
