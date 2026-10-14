"""Official dsh headless profile; its current output is plain text, not JSONL."""

from .agent_common import build_prompt, probe_version
from .core import read_json
from .execution import execute


def run_deepseek(config, run):
    launcher = config.get("launcher", [config.get("executable", "dsh")])
    launcher = [launcher] if isinstance(launcher, str) else launcher
    version = probe_version(launcher)
    prompt = build_prompt(read_json(run / "inputs/case.json"))
    # The official headless profile consumes a positional task, not stdin.
    argv = [*launcher, "--profile", "headless", prompt]
    outcome = execute(
        {"argv": argv, "timeout_seconds": config.get("timeout_seconds", 600)},
        run / "workspace", run / "generation", stdin_text=prompt,
        expand_placeholders=False,
    )
    return outcome, {
        "backend": "deepseek-harness", "cli_version": version, "profile": "headless",
        "completed": outcome["exit_code"] == 0 and not outcome["timed_out"] and outcome["error"] is None,
        "completion_source": "dsh-headless-exit-code", "observed_model": None, "session_id": None,
        "final_message": (run / "generation/stdout.log").read_text(encoding="utf-8", errors="replace").strip(),
        "usage": {"tokens": None, "cost": None, "estimated_cost_usd": None, "source": None},
    }
