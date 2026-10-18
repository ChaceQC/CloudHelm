"""Explicit root maintenance: one fresh bounded pool and the same-namespace UID1000 method."""

from __future__ import annotations

import argparse
import importlib
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--development", action="store_true")
    mode.add_argument("--input-set")
    parser.add_argument("--capacity-bytes", type=int, default=8 * 1024**3)
    parser.add_argument("--port", type=int, default=55439)
    parser.add_argument("--through-candidate", action="store_true")
    parser.add_argument("--method", choices=("engineering", "workspace-development", "task-control"),
                        default="engineering")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    if args.through_candidate and args.method != "engineering":
        parser.error("--through-candidate only applies to the engineering method")
    if (os.name != "posix" or os.getuid() != 0 or os.environ.get("WSL_DISTRO_NAME") != "Ubuntu-24.04"
            or ROOT != Path("/mnt/e/Project/CloudHelm")):
        print(json.dumps({"status": "failed", "failure_code": "engineering_root_wsl_maintenance_required"}))
        return 1
    maintenance = importlib.import_module("services.dev-runner.development_storage_maintenance")
    created = None
    child_started = False
    environment_group = None
    report = {"status": "failed", "storage_cleanup": "not_started", "human_acceptance": None,
              "method_kind": args.method}
    try:
        groups = importlib.import_module("services.dev-runner.artifact_environment_docker")
        groups.enter_docker_mount_namespace("scripts.p1.engineering_storage_fixture", sys.argv[1:])
        created = maintenance.create_instance(args.capacity_bytes)
        identity = created["storage_id"]
        report["storage_created"] = created
        if not args.through_candidate and args.method != "task-control":
            environment_group = groups.EnvironmentGroup(identity)
            report["environment_parent_prepared"] = environment_group.prepare_unit()
            report["environment_parent_scope"] = (
                "development backend, database, migration and dependency preparation; HTTP/Hub/DBOS are platform overhead"
                if args.method == "workspace-development" else
                "three services, migration and container helpers; HTTP/Hub/DBOS are platform overhead"
            )
        module = {"engineering": "scripts.p1.check_engineering",
                  "workspace-development": "scripts.p1.check_workspace_development",
                  "task-control": "scripts.p1.check_engineering_task_control"}[args.method]
        arguments = ["/usr/sbin/runuser", "-u", "cloudhelm", "--", "/usr/bin/env",
            "PYTHONUTF8=1", "PYTHONIOENCODING=utf-8", "PYTHONDONTWRITEBYTECODE=1",
            "WSL_DISTRO_NAME=Ubuntu-24.04", str(ROOT / ".venv/bin/python"), "-B", "-m",
            module, "--storage-id", identity,
            "--storage-revision", created["registration"]["instance_revision"], "--port", str(args.port)]
        arguments += ["--development"] if args.development else ["--input-set", args.input_set]
        if args.through_candidate:
            arguments.append("--through-candidate")
        child_started = True
        result = subprocess.run(arguments, cwd=ROOT, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, timeout=2400, check=False,
            env={"PATH": "/usr/local/bin:/usr/bin:/bin", "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8",
                 "WSL_DISTRO_NAME": "Ubuntu-24.04"})
        if len(result.stdout) > 2_000_000:
            raise ValueError("engineering_child_report_exceeded")
        report["method"] = json.loads(result.stdout.decode("utf-8"))
        method = report["method"]
        method_passed = result.returncode == 0 and method.get("status") == "passed"
        if not method_passed:
            report["failure_code"] = "engineering_child_method_failed"
        if method.get("database_and_process_cleanup") != "complete" or not method.get("storage_release_safe"):
            report.update(failure_code="engineering_child_stop_unconfirmed", storage_cleanup="retained_for_reconciliation")
        elif method.get("environment", {}).get("mount_namespace") != os.readlink("/proc/self/ns/mnt"):
            report.update(failure_code="engineering_child_mount_namespace_changed", storage_cleanup="retained_for_reconciliation")
        else:
            if environment_group is not None:
                report["environment_parent_stopped"] = environment_group.dispose()
            report["storage_removed"] = maintenance.change_fixture(identity, "remove")
            if report["storage_removed"].get("host_reclamation_confirmed"):
                report["storage_cleanup"] = "complete"
                report["status"] = "passed" if method_passed else "failed"
            else:
                report.update(failure_code="engineering_storage_host_reclamation_unconfirmed",
                              storage_cleanup="host_reclamation_unconfirmed")
    except Exception as failure:
        report.update(status="failed", failure_code="engineering_storage_fixture_failed",
                      failure_type=type(failure).__name__,
                      storage_cleanup="retained_for_reconciliation" if created else "creation_unconfirmed")
        if type(failure).__name__ == "DevelopmentStorageError":
            report["storage_failure_category"] = str(failure)
        if created and not child_started:
            try:
                if environment_group is not None:
                    report["environment_parent_stopped"] = environment_group.dispose()
                report["storage_removed"] = maintenance.change_fixture(created["storage_id"], "remove")
                report["storage_cleanup"] = ("complete" if report["storage_removed"].get("host_reclamation_confirmed")
                                             else "host_reclamation_unconfirmed")
            except Exception:
                report["storage_cleanup"] = "retained_for_reconciliation"
    report["storage_reconciliation_required"] = report["storage_cleanup"] not in {"complete", "not_started"}
    encoded = json.dumps(report, ensure_ascii=False, sort_keys=True)
    if args.report is not None:
        try:
            with args.report.open("x", encoding="utf-8", newline="\n") as output:
                output.write(encoded + "\n")
        except OSError:
            report.update(status="failed", failure_code="engineering_fixture_report_not_saved")
    print(json.dumps(report, ensure_ascii=False, sort_keys=True), flush=True)
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
