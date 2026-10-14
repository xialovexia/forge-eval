"""Command backend for trusted local code, not an isolation boundary."""

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

from .core import HarnessError


def expand_argv(argv, replacements):
    def expand(arg):
        arg = str(arg)
        for token, value in replacements.items():
            arg = arg.replace(token, str(value))
        return arg

    if isinstance(argv, str):
        return expand(argv)
    return [expand(arg) for arg in argv]


def execute(command, cwd, evidence, replacements=None):
    """Run an argument array or shell command and capture execution evidence.

    The caller must obtain explicit trusted-local opt-in. Environment variables
    are inherited; this backend is not suitable for untrusted candidate code.
    """
    if os.name != "posix":
        raise HarnessError("The local command backend currently requires POSIX")
    evidence = Path(evidence)
    evidence.mkdir()
    replacements = {"{python}": sys.executable, **(replacements or {})}
    started = time.monotonic()
    spec = command if isinstance(command, dict) else {"argv": command}
    outcome = {"argv": spec.get("argv", spec.get("command")), "exit_code": None, "timed_out": False, "error": None}
    process = None
    with (evidence / "stdout.log").open("wb") as stdout, (evidence / "stderr.log").open("wb") as stderr:
        try:
            argv = expand_argv(outcome["argv"], replacements)
            timeout = spec.get("timeout_seconds")
            timeout = float(timeout) if timeout is not None else None
            outcome.update(argv=argv, shell=isinstance(argv, str))
            process = subprocess.Popen(argv, shell=outcome["shell"], cwd=cwd, stdout=stdout, stderr=stderr, start_new_session=True)
            try:
                outcome["exit_code"] = process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                outcome["timed_out"] = True
        except (OSError, TypeError, ValueError, OverflowError) as exc:
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
