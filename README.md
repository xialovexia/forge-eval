# ForgeEval

**Run coding agents on project tasks and evaluate the code they produce.**

ForgeEval is a Python CLI that uses change documents and a project's Git history
to select a baseline, prepares a workspace, runs an agent, seals its output,
and checks that output against your acceptance tests. Each
run keeps its inputs, execution logs, and feature-level results so you can
inspect what happened rather than rely on the agent's final message.

> **Early prototype for trusted local use.** Agents and checks run on your
> machine. ForgeEval does not provide a security sandbox, protect hidden tests,
> or freeze the host's settings and skills. Use trusted projects and commands.

## What works today

- Run Claude Code, OpenCode, DeepSeek Harness, or a custom command.
- Let the configured agent locate a documented historical change and select the
  project version before it, directly within run preparation.
- Copy a baseline into a new workspace and freeze public task/check inputs.
- Capture generation logs, timeouts, exit status, and available usage data.
- Seal candidate files and detect subsequent changes relative to the seal.
- Run acceptance checks against fresh copies of the sealed candidate.
- Produce JSON and Markdown reports with per-feature evidence.

A baseline is the project before the requested change. A case describes the
change and its required behavior. A check bundle contains commands that test
that behavior. You supply the criteria; ForgeEval runs and records them.

## Requirements and installation

- Python 3.9 or later.
- macOS or Linux for command execution.
- An installed, authenticated agent CLI for real-agent runs.
- Git for document-driven baseline selection from a local repository.

The Python core has no runtime package dependencies. Install from this repository:

```sh
git clone https://github.com/xialovexia/forge-eval.git
cd forge-eval
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
forge-eval --help
```

Alternatively, run directly from the checkout without installing:

```sh
export PYTHONPATH="$PWD/src"
python3 -m forge_eval --help
```

Replace `forge-eval` in the examples below with `python3 -m forge_eval` when
using the source-only approach. Run all examples from the repository root.

## Try the offline example

This example uses a deterministic fixture that writes a known implementation.
It makes no model requests and demonstrates the evaluation workflow, not an
agent's coding ability.

```sh
forge-eval prepare \
  --case examples/hello/case.json \
  --baseline examples/hello/baseline \
  --checks examples/hello/checks \
  --agent-config examples/hello/fixture-agent.json \
  --run .forge-eval/runs/hello-001

forge-eval generate --run .forge-eval/runs/hello-001 --trusted-local
forge-eval seal --run .forge-eval/runs/hello-001
forge-eval verify --run .forge-eval/runs/hello-001
forge-eval evaluate --run .forge-eval/runs/hello-001 --trusted-local
```

Expected result: `generate` reports `GENERATED`, `verify` reports `VERIFIED`,
and `evaluate` reports `PASS` with both required features covered. Evaluation
prints a `report_path` pointing to the Markdown report; `result.json` and the
check logs sit alongside it.

`--trusted-local` allows commands to run with host access and inherited
configuration. Always choose a new run directory for a new attempt. Existing
runs and seals are not overwritten.

To see a functional failure, prepare another run and skip `generate` before
sealing and evaluating it. The unfinished baseline fails both checks. To try
manual development, edit the prepared `workspace/` yourself before sealing.

## Choose an agent

Replace `--agent-config` in the preparation command and choose a new run path:

| Backend | Example configuration | Current validation |
| --- | --- | --- |
| Claude Code | [`claude-agent.json`](examples/hello/claude-agent.json) | Live hello generation and independent checks passed |
| OpenCode | [`opencode-agent.json`](examples/hello/opencode-agent.json) | Live hello generation and independent checks passed |
| DeepSeek Harness | [`deepseek-agent.json`](examples/hello/deepseek-agent.json) | Offline adapter tests passed; live integration not yet verified |
| Custom command | [`fixture-agent.json`](examples/hello/fixture-agent.json) | Offline example; replace its command with your own |

Real-agent runs consume your configured account's usage. Claude's example sets
a 300-second timeout and a USD 1 client-estimated budget cap. OpenCode and
DeepSeek examples set a 300-second timeout but no monetary cap.

Optional model selection is supported by the Claude Code and OpenCode adapters.
DeepSeek uses the model configured in its own headless profile. A local source
checkout alone is not enough: its launcher and dependencies must be ready.
See [all backend options](docs/agent-backends.md) and
[Claude Code setup](docs/claude-code.md).

## Evaluate your own project

Start with a local Git repository and a change document in UTF-8 text or Markdown.
You do not need to identify the baseline commit yourself:

```sh
forge-eval resolve-baseline \
  --repo /path/to/project \
  --document /path/to/change.md \
  --agent-config examples/hello/claude-agent.json \
  --run .forge-eval/runs/project-001 \
  --trusted-local

forge-eval generate --run .forge-eval/runs/project-001 --trusted-local
```

`resolve-baseline` is an alias of `prepare`, using the same run lifecycle. It
analyzes history, selects the baseline, and creates `workspace/` in one call.
There is no separate result to manually pass between commands. The existing
`prepare --baseline DIRECTORY --case FILE` workflow also remains available.

The agent searches a disposable local clone, examines diffs, and chooses the
state before the complete documented change. It can consider multiple commits
or a merge and explain uncertainty. ForgeEval resolves its chosen Git revision
to a full commit ID and exports the tracked files directly; it does not switch
your source checkout or include its uncommitted files. The analysis clone is
removed after preparation. In-tree Git symlinks are materialized as ordinary
copies of their targets, including directory aliases, and listed in the
resolution record. External, dangling, cyclic links and submodules are
unsupported; symlink identity is not preserved in the evaluation workspace.

