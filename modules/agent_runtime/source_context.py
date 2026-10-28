"""Bounded text from a registered, immutable Git source."""

import re

from modules.workspaces.safe_paths import WorkspaceFileError
from packages.contracts.p1.workspace_git import RegisteredGitSource, content_digest

_FILE_LIMIT = 64 * 1024
_TEXT_LIMIT = 32 * 1024
_REDACTED = "[REDACTED]"
_LINE_BREAKS = "\r\n\v\f\x1c\x1d\x1e\x85\u2028\u2029"
_PRIVATE_KEY = re.compile(
    r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----[\s\S]*?"
    r"(?:-----END [A-Z0-9 ]*PRIVATE KEY-----|\Z)", re.IGNORECASE,
)
_URL_CREDENTIALS = re.compile(r"\b([a-z][a-z0-9+.-]*://)[^\s/\"'<>]+@", re.IGNORECASE)
_ASSIGNMENT = re.compile(
    r"(?<![\w.-])[\"']?(?=[\w.-]*(?:secret|token|password|passwd|credential|"
    r"api[_-]?key|private[_-]?key|authorization))[a-z_][\w.-]*[\"']?[ \t]*[:=][ \t]*",
    re.IGNORECASE,
)
_SECRET_PART = re.compile(
    r"(?:^|[._-])(?:credentials?|secrets?|password|passwd|tokens?|private[_-]?keys?)(?:[._-]|$)"
)


def safe_context_text(text: str) -> str:
    """Remove obvious credentials without changing the original line boundaries."""
    text = _PRIVATE_KEY.sub(
        lambda match: _REDACTED + "".join(char for char in match.group() if char in _LINE_BREAKS), text,
    )
    text = _URL_CREDENTIALS.sub(r"\1[REDACTED]@", text)
    result = []
    continuation_indent = None
    continuation_first = False
    for line in text.splitlines(keepends=True):
        body = line.rstrip(_LINE_BREAKS)
        ending = line[len(body):]
        indent = len(body) - len(body.lstrip(" \t"))
        if continuation_indent is not None:
            if body.strip() and indent <= continuation_indent and not continuation_first:
                continuation_indent = None
            else:
                result.append((body[:indent] + _REDACTED if body.strip() else body) + ending)
                if body.strip():
                    continuation_first = False
                    if indent <= continuation_indent:
                        continuation_indent = None
                continue
        match = _ASSIGNMENT.search(body)
        if match:
            value = body[match.end():].split("#", 1)[0].strip()
            if not value or re.fullmatch(r"[|>][+-]?", value):
                continuation_indent = indent
                continuation_first = True
            body = body[:match.end()] + _REDACTED
        result.append(body + ending)
    return "".join(result)


def secret_context_path(path: str) -> bool:
    parts = path.casefold().split("/")
    return any(
        part.startswith(".env")
        or part in {".ssh", ".gnupg", ".aws", ".kube", ".docker", ".netrc", ".npmrc", ".pypirc", ".git-credentials"}
        or part.startswith(("id_rsa", "id_dsa", "id_ecdsa", "id_ed25519"))
        or part.endswith((".pem", ".key", ".p12", ".pfx", ".ppk", ".der", ".jks", ".keystore", ".keytab"))
        or _SECRET_PART.search(part)
        for part in parts
    )


def read_source_context(git, source: RegisteredGitSource, commit: str, reads) -> dict:
    """Read selected files and inherited rules from the verified source commit."""
    if source.source_prefix:
        raise WorkspaceFileError("source_context_prefix_unsupported")
    reads = tuple(reads)
    with git.open_commit(source, commit) as (tree, read_file):
        files = {item.path: item for item in tree.files}
        rules = {"AGENTS.md"}
        for read in reads:
            if secret_context_path(read.path):
                raise WorkspaceFileError("source_context_secret_path")
            entry = files.get(read.path)
            if entry is None:
                raise WorkspaceFileError("source_context_file_not_found")
            if entry.content_digest != read.digest:
                raise WorkspaceFileError("source_context_digest_mismatch")
            parts = read.path.split("/")[:-1]
            rules.update("/".join(parts[:depth] + ["AGENTS.md"]) for depth in range(1, len(parts) + 1))

        rule_paths = sorted((path for path in rules if path in files), key=lambda path: (path.count("/"), path))
        selected = [(files[path], "repository_rules", 1, 160) for path in rule_paths]
        selected.extend((files[read.path], read.purpose, read.start_line, read.max_lines) for read in reads)
        relevant = rules | {read.path for read in reads}
        safe_files = sorted(
            (item for item in tree.files if not secret_context_path(item.path)),
            key=lambda item: (item.path not in relevant, item.path),
        )
        paths = [{"path": item.path, "digest": item.content_digest, "size_bytes": item.size_bytes}
                 for item in safe_files[:64]]
        documents = []
        text_bytes = 0
        for entry, purpose, start_line, max_lines in selected:
            if entry.size_bytes > _FILE_LIMIT:
                raise WorkspaceFileError("source_context_file_too_large")
            data = read_file(entry)
            try:
                text = data.decode("utf-8")
            except UnicodeDecodeError:
                raise WorkspaceFileError("source_context_not_text") from None
            if "\x00" in text:
                raise WorkspaceFileError("source_context_not_text")
            lines = safe_context_text(text).splitlines(keepends=True)
            total_lines = len(lines)
            if start_line > max(total_lines, 1):
                raise WorkspaceFileError("source_context_line_out_of_range")
            content_lines = lines[start_line - 1:start_line - 1 + max_lines]
            content = "".join(content_lines)
            text_bytes += len(content.encode("utf-8"))
            if text_bytes > _TEXT_LIMIT:
                raise WorkspaceFileError("source_context_output_limit")
            end_line = start_line - 1 + len(content_lines)
            documents.append({
                "path": entry.path, "purpose": purpose, "digest": content_digest(data),
                "start_line": start_line, "end_line": end_line, "total_lines": total_lines,
                "content": content, "truncated": start_line > 1 or end_line < total_lines,
                "next_start_line": end_line + 1 if end_line < total_lines else None,
            })
        return {
            "commit": tree.commit, "manifest_digest": tree.manifest_digest, "paths": paths,
            "paths_truncated": len(safe_files) > len(paths), "documents": documents,
        }
