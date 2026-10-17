"""Real fixed-reference HTTP/DBOS engineering chain; no stage or human acceptance."""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import os
import platform
import sys
import traceback
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path

from packages.contracts.p1.development_storage import DevelopmentStorageRef
from packages.contracts.p1.task_results import TaskView
from scripts.p1.database_fixture import DatabaseFixtureError, database_fixture
from scripts.p1.engineering_chain import (
    FROZEN_CONTENT, RESUMED_CONTENT, accept_source, freeze_candidate, grant_engineering,
    materialize, mutate, reference_task, revoke_and_check_replay,
)
from scripts.p1.engineering_fixture import EngineeringCheckFailure, EngineeringProbe, ROOT, fixed_inputs, process_fixture, require
from scripts.p1.runtime_processes import RuntimeProcessError, api_running, worker_running

METHOD_REVISION = "p1-2-engineering-chain-r1"


def _environment():
    require(os.name == "posix" and os.environ.get("WSL_DISTRO_NAME") == "Ubuntu-24.04"
            and os.getuid() == 1000 and ROOT == Path("/mnt/e/Project/CloudHelm"),
            "engineering_requires_registered_wsl_checkout_and_uid")
    return {"distribution": "Ubuntu-24.04", "kernel": platform.release(), "uid": os.getuid(),
            "repository": str(ROOT), "mount_namespace": os.readlink("/proc/self/ns/mnt"),
            "python": platform.python_version(), "dbos": version("dbos"),
            "sqlalchemy": version("sqlalchemy"), "interpreter": sys.executable}


def _chain(probe, storage, report, through_candidate):
    from scripts.p1.engineering_physical import build_and_environment, observe_candidate

    with api_running(probe.fixture, instance="engineer") as api:
        probe.http = api.client
        grant = grant_engineering(probe)
        report["last_stage"] = "source_http_accepted"
        source, workflow = accept_source(probe)
        with worker_running(probe.fixture) as worker:
            report["worker"] = {"pid": worker.process.pid, "installation_id": worker.installation_id,
                                "instances_started_by_method": 1}
            report["last_stage"] = "real_reference_task"
            active, input_ref = reference_task(probe, source, workflow)
            report["last_stage"] = "workspace_materialization"
            workspace_id, manifest, create_request, create_key = materialize(probe, active, input_ref)
            report["last_stage"] = "controlled_file_mutation"
            manifest, proof_file = mutate(probe, workspace_id, input_ref, manifest, FROZEN_CONTENT)
            report["last_stage"] = "candidate_freeze"
            candidate = freeze_candidate(probe, workspace_id, input_ref, manifest)
            before = observe_candidate(storage, candidate, FROZEN_CONTENT)
            report["last_stage"] = "development_resume"
            changed, _ = mutate(probe, workspace_id, input_ref, manifest, RESUMED_CONTENT, proof_file)
            after = observe_candidate(storage, candidate, FROZEN_CONTENT)
            require(before == after and changed != manifest, "engineering_frozen_candidate_changed_after_resume")
            probe.evidence["candidate_after_development_resume"] = {
                "before": before, "after": after, "development_manifest_digest": changed,
                "candidate_unchanged": True,
            }
            if not through_candidate:
                report["last_stage"] = "candidate_bound_build_and_environment"
                build_and_environment(probe, storage, candidate, input_ref, report)
            report["last_stage"] = "current_grant_rejection"
            revoke_and_check_replay(probe, active.task_id, grant, create_request, create_key)
            task = probe.get(f"/api/tasks/{active.task_id}", TaskView)
            require(task.state == "active" and task.completion_report_id is None,
                    "engineering_method_fabricated_task_completion")
            probe.evidence["task_after_method"] = task.model_dump(mode="json")
    report["last_stage"] = "processes_stopped"


