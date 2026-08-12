"""Optional narrative composer — shells out to the `claude` CLI, if present.

The composer is a *nicety*. The pipeline's real output is the static digest in
``brief.format_digest``: a plain data dump with no interpretation in it at all.
When the CLI is missing, unauthenticated, slow, or returns something that is
not shaped like a brief, the static digest is what ships — see the positive
header check in ``brief.compose_brief``.

That ordering is the whole safety story. A model that cannot be reached costs
you prose, never correctness, and never an unreviewed sentence about money.
"""

import asyncio
import logging
import shutil

logger = logging.getLogger(__name__)

#: Seconds to wait for the CLI before giving up and using the static digest.
_TIMEOUT = 180


def claude_available() -> bool:
    """True if a `claude` executable is on PATH."""
    return shutil.which("claude") is not None


class ClaudeRunner:
    """Thin async wrapper over `claude -p`.

    The interface is deliberately narrow — one method, keyword-only options —
    so the pipeline can be handed any object with a matching ``run`` (a real
    API client, a fake in tests) without knowing a CLI exists.
    """

    def __init__(self, executable: str | None = None, timeout: int = _TIMEOUT):
        self.executable = executable or shutil.which("claude") or "claude"
        self.timeout = timeout

    async def run(self, prompt: str, *, model: str = "",
                  max_turns: int = 6,
                  disallowed_tools: list[str] | None = None) -> tuple[str, dict]:
        """Run one prompt. Returns (text, meta). Never raises on CLI failure.

        `disallowed_tools` is not decoration: the prompt embeds untrusted feed
        text, so every tool the CLI could otherwise reach is denied explicitly.
        The composer needs no tools — it is handed all its data inline.
        """
        argv = [self.executable, "-p", "--output-format", "text"]
        if model:
            argv += ["--model", model]
        if max_turns:
            argv += ["--max-turns", str(max_turns)]
        if disallowed_tools:
            argv += ["--disallowed-tools", ",".join(disallowed_tools)]

        try:
            proc = await asyncio.create_subprocess_exec(
                *argv,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            out, err = await asyncio.wait_for(
                proc.communicate(prompt.encode("utf-8")), timeout=self.timeout
            )
        except asyncio.TimeoutError:
            logger.warning("Claude compose timed out after %ss", self.timeout)
            return "", {"ok": False, "reason": "timeout"}
        except Exception as e:
            logger.warning("Claude compose could not start: %s", e)
            return "", {"ok": False, "reason": "spawn-failed"}

        if proc.returncode != 0:
            logger.warning(
                "Claude compose exited %s: %s",
                proc.returncode, (err or b"").decode("utf-8", "replace")[:400],
            )
            return "", {"ok": False, "reason": f"exit-{proc.returncode}"}

        return (out or b"").decode("utf-8", "replace").strip(), {"ok": True}


def get_runner() -> ClaudeRunner | None:
    """A runner if the CLI is installed, else None (→ static digest)."""
    if not claude_available():
        logger.info("`claude` CLI not found — using the static digest formatter")
        return None
    return ClaudeRunner()
