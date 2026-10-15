"""Check the real fixed reference import and bounded durable-result failure paths."""

import json
import os
import sys
import tempfile
import zlib
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

from modules.workspaces.git_objects import GitObjectStore, managed_repository_slot
from modules.workspaces.reference_seed import REFERENCE_COMMIT, REFERENCE_INPUT_SET, REFERENCE_PREFIX
from modules.workspaces.safe_paths import WorkspaceFileError
from modules.workspaces.source_import import ReferenceImportSpec, ReferenceSourceImporter, reference_import_digest
from packages.contracts.p1.workspace_git import RegisteredGitSource

ROOT = Path(__file__).resolve().parents[2]


def _spec(project: str) -> ReferenceImportSpec:
    return ReferenceImportSpec(source=RegisteredGitSource(
        project_id=project, source_id="source-" + project, source_revision=1,
        kind="managed_bare", target_branch="refs/heads/main", source_prefix="",
        object_format="sha1", access_mode="read_write",
    ))


def _reject(checks: list[str], label: str, code: str, call) -> None:
    try:
        call()
    except WorkspaceFileError as error:
        if error.code != code:
            raise AssertionError(f"{label}: expected {code}, got {error.code}") from None
    else:
        raise AssertionError(f"{label}: rejection missing")
    checks.append(label)


def _real_import(importer, repositories: Path, operations: dict, checks: list[str]):
    assert importer.query("initial").state == "not_found"
    rename = os.rename

    def lost_completion(*args, **kwargs):
        rename(*args, **kwargs)
        raise OSError("synthetic lost completion after rename")

    with patch("modules.workspaces.source_import.os.rename", side_effect=lost_completion):
        _reject(checks, "lost-publish-completion", "source_import_unconfirmed",
                lambda: importer.import_reference("initial"))
    status = importer.query("initial")
    assert status.state == "published"
    receipt = status.receipt
    assert receipt.request_digest == reference_import_digest(operations["initial"])
    assert receipt.seed_commit == REFERENCE_COMMIT and receipt.file_count == len(receipt.files) == 32
    assert receipt.import_commit != receipt.seed_commit and receipt.source.source_prefix == ""
    expected = {entry["path"][len(REFERENCE_PREFIX) + 1:]: "sha256:" + entry["sha256"]
                for entry in json.loads((ROOT / REFERENCE_INPUT_SET).read_bytes())["files"]
                if entry["path"].startswith(REFERENCE_PREFIX + "/")}
    assert {entry.path: entry.content_digest for entry in receipt.files} == expected
    assert not any(entry.path.startswith(("docs/acceptance/", "examples/standalone-project/")) for entry in receipt.files)
    repository = repositories / managed_repository_slot(receipt.source)
    assert not any((repository / name).exists() for name in ("hooks", "refs/remotes", "objects/info/alternates"))
    git = GitObjectStore(repositories)
    try:
        git.register_source(receipt.source)
        tree = git.inspect_commit(receipt.source, receipt.import_commit)
        assert tree.files == receipt.files and tree.manifest_digest == receipt.manifest_digest
        _reject(checks, "seed-history-not-imported", "git_object_unavailable",
                lambda: git.inspect_commit(receipt.source, REFERENCE_COMMIT))
    finally:
        git.close()
    assert importer.import_reference("initial") == receipt
    checks.extend(["real-fixed-reference-32-source-files", "private-bare-without-hooks-remotes-or-assets", "original-result-replay"])
    operations["initial"] = _spec("different-project")
    _reject(checks, "same-operation-different-digest", "source_import_request_digest_conflict",
            lambda: importer.import_reference("initial"))
    operations["initial"] = ReferenceImportSpec(source=receipt.source)
    operations["second-operation"] = operations["initial"]
    _reject(checks, "project-source-replacement", "source_import_project_already_claimed",
            lambda: importer.import_reference("second-operation"))
    return receipt


