"""Trusted local maintenance of the two registered fixed-reference seeds."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

from modules.artifacts.errors import ArtifactContentError
from modules.workspaces.safe_paths import WorkspaceFileError
from packages.contracts.p1.npm_cache import npm_seed_id

from . import python_dependencies
from .engineering_registry import NPM_DOWNLOAD_ROOT, REPOSITORY
from .engineering_seeds import _copy, read_npm_seed, reference_npm_spec
from .npm_download_io import NpmDownloadError
from .npm_downloads import NpmDownloadStore
from .toolchain import ProbeFailure, private_directory

LEGACY_NPM_ROOT = Path("/home/cloudhelm/.local/state/cloudhelm/npm-download-seed")
LEGACY_NPM_MANIFEST = "sha256:1763287887271b7713a4d0764739b73bf592d37b6cab85535546d0b3f15c98d0"


def _npm_summary(receipt):
    return {"seed_id": receipt.manifest.cache_id, "manifest_digest": receipt.manifest_digest,
            "file_count": receipt.manifest.file_count, "seed_bytes": receipt.seed_bytes,
            "cache_hit": receipt.cache_hit}


def _python_summary(receipt):
    return {key: receipt[key] for key in (
        "cache_key", "manifest_digest", "wheel_count", "retained_bytes", "cache_hit", "downloaded_bytes")
        if key in receipt}


def prepare():
    """Only this explicit maintenance action may acquire fixed public downloads."""
    private_directory(NPM_DOWNLOAD_ROOT.parent)
    private_directory(NPM_DOWNLOAD_ROOT)
    with NpmDownloadStore(NPM_DOWNLOAD_ROOT) as store:
        npm = store.prepare(reference_npm_spec(), REPOSITORY / "examples/standalone-project/frontend")
    python = python_dependencies.prepare_seed(python_dependencies.PythonDependencyInput())
    return {"npm": _npm_summary(npm), "python": _python_summary(python)}


def verify():
    """No directory creation, acquisition or installation."""
    npm = read_npm_seed()
    inputs = python_dependencies.PythonDependencyInput()
    python = python_dependencies.verify_seed(python_dependencies.CACHE_ROOT / inputs.cache_key, inputs)
    return {"npm": _npm_summary(npm), "python": _python_summary(python)}


def import_legacy(probe_id):
    """Import one explicitly named old seed; never discover or delete old data."""
    if not re.fullmatch(r"npm-check-[0-9a-f]{32}", probe_id):
        raise ProbeFailure("engineering_legacy_npm_id_invalid")
    spec = reference_npm_spec()
    source = LEGACY_NPM_ROOT / probe_id / "cache"
    with NpmDownloadStore(source) as old:
        previous = old.verify(spec, expected_manifest_digest=LEGACY_NPM_MANIFEST)
    # The Python seed already uses its fixed content key. Import never downloads.
    inputs = python_dependencies.PythonDependencyInput()
    python = python_dependencies.verify_seed(python_dependencies.CACHE_ROOT / inputs.cache_key, inputs)
    private_directory(NPM_DOWNLOAD_ROOT.parent)
    private_directory(NPM_DOWNLOAD_ROOT)
    with NpmDownloadStore(NPM_DOWNLOAD_ROOT) as store:
        with store.root.exclusive():
            target = NPM_DOWNLOAD_ROOT / npm_seed_id(spec)
            reused = os.path.lexists(target)
            if not reused:
                _copy(source / npm_seed_id(spec), target)
        current = store.verify(spec)
    if (current.manifest.model_dump(exclude={"created_at"})
            != previous.manifest.model_dump(exclude={"created_at"})):
        raise ProbeFailure("engineering_legacy_npm_content_mismatch")
    return {"npm": _npm_summary(current), "python": _python_summary(python),
            "reused": reused, "legacy_source_retained": True}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="action", required=True)
    commands.add_parser("prepare", help="Acquire or reuse the fixed npm and Python seeds")
    commands.add_parser("verify", help="Verify both registered seeds offline")
    legacy = commands.add_parser("import-legacy", help="Copy one verified legacy npm seed offline")
    legacy.add_argument("--npm-probe-id", required=True)
    arguments = parser.parse_args(argv)
    try:
        if sys.platform != "linux" or os.getuid() != 1000:
            raise ProbeFailure("engineering_seed_trusted_linux_uid_1000_required")
        if arguments.action == "prepare":
            result = prepare()
        elif arguments.action == "verify":
            result = verify()
        else:
            result = import_legacy(arguments.npm_probe_id)
        print(json.dumps({"action": arguments.action, **result}, sort_keys=True))
        return 0
    except (ProbeFailure, NpmDownloadError, WorkspaceFileError, ArtifactContentError) as error:
        print(json.dumps({"error": str(error)}, sort_keys=True))
        return 1
    except (OSError, ValueError):
        print(json.dumps({"error": "engineering_seed_maintenance_rejected"}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
