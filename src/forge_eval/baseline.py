"""Let an existing agent choose a historical baseline, then export its Git tree."""

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from .agents import completed, run_agent
from .core import HarnessError, now, read_json, write_json


def git(repo, *args):
    result = subprocess.run(["git", "-C", str(repo), *args], capture_output=True)
    if result.returncode:
        raise HarnessError(result.stderr.decode("utf-8", errors="replace").strip())
    return result.stdout


def commit_id(repo, ref):
    return git(repo, "rev-parse", "--verify", "--end-of-options", str(ref) + "^{commit}").decode().strip()


def resolution_prompt(case, documents, repository_head):
    return (
        "Resolve the baseline for a coding evaluation from the supplied change documents. "
        "You are in a disposable local clone with Git history. Its initial HEAD is "
        + repository_head + ". Inspect history, code and diffs using your own search strategy. "
        "Do not implement the task, edit project files, switch the source repository, "
        "or inspect sibling run directories.\n\n"
        "Find the historical change most closely implementing the documented behavior. "
        "A change can span several commits: choose the project state before the first "
        "necessary implementation, not merely the parent of the best keyword match. "
        "Use Git ancestry rather than timestamps. For a merge that introduces the whole "
        "change to the target branch, its first parent is usually the baseline; inspect "
        "the diff to decide. Account for partial implementations, follow-up fixes and "
        "unrelated changes. Do not choose HEAD as a fallback when no matching change exists.\n\n"
        "Finish with a JSON object (a Markdown code fence is fine). Return baseline_commit "
        "as a Git revision for the state before the change, with an explanation in reason. "
        "You may include change_commits, evidence, alternatives or any other useful fields. "
        "For a single change, you may instead return change_commit; ForgeEval will use its "
        "first parent. If the match is unresolved, return baseline_commit: null and explain "
        "why. No confidence score or fixed analysis steps are required.\n\n"
        "Public task specification:\n" + json.dumps(case, ensure_ascii=False, indent=2)
        + "\n\nChange documents:\n" + json.dumps(documents, ensure_ascii=False, indent=2) + "\n"
    )


def selection_from_text(message):
    """Accept a JSON object embedded in prose or fences, without a schema gate."""
    decoder = json.JSONDecoder()
    for index, character in enumerate(message):
        if character != "{":
            continue
        try:
            selection, _ = decoder.raw_decode(message[index:])
        except ValueError:
            continue
        if isinstance(selection, dict) and any(
            key in selection for key in ("baseline_commit", "change_commit")
        ):
            return selection
    raise HarnessError("Agent did not return a baseline_commit or change_commit; see resolution logs")


