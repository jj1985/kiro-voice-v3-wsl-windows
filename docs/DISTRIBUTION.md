# Distribution and portability

## What is portable

Distribute a verified **setup ZIP** or Python wheel, not an installed virtual
environment. Installation creates a fresh environment for the recipient's operating
system and location. The Windows `.venv` and Linux `.venv-wsl` must remain separate.
An installed environment, its generated entry points and an optional startup
shortcut can contain local absolute paths. Do not redistribute those files or
assume that moving a configured installation preserves them. Recreate the
environment and startup entry at the new location instead.

Supported deployment targets are Windows 11 x64 and WSL2 Ubuntu 24.04. Python
metadata currently permits 3.12 and 3.13; installers select 3.12. ARM, macOS,
Windows on ARM emulation, arbitrary Linux desktop audio, and air-gapped deployment
are not certified by the current tests. Hosted Windows CI is a Windows Server
runner, not a physical Windows 11 desktop or microphone test. A pure-Python wheel tag does not mean
that its optional audio dependencies are available on every platform.

Initial setup requires downloads for Python, packages and speech models. The
coding-agent CLIs and their authentication are separate prerequisites. A virtual
environment does not bundle Windows voices, Linux system audio libraries, a GPU
driver, CUDA, or provider access. Corporate CA/proxy configuration is local to
the recipient; never embed it or disable TLS validation in a release.

Copilot additionally requires PowerShell 6+ on Windows (PowerShell 7 is a suitable
choice), and Node.js 22+ when installed through npm. Native installers can have
different prerequisites. Check the linked vendor documentation rather than
assuming that Python/uv installation also installs every agent runtime.

## Release hygiene

`RELEASE-FILES.txt` is the explicit setup-source allowlist. Every listed file,
including `uv.lock`, must exist. Symlinks and paths outside the tree fail the
build. Adding a module or shipping documentation requires updating that list.
Unrelated Markdown or Python files must not silently enter a setup archive.

After `uv build`, `scripts/build_release.py` checks that the wheel and source
distribution match the reviewed source, rejects unapproved archive entries and
stale output archives, removes source-tar builder names/IDs, and creates the setup
ZIP. `scripts/verify_release.py` rejects empty, duplicate, malformed, unsafe and
mismatched checksums and verifies the setup ZIP's internal file manifest.
Checksums detect corruption; they are not a code signature or identity proof.

```bash
uv run --locked python scripts/release_audit.py
uv build
uv run --locked python scripts/build_release.py
uv run --locked python scripts/verify_release.py dist
```

The audit guard checks named home-directory paths, recognizable credential shapes,
local/private dependency sources and author/maintainer fields in wheel metadata.
It is deliberately not described as a complete secret scanner. Optional private
terms can be supplied as a JSON array in `QUACK_ACTUAL_AUDIT_TERMS_JSON`; keep
that setting outside the repository and CI logs. Findings do not print matched
values. Do not put real identities, credentials, hostnames or employer names in
regression tests. Use generated fixtures.

Configuration files, `.env` files, model caches, audio recordings, logs and local
venvs are not distributable source. A diagnostic printed on the recipient's
machine may show that recipient's interpreter, operating system and paths. Review
and redact diagnostics before sharing them. The coding CLIs may separately save
sessions or transmit project context under their own policies.

## Git metadata is separate

An identity-free setup package is not an anonymous GitHub repository. Git author
and committer records, repository ownership, commit messages, historical source,
release uploader information and CI logs can identify contributors or build
accounts. Deleting text from current files does not erase history. History
rewriting, repository transfer and deleting published assets require separate,
explicit decisions; a portability review does not perform those operations.

## Licensing decision remains open

No project license has been selected. Passing package tests is not permission for
third parties to modify or redistribute the project. Choose the project's license
and add its license file and package metadata before advertising an open-source
distribution. Also review the applicable terms for dependencies, speech models
and separately installed coding CLIs. This document does not choose a license or
change anyone's rights.

References:
- Python virtual environments: https://docs.python.org/3.12/library/venv.html
- uv locking and syncing: https://docs.astral.sh/uv/concepts/projects/sync/
- GitHub licensing: https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/licensing-a-repository

- Copilot prerequisites: https://docs.github.com/en/copilot/how-tos/copilot-cli/set-up-copilot-cli/install-copilot-cli
