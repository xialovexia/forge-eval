# ForgeEval

**Evaluate coding agents and skills on real project tasks.**

ForgeEval is a project-level evaluation harness designed for isolated runs, evidence-backed verification, and reproducible comparisons.

> **Status: trusted-local prototype.** The CLI freezes public contract checks and command-agent configuration, runs trusted commands, seals candidates, and produces feature-level JSON and Markdown evaluations. It has no security sandbox, hidden-test protection, real-agent-specific integration, or statistical comparison engine.

## Quick Start

Requires Python 3.9 or newer; local command execution currently requires macOS
or Linux. No runtime dependencies are required. Run from the repository root:

```sh
export PYTHONPATH="$PWD/src"
python3 -m forge_eval prepare \
  --case examples/hello/case.json \
  --baseline examples/hello/baseline \
  --checks examples/hello/checks \
  --agent-config examples/hello/fixture-agent.json \
  --run .forge-eval/runs/hello-001
python3 -m forge_eval generate --run .forge-eval/runs/hello-001 --trusted-local
python3 -m forge_eval seal --run .forge-eval/runs/hello-001
python3 -m forge_eval verify --run .forge-eval/runs/hello-001
python3 -m forge_eval evaluate --run .forge-eval/runs/hello-001 --trusted-local
```

**This example uses a deterministic fixture that writes a known implementation,
not a real coding agent.** It demonstrates the orchestration and evaluation
mechanics only. `--trusted-local` acknowledges that commands and candidate code
run with your user permissions and inherited environment. Use only trusted code.

Evaluation returns its report path under the run's `evaluations/` directory.
Each attempt gets a new directory. `verify` checks file integrity only and always
returns `NOT_EVALUATED`; functional results belong to separate evaluation records.

To evaluate the unfinished baseline, prepare another run with the same checks,
skip `generate`, then seal and evaluate it: both required features should fail.
A run without a check bundle produces `UNVERIFIED`, never a functional pass.

```sh
python3 -m unittest discover -s tests -v
```

For an installed CLI, use `python3 -m pip install -e .` in a virtual environment;
the equivalent command is then `forge-eval`. See the
[execution contract](docs/execution.md) and [foundation contract](docs/foundation.md).

## Purpose

ForgeEval evaluates whether an agent or skill can turn requirements into working project code. It focuses on functional correctness, verification coverage, reliability, and cost.

The unit of evaluation is a complete configuration: agent and model, skill version, knowledge snapshot, tool permissions, project environment, and execution budget. Comparisons should keep all variables fixed except the one being evaluated.

## Planned Architecture

- **Standalone engine and CLI:** manage cases, execution, verification, artifact sealing, scoring, and comparisons.
- **MCP and skill integration:** let general-purpose agents configure evaluations, inspect progress, and explain results.
- **Agent adapters:** connect different CLI and API execution backends.
- **Project adapters:** define environment setup, build commands, tests, and acceptance contracts.
- **Reports:** provide machine-readable results and browsable evidence.

The agent managing an evaluation and the agent under test run in separate sessions and controlled workspaces. The core workflow should also run independently of any chat interface.

## Evaluation Modes

| Mode | Generation inputs | What it measures |
| --- | --- | --- |
| Strict holdout | Requirements, baseline, and permitted knowledge and tools | Independent delivery capability, without access to the reference implementation or hidden evaluation information |
| Guided design replay | The same inputs plus sanitized design feedback derived from a reference implementation | Implementation capability after design correction; results are reported separately from strict holdout |
| Contract evaluation | Requirements, baseline, and acceptance contracts frozen before the run | Delivery on new features and projects without a historical reference implementation |

A **baseline** is the project state before the task. A **Goldline** is a reference implementation used as evidence. Requirements and confirmed business contracts define correctness; alternative implementations may pass when their observable behavior is equivalent.

## Planned Workflow

1. Register requirement sources, task scope, and acceptance criteria.
2. Freeze the baseline, skill, knowledge snapshot, execution configuration, and scoring criteria.
3. Prepare an isolated workspace and run the agent under test.
4. Capture candidate code, execution traces, usage, and exit status.
5. Seal candidate artifacts through an external controller.
6. Run builds, contract tests, regression checks, and any necessary semantic review in an independent evaluation environment.
7. Report feature-level outcomes, supporting evidence, limitations, and cost.
8. Produce knowledge improvement candidates for review and use in later versions only.

In strict holdout mode, hidden reference information is used for scoring only after candidate artifacts are sealed. In guided replay, a private reviewer may inspect the Goldline earlier, but only controlled feedback reaches the generating agent, and the run is explicitly labeled as guided.

## Evaluation Principles

- Judge observable behavior rather than code similarity or matching file layouts.
- Report build checks, static analysis, dynamic tests, and model judgments separately, including whether each check actually ran.
- Distinguish PASS, FAIL, unverified behavior, environment errors, and disputed criteria. A case cannot pass while a required feature remains unverified.
- Report both functional pass rate and verification coverage. Do not hide unverified items to inflate results.
- Preserve input versions, evaluator versions, artifact hashes, and evidence. Repairs and rescoring produce new records.
- Repeat runs under fixed conditions and report quality, reliability, latency, and usage. Separate estimated costs from verified billing.
- Use development cases for knowledge improvement and untouched holdout cases for claims about generalization.

## Initial Roadmap

- [ ] Define Case, Run, Artifact, Oracle, and Evaluation schemas.
- [x] Implement a minimal CLI and file-based persistent run state.
- [x] Prepare local workspaces and seal and verify candidate files.
- [ ] Implement isolated workspaces, evidence capture, and artifact sealing.
- [x] Add a generic trusted-local command adapter and a Python contract example.
- [x] Produce feature-level reports with evidence and verification coverage.
- [ ] Integrate a real agent backend and an isolated project execution environment.
- [ ] Run a historical change case and a contract case without a Goldline.
- [ ] Add a second project technology stack without modifying the core engine.
- [ ] Produce version comparison reports.
- [ ] Package an MCP interface and a management skill.

## Planned Technical Foundation

The foundation uses a Python core, local artifact storage, and versioned JSON records. A SQLite run index and complete evaluation schemas are planned. Project adapters define execution environments. Independent workers and shared storage can later support team deployments.
