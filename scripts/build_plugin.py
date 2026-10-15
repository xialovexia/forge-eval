#!/usr/bin/env python3
"""Build a relocatable plugin directory without checkout data or run evidence."""

import argparse
import json
import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FILES = (
    "plugin.json", ".claude-plugin/plugin.json", ".claude-plugin/marketplace.json",
    ".codex-plugin/plugin.json", "README.md", "pyproject.toml",
)
DIRECTORIES = ("src/forge_eval", "skills", "docs", "examples/hello")


def build(output, source=ROOT):
    source = Path(source).resolve()
    output = Path(output).absolute()
    if output.exists() or output.is_symlink():
        raise ValueError("Output already exists; choose a new directory")
    paths = [source / name for name in FILES]
    for name in DIRECTORIES:
        directory = source / name
        if directory.is_symlink() or not directory.is_dir():
            raise ValueError("Expected a real package directory: %s" % directory)
        paths.extend(directory.rglob("*"))
    selected = []
    for path in sorted(paths):
        relative = path.relative_to(source)
        if "__pycache__" in relative.parts or path.suffix == ".pyc":
            continue
        if path.is_symlink():
            raise ValueError("Package links are unsupported: %s" % relative)
        if path.is_dir():
            continue
        if not path.is_file():
            raise ValueError("Missing or non-regular package file: %s" % relative)
        selected.append((path, relative))
    for name in DIRECTORIES:
        directory = (source / name).resolve()
        if output.resolve() == directory or directory in output.resolve().parents:
            raise ValueError("Output must be outside package source directories")
    output.mkdir(parents=True)
    for path, relative in selected:
        target = output / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
    # Codex has its own catalog metadata. Both catalogs load the identical root
    # package; there is no generated fork of the core or skill instructions.
    marketplace = output / ".agents/plugins/marketplace.json"
    marketplace.parent.mkdir(parents=True)
    marketplace.write_text(json.dumps({
        "name": "forge-eval-local",
        "interface": {"displayName": "ForgeEval"},
        "plugins": [{
            "name": "forge-eval", "source": {"source": "local", "path": "./"},
            "policy": {"installation": "AVAILABLE", "authentication": "ON_USE"},
            "category": "Developer Tools",
        }],
    }, indent=2) + "\n", encoding="utf-8")
    return output


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="dist/forge-eval", help="New plugin directory (never overwritten)")
    args = parser.parse_args(argv)
    try:
        output = build(args.output)
    except (ValueError, OSError) as exc:
        parser.exit(1, str(exc) + "\n")
    print(json.dumps({"plugin_path": str(output)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