Repeat `--document` for multiple documents. Without `--case`, their combined text
becomes the public task in `inputs/case.json`. With `--case`, that JSON remains
the public task and the documents provide additional context for baseline
selection. A case alone can also describe the change when using `--repo`.
PDF/Word parsing and remote repository cloning are not included.

Selection reasons, optional related commits, raw agent logs and document copies
are saved in `resolution/`. The selected full commit ID is also recorded in
`state.json`. The agent controls its search strategy and can return additional
fields; no confidence threshold or intermediate schema validation is imposed.
An unresolved match or failed agent call leaves an `ERROR` run with evidence,
without silently falling back to the latest version. The system does not
independently prove that the selected change matches the document.

Baseline resolution adds no SHA-256 checks or baseline manifests. Export reads
tracked blobs once, retaining their bytes and executable modes. Existing public
input and candidate-sealing integrity checks are unchanged. Resolution evidence
is outside that integrity inventory and is not added to the implementation
prompt. Analysis and implementation use separate invocations of the same agent
configuration; this is not filesystem isolation.

For acceptance evaluation, also supply these optional inputs during preparation:

1. **`--case FILE`:** task JSON with the behavior you want verified.
2. **`--checks DIRECTORY`:** a `plan.json` file and any helper scripts it invokes.

Documents alone do not generate acceptance checks or feature declarations.
Supply these to obtain feature-level PASS/FAIL results, then use `seal` and
`evaluate` as in the offline example.

For example, a case might contain:

```json
{
  "case_id": "greeting",
  "requirement": "Implement greet(name) and reject blank names.",
  "required_features": [
    "Returns a greeting for a valid name.",
    "Rejects blank names."
  ]
}
```

A check in `plan.json` associates an executable test with a feature:

```json
{
  "checks": [
    {
      "check_id": "greeting",
      "features": ["Returns a greeting for a valid name."],
      "argv": ["{python}", "{checks}/check_greeting.py"],
      "timeout_seconds": 30
    }
  ]
}
```

Write `check_greeting.py` to inspect or execute the candidate in the current
working directory. A check returns **0** when its assertions pass, **1** for a
functional mismatch, and another exit code for an execution or environment
error. Normalize your test runner's exit codes to these conventions.

The example plan above leaves the blank-name requirement uncovered, so it
cannot produce an overall pass. Add a corresponding check before preparing
the run. The [complete hello bundle](examples/hello/checks) demonstrates both.

Inputs are intentionally permissive: extra fields and incomplete experiments
are allowed without schema validation. Feature descriptions are matched after
trimming surrounding whitespace. Unmatched required features remain unverified.
See the [execution conventions](docs/execution.md) for custom shell commands,
placeholders, and aggregation rules.

## Understand the results

| Result | Meaning |
| --- | --- |
| `PASS` | Required checks passed for the declared features |
| `FAIL` | At least one check found a functional mismatch |
| `UNVERIFIED` | Required behavior lacks sufficient checks or declarations |
| `ERROR` | Execution, environment, or integrity problems prevented a valid result |

Verification coverage is the fraction of required features with a definitive
`PASS` or `FAIL`. Feature pass rate is the fraction that passed, using every
required feature as the denominator. Errors and missing checks do not count
as passes. Failures and errors from unmapped checks also affect the overall
result; see the detailed report for each check.

**File integrity is separate from functional correctness.** `verify` compares
files with their seal and returns `NOT_EVALUATED` for functional status even
when separate evaluations exist. A trusted seal is required: local hashes do
not protect against someone replacing both the files and the seal.

CLI exit codes are `0` for success, `1` for controller/input errors, `2` for
command-line usage errors, and `3` for failed generation or a completed non-PASS
evaluation. Read the JSON status to distinguish failure from missing evidence.

## Where evidence is stored

```text
.forge-eval/runs/hello-001/
  inputs/                 # Frozen task, optional check bundle and agent config
  resolution/             # Optional history analysis, documents, selected commit
  workspace/              # Agent's editable project copy
  generation/             # Logs, execution result, adapter prompt when available
  artifacts/candidate/    # Sealed candidate copy
  seal.json               # File inventory and digests
  state.json              # Run lifecycle
  evaluations/<id>/       # Result JSON, Markdown report, and per-check logs
```

Every evaluation creates a new ID. Failed attempts remain available for
inspection. `.forge-eval/` is ignored by Git. Stop all writers before sealing;
each check then receives a fresh candidate copy. Logs persist, but temporary
build output is not retained.

Token usage is recorded only when the backend provides it. Client-estimated
cost is kept separate from verified billing; missing data stays unknown.

## Development

```sh
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

Automated tests run offline and use fake agent executables. They cover the run
lifecycle, input/candidate changes, feature aggregation, process errors,
timeouts, backend event parsing, and document-driven preparation against temporary
Git histories (including multi-commit and merge changes). CI runs the suite on Python 3.9 and 3.12;
real provider calls are not part of CI.

## Scope and next steps

The current workflow supports public contract checks on trusted local projects.
It does not implement hidden-reference evaluation, automatic test generation,
controlled Skill snapshots, statistical version comparisons, or MCP/plugin
packaging. A passing example does not establish broad coding capability.

For Skill experiments today, configure the host agent yourself and keep the
model, tools, case, environment, and budget consistent. Host settings are not
captured automatically, so results cannot yet establish isolated Skill effects.

Planned work includes execution isolation, representative project cases,
controlled configuration comparisons, and a thin MCP/Skill interface over the
same engine.

Further reading: [foundation and trust boundaries](docs/foundation.md),
[execution conventions](docs/execution.md), and [backend integration](docs/agent-backends.md).
