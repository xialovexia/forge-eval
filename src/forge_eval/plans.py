"""Read experimental check plans without enforcing a format contract."""
from pathlib import Path

from .core import read_json


def as_list(value):
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def feature_list(value):
    return [item.strip() if isinstance(item, str) else item for item in as_list(value)]


def load_plan(root):
    value = read_json(Path(root) / "plan.json")
    if isinstance(value, dict):
        items = value.get("checks", [value] if "argv" in value or "command" in value else [])
        plan = dict(value)
    else:
        items = value
        plan = {}
    checks = []
    for index, item in enumerate(as_list(items), 1):
        check = dict(item) if isinstance(item, dict) else {"argv": item}
        check["check_id"] = str(check.get("check_id", "check-%s" % index))
        check["features"] = feature_list(check.get("features"))
        checks.append(check)
    return {**plan, "checks": checks}
