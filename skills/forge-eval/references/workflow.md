# CLI workflow

In these examples, `FE` is the absolute path to this skill's
`scripts/forge_eval.py`, `PLUGIN` is the installed plugin root, and all other
paths belong to the user's task directory. Resolve these before execution.
The launcher keeps the current working directory; it never stores runs in its
own package. All CLI commands return JSON. Exit 1 is an input/execution error;
exit 3 from `generate` or `evaluate` is a recorded unsuccessful outcome.

## Historical change documents

```sh
python3 "$FE" resolve-baseline --repo /path/to/project \
  --document /path/to/requirement.md --case /path/to/case.json \
  --checks /path/to/checks --agent-config /path/to/agent.json \
  --run .forge-eval/runs/change-001 --trusted-local
python3 "$FE" generate --run .forge-eval/runs/change-001 --trusted-local
```

`--document` can be repeated. `--case` and `--checks` are optional, but documents
alone do not create feature declarations or acceptance checks. A local Git
repository and a configured external backend are required for history analysis.
Preparation and generation use separate invocations with the same configuration.
For backend options, read `docs/agent-backends.md` under the plugin root.

## Prepared baseline or host-session candidate

```sh
python3 "$FE" prepare --baseline /path/to/baseline \
  --case /path/to/case.json --checks /path/to/checks \
  --agent-config /path/to/agent.json --run .forge-eval/runs/change-001
```

For a configured backend, call `generate` next. For an explicitly requested
host-session candidate, omit `--agent-config`, then implement the task directly
in `.forge-eval/runs/change-001/workspace/`. Neither mode changes the baseline.
Keep the run outside the baseline directory. The host-session mode does not
automatically select a historical Git baseline.

A minimal case:

```json
{
  "case_id": "greeting",
  "requirement": "Implement greet(name); reject blank names.",
  "required_features": ["Returns a greeting", "Rejects blank names"]
}
```

The check bundle contains `plan.json` and any check scripts. A plan entry uses
`argv`, `timeout_seconds`, and feature descriptions matching the case:

```json
{
  "checks": [
    {
      "check_id": "greeting",
      "argv": ["{python}", "{checks}/check_greeting.py", "{candidate}"],
      "timeout_seconds": 10,
      "features": ["Returns a greeting", "Rejects blank names"]
    }
  ]
}
```

Check exit 0 means pass, 1 means functional mismatch, and other codes mean error.
Use the bundled `examples/hello/checks/` for a complete executable example.
Freeze checks before generation; changed inputs prevent sealing.

## Seal, evaluate, inspect

Only continue after successful generation, or completed host-session work in a
PREPARED run. Never seal a failed or running generation.

```sh
python3 "$FE" seal --run .forge-eval/runs/change-001
python3 "$FE" verify --run .forge-eval/runs/change-001
python3 "$FE" evaluate --run .forge-eval/runs/change-001 --trusted-local
python3 "$FE" inspect --run .forge-eval/runs/change-001
```

Every evaluation creates new evidence. Re-evaluate only when requested or useful
for a specific investigation; do not loop until tests pass. Inspect JSON output
even when the CLI exits nonzero. Reports are under `evaluations/<id>/report.md`.

## Offline smoke test

For a user-requested installation check, use the bundled deterministic fixture.
It writes a known candidate and runs acceptance checks without model calls:

```sh
python3 "$FE" prepare --baseline "$PLUGIN/examples/hello/baseline" \
  --case "$PLUGIN/examples/hello/case.json" \
  --checks "$PLUGIN/examples/hello/checks" \
  --agent-config "$PLUGIN/examples/hello/fixture-agent.json" \
  --run .forge-eval/runs/plugin-smoke-001
python3 "$FE" generate --run .forge-eval/runs/plugin-smoke-001 --trusted-local
python3 "$FE" seal --run .forge-eval/runs/plugin-smoke-001
python3 "$FE" verify --run .forge-eval/runs/plugin-smoke-001
python3 "$FE" evaluate --run .forge-eval/runs/plugin-smoke-001 --trusted-local
```

Expected generation is `GENERATED`, integrity is `VERIFIED`, and evaluation is
`PASS`. This validates the plugin runtime, not model capability or authentication.