def export_tree(repo, commit, destination):
    """Stream tracked blobs once, without hashing or applying archive attributes."""
    entries = git(repo, "ls-tree", "-r", "-z", "--full-tree", commit).split(b"\0")
    destination.mkdir()
    links = {}
    with subprocess.Popen(
        ["git", "-C", str(repo), "cat-file", "--batch"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    ) as process:
        try:
            for entry in entries:
                if not entry:
                    continue
                metadata, name = entry.split(b"\t", 1)
                mode, _, oid = metadata.split()
                relative = Path(os.fsdecode(name))
                if relative.is_absolute() or ".." in relative.parts:
                    raise HarnessError("Git tree contains an unsafe path: %s" % relative)
                if ".git" in relative.parts:
                    continue
                if mode not in (b"100644", b"100755", b"120000"):
                    raise HarnessError("Baseline does not support submodules: %s" % relative)
                process.stdin.write(oid + b"\n")
                process.stdin.flush()
                header = process.stdout.readline().split()
                if len(header) != 3 or header[1] != b"blob":
                    raise HarnessError("Cannot read Git blob for %s" % relative)
                remaining = int(header[2])
                if mode == b"120000":
                    links[relative] = os.fsdecode(process.stdout.read(remaining))
                    process.stdout.read(1)
                    continue
                output = destination / relative
                output.parent.mkdir(parents=True, exist_ok=True)
                with output.open("wb") as stream:
                    while remaining:
                        chunk = process.stdout.read(min(remaining, 1024 * 1024))
                        if not chunk:
                            raise HarnessError("Incomplete Git blob for %s" % relative)
                        stream.write(chunk)
                        remaining -= len(chunk)
                process.stdout.read(1)  # Batch protocol's separator, not file content.
                output.chmod(int(mode, 8) & 0o777)
            process.stdin.close()
            if process.wait():
                raise HarnessError(process.stderr.read().decode("utf-8", errors="replace"))
        finally:
            if process.poll() is None:
                process.kill()
    materialize_links(destination, links)
    return {str(path): target for path, target in links.items()}


def materialize_links(root, links):
    """Copy in-tree link targets as ordinary files/directories for local runs."""
    root = root.resolve()
    done = set()

    def copy_link(relative, visiting):
        if relative in done:
            return
        if relative in visiting:
            raise HarnessError("Cyclic baseline symlink: %s" % relative)
        target_text = links[relative]
        target = (root / relative.parent / target_text).resolve()
        if Path(target_text).is_absolute() or root not in target.parents:
            raise HarnessError("Baseline symlink must target a path inside the Git tree: %s" % relative)
        target_relative = target.relative_to(root)
        for other in links:
            if other == target_relative or other in target_relative.parents or target_relative in other.parents:
                copy_link(other, visiting | {relative})
        output = root / relative
        output.parent.mkdir(parents=True, exist_ok=True)
        if target.is_dir():
            shutil.copytree(target, output)
        else:
            shutil.copy2(target, output)
        done.add(relative)

    for relative in links:
        copy_link(relative, set())


def resolve_baseline(repo, run, case, documents):
    """Prepare run/workspace directly; retain analysis separately from public inputs."""
    evidence = run / "resolution"
    evidence.mkdir()
    record = {"status": "RESOLVING", "repository": str(repo), "started_at": now()}
    try:
        document_dir = evidence / "documents"
        document_dir.mkdir()
        for index, document in enumerate(documents, 1):
            (document_dir / ("%04d-%s" % (index, document["name"]))).write_text(
                document["text"], encoding="utf-8",
            )
        repository_head = commit_id(repo, "HEAD")
        record["repository_head"] = repository_head
        config = read_json(run / "inputs/agent.json")
        if isinstance(config, dict) and config.get("backend") == "claude-code":
            config = {"allowed_tools": ["Read", "Glob", "Grep", "Bash"], **config}
        with tempfile.TemporaryDirectory(prefix="forge-resolve-") as temporary:
            clone = Path(temporary) / "repository"
            # Local object sharing avoids copying the entire object database. All
            # writable refs, index and working files belong to the temporary clone.
            git(repo, "clone", "--quiet", "--shared", "--no-checkout", "--", str(repo), str(clone))
            git(clone, "checkout", "--quiet", "--detach", repository_head)
            outcome, agent = run_agent(
                config, clone, evidence / "agent",
                resolution_prompt(case, documents, repository_head), {
                    "{workspace}": str(clone), "{repository}": str(clone),
                    "{case}": str(run / "inputs/case.json"),
                },
            )
            record.update(
                backend=agent["backend"] if agent else "trusted-local-command",
                execution=outcome,
                usage=agent["usage"] if agent else {"tokens": None, "cost": None},
            )
            if agent is not None:
                record["agent"] = agent
            if not completed(outcome, agent):
                raise HarnessError("Baseline analysis failed; see resolution/agent logs")
            message = agent["final_message"] if agent else (evidence / "agent/stdout.log").read_text(
                encoding="utf-8", errors="replace",
            )
            selection = selection_from_text(message or "")
            record["selection"] = selection
            ref = selection.get("baseline_commit")
            if "baseline_commit" not in selection and selection.get("change_commit"):
                ref = str(selection["change_commit"]) + "^1"
            if not ref:
                raise HarnessError("No baseline selected: " + str(selection.get("reason", "unresolved match")))
            baseline_commit = commit_id(clone, ref)
            record["baseline_commit"] = baseline_commit
            # Export from the source object database: ignore dirty files in either
            # checkout and never include commits manufactured by the analysis agent.
            record["materialized_symlinks"] = export_tree(repo, baseline_commit, run / "workspace")
        record.update(status="RESOLVED", finished_at=now())
        write_json(evidence / "result.json", record)
        return {"commit": baseline_commit, "repository_head": repository_head,
                "resolution": "resolution/result.json"}
    except Exception as exc:
        record.update(status="FAILED", finished_at=now(), error=str(exc))
        write_json(evidence / "result.json", record)
        raise
