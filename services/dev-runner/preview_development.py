"""Read a preview-enabled Workspace environment through its existing Runner identity.

The caller submits prepare/dispose through the ordinary Workspace workflow.  This
adapter only observes those operations; the target is for a trusted proxy and is
not a public preview URL or evidence of client/network isolation.
"""

from ipaddress import IPv4Address, IPv4Network, ip_address, ip_interface

from packages.contracts.p1.development_environment import (
    WorkspaceDevelopmentEnvironmentObservation, WorkspaceDevelopmentEnvironmentSpec,
)

from .artifact_environment_docker import engine
from .resource_development import PREVIEW_ENVELOPE
from .toolchain import ProbeFailure
from .workspace_development_journal import WorkspaceDevelopmentJournal


_PRIVATE_NETWORKS = tuple(IPv4Network(value) for value in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"))


class DevelopmentPreview:
    def __init__(self, development, resources):
        if getattr(development, "resources", None) is not resources:
            raise ValueError("preview_development_resources_mismatch")
        self.development, self.resources = development, resources

    def observe(self, prepare_operation_id):
        access = self.development._access(prepare_operation_id, reconciliation=True)
        if access.intent.request.action != "prepare" or not access.client_request.preview:
            raise ProbeFailure("preview_development_prepare_identity_required")
        environment_id = access.environment["environment_id"]
        result = {"environment_id": environment_id, "ready": False, "route_supported": False,
                  "reservation_id": None, "allocation_state": None, "workspace_revision": None,
                  "source_manifest_digest": None, "data_revision": None, "data_generation": None,
                  "observed_at": None, "process_id": None, "target": None}
        with self.resources.admitted() as storage:
            binding = self.resources.environment(access, storage)
            if binding is None:
                return result
            resource = binding.request.resources
            if (resource.request_vector != PREVIEW_ENVELOPE or resource.accounted_vector != PREVIEW_ENVELOPE
                    or resource.hard_limits != PREVIEW_ENVELOPE):
                raise ProbeFailure("preview_development_reservation_mismatch")
            reservation_id = resource.identity.reservation_id
            allocation = binding.dispatcher.reconcile(reservation_id)
            result.update(reservation_id=reservation_id, allocation_state=allocation.state)
            if allocation.state != "active" or access.environment["state"] != "ready":
                return result
            controller = self.development._controller_for_access(access)
            controller.resource_binding = binding
            with binding.context():
                journal = WorkspaceDevelopmentJournal(storage)
                with journal.environment(environment_id) as session:
                    environment = session.read_environment()
                    if (environment is None or environment.get("state") != "ready"
                            or environment.get("pending_operation_id")
                            or environment.get("environment_revision") != access.environment["environment_revision"]):
                        return result
                    prior = WorkspaceDevelopmentEnvironmentObservation.model_validate(
                        environment["latest_observation_json"])
                    refreshed = environment.get("refresh_observation_json")
                    if refreshed is not None:
                        candidate = WorkspaceDevelopmentEnvironmentObservation.model_validate(refreshed)
                        if (candidate.state == "ready" and candidate.operation_id == prior.operation_id
                                and candidate.request_digest == prior.request_digest):
                            prior = candidate
                    if prior.state != "ready":
                        return result
                    result.update(last_known_workspace_revision=prior.binding.workspace_revision,
                                  last_known_source_manifest_digest=prior.source_manifest_digest)
                    base = WorkspaceDevelopmentEnvironmentSpec.model_validate(environment["spec"])
                    spec = WorkspaceDevelopmentEnvironmentSpec.model_validate(base.model_dump() | {
                        "binding": prior.binding, "source_manifest_digest": prior.source_manifest_digest,
                        "data_revision": prior.data_revision, "data_generation": prior.data_generation,
                    })
                    runtime = controller._runtime(spec, environment["prepare_operation_id"])
                    if runtime.docker is None:
                        runtime.discover(storage, prepare_operation_id=environment["prepare_operation_id"])
                    observed = runtime.observe_current(prior.operation_id, prior.request_digest, spec, storage,
                                                       prepare_operation_id=environment["prepare_operation_id"])
                    if (observed is None or observed.state != "ready" or prior.runtime_fact is None
                            or observed.runtime_fact.process_id != prior.runtime_fact.process_id):
                        return result
                    target = self._target(runtime, binding)
                    result.update(ready=True, workspace_revision=observed.binding.workspace_revision,
                        source_manifest_digest=observed.source_manifest_digest,
                        data_revision=observed.data_revision, data_generation=observed.data_generation,
                        observed_at=observed.runtime_fact.runner.observed_at.isoformat(),
                        process_id=observed.runtime_fact.process_id, target=target)
                    return result

    @staticmethod
    def _target(runtime, binding):
        docker = runtime.docker
        docker.verify_container("backend")
        value = docker.inspect("backend")
        network = engine("GET", "/networks/" + docker.network_id)
        labels = network.get("Labels") or {}
        if (network.get("Id") != docker.network_id or network.get("Internal") is not True
                or network.get("EnableIPv6") is not False
                or labels.get("cloudhelm.resource-binding") != binding.binding
                or value["HostConfig"].get("PortBindings")):
            raise ProbeFailure("preview_development_network_unconfirmed")
        endpoints = [item for item in value["NetworkSettings"]["Networks"].values()
                     if item.get("NetworkID") == docker.network_id]
        if len(endpoints) != 1:
            raise ProbeFailure("preview_development_target_unconfirmed")
        try:
            address = ip_address(endpoints[0]["IPAddress"])
            registered = ip_interface(network["Containers"][docker.containers["backend"]]["IPv4Address"]).ip
        except (KeyError, ValueError):
            raise ProbeFailure("preview_development_target_unconfirmed") from None
        if (not isinstance(address, IPv4Address) or address != registered
                or not any(address in private for private in _PRIVATE_NETWORKS)):
            raise ProbeFailure("preview_development_target_unconfirmed")
        return {"address": str(address), "port": 8000, "protocol": "http",
                "container_id": docker.containers["backend"], "network_id": docker.network_id}
