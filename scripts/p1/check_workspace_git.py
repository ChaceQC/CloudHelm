"""Focused development check for safe paths and a real bare-Git file view."""

import os
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import patch

from modules.workspaces.git_objects import GitObjectStore, managed_repository_slot
from modules.workspaces.safe_paths import PrivateRoot, WorkspaceFileError, read_regular, write_new_file
from modules.workspaces.workfiles import WorkfileStore
from packages.contracts.p1.workspace_git import RegisteredGitSource, WorkspaceBinding

_FIXTURE_ENV = {
    "PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8",
    "HOME": "/nonexistent", "XDG_CONFIG_HOME": "/nonexistent",
    "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null",
    "GIT_AUTHOR_NAME": "CloudHelm fixture", "GIT_AUTHOR_EMAIL": "fixture@example.invalid",
    "GIT_COMMITTER_NAME": "CloudHelm fixture", "GIT_COMMITTER_EMAIL": "fixture@example.invalid",
    "GIT_AUTHOR_DATE": "2026-10-15T00:00:00Z", "GIT_COMMITTER_DATE": "2026-10-15T00:00:00Z",
}


def _git(repository: Path, *arguments: str, data: bytes | None = None) -> str:
    result = subprocess.run(
        ["/usr/bin/git", f"--git-dir={repository}", *arguments], input=data,
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=_FIXTURE_ENV,
        cwd="/", timeout=10, check=False,
    )
    if result.returncode:
        raise RuntimeError("fixture_git_failed")
    return result.stdout.decode("utf-8").strip()


def _tree(repository: Path, files: dict) -> str:
    entries = []
    for name, value in sorted(files.items()):
        if isinstance(value, dict):
            mode, oid = "40000", _tree(repository, value)
        else:
            mode, data = value
            oid = _git(repository, "hash-object", "-w", "--stdin", data=data)
        entries.append(mode.encode() + b" " + name.encode("utf-8") + b"\0" + bytes.fromhex(oid))
    return _git(repository, "hash-object", "--literally", "-t", "tree", "-w", "--stdin",
                data=b"".join(entries))


def _commit(repository: Path, tree: str, parent: str | None = None) -> str:
    parent_arg = ("-p", parent) if parent else ()
    return _git(repository, "commit-tree", tree, *parent_arg, data=b"controlled fixture\n")


def _reject(checks: list[str], label: str, code: str, call) -> None:
    try:
        call()
    except WorkspaceFileError as error:
        if error.code != code:
            raise AssertionError(f"{label}: expected {code}, got {error.code}") from None
    else:
        raise AssertionError(f"{label}: rejection missing")
    checks.append(label)


def _safe_paths(root: Path, checks: list[str]) -> None:
    boundary = root / "boundary"
    boundary.mkdir(mode=0o700)
    outside = root / "outside.txt"
    outside.write_bytes(b"outside")
    (boundary / "linked").symlink_to(outside)
    (boundary / "linked-dir").symlink_to(root, target_is_directory=True)
    os.mkfifo(boundary / "fifo", 0o600)
    os.link(outside, boundary / "hardlink")
    (boundary / "large").write_bytes(b"four")

    storage = PrivateRoot(boundary)
    try:
        with storage.exclusive() as directory:
            for path in ("../outside.txt", ".git/config", "a\\b"):
                _reject(checks, f"path:{path}", "workspace_path_invalid",
                        lambda path=path: write_new_file(directory, path, b"forbidden"))
            _reject(checks, "symlink-file", "storage_not_service_owned",
                    lambda: read_regular(directory, "linked", 32))
            _reject(checks, "symlink-directory", "storage_path_unavailable",
                    lambda: read_regular(directory, "linked-dir/outside.txt", 32))
            _reject(checks, "fifo", "storage_not_service_owned",
                    lambda: read_regular(directory, "fifo", 32))
            _reject(checks, "hardlink", "storage_hardlink_forbidden",
                    lambda: read_regular(directory, "hardlink", 32))
            _reject(checks, "read-limit", "storage_file_too_large",
                    lambda: read_regular(directory, "large", 3))
            write_new_file(directory, "nested/valid.txt", b"UTF-8: \xe4\xb8\xad\xe6\x96\x87")
            assert read_regular(directory, "nested/valid.txt", 32).startswith(b"UTF-8:")
        assert outside.read_bytes() == b"outside"
    finally:
        storage.close()


