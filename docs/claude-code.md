# Claude Code adapter

ForgeEval can invoke an installed, authenticated Claude Code CLI. This is a
trusted-local backend: it inherits the host environment and Claude configuration.
It is not a sandbox, a hidden-test boundary, or a reproducible snapshot of the
host's skills and settings.

## Run the hello case

The CLI must be available as `claude` on PATH. Check installation and login with
`claude --version` and `claude auth status`. Authenticate using Claude Code's own
login flow; do not place credentials in case or agent files.

```sh
export PYTHONPATH="$PWD/src"
python3 -m forge_eval prepare \
  --case examples/hello/case.json \
  --baseline examples/hello/baseline \
  --checks examples/hello/checks \
  --agent-config examples/hello/claude-agent.json \
  --run .forge-eval/runs/claude-hello-001
python3 -m forge_eval generate --run .forge-eval/runs/claude-hello-001 --trusted-local
python3 -m forge_eval seal --run .forge-eval/runs/claude-hello-001
python3 -m forge_eval evaluate --run .forge-eval/runs/claude-hello-001 --trusted-local
```

Generation uses a real model and consumes the configured account's usage. The
example requests a 300-second controller timeout and a USD 1 client-side budget
cap. Claude's budget accounting is an estimate, not a verified invoice or a
guarantee about subscription quota consumption. Change these settings before
preparing a new run; inputs are frozen at preparation.

## Configuration conventions

```json
{
  "backend": "claude-code",
  "timeout_seconds": 300,
  "max_budget_usd": 1.0,
  "allowed_tools": ["Read", "Edit", "Write", "Glob", "Grep"]
}
```

`executable` optionally selects another Claude executable path. `model` passes
an explicit model to Claude; when omitted, Claude's existing default applies.
The requested and observed model are recorded separately. Extra input fields
remain accepted; no schema gate has been added.

The adapter runs `--print --output-format stream-json --verbose`, starts a fresh
session, and disables session persistence. It uses `dontAsk` permission mode,
restricts built-in tools to `allowed_tools`, pre-approves those tools, and uses
`--strict-mcp-config` without additional servers. Default tools allow file
inspection and editing, not shell execution or delegation. Projects needing
agent-side builds can explicitly add appropriate tools before preparation;
independent ForgeEval checks already run after sealing. During document-driven
baseline selection, defaults instead include `Read`, `Glob`, `Grep`, and `Bash`
for Git inspection in a temporary clone. Explicit `allowed_tools` still wins.
See [baseline selection](agent-backends.md#baseline-selection-during-preparation).

These permission settings are not filesystem containment. Host hooks, skills,
instructions, and settings can still influence a run. The adapter does not use
`--bare`, which would change the available context and authentication behavior.
Controlled skill comparisons require a later context-snapshot design.

## Evidence and result semantics

The entire public case JSON becomes the task prompt. It is sent via stdin and
saved as `generation/prompt.txt`, avoiding shell interpolation of task text.
`generation/stdout.log` preserves raw JSONL events, while `stderr.log` preserves
diagnostics. `generation/result.json` includes:

- CLI version, requested model, observed initialization model, and session ID.
- Final result subtype, message, errors, and permission denials when provided.
- Input, output, cache-read, and cache-creation token counts from the final result.
- Client-reported `estimated_cost_usd`; verified `cost` remains null.
- Executed arguments, elapsed time, timeout flag, and process exit code.

Token totals include all four token categories only when every category is
present and numeric; otherwise the total remains unknown. Multiple cumulative
result messages are not summed: the last result controls completion and usage.
Unknown events and non-JSON output lines are tolerated and the latter counted.

Generation requires exit 0, no timeout or execution error, unchanged frozen
inputs, and a final result with `subtype: success` and `is_error: false`. A zero
exit without completion evidence is a failed generation. Functional correctness
still requires sealing and separate evaluation. Permission denials are retained
as evidence; a successful conversation alone does not prove all tools or checks
ran. A failed run is retained and a retry uses a new run directory.

Offline tests use a fake executable to exercise stdin, arguments, events, error
handling, and the full evaluation pipeline without a model request. They do not
measure model quality. The original command backend remains available for other
agents, shell strings, and argument arrays.

## References

Live smoke test on 2026-10-14 (Asia/Shanghai): Claude Code 2.1.299 generated the
hello implementation in 27.87 seconds; independent evaluation passed both
required features and seal verification succeeded. The CLI reported 4,321 input,
11,904 cache-read, 0 cache-creation, and 572 output tokens, with estimated cost
USD 0.041857. This is one small integration test, not a benchmark result. An
earlier attempt failed with a network EPERM error and was preserved as a failed
generation; the retry used a new run directory.

The automated suite includes offline Claude protocol fixtures for generation
and baseline selection.
Network authentication and account availability are only exercised by a manual
live run, never by CI.

- [Claude Code programmatic execution](https://code.claude.com/docs/en/headless)
- [Claude Code CLI reference](https://code.claude.com/docs/en/cli-reference)
