# Foundation contract

This release implements local evidence management and opt-in trusted command
execution. It can execute configured agent commands and contract checks. It does
not enforce an OS sandbox or protect hidden evaluation data. See
[the execution contract](execution.md) for functional evaluation semantics.

## Case

This iteration prioritizes experiments over format enforcement. There are no
Case, Agent, or Check Plan schemas or validation commands. Case inputs may carry
arbitrary fields, identifiers, mode labels, and version metadata. A case can be
a JSON object or a JSON string containing the requirement. Missing `case_id`
uses the input filename stem as the run label.

`required_features` is optional and can contain a list or a single description.
Descriptions and check references are compared after trimming surrounding
whitespace. Unknown references and duplicates do not block execution. Missing
coverage remains visible in evaluation results; a description alone is not
evidence that a criterion has been met. Free-form mode labels do not implement
holdout isolation or guided replay; those capabilities remain planned.

## Run lifecycle

`prepare` requires a new run directory outside the baseline. It records
`PREPARING`, enumerates regular baseline files and copies them into `workspace/`,
then records `PREPARED`. Preparation does not hash baseline files, generate a
baseline manifest, or compare baseline and workspace digests. Git metadata named
`.git` is excluded; symlinks and special files in the copied inputs are rejected.
Empty directories are not
tracked. Failed preparation retains an `ERROR` record and requires a new run.

`inputs/case.json` contains the public case. The baseline is the initial workspace
copy, with file metadata preserved by the copy operation. Frozen case, check,
and agent files have their digests retained in `state.json` and checked again at
sealing time.

An operator can modify the workspace using their preferred development tools,
or invoke a frozen command configuration with `generate`.
Stop all writers before `seal`. The controller checks the frozen inputs and
copies the candidate to `artifacts/candidate/`. It validates the source and copy,
publishes `seal.json`, and records `SEALED`. Existing seals and artifact
directories are never overwritten. Failed sealing retains evidence and records
`ERROR`; use a new run rather than repairing the historical record in place.

`verify` compares the complete candidate file inventory and frozen inputs with
the seal. It detects missing, added, modified, and mode-changed files. Later
edits to the working copy do not alter the sealed candidate. A successful check
means integrity relative to the seal, **not** functional correctness. All seals
and integrity verification results retain `evaluation_status: NOT_EVALUATED`.

## Trust boundary

The workspace and artifacts are ordinary local directories. The same OS user
can change them. There is no filesystem access control, secret filtering,
network restriction, cryptographic signature, immutable storage, or protection
against a malicious process replacing both artifacts and their seal. Snapshot
checks detect many accidental changes but are not an atomic filesystem snapshot.

Use only a curated public baseline for this foundation workflow. Excluding Git
metadata does not remove secrets, reference implementations, or target-derived
knowledge from source files. Future execution adapters must place untrusted
agents behind a real isolation boundary and protect evaluator-owned records.

## Storage layout

```text
run/
  state.json
  inputs/
    case.json
  workspace/
  artifacts/candidate/
  seal.json
```

JSON is the file storage encoding. The controller publishes JSON documents using
atomic replacement and reads the fields needed by each operation. It does not
run intermediate-record format checks or compare schema versions, kind labels,
case identities, or evaluation-status metadata. Generated `schema_version` fields
are informational. The removed `validate-case` command and strict schema files
are not part of this experimental workflow.

Run status transitions and file digest comparisons remain operational checks.
Persistent state is currently file-based; SQLite indexing, worker recovery,
evaluation data models, and agent adapters are future work.

Generation and evaluation records extend this layout; they do not overwrite the
seal. `generate`, `seal`, and `evaluate` acquire an exclusive local controller
lock. A crash can leave `.controller.lock` behind; inspect its PID and ensure all
associated processes have stopped before manually removing it. Automatic crash
recovery and distributed locking are not implemented.
