#!/usr/bin/env python3
"""Run the bundled core from any host's plugin cache without installation."""

import sys
from pathlib import Path


def main():
    if sys.version_info < (3, 9):
        print("ForgeEval requires Python 3.9 or newer", file=sys.stderr)
        return 1
    root = Path(__file__).resolve().parents[3]
    if not (root / "src/forge_eval/cli.py").is_file():
        print("Incomplete ForgeEval plugin: bundled src/forge_eval is missing", file=sys.stderr)
        return 1
    # Plugin caches can be read-only. Keep paths relative to the user's cwd,
    # and prefer this plugin's core over an unrelated installed version.
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(root / "src"))
    from forge_eval.cli import main as cli_main
    return cli_main()


if __name__ == "__main__":
    raise SystemExit(main())
