"""Generic command-agent adapter; usage remains unknown unless measured."""

from pathlib import Path

from .core import HarnessError, inventory, now, read_json, run_lock, write_json
from .execution import execute
from .plans import validate_agent


def generate(run_path, trusted_local=False):
    if not trusted_local:
        raise HarnessError("Local generation requires --trusted-local; commands inherit host access")
    with run_lock(run_path):
        return _generate(run_path)


def _generate(run_path):
    run = Path(run_path).resolve()
    state = read_json(run / "state.json")
    if not isinstance(state, dict) or state.get("status") != "PREPARED":
        raise HarnessError("Generation requires a PREPARED run")
    if inventory(run / "inputs") != state.get("inputs"):
        raise HarnessError("Frozen inputs have changed")
    config = validate_agent(read_json(run / "inputs/agent.json"))
    if (run / "generation").exists():
        raise HarnessError("Generation evidence already exists; use a new run")
    state["status"] = "RUNNING"
    write_json(run / "state.json", state)
    try:
        outcome = execute(config, run / "workspace", run / "generation", {
            "{workspace}": str(run / "workspace"),
            "{case}": str(run / "inputs/case.json"),
        })
        inputs_valid = inventory(run / "inputs") == state["inputs"]
        succeeded = inputs_valid and outcome["exit_code"] == 0 and not outcome["timed_out"] and outcome["error"] is None
        state["status"] = "GENERATED" if succeeded else "GENERATION_FAILED"
        result = {
            "schema_version": "1.0", "status": state["status"], "finished_at": now(),
            "backend": "trusted-local-command", "inputs_verified": inputs_valid,
            "usage": {"tokens": None, "cost": None}, "execution": outcome,
        }
        write_json(run / "generation/result.json", result)
        write_json(run / "state.json", state)
        return result
    except Exception as exc:
        state.update(status="ERROR", error=str(exc))
        write_json(run / "state.json", state)
        raise
