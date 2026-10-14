# Agent backends

All adapters use the same frozen inputs, prepared workspace, generation logs,
sealing, and independent evaluation. Inputs remain permissive. Host settings
and credentials are inherited; these adapters do not provide isolation.

| Backend | Invocation | Completion evidence | Usage |
| --- | --- | --- | --- |
| `claude-code` | `claude --print --output-format stream-json ...` | Successful final result and exit 0 | Final result tokens and estimated cost |
| `opencode` | `opencode run --format json --dir WORKSPACE` | Last step reason `stop`, no errors, exit 0 | Step tokens and estimated cost |
| `deepseek-harness` | `dsh --profile headless TASK` | Official headless profile exit 0 | Unknown |
| Generic command | Supplied command | Exit 0 | Unknown |

All also require no timeout, no launch error, and unchanged frozen inputs.
Generation completion is not functional correctness: seal and independently
evaluate the candidate afterward.

## OpenCode

Install and authenticate OpenCode separately. Example configuration:

```json
{"backend": "opencode", "timeout_seconds": 300}
```

Optional fields: `executable`, `model` (`provider/model`), `agent`, and `variant`.
Omitted fields use OpenCode defaults. The adapter does not pass `--auto`, resume
a session, or request sharing. Permissions, plugins, skills, and model defaults
remain inherited, not frozen. This adapter has no monetary budget cap.

The public case is sent as a prompt on stdin. `generation/prompt.txt` preserves
it; `stdout.log` contains JSONL events and `stderr.log` contains diagnostics.
Step-finish records are deduplicated by part ID before summing their usage.
Tool-call steps, truncated responses, and subsequent unfinished steps are not
successful completion. Any error event prevents success.

Reported total tokens are summed only when all steps provide them. No total is
invented from potentially overlapping token categories. CLI costs are saved as
`estimated_cost_usd`; verified billing `cost` remains null. A reported zero is
not proof that the provider billed nothing. The event stream does not reliably
expose the resolved model, so `observed_model` remains null; the requested model
is recorded separately.

## DeepSeek Harness

This targets the official **deepseek-ai/deepseek-harness** headless profile,
not a DeepSeek API client or third-party CLI fork.

```json
{"backend": "deepseek-harness", "timeout_seconds": 300}
```

`executable` defaults to `dsh`. Alternatively use a `launcher` argument array
for an already-built source installation's product launcher:

```json
{
  "backend": "deepseek-harness",
  "launcher": ["node", "/absolute/deepseek-harness/apps/cli/lib/bin.js"],
  "timeout_seconds": 300
}
```

The file and dependencies must exist. ForgeEval does not install or build the
external harness or configure its credentials. Avoid wrappers that change cwd
to the harness repository: the headless profile derives its project workspace
from the process working directory. Configure model, tools, and credentials
through the harness's own headless profile. ForgeEval adds no unsupported model
or JSON-output flags.

The task is one positional argument, without a shell or placeholder expansion,
and a copy is saved in `generation/prompt.txt`. The OS may expose the task in
process arguments; very large prompts are limited by OS argument size. Stdout
contains the final assistant text. The official profile returns 0 only for a
completed turn, and nonzero for other termination reasons. This completion
source is recorded explicitly. Its stdout does not expose session ID, resolved
model, token counts, or cost; those remain unknown. Internal persistent sessions
are not copied or parsed in this iteration.

## Run a case

Choose `examples/hello/opencode-agent.json` or `deepseek-agent.json`:

```sh
export PYTHONPATH="$PWD/src"
python3 -m forge_eval prepare \
  --case examples/hello/case.json \
  --baseline examples/hello/baseline \
  --checks examples/hello/checks \
  --agent-config examples/hello/opencode-agent.json \
  --run .forge-eval/runs/opencode-hello-001
python3 -m forge_eval generate --run .forge-eval/runs/opencode-hello-001 --trusted-local
python3 -m forge_eval seal --run .forge-eval/runs/opencode-hello-001
python3 -m forge_eval evaluate --run .forge-eval/runs/opencode-hello-001 --trusted-local
```

Use a new directory for every backend and retry. Missing executables, provider
errors, and timeouts are recorded as failed generation, not functional scores.
Offline tests use fake executables and protocol samples and do not establish
provider connectivity or model quality.

Protocol sources checked: local OpenCode CLI 1.18.16 and DeepSeek Harness source
0.1.0-rc.5. DeepSeek's local checkout had neither installed dependencies nor a
built CLI during integration, so only its offline adapter tests were executed.

OpenCode live hello smoke test on 2026-10-14 (Asia/Shanghai): generation completed
in 20.28 seconds, both required features passed independent evaluation, and seal
verification succeeded. The CLI reported five steps and 38,155 total tokens.
Its reported estimated cost was zero; billing was not verified. This small
integration example is not evidence of broad project-generation capability.

- [OpenCode CLI](https://opencode.ai/docs/cli/)
- [Official DeepSeek headless profile](https://github.com/deepseek-ai/deepseek-harness/tree/master/packages/bundle/headless)
