"""Command backend for trusted local code, not an isolation boundary."""

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

from .core import HarnessError


def validate_command(value, extra_keys=()):
    if not isinstance(value, dict) or set(value) != {"argv", "timeout_seconds", *extra_keys}:
        raise HarnessError("Command fields must be argv, timeout_seconds, and declared metadata")
    argv = value["argv"]
    if not isinstance(argv, list) or not argv or any(not isinstance(a, str) or not a or "\x00" in a for a in argv):
        raise HarnessError("argv must be a non-empty array of non-empty strings")
    timeout = value["timeout_seconds"]
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not 0 < timeout <= 86400:
        raise HarnessError("timeout_seconds must be between 0 and 86400")
    return value


def expand_argv(argv, replacements):
    # Replace complete arguments or leading path tokens; never use a shell.
    expanded = []
    for arg in argv:
        if arg in replacements:
            expanded.append(replacements[arg])
            continue
        for token, value in replacements.items():
            if arg.startswith(token + "/"):
                arg = value + arg[len(token):]
                break
        expanded.append(arg)
    return expanded


def execute(command, cwd, evidence, replacements=None):
    """Run an argv list, capture logs, and terminate its POSIX process group.

    The caller must obtain explicit trusted-local opt-in. Environment variables
    are inherited; this backend is not suitable for untrusted candidate code.
    """
    if os.name != "posix":
        raise HarnessError("The local command backend currently requires POSIX")
    evidence = Path(evidence)
    evidence.mkdir()
    replacements = {"{python}": sys.executable, **(replacements or {})}
    argv = expand_argv(command["argv"], replacements)
    started = time.monotonic()
    outcome = {"argv": argv, "exit_code": None, "timed_out": False, "error": None}
    process = None
    with (evidence / "stdout.log").open("wb") as stdout, (evidence / "stderr.log").open("wb") as stderr:
        try:
            process = subprocess.Popen(argv, cwd=cwd, stdout=stdout, stderr=stderr, start_new_session=True)
            try:
                outcome["exit_code"] = process.wait(timeout=command["timeout_seconds"])
            except subprocess.TimeoutExpired:
                outcome["timed_out"] = True
        except OSError as exc:
            outcome["error"] = str(exc)
        finally:
            if process is not None:
                # Also stop descendants left behind by a parent that exited.
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait()
    outcome["duration_seconds"] = round(time.monotonic() - started, 6)
    outcome["stdout"] = "stdout.log"
    outcome["stderr"] = "stderr.log"
    return outcome
