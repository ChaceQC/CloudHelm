"""Retain a bounded, credential-filtered output from one real build command."""

import json
from contextlib import closing
from datetime import UTC, datetime

from modules.agent_runtime.source_context import safe_context_text
from modules.workspaces.safe_paths import PrivateRoot, write_new_file

BUILD_LOG_BYTES = 64 * 1024


def retain_build_output(directory, result, *, name="build-output"):
    raw = safe_context_text(result.stdout + result.stderr).encode("utf-8")
    value = {"text": raw[-BUILD_LOG_BYTES:].decode("utf-8", errors="ignore"),
             "exit_code": result.returncode, "truncated": len(raw) > BUILD_LOG_BYTES,
             "source_bytes": len(raw), "captured_at": datetime.now(UTC).isoformat(),
             "stream_order": "stdout_then_stderr"}
    with closing(PrivateRoot(directory)) as root:
        write_new_file(root.fd, name + ".json", json.dumps(value, ensure_ascii=False).encode("utf-8"))
