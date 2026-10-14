"""Claude Code print-mode adapter; parse observed events without imposing input schemas."""

import json
import math

from .agent_common import build_prompt, probe_version
from .core import read_json
from .execution import execute


def summarize_events(path):
    session_id = None
    observed_model = None
    result = None
    ignored_lines = 0
    api_retries = 0
    with path.open(encoding="utf-8", errors="replace") as stream:
        for line in stream:
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
            if event.get("type") == "system" and event.get("subtype") == "init":
                session_id = event.get("session_id")
                observed_model = event.get("model")
            elif event.get("type") == "system" and event.get("subtype") == "api_retry":
                api_retries += 1
            elif event.get("type") == "result":
                result = event
    result = result or {}
    usage = result.get("usage")
    usage = usage if isinstance(usage, dict) else {}

    def count(key):
        value = usage.get(key)
        return value if type(value) is int and value >= 0 else None

    counts = {key: count(key) for key in (
        "input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")}
    # Anthropic reports cache input separately. Do not silently omit it.
    total = sum(counts.values()) if all(v is not None for v in counts.values()) else None
    estimate = result.get("total_cost_usd")
    if type(estimate) not in (int, float) or not math.isfinite(estimate) or estimate < 0:
        estimate = None
    return {
        "completed": result.get("subtype") == "success" and result.get("is_error") is False,
        "session_id": result.get("session_id", session_id), "observed_model": observed_model,
        "result_subtype": result.get("subtype"), "final_message": result.get("result"),
        "is_error": result.get("is_error"), "api_retries": api_retries,
        "errors": result.get("errors", []), "permission_denials": result.get("permission_denials", []),
        "ignored_lines": ignored_lines,
        "usage": {**counts, "tokens": total, "cost": None, "estimated_cost_usd": estimate,
                  "source": "claude-result" if result else None},
    }


def run_claude(config, run):
    executable = config.get("executable", "claude")
    version = probe_version([executable])
    tools = config.get("allowed_tools", ["Read", "Edit", "Write", "Glob", "Grep"])
    tools = ",".join(tools) if isinstance(tools, list) else str(tools)
    argv = [executable, "--print", "--output-format", "stream-json", "--verbose",
            "--no-session-persistence", "--permission-mode", "dontAsk",
            "--tools", tools, "--allowedTools", tools, "--strict-mcp-config"]
    if config.get("model"):
        argv.extend(["--model", str(config["model"])])
    if config.get("max_budget_usd") is not None:
        argv.extend(["--max-budget-usd", str(config["max_budget_usd"])])
    outcome = execute(
        {"argv": argv, "timeout_seconds": config.get("timeout_seconds", 600)},
        run / "workspace", run / "generation",
        stdin_text=build_prompt(read_json(run / "inputs/case.json")),
    )
    summary = summarize_events(run / "generation/stdout.log")
    return outcome, {
        "backend": "claude-code", "cli_version": version, "requested_model": config.get("model"),
        "permission_mode": "dontAsk", "allowed_tools": tools,
        "max_budget_usd": config.get("max_budget_usd"), **summary,
    }
