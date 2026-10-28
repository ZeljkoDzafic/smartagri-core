from __future__ import annotations

import json
import os
import shutil
import subprocess
from typing import Dict, List, Optional

from .base import LLMError, LLMResponse, Provider


def render_conversation(messages: List[Dict[str, str]]) -> str:
    if len(messages) == 1:
        return messages[0]["content"]
    parts = []
    for m in messages:
        who = "KORISNIK" if m["role"] == "user" else "ASISTENT"
        parts.append("[%s]\n%s" % (who, m["content"]))
    return "\n\n".join(parts) + "\n\nOdgovori na poslednju poruku korisnika."


class ClaudeCliProvider(Provider):
    """Claude through the locally installed Claude Code CLI (`claude -p`), using the user's own login.

    Runs with no tools, no session persistence and its own system prompt, so a call is a plain completion.
    """
    name = "claude-cli"
    # `claude -p` takes the prompt as text on stdin and runs here with no tools, so it cannot read an image;
    # photo descriptions report "not available" for this provider (graceful degradation, no 500).
    supports_images = False

    def __init__(self, model: Optional[str] = None, binary: Optional[str] = None, runner=None, timeout: int = 180):
        self.binary = binary or os.environ.get("CLAUDE_CLI", "claude")
        # An exact model id by default, never an alias such as "sonnet" that moves to a new version on its own.
        self.model = model or os.environ.get("CLAUDE_CLI_MODEL") or os.environ.get("LLM_MODEL") or "claude-sonnet-5-5"
        self.timeout = timeout
        self._run = runner or subprocess.run
        if runner is None and shutil.which(self.binary) is None:
            raise LLMError("claude-cli: `%s` not found on PATH" % self.binary)

    def complete(self, system, messages, json_schema=None, max_tokens=4000) -> LLMResponse:
        args = [self.binary, "-p", "--output-format", "json", "--no-session-persistence", "--tools", "",
                "--model", self.model, "--system-prompt", system]
        if json_schema:
            args += ["--json-schema", json.dumps(json_schema)]
        try:
            proc = self._run(args, input=render_conversation(messages), capture_output=True, text=True,
                             timeout=self.timeout, cwd=os.environ.get("CLAUDE_CLI_CWD", "/tmp"))
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise LLMError("claude-cli: %s" % exc.__class__.__name__)
        try:
            out = json.loads(proc.stdout)
        except ValueError:
            raise LLMError("claude-cli: no JSON output (exit %s)" % proc.returncode)
        if out.get("is_error") or out.get("subtype") != "success":
            raise LLMError("claude-cli: %s" % (out.get("subtype") or "error"))
        usage = out.get("usage") or {}
        data = out.get("structured_output") if json_schema else None
        text = out.get("result") or ""
        return LLMResponse(text if data is None else json.dumps(data, ensure_ascii=False), self.name, self.model,
                           int(usage.get("input_tokens", 0)) + int(usage.get("cache_read_input_tokens", 0)),
                           int(usage.get("output_tokens", 0)), out.get("total_cost_usd"),
                           out.get("stop_reason") or "end_turn", data, request_id=out.get("session_id"))
