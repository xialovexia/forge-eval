"""OpenCode run JSONL adapter."""

import json
import math

from .agent_common import build_prompt, probe_version
from .core import read_json
from .execution import execute


def summarize_events(path):
    steps, texts, errors = {}, {}, []
    session_id = None
    finish_reason = None
    ignored_lines = 0
    with path.open(encoding="utf-8", errors="replace") as stream:
        for index, line in enumerate(stream):
            if not line.strip():
                continue
            try:
                event = json.loads(line)
            except ValueError:
                ignored_lines += 1
                continue
            if not isinstance(event, dict):
                ignored_lines += 1
                continue
            session_id = event.get("sessionID", session_id)
            part = event.get("part")
            part = part if isinstance(part, dict) else {}
            kind = event.get("type")
            if kind == "error":
                errors.append(event.get("error"))
            elif kind == "step_start":
                finish_reason = None
            elif kind == "step_finish":
                finish_reason = part.get("reason")
                steps[part.get("id", index)] = part
            elif kind == "text":
                texts[part.get("id", index)] = part.get("text", "")

    def total(*keys):
        values = []
        for part in steps.values():
            value = part
            for key in keys:
                value = value.get(key) if isinstance(value, dict) else None
            if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
                return None
            values.append(value)
        return sum(values) if values else None

    return {
        "completed": bool(steps) and finish_reason == "stop" and not errors,
        "session_id": session_id, "finish_reason": finish_reason, "errors": errors,
        "final_message": "\n".join(str(v) for v in texts.values()),
        "ignored_lines": ignored_lines, "steps": len(steps), "observed_model": None,
        "usage": {
            "tokens": total("tokens", "total"), "input_tokens": total("tokens", "input"),
            "output_tokens": total("tokens", "output"), "reasoning_tokens": total("tokens", "reasoning"),
            "cache_read_input_tokens": total("tokens", "cache", "read"),
            "cache_creation_input_tokens": total("tokens", "cache", "write"),
            "cost": None, "estimated_cost_usd": total("cost"),
            "source": "opencode-step-finish" if steps else None,
        },
    }


def run_opencode(config, run):
    executable = config.get("executable", "opencode")
    version = probe_version([executable])
    argv = [executable, "run", "--format", "json", "--dir", str(run / "workspace")]
    for key in ("model", "agent", "variant"):
        if config.get(key):
            argv.extend(["--" + key, str(config[key])])
    outcome = execute(
        {"argv": argv, "timeout_seconds": config.get("timeout_seconds", 600)},
        run / "workspace", run / "generation",
        stdin_text=build_prompt(read_json(run / "inputs/case.json")),
    )
    return outcome, {
        "backend": "opencode", "cli_version": version, "requested_model": config.get("model"),
        "requested_agent": config.get("agent"), "requested_variant": config.get("variant"),
        "permissions": "inherited; no auto-approval override",
        **summarize_events(run / "generation/stdout.log"),
    }
