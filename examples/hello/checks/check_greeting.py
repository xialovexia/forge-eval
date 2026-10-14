"""Trusted fixture: exit 0 means satisfied, 1 mismatch, 2 check failure."""

import importlib.util
import sys
from pathlib import Path


def main():
    spec = importlib.util.spec_from_file_location("candidate_greeting", Path.cwd() / "greeting.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if sys.argv[1] == "greeting":
        assert module.greet("Ada") == "Hello, Ada!"
        assert module.greet("World") == "Hello, World!"
    elif sys.argv[1] == "empty":
        for name in ("", " ", "\t\n"):
            try:
                module.greet(name)
            except ValueError:
                continue
            raise AssertionError("Expected ValueError for a blank name")
    else:
        raise RuntimeError("Unknown check selector")


if __name__ == "__main__":
    try:
        main()
    except (AssertionError, NotImplementedError) as exc:
        print("Contract mismatch:", exc, file=sys.stderr)
        sys.exit(1)
    except Exception as exc:
        print("Check could not complete:", repr(exc), file=sys.stderr)
        sys.exit(2)
