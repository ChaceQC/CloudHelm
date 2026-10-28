"""Fixed, read-only developer checks in the registered notes backend container."""

import json
from datetime import UTC, datetime
from textwrap import indent

from modules.agent_runtime.source_context import safe_context_text
from packages.contracts.p1.development_environment import WorkspaceDevelopmentEnvironmentSpec
from packages.contracts.p1.workspace_git import content_digest

from .toolchain import ProbeFailure
from .workspace_development_journal import WorkspaceDevelopmentJournal
from .workspace_development_recipe import HTTP_PROBE, parse_backend_probe
from .workspace_development_source import observe_workspace_source


SYNTAX_CHECK = r'''import json,pathlib,signal
signal.alarm(5)
files=[]
for root in ('app','migrations'):
    for path in pathlib.Path('/workspace/backend',root).rglob('*.py'):
        files.append(path)
        if len(files)>256: raise SystemExit(90)
if not files: raise SystemExit(91)
failures=[]; total=0
for path in sorted(files):
    with path.open('rb') as stream: raw=stream.read(262145)
    total+=len(raw)
    if len(raw)>262144 or total>2097152: raise SystemExit(90)
    name=str(path.relative_to('/workspace'))
    try:
        compile(raw.decode('utf-8'),name,'exec',dont_inherit=True)
    except SyntaxError as error:
        failures.append({'path':name[:256],'line':error.lineno,'column':error.offset,
                         'code':'python_syntax_error','message':error.msg[:160]})
    except (UnicodeDecodeError,ValueError):
        failures.append({'path':name[:256],'code':'python_source_invalid_utf8_or_null'})
print(json.dumps({'files_checked':len(files),'failure_count':len(failures),
                  'failures':failures[:8]},sort_keys=True))
raise SystemExit(1 if failures else 0)
'''

HTTP_FAILURES = {
    80: "http_connection_failed", 81: "http_response_limit_exceeded",
    82: "notes_dataset_revision_unsupported", 83: "http_response_invalid_json",
    84: "health_ready_or_notes_contract_failed", 85: "note_fields_invalid",
    86: "note_fields_limit_exceeded", 87: "notes_seed_mismatch",
}
HTTP_CHECK = "try:\n" + indent(HTTP_PROBE, "    ") + '''
except SystemExit:
    print(json.dumps({'http_statuses':{name:globals().get(key) for name,key in
        (('health','hs'),('ready','rs'),('notes','ns'),('devmarker','ms'))}},sort_keys=True))
    raise
'''


def run_workspace_check(controller, spec, query):
    """Use existing storage, reader identity and source checks; never import project code."""
    with controller._storage() as storage:
        controller._check_storage(storage)
        with WorkspaceDevelopmentJournal(storage).environment(query.environment_id) as session:
            environment = session.read_environment()
            if (environment is None or environment.get("state") != "ready"
                    or environment.get("binding") != spec.binding.model_dump(mode="json")):
                raise ProbeFailure("workspace_check_environment_not_ready")
            prepare_id = environment.get("prepare_operation_id")
            environment_spec = WorkspaceDevelopmentEnvironmentSpec.model_validate(environment["spec"])
        readers = [reader for reader in controller.registered_readers(spec.binding)
                   if reader.operation_id == prepare_id]
        if len(readers) != 1:
            raise ProbeFailure("workspace_check_backend_unavailable")
        source = observe_workspace_source(storage, spec.binding)
        if source.manifest_digest != query.expected_manifest_digest:
            raise ProbeFailure("workspace_check_source_stale")
        script = SYNTAX_CHECK if query.check == "backend.syntax" else HTTP_CHECK
        started_at = datetime.now(UTC).isoformat()
        runtime = controller._runtime(environment_spec, prepare_id)
        runtime._open_runtime_directories(storage, create=False)
        client = runtime._make_client(create=False)
        try:
            process = client.run("exec", readers[0].container_id, "/environment/bin/python",
                                 "-B", "-I", "-c", script, timeout=8, required=False)
        except ProbeFailure as error:
            if error.category != "probe_docker_command_timeout":
                raise
            process = None
        after = observe_workspace_source(storage, spec.binding)
        if after.manifest_digest != source.manifest_digest:
            raise ProbeFailure("workspace_check_source_changed")
        exit_code = None if process is None else process.returncode
        details = {}
        if query.check == "backend.syntax" and exit_code in (0, 1):
            details = json.loads(process.stdout)
            for failure in details["failures"]:
                for field in ("path", "message"):
                    if field in failure:
                        failure[field] = safe_context_text(failure[field])
        elif query.check == "backend.http" and exit_code == 0:
            report = parse_backend_probe(process.stdout)
            details = {key: report[key] for key in (
                "health_status", "health_digest", "ready_status", "ready_digest",
                "notes_status", "notes_digest", "seed_verified")}
        else:
            codes = ({90: "python_source_limit_exceeded", 91: "python_source_missing"}
                     if query.check == "backend.syntax" else HTTP_FAILURES)
            code = "workspace_check_timeout" if process is None else codes.get(exit_code, "workspace_check_execution_failed")
            details = {"failures": [{"code": code}]}
            if query.check == "backend.http" and exit_code in HTTP_FAILURES:
                details.update(json.loads(process.stdout))
        completed = exit_code in (0, 1) if query.check == "backend.syntax" else exit_code == 0 or exit_code in HTTP_FAILURES
        result = {"status": "passed" if exit_code == 0 else "failed" if completed else "unknown",
                  "check": query.check, "method_revision": "notes-developer-check-r1",
                  "method_digest": content_digest(script.encode("utf-8")),
                  "binding": spec.binding.model_dump(mode="json"),
                  "source_manifest_digest": source.manifest_digest,
                  "environment_id": query.environment_id, "container_id": readers[0].container_id,
                  "exit_code": exit_code, "started_at": started_at,
                  "finished_at": datetime.now(UTC).isoformat(), **details}
        encoded = json.dumps(result, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("ascii")
        result["evidence_digest"] = content_digest(encoded)
        return result