def run(args, report):
    report["environment"] = _environment()
    storage = DevelopmentStorageRef(storage_id=args.storage_id, instance_revision=args.storage_revision,
                                    purpose="workspace")
    storage_api = importlib.import_module("services.dev-runner.development_storage")
    with storage_api.DevelopmentStorage(storage.storage_id).admit_ref(storage, requested_bytes=0) as admission:
        report["storage_before"] = admission.observe().model_dump(mode="json")
    probe = None
    pending = None
    with database_fixture(port=args.port) as fixture:
        report["database_fixture"] = {"project_name": fixture.project_name, "port": fixture.port,
            "installation_id": fixture.baseline.installation_id, "isolated_new_database": True}
        try:
            probe = EngineeringProbe(process_fixture(fixture, storage))
            probe.open()
            report["checks"] = probe.evidence
            try:
                _chain(probe, storage, report, args.through_candidate)
                report["process_cleanup"] = "complete"
            except Exception as failure:
                pending = failure
                report["process_cleanup"] = "unconfirmed" if isinstance(failure, RuntimeProcessError) else "complete"
        finally:
            if probe is not None:
                probe.close()
        report["observer_cleanup"] = "complete"
    report["database_cleanup"] = "complete"
    report["database_and_process_cleanup"] = report.get("process_cleanup", "not_started")
    safe_stages = {"source_http_accepted", "real_reference_task", "workspace_materialization",
                   "controlled_file_mutation", "candidate_freeze", "development_resume", "build_input_definition"}
    report["storage_release_safe"] = (report["database_and_process_cleanup"] == "complete" and (
        args.through_candidate or report.get("last_stage") in safe_stages or pending is None))
    if pending is not None:
        raise pending
    with storage_api.DevelopmentStorage(storage.storage_id).admit_ref(storage, requested_bytes=0) as admission:
        report["storage_after"] = admission.observe().model_dump(mode="json")
    report.update(database_and_process_cleanup="complete", end_to_end_chain_complete=not args.through_candidate)


def _public_input(value):
    return {key: item for key, item in value.items() if key != "files"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--development", action="store_true")
    mode.add_argument("--input-set")
    parser.add_argument("--storage-id", required=True)
    parser.add_argument("--storage-revision", required=True)
    parser.add_argument("--port", type=int, default=55439)
    parser.add_argument("--through-candidate", action="store_true")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    report = {"method_revision": METHOD_REVISION, "method_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "started_at_utc": datetime.now(UTC).isoformat(), "status": "failed", "complete_scope": False,
        "human_acceptance": None, "p1_2_stage_acceptance": False,
        "mode": "development_worktree" if args.development else "fixed_input_set",
        "scope": "source/task/workspace/candidate" if args.through_candidate else "fixed_reference_engineering_chain",
        "support_scope": "one WSL Ubuntu-24.04 local controlled development fixture; no Desktop or remote delivery"}
    before = None
    try:
        before = fixed_inputs(args.input_set)
        report["input_before"] = _public_input(before)
        run(args, report)
        report["status"] = "passed"
    except EngineeringCheckFailure as failure:
        report.update(status="failed", failure_code=str(failure))
    except DatabaseFixtureError:
        report.update(status="failed", failure_code="engineering_database_fixture_failed")
    except Exception as failure:
        report.update(status="failed", failure_code="engineering_integration_method_failed",
                      failure_type=type(failure).__name__)
        report["failure_location"] = [{"file": Path(item.filename).name, "line": item.lineno,
                                        "function": item.name}
                                       for item in traceback.extract_tb(failure.__traceback__)[-6:]]
    finally:
        if before is not None:
            try:
                after = fixed_inputs(args.input_set)
                report["input_after"] = _public_input(after)
                report["public_inputs_unchanged"] = before == after
                if args.development and before != after:
                    old = {item["path"]: item["sha256"] for item in before["files"]}
                    new = {item["path"]: item["sha256"] for item in after["files"]}
                    report["changed_inputs"] = [{"path": name, "before_sha256": old.get(name),
                        "after_sha256": new.get(name)} for name in sorted(set(old) | set(new)) if old.get(name) != new.get(name)]
                elif not args.development:
                    require(before == after, "engineering_public_input_changed_during_run")
            except Exception:
                report.update(status="failed", failure_code="engineering_input_postcheck_failed",
                              public_inputs_unchanged=False)
    report["finished_at_utc"] = datetime.now(UTC).isoformat()
    encoded = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.report is not None:
        try:
            with args.report.open("x", encoding="utf-8", newline="\n") as output:
                output.write(encoded)
        except OSError:
            report.update(status="failed", failure_code="engineering_report_not_saved")
    print(json.dumps(report, ensure_ascii=False, sort_keys=True), flush=True)
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
