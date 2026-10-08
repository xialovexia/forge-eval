# Trusted-local execution contract

This backend runs commands with the controller's user permissions and inherited
environment. It does not restrict filesystem or network access, hide checks,
limit log size or memory, or protect records from malicious code. Do not use it
to evaluate untrusted agents or candidates. POSIX process groups support timeout
cleanup, but are not containment: a process can deliberately escape its group.

## Frozen inputs

`prepare --checks DIRECTORY --agent-config FILE` snapshots the optional public
check bundle and command configuration under `inputs/`. Their file digests are
included in the same frozen input inventory as the case. Subsequent edits to
the source bundle cannot alter the run. Edits to the frozen bundle invalidate
the run. All of these inputs are public in this prototype; only contract mode
is supported. Hidden evaluation material requires a future isolated backend.

The check bundle contains `plan.json` plus any needed helper scripts. A plan has
`schema_version: "1.0"` and a `checks` array. Each check contains:

- `check_id`: unique portable identifier used for its evidence directory.
- `features`: exact strings from the case's `required_features` list.
- `argv`: argument array; no implicit shell parsing.
- `timeout_seconds`: a positive number no greater than 86400.

An empty plan is allowed but cannot produce a pass. Unknown feature references
and duplicate check IDs are rejected. JSON schemas document the structure;
the runtime also validates cross-references and uniqueness. Feature descriptions
serve as identities for this prototype; stable feature IDs need a later case
schema revision.

## Command-agent adapter

Agent configuration contains only `argv` and `timeout_seconds` for now.
`{python}`, `{workspace}`, and `{case}` are available as complete argument tokens
or leading path tokens. `{case}` is the frozen case JSON path. The command is
responsible for loading the requirement and invoking its chosen agent. The
working directory is the prepared workspace. The configuration must capture any
model or tool options explicitly in its command; no backend-specific defaults
are inferred or usage estimates invented.

`generate --trusted-local` transitions `PREPARED` to `RUNNING`, then `GENERATED`
or `GENERATION_FAILED`. A zero exit code and unchanged frozen inputs are required
for `GENERATED`. This status does not imply functional correctness. Stdout,
stderr, timing, exit status, and unknown token/cost fields are saved under
`generation/`. A failed generation cannot be retried or sealed in place; create
a new run. Manual code editing can still proceed directly from `PREPARED` to
sealing, without a configured agent.

The hello fixture writes a predetermined implementation. It tests plumbing,
not an agent's ability to solve a task. Real-agent integration, model identity,
skill snapshots, and provider-reported usage remain future work.

## Independent evaluation attempts

`evaluate --trusted-local` requires a valid seal. It uses the frozen plan and
copies the sealed candidate and checks into a fresh temporary directory for
each check. `{candidate}`, `{checks}`, and `{python}` are argument tokens. The
working directory is the candidate copy. Each check must perform any required
setup itself; no build state is shared across checks. Copies are cleaned up
afterward. Generated build output is not retained in this prototype; captured
stdout, stderr, and execution metadata are retained.

Check exit conventions are an adapter contract:

| Outcome | Check status |
| --- | --- |
| Exit 0 | PASS |
| Exit 1 | FAIL: a contract assertion was violated |
| Other exit, signal, timeout, launch error | ERROR |

A wrapper around a test runner must normalize its exit codes to this contract.
The harness cannot infer whether an arbitrary command returning 1 represents a
failed assertion or a broken environment. A command returning 0 without testing
anything is not a valid oracle. The example suite verifies the unfinished
baseline fails and a deliberately incorrect implementation is detected.

Every required feature aggregates all mapped checks: FAIL takes precedence,
then ERROR, then UNVERIFIED, then PASS. An unmapped feature is UNVERIFIED. The
overall result uses the same precedence. Individual check errors remain visible
even when a functional failure determines the overall status.

Verification coverage is the fraction of features with a definitive PASS or
FAIL. Feature pass rate uses every required feature as its denominator. Missing
checks and infrastructure errors cannot inflate either metric. Failed integrity
checks during execution invalidate all feature results and set overall ERROR.

Each attempt writes `evaluations/<id>/result.json`, `report.md`, `state.json`,
and per-check evidence. Records include the seal digest, evaluator version,
Python version, and executed commands. Re-evaluation creates a new ID. A process
crash may leave an EVALUATING attempt; it is not a completed evaluation. The
original seal and its NOT_EVALUATED marker never change. Records are ordinary
local files, not signed or tamper-proof attestations.

## CLI exit codes

- `0`: requested operation succeeded; evaluation specifically means PASS.
- `1`: invalid input, integrity failure, or controller error.
- `2`: command-line usage error from the argument parser.
- `3`: generation failed or evaluation completed with a non-PASS result.

Treat the JSON status as authoritative for distinguishing FAIL, ERROR, and
UNVERIFIED. These result statuses are separate from CLI exit codes and check
process exit codes.
