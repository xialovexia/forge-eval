# ForgeEval

ForgeEval evaluates the code-generation capabilities of coding agents on existing codebases. It provides a defined project baseline and change requirements, then assesses the generated code through independent acceptance checks. Each run preserves the inputs, generated code, logs, and results for inspection.

ForgeEval works as a standalone Python CLI and as a shared plugin for Claude Code and Codex.

## Project Purpose

Working on an existing codebase requires an agent to understand the surrounding code, implement the requested change, and preserve behavior that should remain unchanged. ForgeEval supports evaluating these capabilities through project tasks such as adding features, fixing bugs, and modifying existing functionality.

An evaluation connects three things: the project's starting state, the requested change, and executable checks of the resulting behavior.

```text
Existing codebase + change requirements
                  ↓
Prepare a baseline workspace
(supplied directly or resolved from Git history)
                  ↓
Let the coding agent implement the change
                  ↓
Seal the generated code and run independent acceptance checks
                  ↓
Report feature-level results with execution evidence
```

You can supply a prepared baseline or use change documents to construct a task from project history. For historical tasks, the configured agent searches the repository's code, commits, and diffs to identify the relevant change and select the version before it. ForgeEval pins that baseline to a full Git commit ID and retains the selection evidence.

Acceptance checks determine whether the generated code satisfies the declared requirements. They can cover both the requested functionality and existing behavior that must be preserved. Generation failures, baseline-selection errors, and unmet requirements remain distinguishable in the run records; an agent's completion message alone does not establish success.

ForgeEval runs in a trusted local environment. Agents and check commands use host permissions and existing configuration. There is no security sandbox, hidden-test isolation, or controlled Skill snapshot. Baseline selection still depends on the agent's judgment; pinning a commit does not prove that the selection is correct.

## Usage

### Use as a Claude Code or Codex Plugin

Both hosts can load the same ForgeEval skill and bundled Python core. Build a
clean plugin directory from this checkout:

```sh
python3 scripts/build_plugin.py --output dist/forge-eval
```

For a Claude Code session, run
`claude --plugin-dir /absolute/path/to/dist/forge-eval`, then invoke
`/forge-eval:forge-eval`. For Codex, register and install the same package:

```sh
codex plugin marketplace add /absolute/path/to/dist/forge-eval
codex plugin add forge-eval@forge-eval-local
```

The plugin needs Python 3.9+ and local shell access, but no pip installation.
It preserves the standalone CLI and existing backend selection. See the
[plugin guide](docs/plugins.md) for persistent Claude installation, Codex desktop
setup, the offline smoke test, and the distinction between the plugin host and
the evaluated agent. Both hosts reuse the same skill and runtime; the evaluated
agent is selected independently through its configuration.

### Standalone CLI Installation

Use Python 3.9+ on macOS or Linux. History analysis requires Git, and live model calls require a separately installed and authenticated agent CLI. The Python core has no third-party runtime dependencies.

```sh
git clone https://github.com/xialovexia/forge-eval.git
cd forge-eval
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
forge-eval --help
```

Run the following examples from the ForgeEval repository root. To run without installing, set `PYTHONPATH=src` and use `python3 -m forge_eval` in place of `forge-eval`.

### Create a Task from Change Documents

Prepare a local project repository, a UTF-8 text or Markdown requirements document, and an agent configuration. For example, save the following as `agent.json` in your task directory:

```json
{
  "backend": "claude-code",
  "timeout_seconds": 600,
  "max_budget_usd": 5.0,
  "allowed_tools": ["Read", "Edit", "Write", "Glob", "Grep", "Bash"]
}
```

Adjust the example timeout and budget for your task. They apply separately to each baseline-resolution and code-generation invocation. Live calls consume usage on your configured account.

Replace `/path/to/...` below with your actual paths:

```sh
forge-eval resolve-baseline \
  --repo /path/to/project \
  --document /path/to/task/requirement.md \
  --agent-config /path/to/task/agent.json \
  --run .forge-eval/runs/project-001 \
  --trusted-local

forge-eval generate --run .forge-eval/runs/project-001 --trusted-local
```

`resolve-baseline` is an alias of `prepare`. It analyzes history, pins the baseline, and creates the workspace in one operation, with no resolution result to pass manually between separate workflows.

- Repeat `--document` to supply multiple documents. Without `--case`, their combined text becomes the public task.
- Add `--case FILE` to define the implementation task in JSON, with the documents providing extra context for baseline analysis. A case alone can also describe the change.
- The agent analyzes history in a temporary clone and chooses its own search strategy and grouping of related commits. An unresolved baseline or failed invocation leaves an error record; ForgeEval does not fall back to the latest version.
- The workspace is exported from the selected commit's Git objects. The source checkout is not switched, and its uncommitted files are not included.
- Baseline analysis and implementation use separate invocations of the same agent configuration. Resolution evidence is omitted from the implementation prompt, but local files are not isolated by a security boundary.

`--trusted-local` allows agents or check commands to access the host environment. Use a new `--run` directory for each attempt; failed runs remain available for inspection.

### Configure Acceptance Checks and Evaluate

**Requirements documents do not automatically generate acceptance checks.** To obtain results for declared features, also supply `--case` and `--checks` during preparation:

```sh
forge-eval resolve-baseline \
  --repo /path/to/project \
  --document /path/to/task/requirement.md \
  --case /path/to/task/case.json \
  --checks /path/to/task/checks \
  --agent-config /path/to/task/agent.json \
  --run .forge-eval/runs/project-002 \
  --trusted-local

forge-eval generate --run .forge-eval/runs/project-002 --trusted-local
```

