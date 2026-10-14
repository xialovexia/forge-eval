"""Use the same CLI backends for history analysis and implementation."""

from .claude import run_claude
from .deepseek import run_deepseek
from .execution import execute
from .opencode import run_opencode


BACKENDS = {"claude-code": run_claude, "opencode": run_opencode, "deepseek-harness": run_deepseek}


def run_agent(config, workspace, evidence, prompt, replacements=None):
    adapter = BACKENDS.get(config.get("backend")) if isinstance(config, dict) else None
    if adapter is not None:
        return adapter(config, workspace, evidence, prompt)
    outcome = execute(config, workspace, evidence, replacements, stdin_text=prompt)
    return outcome, None


def completed(outcome, agent):
    return (outcome["exit_code"] == 0 and not outcome["timed_out"]
            and outcome["error"] is None and (agent is None or agent["completed"]))