def _pending_and_revocation(importer, repositories: Path, operations: dict, checks: list[str]) -> None:
    with patch.object(ReferenceSourceImporter, "_prepare", side_effect=OSError("synthetic interrupted preparation")):
        _reject(checks, "interrupted-intent", "source_import_unconfirmed", lambda: importer.import_reference("interrupted"))
    assert importer.query("interrupted").state == "pending"
    before = set(repositories.iterdir())
    _reject(checks, "pending-does-not-recreate", "source_import_pending_reconciliation",
            lambda: importer.import_reference("interrupted"))
    assert set(repositories.iterdir()) == before
    _reject(checks, "prepublish-revocation", "source_import_operation_unregistered",
            lambda: importer.import_reference("revoked"))
    status = importer.query("revoked")
    assert status.state == "failed" and status.reason_code == "source_import_operation_unregistered"
    assert not (repositories / managed_repository_slot(operations["revoked"].source)).exists()
    assert not any(path.name.startswith("stage-") for path in repositories.iterdir())
    checks.append("revocation-cleans-only-unpublished-stage")


def _bad_digests(root: Path, repositories: Path, resolve, checks: list[str]) -> None:
    for identity, corrupt_manifest in (("bad-manifest", True), ("bad-object", False)):
        seed = root / identity
        manifest = seed / REFERENCE_INPUT_SET
        manifest.parent.mkdir(parents=True)
        manifest.write_bytes((ROOT / REFERENCE_INPUT_SET).read_bytes() + (b"\n" if corrupt_manifest else b""))
        if not corrupt_manifest:
            objects = seed / ".git/objects" / REFERENCE_COMMIT[:2]
            objects.mkdir(parents=True)
            body = b"tree " + b"0" * 40 + b"\n"
            (objects / REFERENCE_COMMIT[2:]).write_bytes(zlib.compress(f"commit {len(body)}\0".encode("ascii") + body))
        importer = ReferenceSourceImporter(repositories, seed, resolve)
        try:
            code = "reference_input_set_mismatch" if corrupt_manifest else "git_object_digest_mismatch"
            _reject(checks, identity, code, lambda: importer.import_reference(identity))
            status = importer.query(identity)
            assert status.state == "failed" and status.reason_code == code
            _reject(checks, identity + "-original-failure", "source_import_failed", lambda: importer.import_reference(identity))
        finally:
            importer.close()


def main() -> None:
    started = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    checks, calls = [], {}
    operations = {identity: _spec(identity) for identity in ("initial", "interrupted", "revoked", "bad-manifest", "bad-object")}

    def resolve(operation_id):
        calls[operation_id] = calls.get(operation_id, 0) + 1
        if operation_id == "revoked" and calls[operation_id] == 2:
            raise LookupError
        return operations[operation_id]

    with tempfile.TemporaryDirectory(prefix="cloudhelm-source-import-") as directory:
        root = Path(directory)
        repositories = root / "repositories"
        repositories.mkdir(mode=0o700)
        importer = ReferenceSourceImporter(repositories, ROOT, resolve)
        try:
            receipt = _real_import(importer, repositories, operations, checks)
            _pending_and_revocation(importer, repositories, operations, checks)
            _bad_digests(root, repositories, resolve, checks)
        finally:
            importer.close()
        restored = ReferenceSourceImporter(repositories, root / "absent-seed", resolve)
        try:
            assert restored.query("initial").receipt == restored.import_reference("initial") == receipt
            checks.append("restored-query-and-replay-without-seed")
        finally:
            restored.close()
    print(json.dumps({
        "method_revision": "p1-reference-source-import-r1", "input_kind": "development_worktree",
        "started_at": started, "finished_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "platform": sys.platform, "python": sys.version.split()[0], "seed_commit": receipt.seed_commit,
        "seed_tree": receipt.seed_tree, "import_commit": receipt.import_commit,
        "input_set_digest": receipt.input_set_digest, "manifest_digest": receipt.manifest_digest,
        "file_count": receipt.file_count, "total_bytes": receipt.total_bytes,
        "checks": checks, "check_count": len(checks), "result": "passed",
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
