# Kiro Voice V3 — Windows 11 + WSL2 Ubuntu 24.04

Always-listening, local voice activation for Kiro CLI.

## What V3 adds

- **Always-listening wake phrase** — default: `Hey Kiro`
- **No keypress required**
- **Conversation mode** — follow-ups do not need the wake phrase for 30 seconds
- **Barge-in** while Kiro is speaking
- **"Kiro stop" / "Kiro cancel"**
- **Activation/sleep sounds**
- **Cancelable Windows TTS**
- **Optional openWakeWord custom model**
- **Windows logon auto-start**
- Kiro itself still runs in **WSL Ubuntu 24.04** through ACP

## Architecture

```text
Windows 11
  microphone
     │
     ├── speech segmentation
     │
     ├── wake detector
     │     ├── whisper_phrase (default; any phrase, no training)
     │     └── openWakeWord (optional custom ONNX model)
     │
     ├── faster-whisper STT
     └── cancelable Windows SAPI TTS
              │
              │ JSONL/stdin/stdout over WSL interop
              ▼
WSL2 Ubuntu 24.04
  kiro_voice.py
     │
     ▼
  ACP Python SDK
     │
     ▼
  kiro-cli acp
     │
     ├── project files
     ├── shell/tools
     └── MCP/agents
```

## Why the default wake backend is `whisper_phrase`

A dedicated wake-word model is the lowest-power option, but a phrase such as
**"Hey Kiro"** needs a matching model.

V3 works immediately by using a lightweight audio gate continuously and only
running a tiny Whisper model after an actual speech segment is detected. The resulting local
transcript is checked for `Hey Kiro`. After activation, the command is transcribed again
with the higher-quality command model. Audio/transcription stays on the Windows
machine.

Once you train or obtain an openWakeWord `.onnx` model for `Hey Kiro`, change
`wake_backend` to `openwakeword` and set `wake_model` in `windows/config.json`.

## 1. Windows setup

Install **Python 3.12 x64**.

Enable desktop microphone access:

`Settings → Privacy & security → Microphone → Let desktop apps access your microphone`

In PowerShell:

```powershell
cd C:\path\to\kiro-voice-v3-wsl-windows
Set-ExecutionPolicy -Scope Process Bypass
.\windows\setup.ps1
```

The script prints a WSL environment line:

```bash
export KIRO_VOICE_WINDOWS_PY='/mnt/c/.../windows/.venv/Scripts/python.exe'
```

Put it in `~/.bashrc` inside WSL:

```bash
echo "export KIRO_VOICE_WINDOWS_PY='/mnt/c/.../python.exe'" >> ~/.bashrc
source ~/.bashrc
```

## 2. WSL Ubuntu 24.04 setup

Kiro CLI must be installed and authenticated **inside WSL**:

```bash
curl -fsSL https://cli.kiro.dev/install | bash
kiro-cli
```

Then:

```bash
cd /mnt/c/path/to/kiro-voice-v3-wsl-windows
bash wsl/setup.sh
```

## 3. Run it

Set the project Kiro should work in:

```bash
export KIRO_VOICE_PROJECT="$HOME/src/my-project"
./wsl/run.sh
```

Now leave the terminal open and say:

```text
Hey Kiro
```

You hear an activation tone. Then say:

```text
Look through this project and explain how authentication works.
```

Kiro replies normally in the terminal and the response is spoken.

You can also say the phrase and command together:

```text
Hey Kiro, run the unit tests.
```

## Conversation mode

After Kiro finishes speaking, V3 automatically opens a 30-second follow-up
window:

```text
You:  Hey Kiro, inspect auth.py.
Kiro: ...
You:  Fix the token expiration bug.
Kiro: ...
You:  Run the tests.
```

No repeated `Hey Kiro` is required until the conversation window expires.

## Barge-in

While Kiro is speaking:

```text
Kiro stop
```

stops TTS and cancels the active turn where possible.

```text
Kiro cancel
```

does the same and leaves the assistant ready for a follow-up.

For protection against the speakers accidentally triggering the microphone,
barge-in requires the word `Kiro` by default.

## Change the wake phrase

Edit:

```text
windows/config.json
```

For the default backend:

```json
{
  "wake_backend": "whisper_phrase",
  "wake_phrase": "computer"
}
```

Any spoken phrase can be used without training a model.

## Lower-power openWakeWord mode

For an openWakeWord custom `.onnx` model:

```json
{
  "wake_backend": "openwakeword",
  "wake_phrase": "hey kiro",
  "wake_model": "models/hey_kiro.onnx",
  "wake_threshold": 0.55
}
```

Model paths are relative to `windows/` unless absolute.

With this mode, openWakeWord examines the 16 kHz PCM microphone stream and
Whisper is used for the command text after activation.

## Whisper GPU mode

Start with CPU mode first.

If your Windows CUDA/CTranslate2 setup supports it, edit:

```json
{
  "wake_whisper_model": "tiny.en",
  "whisper_model": "small.en",
  "whisper_device": "cuda",
  "whisper_compute_type": "float16"
}
```

A modern GPU can make command transcription substantially faster.

## Tune microphone sensitivity

If ambient noise is starting recordings, increase:

```json
"speech_rms_threshold": 0.018
```

If your voice is not detected consistently, lower it:

```json
"speech_rms_threshold": 0.008
```

The default is `0.012`.

## Terminal controls

```text
/help
/listen
/sleep
/mute
/unmute
/cancel
/status
/quit
```

`/listen` manually arms one voice command without saying the wake phrase.

## Auto-start at Windows login

This intentionally starts the WSL controller in **Windows Terminal**, rather
than hiding it in the background, because Kiro may need interactive permission
approval.

PowerShell:

```powershell
cd C:\path\to\kiro-voice-v3-wsl-windows\windows

.\install-autostart.ps1 `
    -Distro "Ubuntu-24.04" `
    -KiroProject "~/src/my-project"
```

At the next Windows login, Windows Terminal opens a Kiro Voice tab and starts
the WSL controller.

Remove it with:

```powershell
.\install-autostart.ps1 -Remove
```

## Smoke test before connecting Kiro

From WSL:

```bash
source ~/.venvs/kiro-voice/bin/activate
python wsl/test_audio_bridge.py
```

Say `Hey Kiro`. You should see wake and utterance events.

## Privacy

With `whisper_phrase`, microphone speech segments are transcribed locally by
faster-whisper to determine whether the wake phrase was spoken. Nothing in this
project sends microphone audio to Kiro.

Only command **text** is sent to Kiro after activation.

With a dedicated openWakeWord model, Whisper does not need to run on ordinary
room speech; only the wake-word model processes the continuous stream.

## Practical audio note

If you use speakers rather than headphones, Kiro's own TTS can be picked up by
the microphone. V3 ignores ordinary speech while TTS is active and requires the
configured `barge_name` (`Kiro`) for barge-in by default. A headset provides
the best full-duplex behavior.
