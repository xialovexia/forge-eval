# Foundation contract

This release implements local evidence management and opt-in trusted command
execution. It can execute configured agent commands and contract checks. It does
not enforce an OS sandbox or protect hidden evaluation data. See
[the execution contract](execution.md) for functional evaluation semantics.

## Case

`schemas/case.schema.json` defines the public JSON format. The dependency-free
CLI enforces these constraints directly. Only `contract` mode is accepted;
strict holdout and guided replay remain planned until their boundaries exist.
Required feature descriptions are public acceptance criteria. Frozen check
bundles map executable checks to these exact descriptions. A description alone
is not evidence that the criterion has been met.

## Run lifecycle

`prepare` requires a new run directory outside the baseline. It records
`PREPARING`, copies regular baseline files into `workspace/`, validates the copy,
then records `PREPARED`. Git metadata named `.git` is excluded; symlinks and
special files in the copied inputs are rejected. Empty directories are not
tracked. Failed preparation retains an `ERROR` record and requires a new run.

`inputs/case.json` contains the normalized public case. The baseline manifest
records original file hashes, sizes, and modes. Their own digests are retained in
`state.json` and checked again at sealing time.

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
    baseline-manifest.json
  workspace/
  artifacts/candidate/
  seal.json
```

JSON records carry `schema_version: 1.0`. JSON documents are published using
atomic replacement. Persistent state is currently file-based; SQLite indexing,
worker recovery, Oracle/Evaluation schemas, and agent adapters are next steps.

Generation and evaluation records extend this layout; they do not overwrite the
seal. `generate`, `seal`, and `evaluate` acquire an exclusive local controller
lock. A crash can leave `.controller.lock` behind; inspect its PID and ensure all
associated processes have stopped before manually removing it. Automatic crash
recovery and distributed locking are not implemented.
