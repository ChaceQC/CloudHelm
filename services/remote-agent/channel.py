"""Outbound authenticated HTTPS, bounded JSON and content-addressed archive transfer."""

import json
import os
import stat
from urllib.parse import urlsplit

import httpx
from pydantic import SecretStr, ValidationError

from modules.delivery.release_recipe import delivery_digest
from packages.contracts.p1.remote_delivery import (
    RemoteBindings, RemoteObservationRequest, RemotePermit, RemotePoll, RemotePollResult, RemoteTimeSample,
)
from .ledger import RemoteError


_JSON_LIMIT = 131072
_HUB_ERROR_ACTIONS = {
    code: action
    for action, codes in {
        "check_registration": (
            "remote_authentication_failed", "remote_executor_stale", "remote_target_scope_mismatch",
            "delivery_target_unavailable", "delivery_target_invalid", "target_observation_binding_mismatch",
        ),
        "correct_request": ("remote_request_invalid", "remote_message_too_large", "remote_step_unknown"),
        "reconcile_original": (
            "remote_gate_unavailable", "remote_time_sample_missing", "remote_time_mapping_invalid",
            "remote_sample_nonce_rebound", "remote_plan_digest_mismatch", "remote_previous_execution_unresolved",
            "remote_original_execution_needs_reconciliation", "remote_execution_gate_closed",
            "remote_intermediate_state_drift", "remote_grant_limit", "remote_old_start_path_not_closed",
            "remote_environment_execution_conflict", "remote_artifact_not_in_plan",
            "remote_message_identity_conflict", "remote_terminal_fact_conflict", "remote_result_unbound",
            "remote_result_binding_invalid", "remote_result_unreconciled_resources",
            "remote_database_evidence_incomplete", "remote_health_window_incomplete", "remote_service_identity_mismatch",
            "remote_closeout_binding_invalid", "remote_closeout_scope_invalid", "remote_closeout_revision_mismatch",
            "remote_closeout_grants_invalid", "remote_closeout_runtime_started", "deployment_operation_conflict",
            "deployment_operation_not_found", "deployment_operation_closed", "deployment_approval_digest_mismatch",
            "deployment_approval_expired", "deployment_approval_credential_not_current", "deployment_policy_changed",
            "deployment_plan_expired", "deployment_plan_expired_or_changed", "deployment_plan_binding_invalid",
            "deployment_secret_reference_unavailable", "deployment_step_unsupported", "deployment_resources_out_of_bounds",
            "remote_target_capacity_unavailable", "environment_execution_pending", "first_installation_not_empty",
            "controlled_verification_required", "verification_not_applicable", "project_integration_required",
            "project_integration_not_accepted",
            "remote_observation_stale", "target_observation_stale", "target_observation_missing", "target_state_unknown",
            "replan_required",
        ),
        "reconnect": ("remote_channel_unavailable", "remote_artifact_store_unavailable"),
        "check_protocol": ("remote_tls_required",),
    }.items()
    for code in codes
}
CHANNEL_ERROR_ACTIONS = {
    **_HUB_ERROR_ACTIONS,
    "remote_connection_unavailable": "reconnect",
    "remote_archive_transfer_unknown": "reconnect",
    "remote_response_invalid": "check_protocol",
    "remote_response_too_large": "check_protocol",
    "remote_archive_bound_exceeded": "check_protocol",
    "remote_archive_incomplete": "check_protocol",
}


class RemoteChannelError(RemoteError):
    """A fixed diagnostic safe to surface at the executor's maintenance entry point."""

    def __init__(self, code):
        super().__init__(code)
        self.code = code
        self.action = CHANNEL_ERROR_ACTIONS[code]


def _require_identity(response):
    if response.headers.get("content-encoding", "identity").strip().lower() != "identity":
        raise RemoteChannelError("remote_response_invalid")


def _response_data(response):
    _require_identity(response)
    data = bytearray()
    for chunk in response.iter_bytes():
        if len(data) + len(chunk) > _JSON_LIMIT:
            raise RemoteChannelError("remote_response_too_large")
        data.extend(chunk)
    return data


def _unique_object(pairs):
    value = dict(pairs)
    if len(value) != len(pairs):
        raise ValueError
    return value


def _json_object(data):
    try:
        value = json.loads(data.decode("utf-8"), object_pairs_hook=_unique_object)
    except (ValueError, RecursionError):
        raise RemoteChannelError("remote_response_invalid") from None
    if not isinstance(value, dict):
        raise RemoteChannelError("remote_response_invalid")
    return value


