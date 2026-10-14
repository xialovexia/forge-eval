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

`prepare` (also named `resolve-baseline`) requires a new run directory. With
`--baseline`, that directory must be outside the baseline. It records
`PREPARING`, prepares `workspace/`, then records `PREPARED`.

With `--repo` and `--document` (or `--case`), the configured agent searches a
temporary local clone and selects the version before the documented change.
This requires `--trusted-local` and `--agent-config`. The source repository is
not checked out or reset. Selection uses the clone's initial HEAD as recorded
context, while the agent can explore other available history. The chosen
revision is resolved to a full commit ID, and tracked blobs are streamed into
the workspace, preserving bytes and executable modes without checkout filters
or Git archive substitutions. Git LFS pointers remain pointers; the exporter
does not fetch external LFS objects. Source working-tree edits and analysis scratch files
are not included. The temporary clone is removed on success or failure.

With `--baseline`, regular files are copied from the supplied directory.
Preparation does not hash baseline files, generate a
baseline manifest, or compare baseline and workspace digests. Git metadata named
`.git` is excluded. Git exports materialize internal symlinks as ordinary
target copies and record the mapping in `materialized_symlinks`; this supports
instruction aliases such as `CLAUDE.md -> AGENTS.md`. Directory aliases are
copied too. Symlink identity is not preserved, so tests of symlink semantics
need a different workspace backend. External, dangling, cyclic links and
submodules are unsupported. Directory-based preparation continues to reject
symlinks and special files.
Empty directories are not
tracked. Failed preparation retains an `ERROR` record and requires a new run.

`inputs/case.json` contains the supplied public case, or a task built from the
documents when no case is supplied. Frozen case, check,
and agent files have their digests retained in `state.json` and checked again at
sealing time.

`resolution/result.json` retains the agent's decision and explanation, optional
evidence, the source HEAD, selected baseline commit ID, and execution metadata.
Document copies and agent logs live alongside it. These records are not hashed,
sealed, or included in the generation prompt. `state.json` points to the record
and stores the selected full commit ID. Extra decision fields are preserved;
there is no confidence gate or required analysis sequence. The only selection
fields consumed are `baseline_commit`, or `change_commit` whose first parent
is used. Git must be able to resolve and export the chosen version. An unresolved
match, invalid revision or failed invocation retains evidence and marks the run
`ERROR`, requiring a new run. Selection relevance is the agent's judgment, not
an independently verified evaluation result.

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

Review an automatically selected baseline before relying on an evaluation. Excluding Git
metadata does not remove secrets, reference implementations, or target-derived
knowledge from source files. Future execution adapters must place untrusted
agents behind a real isolation boundary and protect evaluator-owned records.

## Storage layout

```text
run/
  state.json
  inputs/
    case.json
  resolution/              # When preparing from a repository
    result.json
    documents/
    agent/
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
and richer evaluation data models are future work.

Generation and evaluation records extend this layout; they do not overwrite the
seal. `generate`, `seal`, and `evaluate` acquire an exclusive local controller
lock. A crash can leave `.controller.lock` behind; inspect its PID and ensure all
associated processes have stopped before manually removing it. Automatic crash
recovery and distributed locking are not implemented.
