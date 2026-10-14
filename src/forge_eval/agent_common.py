"""Small shared helpers for local CLI adapters."""

import json
import subprocess


def build_prompt(case):
    return (
        "Implement the task in the current project workspace. Inspect the baseline, "
        "make the required code changes, and run relevant local checks. "
        "Do not modify controller records or inspect sibling evaluation directories. "
        "Finish with a concise summary of changes and checks.\n\n"
        "Public task specification:\n" + json.dumps(case, ensure_ascii=False, indent=2) + "\n"
    )


def probe_version(launcher):
    try:
        probe = subprocess.run([*launcher, "--version"], capture_output=True, text=True, timeout=5)
        if probe.returncode == 0:
            return probe.stdout.strip() or None
    except (OSError, subprocess.TimeoutExpired):
        pass
    return None
