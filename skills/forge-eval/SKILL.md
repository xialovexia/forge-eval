---
name: forge-eval
description: Prepare and evaluate project-level coding tasks with ForgeEval, resolve historical baselines from change documents, or inspect ForgeEval run evidence. Use for coding-agent evaluation and acceptance-check workflows, not ordinary implementation or code review.
---

# ForgeEval

Use the bundled CLI to preserve inputs, candidate code, and acceptance evidence.
The plugin host coordinates the evaluation; the configured backend is the agent
being evaluated. Installing this plugin in Codex does not select a Codex backend.

## Locate the runtime

Resolve [scripts/forge_eval.py](scripts/forge_eval.py) relative to **this skill's
installed directory**, then use its absolute path with Python 3.9+:

```sh
python3 /absolute/plugin/skills/forge-eval/scripts/forge_eval.py doctor
```

Use that prefix for every command below. No pip install, PYTHONPATH change, or
host-specific environment substitution is required. Run from the user's working
directory; keep run data there, outside the plugin installation and baseline.
The plugin root is two directories above this SKILL.md's directory and contains
`docs/` and `examples/hello/`. Quote paths containing spaces.

`doctor` reports executable availability, not authentication or model readiness.
If `claude_code_session` is true, do not start the `claude-code` backend from that
session or unset its nesting guard. Use an already selected other backend, or
explain the host-session option below and let the user choose if their intended
evaluation would change. Never silently substitute the model being evaluated.

## Prepare and run

Use paths, backend, budget, and local-execution authorization already supplied by
the user. Inspect an existing run before continuing it. Use a new run directory
for each attempt. Read [the workflow reference](references/workflow.md) for exact
commands and input formats, including a deterministic smoke test.

- For historical change documents, use `resolve-baseline --repo ... --document
  ... --agent-config ... --run ... --trusted-local`. The configured backend
  chooses the baseline; never invent a commit or fall back to HEAD on failure.
- For a prepared baseline, use `prepare --baseline ... --case ... --checks ...
  --agent-config ... --run ...`, then `generate --run ... --trusted-local`.
- For an explicitly requested evaluation of the **current host session**, prepare
  a baseline without `--agent-config`, read `inputs/case.json`, and implement in
  `workspace/` using the host's normal tools. Skip `generate`; `seal` supports a
  `PREPARED` run. Describe the result as a host-session/manual candidate: this
  mode has no isolated generation invocation, generation usage, or model record.
  Do not present it as equivalent to a configured-backend benchmark.

For host-session implementation, edit only the run's `workspace/`; preserve
frozen inputs and checks. If a configured backend fails, preserve the failed run
and report its logs. Do not repair the candidate yourself and attribute the
repair to that backend, or change its state to allow sealing.

After implementation finishes and all workspace writers stop, `seal`, `verify`,
then `evaluate --trusted-local`. Commands with `--trusted-local` execute local
code with host access; honor the user's existing authorization and host approval
mechanisms. Plugin installation alone does not authorize arbitrary tasks.

## Inspect and report

Use `inspect --run ...` for run state, controller lock, current integrity,
generation evidence, and evaluation reports. Inspection never executes checks.
A lock means another controller may still be active; do not delete it to retry.

Report the run path, baseline choice if available, generation outcome, integrity,
feature results, and report path. `GENERATED` only means the invocation completed;
`VERIFIED` only means files match the seal. Functional results are `PASS`, `FAIL`,
`UNVERIFIED`, or `ERROR`. Missing checks or feature coverage mean `UNVERIFIED`.
Report unknown tokens or cost as unknown. Preserve the distinction between a
historical passing report and current integrity failure.
