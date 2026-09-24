# Quack Actual 0.5.0 - Radio Check

Preview release: one voice console for Copilot CLI, Claude Code, Codex CLI, and Kiro CLI.

## Changes

- Rebranded the application, package, launchers, environment variables, configuration,
  startup entry, and distribution artifacts as Quack Actual.
- Added Copilot's native ACP integration with streamed replies and explicit tool permissions.
- Replaced WSL-only scripts with a shared Python package and a native Windows 11 launch path.
- Added uv-managed Python 3.12 installation and separate Windows/WSL virtual environments.
- Preserved backend sessions across switching during the application lifetime.
- Added anchored wake matching, bounded STT queues, stale-event filtering, predictable
  shutdown, subprocess-tree cancellation, and a single approval-aware keyboard reader.
- Added diagnostics, model prefetch, optional visible auto-start, installation documentation,
  a source/setup ZIP, Python wheel, source distribution, and SHA-256 checksums.

## Validation and limitations

Automated checks exercise simulated ACP and headless agents, session handling,
permissions, input safety, configuration, speech routing, process cleanup, and package
contents. The release workflow runs these checks on Windows and Ubuntu. No live
provider credentials, microphone hardware, or paid AI requests are used in CI.

Run the README manual smoke tests on your Windows 11 / WSL installation before
relying on the voice path. This is an online setup package: Python, dependencies,
model files, and separately licensed agent CLIs are not all bundled for offline use.
Authentication is performed through the vendor's own CLI.

Claude/Codex headless approvals are not implemented as interactive wrapper prompts.
Copilot ACP remains an upstream preview interface. Wake detection uses local Whisper,
not a dedicated low-power wake-word model. There is no echo cancellation or speaker
verification, and barge-in includes transcription latency. TTS starts after each turn.

## Upgrade

Use a fresh application folder or update your checkout, then run the new installer.
Do not reuse an older virtual environment. Old settings are not automatically imported;
copy the desired values to the new configuration schema. Re-create any startup entry.
The default wake phrase is now "Quack Actual". Your coding project files are not moved.
