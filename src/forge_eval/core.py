"""Local, operator-controlled workspace preparation and artifact sealing.

These helpers are not a security sandbox. They never execute candidate code.
Digests establish consistency with a trusted seal, not authenticity of the seal.
"""

import hashlib
import json
import os
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
    """Deserialize a record without checking its schema or metadata."""
    return json.loads(Path(path).read_text(encoding="utf-8"))


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


def _walk_files(root, exclude_git=False):
    """Enumerate regular files without reading their contents."""
    root = Path(root)
    if root.is_symlink() or not root.is_dir():
        raise HarnessError("Expected a real directory: %s" % root)

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
            yield path, mode


def inventory(root, exclude_git=False):
    """Hash regular files, preserving executable modes; reject links/special files."""
    root = Path(root)
    result = {}
    for path, mode in _walk_files(root, exclude_git):
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
    case = read_json(case_path)
    case_id = case.get("case_id", Path(case_path).stem) if isinstance(case, dict) else Path(case_path).stem
    if checks_path is not None:
        checks_path = Path(checks_path).absolute()
        check_files = inventory(checks_path)
    baseline = Path(baseline).absolute()
    run = Path(run_path).absolute()
    if run.exists() or run.is_symlink():
        raise HarnessError("Run directory already exists; use a new run path")
    if baseline.resolve() in (run.resolve(), *run.resolve().parents):
        raise HarnessError("Run directory must be outside the baseline")
    if checks_path is not None and checks_path.resolve() in (run.resolve(), *run.resolve().parents):
        raise HarnessError("Run directory must be outside the check bundle")
    source_files = sorted(path.relative_to(baseline).as_posix() for path, _ in _walk_files(baseline, exclude_git=True))
    run.mkdir(parents=True)
    write_json(run / "state.json", {"schema_version": "1.0", "status": "PREPARING"})
    try:
        inputs = run / "inputs"
        inputs.mkdir()
        write_json(inputs / "case.json", case)
        if checks_path is not None:
            copy_files(checks_path, inputs / "checks", check_files)
            if inventory(inputs / "checks") != check_files or inventory(checks_path) != check_files:
                raise HarnessError("Check bundle changed during preparation")
        if agent_path is not None:
            shutil.copy2(agent_path, inputs / "agent.json")
        copy_files(baseline, run / "workspace", source_files)
        state = {
            "schema_version": "1.0", "status": "PREPARED", "case_id": case_id,
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
    if state.get("status") not in ("PREPARED", "GENERATED"):
        raise HarnessError("Only a PREPARED or GENERATED run can be sealed")
    if inventory(run / "inputs") != state.get("inputs"):
        raise HarnessError("Frozen inputs have changed")
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
            "schema_version": "1.0", "kind": "seal", "case_id": state.get("case_id"),
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
    if inventory(run / "inputs") != record.get("inputs"):
        raise HarnessError("Sealed inputs do not match their recorded digests")
    if inventory(run / "artifacts" / "candidate") != record.get("candidate"):
        raise HarnessError("Sealed candidate does not match its recorded digests")
    return {"case_id": record.get("case_id"), "integrity": "VERIFIED", "evaluation_status": "NOT_EVALUATED"}
