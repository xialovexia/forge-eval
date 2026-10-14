# ForgeEval

Use change documents to locate a baseline in a real project's history, ask a coding agent to implement the requirements, and evaluate its output with independent acceptance checks.

## Project Purpose

Evaluating a coding agent requires answering three questions: what state did it start from, what change was it asked to make, and does the resulting code meet the requirements? The agent's completion message alone cannot answer them.

ForgeEval organizes these questions into an inspectable workflow:

```text
Change documents + project Git history
                  ↓
Agent locates the most relevant historical change
and selects the baseline before that change
                  ↓
Create a workspace from the pinned baseline
and let the agent implement the requirements
                  ↓
Seal the candidate, run independent checks, and report results
```

**The primary input is a document describing the change. You do not need to supply a baseline commit in advance.** The configured agent searches code, commit history, and diffs to identify a change spanning one commit, several related commits, or a merge. It then selects the version before the complete change. ForgeEval pins that choice to a full Git commit ID and retains the reasoning and execution records.

This turns historical project changes into coding tasks and provides evidence for investigating baseline selection errors, generation failures, and unmet requirements separately. Inputs, logs, candidate code, and results for each declared feature remain available for review and later comparison.

The current version is **0.1.0a1, an early prototype for trusted local use**. Agents and check commands use host permissions and existing configuration. There is no security sandbox, hidden-test isolation, or controlled Skill snapshot. Baseline selection still depends on the agent's judgment; pinning a commit does not prove that the selection is correct.

## Usage

### Installation and Requirements

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

## Current Test Status

The following local validation results are current as of **2026-10-14**, distinguishing offline tests, live agent calls, and project experiments.

| Test Scope | Current Result |
| --- | --- |
| ForgeEval automated tests | 77 offline tests passed, covering the run lifecycle, historical baseline selection, file integrity, feature aggregation, timeouts, and backend protocols |
| Claude Code hello example | Live generation completed and independent acceptance checks passed |
| OpenCode hello example | Live generation completed, both required features passed independent checks, and seal verification passed |
| DeepSeek Harness backend | Offline adapter tests passed; live `dsh` invocation has not yet been validated |

Run the automated tests locally with:

```sh
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

CI is configured for Python 3.9 and 3.12. Offline tests use simulated agents, exclude live provider calls, and do not establish model capability on project tasks.

### DeepSeek Harness Historical Change Experiment

This experiment used **PR #2484, `fix(web): reject unsupported wildcard host`**, from the DeepSeek Harness repository. A requirements file was derived from the historical change, then local Claude Code selected the baseline and attempted a fresh implementation. The requirements input contained neither the PR number nor a commit ID.

The case came from local Git merge records and diffs, which record a merge date of 2026-08-13. The public PR endpoint did not return the PR, so this is a case from locally available history, not a verified latest PR from the public repository.

Baseline resolution correctly selected the version before the complete change was merged:

```text
5d114c283391a19d541dfb18d5c4c956d73241a6
```

The same independent acceptance checks were applied to three versions:

| Evaluated Version | Result | Details |
| --- | --- | --- |
| Baseline before the change | `FAIL`, 2/4 groups passed | Wildcard host rejection and the help/documentation updates were absent |
| Historical PR implementation | `PASS`, 4/4 groups passed | Used as a reference to validate the checks |
| Claude Code candidate | `PASS`, 4/4 groups passed | 47 assertions covering address rejection, compatibility, help/documentation, and trust rules |

**The experiment did not complete the entire workflow successfully.** Claude Code's generation invocation timed out after 600 seconds, and the original run remains `GENERATION_FAILED`. The candidate left at timeout was subsequently sealed and evaluated in a separate run, with no manual source-code repairs. Passing candidate checks and a failed generation lifecycle are separate outcomes.

The checks executed actual TypeScript modules with a simulated service context. They did not validate the fully built CLI, a live web server, or the project's entire CI suite. Generation tokens and cost remain unknown because no final result was received. Using DeepSeek Harness as the target project also does not validate its `dsh` agent backend.

The requirements, checks, summaries, and reports are stored locally under `.forge-eval/experiments/deepseek-pr2484/` and the corresponding run directories. They are not distributed with the repository.

## Supported Tools

ForgeEval currently provides a Python CLI with these coding-agent backends:

| Tool / Backend | Integration | Model Configuration | Example |
| --- | --- | --- | --- |
| Claude Code / `claude-code` | Local `claude`, with structured events and a final result | Optional `model` in the agent configuration | [claude-agent.json](examples/hello/claude-agent.json) |
| OpenCode / `opencode` | Local `opencode run`, with JSON events | Optional `provider/model` selection | [opencode-agent.json](examples/hello/opencode-agent.json) |
| DeepSeek Harness / `deepseek-harness` | Official `dsh` headless profile or an already-built source launcher | Uses the Harness profile configuration | [deepseek-agent.json](examples/hello/deepseek-agent.json) |
| Custom command | Receives the task on stdin; exit status and logs are recorded | Controlled by the command | [fixture-agent.json](examples/hello/fixture-agent.json) |

All backends share the preparation, generation, sealing, and evaluation lifecycle. A custom command used for baseline resolution must also return its selection on stdout; the example fixture demonstrates generation only. Tool installation, authentication, permissions, and dependencies come from the local environment. ForgeEval does not install or freeze them.

Claude Code and OpenCode can record backend-reported tokens and estimated costs. DeepSeek Harness and generic commands currently provide no standard usage data. See [backend integration](docs/agent-backends.md) for all options and the [Claude Code guide](docs/claude-code.md) for its setup.

Supported inputs are local Git repositories, UTF-8 text or Markdown documents, and existing baseline directories. Git export can materialize links within the repository as ordinary files or directories, without preserving symlink identity. External, dangling, or cyclic links and submodules are unsupported. Directly supplied baseline directories also do not support symlinks.

Remote repository cloning, PDF/Word parsing, automatic acceptance-test generation, hidden-reference evaluation, controlled Skill comparisons, statistical version comparisons, and MCP/plugin packaging are not yet implemented.