Use the complete example in this repository as a reference:

| File | Contents |
| --- | --- |
| [`case.json`](examples/hello/case.json) | `case_id`, the task text in `requirement`, and the `required_features` to verify |
| [`checks/plan.json`](examples/hello/checks/plan.json) | Each check's command (`argv`), timeout, and covered `features` |
| [`checks/check_greeting.py`](examples/hello/checks/check_greeting.py) | A check script that executes the candidate and asserts its behavior |

Feature descriptions in checks should match those declared in the case. Checks run in copies of the candidate: exit code `0` means pass, `1` means a functional mismatch, and other codes indicate execution or environment errors. Missing feature declarations or coverage prevent an overall functional pass. Additional fields and incomplete experiments are accepted without requiring strict schemas for intermediate steps.

Once `generate` returns `GENERATED` and all workspace writers have stopped, seal and evaluate the candidate:

```sh
forge-eval seal --run .forge-eval/runs/project-002
forge-eval verify --run .forge-eval/runs/project-002
forge-eval evaluate --run .forge-eval/runs/project-002 --trusted-local
```

`GENERATED` means only that the agent invocation completed. `verify` checks that candidate files match their seal; it does not assess functionality. `evaluate` creates a fresh candidate copy for each check and produces JSON results, a Markdown report, and check logs.

| Evaluation Status | Meaning |
| --- | --- |
| `PASS` | All declared required features passed their acceptance checks |
| `FAIL` | A check found behavior that does not meet the requirements |
| `UNVERIFIED` | Feature declarations or sufficient check coverage are missing |
| `ERROR` | Execution, environment, or integrity problems prevented a valid evaluation |

Timeouts and failed invocations are recorded as `GENERATION_FAILED`. They are not successful generations, and that failed run cannot proceed directly to sealing. Create a new run directory for a retry.

### Try the Example Without a Model

The repository includes a deterministic fixture for checking the local evaluation workflow. It writes a known implementation without calling a model and cannot analyze history to select a baseline.

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

Expected results are `GENERATED` for generation, `VERIFIED` for file verification, and `PASS` for evaluation. This uses the existing `--baseline DIRECTORY` entry point for tasks with an already prepared baseline directory.

### Inspect Run Records

```sh
forge-eval doctor
forge-eval inspect --run .forge-eval/runs/project-002
```

`doctor` reports local prerequisites without calling models. `inspect` reads run
state, generation/evaluation evidence, and current integrity without executing
checks. Historical evaluation results and current integrity are shown separately.

```text
.forge-eval/runs/<run>/
  inputs/                 # Frozen task, checks, and agent configuration
  resolution/             # Document copies, analysis logs, baseline choice (optional)
  workspace/              # Editable project copy for the agent
  generation/             # Implementation prompt, invocation logs, generation status
  artifacts/candidate/    # Sealed candidate code
  seal.json               # Candidate file integrity record
  state.json              # Run state and selected baseline commit
  evaluations/<id>/       # result.json, report.md, and individual check logs
```

Every evaluation receives a new ID. The command's `report_path` points to its report. `.forge-eval/` is ignored by Git. Tokens and costs are recorded only when provided by the backend; client estimates are separate from actual billing, and missing values remain unknown.

See [execution conventions](docs/execution.md) for commands, placeholders, and result aggregation, and [foundation and trust boundaries](docs/foundation.md) for evaluation scope.

## Supported Tools

ForgeEval provides a Python CLI and a shared Claude Code/Codex plugin, with these
coding-agent backends:

| Tool / Backend | Integration | Model Configuration | Example |
| --- | --- | --- | --- |
| Claude Code / `claude-code` | Local `claude`, with structured events and a final result | Optional `model` in the agent configuration | [claude-agent.json](examples/hello/claude-agent.json) |
| OpenCode / `opencode` | Local `opencode run`, with JSON events | Optional `provider/model` selection | [opencode-agent.json](examples/hello/opencode-agent.json) |
| DeepSeek Harness / `deepseek-harness` | Official `dsh` headless profile or an already-built source launcher | Uses the Harness profile configuration | [deepseek-agent.json](examples/hello/deepseek-agent.json) |
| Custom command | Receives the task on stdin; exit status and logs are recorded | Controlled by the command | [fixture-agent.json](examples/hello/fixture-agent.json) |

All backends share the preparation, generation, sealing, and evaluation lifecycle. A custom command used for baseline resolution must also return its selection on stdout; the example fixture demonstrates generation only. Tool installation, authentication, permissions, and dependencies come from the local environment. ForgeEval does not install or freeze them.

Claude Code and OpenCode can record backend-reported tokens and estimated costs. DeepSeek Harness and generic commands currently provide no standard usage data. See [backend integration](docs/agent-backends.md) for all options and the [Claude Code guide](docs/claude-code.md) for its setup.

Supported inputs are local Git repositories, UTF-8 text or Markdown documents, and existing baseline directories. Git export can materialize links within the repository as ordinary files or directories, without preserving symlink identity. External, dangling, or cyclic links and submodules are unsupported. Directly supplied baseline directories also do not support symlinks.

## Development

Run the automated tests from the repository root:

```sh
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

The offline suite covers the evaluation lifecycle, backend protocols, file integrity, and relocated plugin execution without live provider calls. CI runs on Python 3.9 and 3.12.