def _source(root: Path, object_format: str, checks: list[str]) -> None:
    repositories, views = root / "repositories", root / "views"
    repositories.mkdir(mode=0o700)
    views.mkdir(mode=0o700)
    source = RegisteredGitSource(
        project_id="project-fixture", source_id="source-fixture", source_revision=1,
        kind="managed_bare", target_branch="refs/heads/main", object_format=object_format,
        access_mode="read_write",
    )
    repository = repositories / managed_repository_slot(source)
    subprocess.run(
        ["/usr/bin/git", "init", "--bare", "--initial-branch=main", "--template=",
         f"--object-format={object_format}", str(repository)],
        env=_FIXTURE_ENV, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        timeout=10, check=True,
    )
    repository.chmod(0o700)
    files = {
        "README.md": ("100644", b"original\r\n"),
        "src": {"main.py": ("100644", b"print('fixture')\n")},
        "run.sh": ("100755", b"#!/bin/sh\nexit 0\n"),
    }
    first = _commit(repository, _tree(repository, files))
    latest = _commit(repository, _tree(repository, {"later.txt": ("100644", b"later")}), first)
    _git(repository, "update-ref", "refs/heads/main", latest)

    git = GitObjectStore(repositories)
    store = None
    try:
        git.register_source(source)
        _reject(checks, "external-source", "git_external_source_unsupported",
                lambda: git.register_source(source.model_copy(update={"kind": "external"})))
        with patch.dict(os.environ, {"GIT_CONFIG_COUNT": "invalid", "GIT_DIR": "/untrusted"}):
            tree = git.inspect_commit(source, first)
        assert tree.commit == first
        assert {entry.path for entry in tree.files} == {"README.md", "src/main.py", "run.sh"}

        with git.open_commit(source, first) as (tree, reader):
            readme = next(entry for entry in tree.files if entry.path == "README.md")
            assert reader(readme) == b"original\r\n"
        _reject(checks, "expired-reader", "git_file_scope_mismatch", lambda: reader(readme))

        outsider = _commit(repository, _tree(repository, {"orphan.txt": ("100644", b"orphan")}))
        _reject(checks, "outside-target", "git_commit_outside_target",
                lambda: git.inspect_commit(source, outsider))
        _reject(checks, "non-exact-commit", "git_object_format_mismatch",
                lambda: git.inspect_commit(source, "HEAD"))

        binding = WorkspaceBinding(
            workspace_id="workspace-one", project_id=source.project_id, task_id="task-fixture",
            work_item_id="item-fixture", owner_user_id="owner-fixture", source_id=source.source_id,
            source_revision=1, base_commit=first, workspace_revision=1, write_generation=1,
        )
        store = WorkfileStore(views, git, lambda operation_id: binding)
        receipt = store.materialize(binding, "materialize-one")
        location = views / receipt.storage_id / "files"
        assert store.materialize(binding, "materialize-one") == receipt
        assert store.query(binding, "materialize-one") == receipt
        assert not (location / ".git").exists()
        assert (location / "README.md").read_bytes() == b"original\r\n"
        assert os.stat(location / "run.sh").st_mode & 0o777 == 0o755
        (location / "README.md").write_bytes(b"later edit")
        assert store.query(binding, "materialize-one") == receipt
        checks.append("real-git-file-view-and-immutable-receipt")

        unsafe = (
            ({"link": ("120000", b"/outside")}, "git_entry_type_unsupported"),
            ({"..": ("100644", b"escape")}, "git_path_unsupported"),
        )
        for index, (bad_files, error) in enumerate(unsafe):
            commit = _commit(repository, _tree(repository, bad_files), latest)
            _git(repository, "update-ref", "refs/heads/main", commit)
            _reject(checks, f"unsafe-git-tree-{index}", error,
                    lambda commit=commit: git.inspect_commit(source, commit))
    finally:
        if store is not None:
            store.close()
        git.close()


def main() -> None:
    checks = []
    with tempfile.TemporaryDirectory(prefix="cloudhelm-workspace-git-") as temporary:
        root = Path(temporary)
        _safe_paths(root, checks)
        for object_format in ("sha1", "sha256"):
            fixture = root / object_format
            fixture.mkdir(mode=0o700)
            _source(fixture, object_format, checks)
    print(f"workspace Git and safe-path checks passed: {len(checks)} cases")


if __name__ == "__main__":
    main()
