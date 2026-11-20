"""Linux maintenance bootstrap and a secret-silent single outbound polling process."""

import argparse
import json
import time
from pathlib import Path
from uuid import uuid4

from modules.delivery.permit_clock import ExecutorClock
from modules.delivery.release_recipe import delivery_digest
from packages.contracts.p1.delivery_records import TargetRegistration
from .backend import Backend
from .channel import CHANNEL_ERROR_ACTIONS, Channel, RemoteChannelError, read_private
from .closeout import closeout
from .docker_io import Docker
from .ledger import Ledger, RemoteError
from .resources import Resources
from .runtime import BINDING_WAIT_CODES, Agent


def main():
    parser = argparse.ArgumentParser(description="CloudHelm finite Remote Agent (ordinary effects default closed)")
    parser.add_argument("--config", required=True)
    parser.add_argument("--initialize-ledger", action="store_true")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--once", action="store_true")
    mode.add_argument("--reconcile-operation")
    mode.add_argument("--closeout-operation")
    arguments = parser.parse_args()
    if arguments.initialize_ledger and (arguments.reconcile_operation or arguments.closeout_operation):
        parser.error("maintenance requires the existing ledger")
    channel = ledger = None
    try:
        config = json.loads(read_private(arguments.config))
        registration = TargetRegistration.model_validate(config["registration"])
        if arguments.closeout_operation:
            ledger = Ledger(config["state_directory"], registration.installation_id, maintenance=True)
            receipt = closeout(ledger, registration, arguments.closeout_operation, config.get("resources", {}))
            result = {"status": "closeout_received", "receipt_digest": delivery_digest(receipt),
                "receipt": receipt.model_dump(mode="json")}
            try:
                channel = Channel(config["hub_url"], config["token_file"], verify=config.get("ca_file", True))
                channel.closeout(receipt)
            except RemoteChannelError as error:
                result.update(status="closeout_delivery_pending", code=error.code, action=error.action)
            except (RemoteError, OSError, KeyError, ValueError):
                result["status"] = "closeout_delivery_pending"
            print(json.dumps(result))
            return
        # A new process has a new physical identity; enrollment must explicitly reconcile it.
        registration = registration.model_copy(update={"executor_instance": "remote-" + uuid4().hex})
        ledger = Ledger(config["state_directory"], registration.installation_id, initialize=arguments.initialize_ledger)
        channel = Channel(config["hub_url"], config["token_file"], verify=config.get("ca_file", True))
        docker = Docker(Path(config["state_directory"]) / "docker-public", config["docker_socket"])
        resources = Resources(docker, **config["resources"])
        backend = Backend(ledger, docker, resources, channel, secret_files=config["secret_files"])
        # Generic Linux/WSL cannot prove the frozen rate and pause requirements.
        # Only a reviewed composition root may inject ClockSupport into both ends.
        agent = Agent(ledger, channel, ExecutorClock(), backend, registration)
        print(json.dumps({"executor_instance": registration.executor_instance, "status": "waiting_enrollment",
            "ordinary_steps": "clock_support_evidence_required"}), flush=True)
        if arguments.reconcile_operation:
            try:
                result = {"status": agent.reconcile(arguments.reconcile_operation)}
            except RemoteChannelError as error:
                result = {"status": "needs_reconciliation", "code": error.code, "action": error.action}
            print(json.dumps(result))
            return
        while True:
            keep_polling = not arguments.once
            try:
                code = agent.run_once()
                if action := CHANNEL_ERROR_ACTIONS.get(code):
                    status = "waiting_enrollment" if code in BINDING_WAIT_CODES else "waiting_authorization"
                    result = {"status": status, "code": code, "action": action}
                else:
                    result = {"status": code}
            except RemoteChannelError as error:
                result = {"status": "waiting_authorization_or_reconciliation", "code": error.code, "action": error.action}
                keep_polling = keep_polling and error.action == "reconnect"
            except Exception:
                result = {"status": "waiting_authorization_or_reconciliation"}
            print(json.dumps(result), flush=True)
            if not keep_polling:
                return
            time.sleep(5)
    except RemoteError as error:
        raise SystemExit(str(error)) from None
    except Exception:
        raise SystemExit("remote_agent_configuration_or_state_unavailable") from None
    finally:
        if channel is not None:
            channel.close()
        if ledger is not None:
            ledger.close()


if __name__ == "__main__":
    main()
