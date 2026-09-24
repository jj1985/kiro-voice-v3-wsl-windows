# Backend interfaces

| Backend | Interface used | Conversation | Approval behavior |
|---|---|---|---|
| GitHub Copilot CLI | `copilot --acp --stdio` | Persistent ACP session | Real ACP requests; keyboard chooses an option |
| Kiro CLI | `kiro-cli acp` | Persistent ACP session | Real ACP requests; keyboard chooses an option |
| Claude Code | `claude -p --output-format stream-json --verbose --include-partial-messages` | CLI session ID and `--resume` | Native headless rules; no wrapper approval UI |
| Codex CLI | `codex exec --json` | Thread ID and `exec resume` | Headless rules; explicitly constrained sandbox |

Claude and Codex receive prompt text over standard input, not via shell command
interpolation. Copilot and Kiro receive JSON-RPC requests over pipes. Unknown
client methods are rejected rather than silently treated as successful operations.
The controller advertises no client-side filesystem or terminal capabilities;
agents use their own tools. Not every UI-only command or extension is implemented.
Copilot ACP is currently a public-preview interface and can change.

On Windows, native executables launch directly. Known npm `.cmd` shims are resolved
to their package's `bin` entry and run using Node without `cmd.exe`. Other script
shims fail with a diagnostic instead of being evaluated by a shell. Advanced users
can specify an argument list in configuration, for example:

```json
{"commands":{"copilot":["C:\\Program Files\\nodejs\\node.exe","C:\\tools\\copilot\\index.js"]}}
```

That is a partial configuration example. Use installed paths on your machine; it
is not a download URL. Command overrides are trusted local configuration.

## Official references

- Copilot ACP: https://docs.github.com/en/copilot/reference/copilot-cli-reference/acp-server
- Copilot install: https://docs.github.com/en/copilot/how-tos/copilot-cli/set-up-copilot-cli/install-copilot-cli
- Claude programmatic mode: https://code.claude.com/docs/en/headless
- Claude Windows setup: https://code.claude.com/docs/en/setup
- Codex CLI: https://developers.openai.com/codex/cli
- Codex noninteractive mode: https://developers.openai.com/codex/noninteractive
- Kiro ACP: https://kiro.dev/docs/cli/acp/
- Kiro install: https://kiro.dev/docs/getting-started/installation/
- uv installation: https://docs.astral.sh/uv/getting-started/installation/
- uv projects: https://docs.astral.sh/uv/guides/projects/

Install and authenticate each CLI in the OS where the controller runs. The package
does not bundle or replace vendor binaries, require a new credential format, change
subscription terms, or claim endorsement by any vendor. Respect organizational
policy and provider terms when using local project context with an agent.
