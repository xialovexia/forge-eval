"""Small JSON-output CLI; command success is not a functional evaluation pass."""

import argparse
import json
import sys

from . import __version__
from .core import HarnessError, prepare, read_json, seal, validate_case, verify
from .evaluation import evaluate
from .generation import generate


def main(argv=None):
    parser = argparse.ArgumentParser(prog="forge-eval")
    parser.add_argument("--version", action="version", version=__version__)
    commands = parser.add_subparsers(dest="command", required=True)
    validate = commands.add_parser("validate-case", help="Validate a public contract case")
    validate.add_argument("case")
    preparation = commands.add_parser("prepare", help="Copy a baseline into a new local run (not a sandbox)")
    preparation.add_argument("--case", required=True)
    preparation.add_argument("--baseline", required=True)
    preparation.add_argument("--run", required=True)
    preparation.add_argument("--checks", help="Public check bundle directory, frozen before generation")
    preparation.add_argument("--agent-config", help="Command-agent JSON configuration")
    for name in ("seal", "verify"):
        commands.add_parser(name).add_argument("--run", required=True)
    for name in ("generate", "evaluate"):
        command = commands.add_parser(name)
        command.add_argument("--run", required=True)
        command.add_argument("--trusted-local", action="store_true", help="Allow commands to run with host access (no sandbox)")
    args = parser.parse_args(argv)
    try:
        if args.command == "validate-case":
            case = validate_case(read_json(args.case))
            result = {"case_id": case["case_id"], "valid": True}
        elif args.command == "prepare":
            result = prepare(args.case, args.baseline, args.run, args.checks, args.agent_config)
        elif args.command == "seal":
            result = seal(args.run)
        elif args.command == "generate":
            result = generate(args.run, args.trusted_local)
        elif args.command == "evaluate":
            result = evaluate(args.run, args.trusted_local)
        else:
            result = verify(args.run)
    except (HarnessError, OSError) as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    if args.command == "evaluate" and result["status"] != "PASS":
        return 3
    if args.command == "generate" and result["status"] != "GENERATED":
        return 3
    return 0
