# Security and privacy

Use Quack Actual only on a trusted local machine. It is not a sandbox, authentication
system, or security boundary. A wake phrase can be spoken by anyone nearby or by
media playing on the computer. A conversation window accepts subsequent speech
without another wake phrase. Use a headset and close the application when not needed.

Tool permissions remain the agent's responsibility. Copilot/Kiro permission
requests are answered only by explicit terminal selection; empty, expired, invalid,
and cancelled decisions fail closed. Claude/Codex headless modes use their own
policy, not this permission UI. No all-tools or full-access bypass is enabled by
default. Codex defaults to a read-only sandbox; workspace-write is explicit.

Cancellation cannot undo completed filesystem changes, network requests, remote
jobs, or child processes that independently detach. Use source control and review
diffs. Commands and context still leave your machine through the selected agent;
local speech recognition does not make the coding agent itself offline.

The package does not write microphone recordings or conversation logs. Agent CLIs
and model-download libraries have their own logging/cache behavior. Configuration
has no credential fields. Never commit credentials, `.env`, personal configurations,
or model caches. Startup at login is optional and visible, not a hidden service.

Dependencies come from package indexes; models download from their upstream hosts.
Release ZIPs include checksums and a file manifest, but are not Authenticode-signed
Windows installers. Review downloads according to your organization's policy. Do not
disable TLS validation to work around a corporate proxy; use an approved CA trust
configuration instead.
