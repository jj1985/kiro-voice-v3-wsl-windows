#!/usr/bin/env python3
import unittest

from backends import BackendError, ClaudeBackend, CodexBackend, KiroBackend, create_backend


class BackendTests(unittest.TestCase):
    def test_factory(self):
        self.assertIsInstance(create_backend("kiro"), KiroBackend)
        self.assertIsInstance(create_backend("claude"), ClaudeBackend)
        self.assertIsInstance(create_backend("codex"), CodexBackend)
        with self.assertRaises(BackendError):
            create_backend("unknown")

    def test_codex_initial_command(self):
        backend = CodexBackend(
            model="test-model", sandbox="workspace-write", skip_git_check=True
        )
        backend.binary = "/usr/bin/codex"
        self.assertEqual(
            backend._command("review this"),
            [
                "/usr/bin/codex",
                "exec",
                "--json",
                "--model",
                "test-model",
                "--skip-git-repo-check",
                "--sandbox",
                "workspace-write",
                "review this",
            ],
        )

    def test_codex_resume_command(self):
        backend = CodexBackend(model="test-model", sandbox="workspace-write")
        backend.binary = "/usr/bin/codex"
        backend.thread_id = "thread-123"
        self.assertEqual(
            backend._command("continue"),
            [
                "/usr/bin/codex",
                "exec",
                "--json",
                "--model",
                "test-model",
                "resume",
                "thread-123",
                "continue",
            ],
        )


if __name__ == "__main__":
    unittest.main()
