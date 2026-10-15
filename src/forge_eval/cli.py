"""Small JSON-output CLI; command success is not a functional evaluation pass."""

import argparse
import json
import sys

from . import __version__
from .core import prepare, seal, verify
from .evaluation import evaluate
from .generation import generate
from .inspection import doctor, inspect_run


def main(argv=None):
    parser = argparse.ArgumentParser(prog="forge-eval")
    parser.add_argument("--version", action="version", version=__version__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("doctor", help="Inspect local prerequisites without invoking agents")
    inspection = commands.add_parser("inspect", help="Read run evidence and verify integrity without executing checks")
    inspection.add_argument("--run", required=True)
    preparation = commands.add_parser(
        "prepare", aliases=["resolve-baseline"],
        help="Resolve a baseline from change documents or copy a baseline into a new run",
        description="Prepare a run directly from a repository and change documents using an agent, "
                    "or from an existing baseline directory. resolve-baseline is the same preparation flow.",
    )
    preparation.add_argument("--case", help="Optional public case JSON; documents supply the task when omitted")
    preparation.add_argument("--document", action="append", help="Change document (UTF-8 text/Markdown); may be repeated")
    source = preparation.add_mutually_exclusive_group(required=True)
    source.add_argument("--repo", help="Local Git repository whose history the agent will analyze")
    source.add_argument("--baseline", help="Already prepared baseline directory")
    preparation.add_argument("--run", required=True)
    preparation.add_argument("--checks", help="Public check bundle directory, frozen before generation")
    preparation.add_argument("--agent-config", help="Command-agent JSON configuration")
    preparation.add_argument("--trusted-local", action="store_true", help="Allow baseline analysis with host access")
    for name in ("seal", "verify"):
        commands.add_parser(name).add_argument("--run", required=True)
    for name in ("generate", "evaluate"):
        command = commands.add_parser(name)
        command.add_argument("--run", required=True)
        command.add_argument("--trusted-local", action="store_true", help="Allow commands to run with host access (no sandbox)")
    args = parser.parse_args(argv)
    try:
        if args.command in ("prepare", "resolve-baseline"):
            result = prepare(args.case, args.baseline, args.run, args.checks, args.agent_config,
                             repo=args.repo, documents=args.document, trusted_local=args.trusted_local)
        elif args.command == "seal":
            result = seal(args.run)
        elif args.command == "generate":
            result = generate(args.run, args.trusted_local)
        elif args.command == "evaluate":
            result = evaluate(args.run, args.trusted_local)
        elif args.command == "verify":
            result = verify(args.run)
        elif args.command == "inspect":
            result = inspect_run(args.run)
        else:
            result = doctor()
    except (ValueError, OSError) as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    if args.command == "evaluate" and result["status"] != "PASS":
        return 3
    if args.command == "generate" and result["status"] != "GENERATED":
        return 3
    return 0
