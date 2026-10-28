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
from .channel import Channel, read_private
from .closeout import closeout
from .docker_io import Docker
from .ledger import Ledger, RemoteError
from .resources import Resources
from .runtime import Agent


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
            try:
                channel = Channel(config["hub_url"], config["token_file"], verify=config.get("ca_file", True))
                channel.closeout(receipt)
                status = "closeout_received"
            except (RemoteError, OSError, KeyError, ValueError):
                status = "closeout_delivery_pending"
            print(json.dumps({"status": status, "receipt_digest": delivery_digest(receipt),
                "receipt": receipt.model_dump(mode="json")}))
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
            "ordinary_steps": "clock_support_evidence_required"}))
        if arguments.reconcile_operation:
            print(json.dumps({"status": agent.reconcile(arguments.reconcile_operation)}))
            return
        while True:
            try:
                status = agent.run_once()
            except Exception:
                status = "waiting_authorization_or_reconciliation"
            print(json.dumps({"status": status}), flush=True)
            if arguments.once:
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
