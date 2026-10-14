# Trusted-local execution contract

This backend runs commands with the controller's user permissions and inherited
environment. It does not restrict filesystem or network access, hide checks,
limit log size or memory, or protect records from malicious code. Do not use it
to evaluate untrusted agents or candidates. POSIX process groups support timeout
cleanup, but are not containment: a process can deliberately escape its group.

## Frozen inputs

`prepare --checks DIRECTORY --agent-config FILE` snapshots the optional public
check bundle and command configuration under `inputs/` without validating their
JSON structure or cross-references. Their file digests are
included in the same frozen input inventory as the case. Subsequent edits to
the source bundle cannot alter the run. Edits to the frozen bundle invalidate
the run. All of these inputs are public in this prototype. Mode labels are
unrestricted metadata; hidden evaluation material requires a future isolated
backend.

The evaluator reads `plan.json` plus any helper scripts from the check bundle.
A plan can be an object with `checks`, a list of checks, or a single command
object or string. These are reading conventions, not an enforced schema:

- `check_id`: optional display label; defaults to `check-1`, `check-2`, etc.
- `features`: optional descriptions from the case; accepts a list or one value.
- `argv` or `command`: argument array or shell command string.
- `timeout_seconds`: optional timeout consumed by the execution backend.

Extra fields, omitted versions, free-form identifiers, duplicate names, and
duplicate or unknown feature references are accepted. A single `checks` object
is treated as one check. Command strings and argument arrays can also be used as
check entries directly. Whitespace around feature descriptions is trimmed for
association; other unmatched descriptions remain unverified.

Evidence directories use execution order, such as `checks/0001/`, independently
of display labels. Results include `evidence_path`, and reports link to that
path, so repeated names and filesystem naming differences do not affect logging.

An empty plan can be run but cannot produce a functional pass. No feature
declarations produces zero feature metrics and UNVERIFIED unless a check fails
or errors. Commands run without requiring a complete acceptance specification.

## Command-agent adapter

Agent configuration accepts a command object, argument array, or shell command
string. An object uses `argv` or `command` and may include extra fields. Argument
arrays run directly and preserve empty arguments. Strings run through the local
shell, allowing normal shell expressions and pipelines.

`{python}`, `{workspace}`, and `{case}` are substituted wherever they occur in
command arguments or strings, including options such as `--case={case}`. `{case}`
is the frozen case JSON path. When using shell strings, quote paths according to
the command's needs. The working directory is the prepared workspace. Model and
tool choices remain the command author's responsibility; usage estimates are
not invented.

`timeout_seconds` is optional. Omitting it or setting it to null supplies no
controller timeout. Numeric strings are converted to numbers, and no type/range
validation pass imposes a fixed upper limit. Values the execution backend cannot
use are recorded as execution errors rather than rejected during preparation.

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

Every declared required feature aggregates all associated checks: FAIL takes precedence,
then ERROR, then UNVERIFIED, then PASS. An unmapped feature is UNVERIFIED. The
overall result uses the same precedence and also includes every executed check,
so failed or broken checks with unmatched references remain visible. Individual
check errors remain visible even when a functional failure determines the
overall status.

Verification coverage is the fraction of features with a definitive PASS or
FAIL. Feature pass rate uses every required feature as its denominator. Missing
checks and infrastructure errors cannot inflate either metric. Failed integrity
checks during execution invalidate all feature results and set overall ERROR.

Each attempt writes `evaluations/<id>/result.json`, `report.md`, `state.json`,
and per-check evidence. Records include the seal digest, evaluator version,
Python version, and executed commands. No JSON/schema checks are run on these
intermediate or result records. Re-evaluation creates a new ID. A process
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
