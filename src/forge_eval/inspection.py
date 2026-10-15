"""Read-only discovery and run inspection for CLI and agent plugin hosts."""

import os
import shutil
import sys
from pathlib import Path

from . import __version__
from .core import HarnessError, inventory, read_json, verify


def doctor():
    """Report local prerequisites without launching agents or probing accounts."""
    return {
        "version": __version__,
        "python": {"executable": sys.executable, "version": sys.version.split()[0]},
        "platform_supported": os.name == "posix",
        "cwd": str(Path.cwd()),
        "core_path": str(Path(__file__).resolve().parent),
        "git": shutil.which("git"),
        "agent_executables": {name: shutil.which(name) for name in ("claude", "opencode", "dsh")},
        "claude_code_session": bool(os.environ.get("CLAUDECODE")),
        "authentication_checked": False,
    }


def inspect_run(run_path):
    """Inspect existing evidence; never generate, seal, or execute checks."""
    run = Path(run_path).resolve()
    state = read_json(run / "state.json")
    if not isinstance(state, dict):
        raise HarnessError("Run state must be a JSON object")
    inputs = run / "inputs"
    sealed = (run / "seal.json").is_file()
    integrity = "NOT_SEALED"
    integrity_error = None
    try:
        if sealed:
            integrity = verify(run)["integrity"]
        elif state.get("status") == "SEALED":
            raise HarnessError("Sealed run is missing seal.json")
        elif "inputs" in state:
            if inventory(inputs) != state["inputs"]:
                raise HarnessError("Frozen inputs have changed")
    except (ValueError, OSError) as exc:
        integrity = "UNVERIFIED"
        integrity_error = str(exc)
    generation_path = run / "generation/result.json"
    evaluations = []
    for directory in sorted((run / "evaluations").glob("*")):
        if not directory.is_dir():
            continue
        result_path = directory / "result.json"
        evaluation_state = directory / "state.json"
        evaluations.append({
            "evaluation_id": directory.name,
            "state": read_json(evaluation_state) if evaluation_state.is_file() else None,
            "result": read_json(result_path) if result_path.is_file() else None,
            "result_path": str(result_path) if result_path.is_file() else None,
            "report_path": str(directory / "report.md") if (directory / "report.md").is_file() else None,
        })
    return {
        "run_path": str(run),
        "state": state,
        "controller_locked": (run / ".controller.lock").exists(),
        "integrity": integrity,
        "integrity_error": integrity_error,
        "workspace_path": str(run / "workspace"),
        "generation": read_json(generation_path) if generation_path.is_file() else None,
        "evaluations": evaluations,
    }
