"""Frozen public check bundles and command-agent configuration."""

import re
from pathlib import Path

from .core import HarnessError, inventory, read_json
from .execution import validate_command


def validate_plan(root, features):
    root = Path(root)
    inventory(root)
    plan = read_json(root / "plan.json")
    if not isinstance(plan, dict) or set(plan) != {"schema_version", "checks"} or plan["schema_version"] != "1.0":
        raise HarnessError("Check plan requires schema_version 1.0 and checks")
    if not isinstance(plan["checks"], list):
        raise HarnessError("checks must be an array")
    seen = set()
    for check in plan["checks"]:
        validate_command(check, ("check_id", "features"))
        identifier = check["check_id"]
        if not isinstance(identifier, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}", identifier):
            raise HarnessError("Invalid check_id")
        if identifier in seen:
            raise HarnessError("Duplicate check_id")
        seen.add(identifier)
        mapped = check["features"]
        if not isinstance(mapped, list) or not mapped or any(not isinstance(f, str) or f not in features for f in mapped):
            raise HarnessError("Each check must reference known required feature descriptions")
        if len(set(mapped)) != len(mapped):
            raise HarnessError("Duplicate feature mapping")
    return plan


def validate_agent(value):
    return validate_command(value)
