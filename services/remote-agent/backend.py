"""Real fixed-recipe execution; dependencies and resources are injected by maintenance."""

import json
import time
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy.engine import make_url

from modules.delivery.compose import bind_environment_config
from modules.delivery.deployment_planning import STEP_KINDS, plan_steps
from modules.delivery.release_recipe import archive_runtime, delivery_digest
from packages.contracts.p1.delivery_records import EnvironmentState
from packages.contracts.p1.remote_delivery import RemotePlan
from . import archive_receipts, archives, containers, observations
from .channel import read_private
from .ledger import RemoteError, private_directory


class Backend:
    def __init__(self, ledger, docker, resources, channel, *, secret_files):
        self.ledger, self.docker, self.resources, self.channel = ledger, docker, resources, channel
        self.secret_files = dict(secret_files)
        if not ledger.directory.resolve().is_relative_to(resources.mount):
            raise RemoteError("remote_state_outside_admitted_filesystem")
        self.directory = private_directory(ledger.directory / "execution")
        self.current = None
        self.revision = None
        self.last_state = None

    def validate(self, deployment):
        plan = deployment.plan
        expected = bind_environment_config(archive_runtime(deployment.manifest.artifacts), plan.configuration.configuration)
        if (expected != plan.normalized_spec or tuple(s.kind for s in plan.steps) != STEP_KINDS
                or tuple(s.step_id for s in plan.steps) != STEP_KINDS
                or plan.expected_state.database_revision not in (None, "0002_add_updated_at_index")):
            raise RemoteError("remote_recipe_unsupported")
        steps, inputs = plan_steps(deployment.manifest, plan.binding, plan.configuration,
            expected, plan.expected_state, plan)
        if steps != plan.steps or inputs != plan.step_inputs:
            raise RemoteError("remote_step_recipe_mismatch")
        self.current = deployment
        self.check_current(deployment)

    def check_local_gate(self):
        if (self.ledger.directory / "maintenance").exists():
            raise RemoteError("remote_maintenance_active")
        if self.current is None:
            raise RemoteError("remote_plan_not_selected")
        self.resources.verify(self.current.plan.configuration.resources)

    def check_current(self, deployment):
        self.check_local_gate()
        if datetime.now(UTC) >= min(deployment.plan.start_before, deployment.approval.expires_at):
            raise RemoteError("remote_plan_expired")
        if not set(deployment.plan.configuration.configuration.secret_refs.values()) <= set(self.available_secret_refs()):
            raise RemoteError("remote_secret_reference_unavailable")
        if self.last_state is not None and self.observe(deployment) != self.last_state:
            raise RemoteError("remote_actual_state_drift")

    def available_secret_refs(self):
        return tuple(sorted(reference for reference, path in self.secret_files.items() if Path(path).is_file()))

    def observe_binding(self, binding):
        row = self.ledger.db.execute("SELECT payload FROM operations WHERE binding=? ORDER BY rowid DESC LIMIT 1",
            (binding.binding_id,)).fetchone()
        if row is not None:
            deployment = RemotePlan.model_validate_json(row[0])
            state = self.observe(deployment)
            unresolved = self.ledger.db.execute("SELECT 1 FROM steps WHERE operation=? AND status='unknown' LIMIT 1",
                (deployment.operation_id,)).fetchone()
            return state if unresolved is None else state.model_copy(update={"unregistered_resources": ("unresolved-execution",)})
        from urllib.parse import quote

        filters = quote(json.dumps({"label": ["cloudhelm.namespace=" + binding.namespace]}))
        containers_present = self.docker.api("GET", "/containers/json?all=1&filters=" + filters)
        volumes = self.docker.api("GET", "/volumes").get("Volumes") or []
        networks = self.docker.api("GET", "/networks")
        unknown = bool(containers_present or any(item["Name"].startswith(binding.namespace + "-") for item in (*volumes, *networks)))
        return EnvironmentState(environment_revision=0,
            unregistered_resources=("unregistered-runtime",) if unknown else ())

    def _environment(self, deployment, role):
        result = dict(deployment.plan.normalized_spec.services[role].environment)
        for key, reference in tuple(result.items()):
            if reference.startswith("secret://"):
                result[key] = read_private(self.secret_files[reference]).decode("utf-8").strip()
        return result

    def observe(self, deployment):
        return observations.observe(self.docker, self.ledger, deployment, self._environment)

    def execute(self, deployment, step, revision):
        self.revision = revision
        self.last_state = None
        dispatch = {"artifact_prepare": self._artifacts, "runtime_input_check": self._inputs,
            "database_migrate": self._migrate, "service_update": self._services, "health_verify": self._health}
        result = dispatch[step.kind](deployment, step)
        self.last_state = self.observe(deployment)
        return result

    def query(self, deployment, step):
        if step.kind == "artifact_prepare":
            return archive_receipts.query_completed(self.docker, deployment, self.directory / deployment.operation_id)
        if step.kind == "database_migrate":
            return self._migration_process(deployment, step, query_only=True)
        return {"status": "unknown"}

    def _artifacts(self, deployment, step):
        directory = self.directory / deployment.operation_id
        facts = archives.prepare_bounded(self.channel, self.docker, deployment, directory,
            resources=self.resources, max_runtime_seconds=step.max_runtime_seconds)
        return {"status": "succeeded", "archives": facts}

    def _inputs(self, deployment, step):
        backend = self._environment(deployment, "backend")
        url = make_url(backend["DATABASE_URL"])
        if (url.host != "postgres" or url.username != "reference_app" or url.database != "reference_notes"
                or url.port not in (None, 5432) or url.password is None):
            raise RemoteError("remote_database_secret_scope_invalid")
        self._environment(deployment, "postgres")
        if deployment.plan.expected_state.services.get("postgres") is not None:
            actual = self.docker.inspect(deployment.plan.binding.namespace + "-postgres")
            environment = dict(value.split("=", 1) for value in actual["Config"].get("Env", ()) if "=" in value)
            if any(environment.get(key) != value for key, value in self._environment(deployment, "postgres").items()):
                raise RemoteError("remote_database_secret_rotation_requires_plan")
        return {"status": "succeeded", "configuration_digest": delivery_digest(deployment.plan.configuration)}

    def _migrate(self, deployment, step):
        self.check_local_gate()
        containers.prepare_storage(self.docker, deployment, self.revision, self.resources.authorize_network)
        present = containers.inventory(self.docker, deployment)
        if not any("/" + deployment.plan.binding.namespace + "-postgres" in item["Names"] for item in present):
            containers.create_service(self.docker, self.resources, deployment, "postgres",
                self._environment(deployment, "postgres"), self.revision)
        containers.wait_postgres(self.docker, deployment.plan.binding.namespace + "-postgres", deadline=time.monotonic() + 60)
        return self._migration_process(deployment, step, query_only=False)

    def _migration_process(self, deployment, step, *, query_only):
        # Query uses an independent read/control process and the original database identity.
        from . import migration

        plan = deployment.plan
        application_url = make_url(self._environment(deployment, "backend")["DATABASE_URL"])
        owner = self._environment(deployment, "postgres")
        url = application_url.set(username="reference_owner", password=owner["POSTGRES_PASSWORD"])
        request = {"operation_id": deployment.operation_id, "input_digest": step.input_digest,
            "installation_id": plan.binding.installation_id, "database_instance_id": plan.binding.namespace + "-postgres",
            "migration_files": {item.path.removeprefix("backend/"): item.digest for item in deployment.manifest.definition.migrations
                if item.path.startswith("backend/migrations/versions/")},
            "query_only": query_only, "expected_revision": plan.expected_state.database_revision,
            "application_password": application_url.password}
        script = Path(migration.__file__).read_text(encoding="utf-8")
        script += "\nimport sys\npayload=json.load(sys.stdin)\nprint(json.dumps(execute(payload['url'],payload['request'])))\n"
        name = plan.binding.namespace + ("-migration-query" if query_only else "-migration")
        image = plan.step_inputs["service_update"]["local_tags"]["backend"]
        raw = self.docker.command("run", "--name", name, "--rm", "-i", "--network", plan.binding.namespace + "-application",
            "--cgroup-parent", self.resources.parent, "--memory", str(plan.configuration.resources.memory_mib * 1024**2),
            "--cpus", str(plan.configuration.resources.cpu_millicores / 1000), "--pids-limit", str(plan.configuration.resources.pids),
            "--pull=never", "--entrypoint", "python", image, "-c", script,
            input_bytes=json.dumps({"url": url.render_as_string(hide_password=False), "request": request}).encode("utf-8"), timeout=600)
        fact = json.loads(raw)
        if fact.get("status") != "succeeded":
            return {"status": "unknown"}
        return {"status": "succeeded", "database_operation_id": fact["operation_id"],
            "database_input_digest": fact["input_digest"], "database_postchecks": fact["postchecks"]}

    def _services(self, deployment, step):
        for role in ("backend", "frontend"):
            self.check_local_gate()
            name = deployment.plan.binding.namespace + "-" + role
            if any("/" + name in item["Names"] for item in containers.inventory(self.docker, deployment)):
                self.docker.api("POST", "/containers/" + name + "/stop?t=20", expected=(204, 304))
                self.docker.api("DELETE", "/containers/" + name)
            containers.create_service(self.docker, self.resources, deployment, role,
                self._environment(deployment, role), self.revision)
        return {"status": "succeeded"}

    def _health(self, deployment, step):
        startup_deadline = time.monotonic() + 60
        while True:
            try:
                self._probe(deployment)
                break
            except RemoteError:
                if time.monotonic() >= startup_deadline:
                    raise
                time.sleep(1)
        started, deadline, samples = datetime.now(UTC), time.monotonic() + 30, 0
        while True:
            self._probe(deployment)
            samples += 1
            if time.monotonic() >= deadline:
                break
            time.sleep(2)
        return {"status": "succeeded", "health_started_at": started.isoformat(),
            "health_finished_at": datetime.now(UTC).isoformat(), "health_samples": samples}

    def _probe(self, deployment):
        namespace = deployment.plan.binding.namespace
        for role in ("postgres", "backend", "frontend"):
            actual = self.docker.inspect(namespace + "-" + role)
            if not actual["State"]["Running"]:
                raise RemoteError("remote_health_failed")
        for path in ("/health", "/ready"):
            code = "import urllib.request; r=urllib.request.urlopen('http://127.0.0.1:8000" + path + "',timeout=2); assert r.status==200"
            self.docker.command("exec", namespace + "-backend", "python", "-c", code)
        for path in ("/", "/api/notes"):
            self.docker.command("exec", namespace + "-frontend", "wget", "-q", "-O", "/dev/null", "http://127.0.0.1" + path)
