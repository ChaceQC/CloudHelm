"""Plan, environment and permit bindings remain one decision."""

from pydantic import ValidationError

from packages.contracts.p0.delivery_contracts import (
    DeploymentPlanBinding, EnvironmentConfigRevision, check_initial_plan_binding,
)
from packages.contracts.p0.engineering_contracts import EngineeringRef
from packages.contracts.p0.permit_contracts import PermitBinding

DIGEST = "sha256:" + "a" * 64


def _ref(kind: str, name: str | None = None, revision: str = "r1") -> EngineeringRef:
    return EngineeringRef(kind=kind, object_id=name or kind, revision=revision,
                          digest=DIGEST, digest_algorithm="sha256")


def _reject(action, reason: str) -> None:
    try:
        action()
    except (ValueError, ValidationError) as error:
        if reason in str(error):
            return
        raise AssertionError(f"unexpected rejection: {reason}") from error
    raise AssertionError(f"missing rejection: {reason}")


def run_checks() -> dict[str, bool]:
    config = EnvironmentConfigRevision(
        config_revision_id="config-1", environment_id="env-1", revision=1,
        parameter_set_ref=_ref("parameter_set"), resource_binding_refs=(_ref("resource_binding"),),
    )
    plan = DeploymentPlanBinding(
        plan_id="plan-1", plan_digest=DIGEST, operation_id="op-1", release_ref=_ref("release"),
        environment_config_ref=_ref("environment_config", "config-1", "1"),
        environment_execution_id="execution-1", expected_environment_revision_id="state-1",
        expected_observed_state_digest=DIGEST, normalized_spec_ref=_ref("deployment_spec"),
        input_set_ref=_ref("input_set"), parser_revision="r1", target_installation_id="install-1",
        executor_instance="executor-1", generation=1, approval_ref=_ref("approval"),
    )
    permit = PermitBinding(
        operation_id="op-1", plan_digest=DIGEST, step_id="step-1", input_digest=DIGEST,
        executor_instance="executor-1", hub_incarnation="hub-1", generation=1,
        environment_execution_id="execution-1", environment_config_revision_id="config-1",
        expected_environment_revision_id="state-1", control_revision=1, authorization_revision=1,
        predecessor_results_digest=DIGEST, actual_state_digest=DIGEST,
    )
    check_initial_plan_binding(plan, config, permit)
    _reject(lambda: check_initial_plan_binding(
        plan, config, permit.model_copy(update={"expected_environment_revision_id": "stale"})
    ), "INITIAL_PLAN_PERMIT_BINDING_MISMATCH")
    return {"initial_plan_requires_current_environment_and_permit": True}
