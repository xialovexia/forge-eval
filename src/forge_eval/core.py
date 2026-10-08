"""Local, operator-controlled workspace preparation and artifact sealing.

These helpers are not a security sandbox. They never execute candidate code.
Digests establish consistency with a trusted seal, not authenticity of the seal.
"""

import hashlib
import json
import os
import re
import shutil
import stat
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path


class HarnessError(ValueError):
    """Invalid input or an inconsistent run."""


@contextmanager
def run_lock(run):
    """Single local controller; a crash leaves a lock for operator inspection."""
    path = Path(run) / ".controller.lock"
    try:
        stream = path.open("x", encoding="utf-8")
    except FileExistsError as exc:
        raise HarnessError("Run is locked; do not remove its lock until the controller has stopped") from exc
    try:
        with stream:
            json.dump({"pid": os.getpid(), "created_at": now()}, stream)
        yield
    finally:
        path.unlink()


def read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise HarnessError("Cannot read JSON from %s: %s" % (path, exc)) from exc


def write_json(path, data):
    """Atomically publish a complete JSON document."""
    path = Path(path)
    fd, name = tempfile.mkstemp(prefix=".forge-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(data, stream, indent=2, sort_keys=True, ensure_ascii=False)
            stream.write("\n")
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def now():
    return datetime.now(timezone.utc).isoformat()


def validate_case(value):
    required = {"schema_version", "case_id", "mode", "requirement", "required_features"}
    if not isinstance(value, dict) or set(value) != required:
        raise HarnessError("Case must contain exactly: %s" % ", ".join(sorted(required)))
    if value["schema_version"] != "1.0":
        raise HarnessError("Unsupported case schema_version")
    if not isinstance(value["case_id"], str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}", value["case_id"]):
        raise HarnessError("case_id must be a portable identifier (1-80 characters)")
    if value["mode"] != "contract":
        raise HarnessError("Only contract mode is supported by this foundation release")
    if not isinstance(value["requirement"], str) or not value["requirement"].strip():
        raise HarnessError("requirement must be non-empty text")
    features = value["required_features"]
    if not isinstance(features, list) or not features:
        raise HarnessError("required_features must be a non-empty list")
    if any(not isinstance(item, str) or not item.strip() for item in features):
        raise HarnessError("Each required feature must be non-empty text")
    if len(set(features)) != len(features):
        raise HarnessError("required_features contains duplicates")
    return value


def inventory(root, exclude_git=False):
    """Hash regular files, preserving executable modes; reject links/special files."""
    root = Path(root)
    if root.is_symlink() or not root.is_dir():
        raise HarnessError("Expected a real directory: %s" % root)
    result = {}
    def fail_walk(error):
        raise error

    for directory, dirs, files in os.walk(root, followlinks=False, onerror=fail_walk):
        for name in sorted(dirs + files):
            path = Path(directory) / name
            if exclude_git and name == ".git":
                if name in dirs:
                    dirs.remove(name)
                continue
            mode = path.lstat().st_mode
            if stat.S_ISDIR(mode):
                continue
            if not stat.S_ISREG(mode):
                raise HarnessError("Symlinks and special files are not allowed: %s" % path)
            result[path.relative_to(root).as_posix()] = {
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "size": path.stat().st_size,
                "mode": stat.S_IMODE(mode),
            }
    return dict(sorted(result.items()))


def copy_files(source, destination, files):
    destination.mkdir()
    for relative in files:
        output = destination / relative
        output.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source / relative, output)


