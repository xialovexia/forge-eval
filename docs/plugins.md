# Agent plugins: Claude Code and Codex

ForgeEval evaluates the code-generation capabilities of coding agents on existing
codebases. It works as a standalone Python CLI and as a shared plugin for Claude
Code and Codex. Both hosts load the same `skills/forge-eval/` workflow and bundled
`src/forge_eval/` runtime. No global Python installation or MCP server is needed.
Python 3.9+ on macOS/Linux is still required. Git and an authenticated agent CLI
are needed only for the operations that use them.

## Build an installable package

From a source checkout:

```sh
python3 scripts/build_plugin.py --output dist/forge-eval
```

The output directory is a complete, relocatable plugin and local marketplace.
The builder copies runtime code, skills, documentation, and the hello example.
It excludes local runs, Git history, virtual environments, tests, bytecode,
and other checkout files. It refuses to overwrite an existing destination;
choose another output path for a new build. Install from this clean directory
when the source checkout contains experiments or other local data.

The plugin package is separate from the Python wheel: `pip install forge-eval`
does not register skills in an agent host. Source development with Claude Code
can also load the checkout directly using `claude --plugin-dir /path/to/forge-eval`.

## Claude Code

Load the built plugin for one session, from the project you want to work on:

```sh
claude --plugin-dir /absolute/path/to/dist/forge-eval
```

Then invoke the shared skill:

```text
/forge-eval:forge-eval Run the bundled offline smoke test in this project.
```

For a persistent local install:

```sh
claude plugin marketplace add /absolute/path/to/dist/forge-eval
claude plugin install forge-eval@forge-eval-local
```

Start a new session after installation. Validate the manifest and marketplace
separately, because validating the package root selects its marketplace:

```sh
claude plugin validate /absolute/path/to/dist/forge-eval/.claude-plugin/plugin.json --strict
claude plugin validate /absolute/path/to/dist/forge-eval --strict
```

After these changes are published to the repository, Git-based installation can
use `/plugin install forge-eval --marketplace xialovexia/forge-eval`. Until then,
use the local package so you test the modified code rather than the remote version.

## Codex

Register the **same built directory**, then install the plugin:

```sh
codex plugin marketplace add /absolute/path/to/dist/forge-eval
codex plugin add forge-eval@forge-eval-local
```

The generated `.agents/plugins/marketplace.json` provides native Codex catalog
metadata. The portable root `plugin.json` describes the package; the
`.codex-plugin/plugin.json` overlay supplies its display metadata and supports
hosts that use the compatibility layout. Both use the shared skill directory.

In the desktop app, refresh/restart if needed, open Plugins, select the
`forge-eval-local` marketplace, and install/enable ForgeEval. Use a new chat for
testing. Select the ForgeEval skill in the host's picker, or request:

```text
Use ForgeEval to run its bundled offline smoke test in this project.
```

This is a local plugin integration. It has not been submitted to either public
plugin directory. Installing it in one host does not automatically install it in
the other; sharing the package avoids maintaining two implementations.

## Host versus evaluated agent

| Role | Responsibility |
| --- | --- |
| Plugin host (Claude Code or Codex) | Read the skill, gather task inputs, invoke the CLI, explain evidence |
| Configured evaluation backend | Resolve historical baselines and implement the frozen task in separate CLI invocations |
| Python core | Freeze inputs, control execution, seal code, verify integrity, run acceptance checks |

Backend selection stays in `agent.json`; it is not inferred from the plugin
host. The existing `claude-code`, `opencode`, `deepseek-harness`, and custom
command backends remain available. This change does not add a `codex` generation
backend or an MCP transport.

Claude Code may refuse to launch another Claude Code session from its own
session. `doctor` exposes the `CLAUDECODE` nesting marker, and the skill does not
unset it. To evaluate the Claude Code backend, launch ForgeEval from an ordinary
terminal or another host. Do not silently replace a requested backend.

If the user instead wants to evaluate work done by the current host, the skill
can use the existing manual lifecycle: `prepare --baseline ...` without an agent
configuration, implement only in the prepared `workspace/`, then seal and
evaluate. This also works with Codex as the implementing host. It does not create
an isolated generation invocation or record model/usage evidence. Historical
baseline resolution still requires a configured external backend.

## Runtime and evidence paths

The skill resolves its helper relative to its own installed location:

```sh
python3 /absolute/plugin/skills/forge-eval/scripts/forge_eval.py doctor
python3 /absolute/plugin/skills/forge-eval/scripts/forge_eval.py inspect --run /path/to/run
```

The helper imports the bundled core using its own path. It does not change the
working directory, depend on `CLAUDE_PLUGIN_ROOT`/`CODEX_HOME`, install packages,
or write Python bytecode into the plugin. Paths supplied to CLI commands remain
relative to the user's working directory. Keep runs outside the installed plugin
and outside the baseline directory.

`doctor` is read-only and reports Python, platform, Git, and backend executable
availability. It does not check account authentication or call models. `inspect`
is read-only and reports lifecycle state, controller lock, generation evidence,
all evaluation attempts, report paths, and current integrity. It does not rerun
checks, select a latest attempt by UUID, or treat an old PASS as current integrity.
It can observe a run in progress, so its fields are not an atomic snapshot.

The existing `--trusted-local` execution contract and exit codes still apply.
Inspection succeeds with exit 0 when evidence was read, even if its `integrity`
is `UNVERIFIED`; use `verify` for an integrity gate with a nonzero exit code.

## Extension boundaries

```text
Claude manifest ─┐
                ├─ shared Skill → bundled launcher → Python CLI/core
Codex manifest ─┘                                      ├─ agent backends
                                                      └─ independent checks
```

Add a new host by supplying its discovery/manifest layer and reusing the skill
and launcher. Add a new evaluated agent in the backend adapter layer. If a host
needs structured tool calls instead of shell access, a future MCP adapter can
call the existing core functions; the first plugin version uses host shell tools.
There are no automatic hooks or host-wide instruction edits.

## Validation and compatibility

Offline tests copy the actual package to a cache path with spaces, run from an
unrelated project directory without `PYTHONPATH`, and execute preparation,
generation, sealing, verification, and evaluation. They also cover host-session
candidates, integrity failures, interrupted attempts, exit codes, and unchanged
package contents. Existing engine tests continue to exercise backend protocols.

Run the full suite from the source checkout:

```sh
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

Manifest validation and offline tests do not establish live model behavior.
Use the bundled smoke test after enabling the plugin in each host. Local shell
access is required; installing this package in a web-only environment does not
deploy its Python runtime there.

On 2026-10-15, Claude Code 2.1.299 passed strict plugin/marketplace validation
and reported the `forge-eval` skill with `--plugin-dir ... plugin details
forge-eval`. Codex CLI 0.160.1 listed the built package as an available local
plugin using temporary command-line marketplace configuration. This checked
discovery without changing the user's installed plugins or calling a model.

The packaging follows the official [Claude Code manifest reference](https://code.claude.com/docs/en/plugins-reference),
[Claude marketplace guide](https://code.claude.com/docs/en/plugin-marketplaces),
and [OpenAI plugin packaging guide](https://developers.openai.com/plugins/build/plugins).
The shared Skill layout also follows OpenAI's [Claude plugin migration guidance](https://developers.openai.com/plugins/guides/submit-claude-plugin).