def _reject_response(response):
    if 400 <= response.status_code < 600:
        value = _json_object(_response_data(response))
        code = value.get("code")
        if len(value) == 1 and isinstance(code, str) and code in _HUB_ERROR_ACTIONS:
            raise RemoteChannelError(code)
    raise RemoteChannelError("remote_response_invalid")


def read_private(path):
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        value = os.fstat(descriptor)
        if (not stat.S_ISREG(value.st_mode) or value.st_uid != os.getuid()
                or value.st_mode & 0o077 or value.st_size > 16384):
            raise RemoteError("remote_secret_file_permissions_invalid")
        with os.fdopen(descriptor, "rb", closefd=False) as stream:
            return stream.read(16385)
    finally:
        os.close(descriptor)


class Channel:
    def __init__(self, url, token_file, *, verify=True):
        parts = urlsplit(url)
        if (parts.username or parts.password or parts.query or parts.fragment or parts.path not in {"", "/"}
                or parts.scheme != "https" and not (parts.scheme == "http" and parts.hostname in {"127.0.0.1", "::1"})
                or verify is False):
            raise RemoteError("remote_authenticated_tls_required")
        self._token = SecretStr(read_private(token_file).decode("ascii").strip())
        self._url, self._verify, self._token_file = url.rstrip("/"), verify, str(token_file)
        self.client = httpx.Client(base_url=self._url, verify=verify, follow_redirects=False,
            trust_env=False, timeout=httpx.Timeout(30, read=60))

    def transfer_configuration(self):
        return {"url": self._url, "token_file": self._token_file,
            "verify": self._verify if isinstance(self._verify, bool) else str(self._verify)}

    def _headers(self):
        return {"Authorization": "Bearer " + self._token.get_secret_value(), "Accept-Encoding": "identity"}

    def post(self, action, body, schema=None, *, expected_receipt=None):
        try:
            with self.client.stream("POST", "/remote/v1/" + action, headers=self._headers(),
                    json=body.model_dump(mode="json")) as response:
                if response.status_code != 200:
                    _reject_response(response)
                data = _response_data(response)
        except httpx.HTTPError:
            raise RemoteChannelError("remote_connection_unavailable") from None
        if schema is None:
            if _json_object(data) != expected_receipt:
                raise RemoteChannelError("remote_response_invalid")
            return None
        try:
            return schema.model_validate_json(data)
        except ValidationError:
            raise RemoteChannelError("remote_response_invalid") from None

    def sample(self, hello):
        return self.post("sample", hello, RemoteTimeSample)

    def poll(self, executor, generation):
        result = self.post("poll", RemotePoll(executor_instance=executor, generation=generation), RemotePollResult)
        if result.status == "ready" and result.code == "original_operation" and result.deployment is not None:
            return result
        if result.deployment is None:
            if result.status == "idle" and result.code == "no_pending_plan":
                return result
            if result.status == "waiting_authorization" and _HUB_ERROR_ACTIONS.get(result.code) == "reconcile_original":
                return result
        raise RemoteChannelError("remote_response_invalid")

    def bindings(self, executor, generation):
        return self.post("bindings", RemotePoll(executor_instance=executor, generation=generation), RemoteBindings)

    def permit(self, request):
        return self.post("permits", request, RemotePermit)

    def report(self, result):
        return self.post("results", result,
            expected_receipt={"digest": delivery_digest(result), "status": result.status})

    def closeout(self, receipt):
        return self.post("closeouts", receipt,
            expected_receipt={"digest": delivery_digest(receipt), "status": "received"})

    def observe(self, observation):
        return self.post("observations", RemoteObservationRequest(observation=observation),
            expected_receipt={"digest": delivery_digest(observation)})

    def download(self, operation, artifact, output):
        count = 0
        try:
            with self.client.stream("GET", f"/remote/v1/artifacts/{operation}/{artifact.storage_id}",
                    headers=self._headers()) as response:
                if response.status_code != 200:
                    _reject_response(response)
                _require_identity(response)
                for block in response.iter_bytes(65536):
                    count += len(block)
                    if count > artifact.archive_bytes:
                        raise RemoteChannelError("remote_archive_bound_exceeded")
                    output.write(block)
            if count != artifact.archive_bytes:
                raise RemoteChannelError("remote_archive_incomplete")
        except httpx.HTTPError:
            raise RemoteChannelError("remote_archive_transfer_unknown") from None

    def close(self):
        self.client.close()