def prepare(case_path, baseline, run_path, checks_path=None, agent_path=None):
    from .plans import validate_agent, validate_plan

    case = validate_case(read_json(case_path))
    if checks_path is not None:
        checks_path = Path(checks_path).absolute()
        validate_plan(checks_path, case["required_features"])
        check_files = inventory(checks_path)
    agent = validate_agent(read_json(agent_path)) if agent_path is not None else None
    baseline = Path(baseline).absolute()
    run = Path(run_path).absolute()
    if run.exists() or run.is_symlink():
        raise HarnessError("Run directory already exists; use a new run path")
    if baseline.resolve() in (run.resolve(), *run.resolve().parents):
        raise HarnessError("Run directory must be outside the baseline")
    if checks_path is not None and checks_path.resolve() in (run.resolve(), *run.resolve().parents):
        raise HarnessError("Run directory must be outside the check bundle")
    source_files = inventory(baseline, exclude_git=True)
    run.mkdir(parents=True)
    write_json(run / "state.json", {"schema_version": "1.0", "status": "PREPARING"})
    try:
        inputs = run / "inputs"
        inputs.mkdir()
        write_json(inputs / "case.json", case)
        write_json(inputs / "baseline-manifest.json", source_files)
        if checks_path is not None:
            copy_files(checks_path, inputs / "checks", check_files)
            if inventory(inputs / "checks") != check_files or inventory(checks_path) != check_files:
                raise HarnessError("Check bundle changed during preparation")
        if agent is not None:
            write_json(inputs / "agent.json", agent)
        copy_files(baseline, run / "workspace", source_files)
        if inventory(run / "workspace") != source_files or inventory(baseline, exclude_git=True) != source_files:
            raise HarnessError("Baseline changed while preparing the workspace")
        state = {
            "schema_version": "1.0", "status": "PREPARED", "case_id": case["case_id"],
            "created_at": now(), "isolation": "local-copy-not-sandboxed",
            "inputs": inventory(inputs),
        }
        write_json(run / "state.json", state)
        return state
    except Exception as exc:
        write_json(run / "state.json", {"schema_version": "1.0", "status": "ERROR", "error": str(exc)})
        raise


def seal(run_path):
    with run_lock(run_path):
        return _seal(run_path)


def _seal(run_path):
    run = Path(run_path)
    state = read_json(run / "state.json")
    if not isinstance(state, dict) or state.get("schema_version") != "1.0" or state.get("status") not in ("PREPARED", "GENERATED"):
        raise HarnessError("Only a PREPARED or GENERATED run can be sealed")
    if inventory(run / "inputs") != state.get("inputs"):
        raise HarnessError("Frozen inputs have changed")
    case = validate_case(read_json(run / "inputs/case.json"))
    if state.get("case_id") != case["case_id"]:
        raise HarnessError("Run and case identities do not match")
    files = inventory(run / "workspace")
    artifacts = run / "artifacts"
    if artifacts.exists() or artifacts.is_symlink() or (run / "seal.json").exists():
        raise HarnessError("Seal or artifacts already exist; use a new run")
    artifacts.mkdir()
    try:
        copy_files(run / "workspace", artifacts / "candidate", files)
        if inventory(artifacts / "candidate") != files or inventory(run / "workspace") != files:
            raise HarnessError("Workspace changed while sealing; stop all writers first")
        if inventory(run / "inputs") != state["inputs"]:
            raise HarnessError("Frozen inputs changed while sealing")
        record = {
            "schema_version": "1.0", "kind": "seal", "case_id": state["case_id"],
            "sealed_at": now(), "inputs": state["inputs"], "candidate": files,
            "evaluation_status": "NOT_EVALUATED",
        }
        write_json(run / "seal.json", record)
        state["status"] = "SEALED"
        write_json(run / "state.json", state)
        return record
    except Exception as exc:
        state.update(status="ERROR", error=str(exc))
        write_json(run / "state.json", state)
        raise


def verify(run_path):
    run = Path(run_path)
    record = read_json(run / "seal.json")
    if not isinstance(record, dict) or record.get("schema_version") != "1.0" or record.get("kind") != "seal":
        raise HarnessError("Invalid seal format")
    if inventory(run / "inputs") != record.get("inputs"):
        raise HarnessError("Sealed inputs do not match their recorded digests")
    if inventory(run / "artifacts" / "candidate") != record.get("candidate"):
        raise HarnessError("Sealed candidate does not match its recorded digests")
    case = validate_case(read_json(run / "inputs/case.json"))
    if record.get("case_id") != case["case_id"] or record.get("evaluation_status") != "NOT_EVALUATED":
        raise HarnessError("Invalid seal identity or evaluation status")
    return {"case_id": record["case_id"], "integrity": "VERIFIED", "evaluation_status": "NOT_EVALUATED"}
