"""Feature-level evaluation with append-only attempt directories."""

import hashlib
import platform
import tempfile
import uuid
from pathlib import Path

from . import __version__
from .core import HarnessError, copy_files, inventory, now, read_json, run_lock, verify, write_json
from .execution import execute
from .plans import feature_list, load_plan


def aggregate(statuses):
    if not statuses:
        return "UNVERIFIED"
    for status in ("FAIL", "ERROR", "UNVERIFIED"):
        if status in statuses:
            return status
    return "PASS"


def render_report(result):
    lines = ["# ForgeEval evaluation", "", "- Case: `%s`" % result["case_id"],
             "- Evaluation: `%s`" % result["evaluation_id"], "- Status: **%s**" % result["status"],
             "- Backend: trusted local commands (no sandbox)",
             "- Candidate integrity: %s" % result["integrity"],
             "- Seal SHA-256: `%s`" % result["seal_sha256"],
             "- Evaluator: ForgeEval %s / Python %s" % (result["evaluator_version"], result["python_version"]),
             "- Verification coverage: %.1f%%" % (100 * result["verification_coverage"]),
             "- Feature pass rate: %.1f%%" % (100 * result["feature_pass_rate"]), "", "## Features", ""]
    for feature in result["features"]:
        text = str(feature["requirement"]).replace("\n", " ")
        lines.append("- **%s** — %s (checks: %s)" % (feature["status"], text, ", ".join(feature["checks"]) or "none"))
    lines.extend(["", "## Evidence", ""])
    for check in result["checks"]:
        identifier = check["check_id"]
        evidence = check["evidence_path"]
        lines.append("- `%s`: **%s** — [stdout](%s/stdout.log), [stderr](%s/stderr.log)" % (identifier, check["status"], evidence, evidence))
    if result.get("error"):
        lines.extend(["", "Error: " + result["error"]])
    return "\n".join(lines) + "\n"


def evaluate(run_path, trusted_local=False):
    if not trusted_local:
        raise HarnessError("Local evaluation requires --trusted-local; candidate code inherits host access")
    with run_lock(run_path):
        return _evaluate(run_path)


def _evaluate(run_path):
    run = Path(run_path).resolve()
    verification = verify(run)
    seal_digest = hashlib.sha256((run / "seal.json").read_bytes()).hexdigest()
    case = read_json(run / "inputs/case.json")
    case = case if isinstance(case, dict) else {"requirement": case}
    required_features = feature_list(case.get("required_features"))
    bundle = run / "inputs/checks"
    plan = load_plan(bundle) if bundle.exists() else {"checks": []}
    identifier = uuid.uuid4().hex
    output = run / "evaluations" / identifier
    output.mkdir(parents=True)
    write_json(output / "state.json", {"status": "EVALUATING", "started_at": now()})
    (output / "checks").mkdir()
    checks = []
    error = None
    integrity = "VERIFIED"
    try:
        for index, check in enumerate(plan["checks"], 1):
            # Each check receives a clean candidate copy, so test order cannot
            # accidentally carry build output or data into the next check.
            with tempfile.TemporaryDirectory(prefix="forge-eval-check-") as temporary:
                root = Path(temporary)
                candidate = root / "candidate"
                copy_files(run / "artifacts/candidate", candidate, inventory(run / "artifacts/candidate"))
                copy_files(bundle, root / "checks", inventory(bundle))
                evidence_path = "checks/%04d" % index
                execution = execute(check, candidate, output / evidence_path, {
                    "{candidate}": str(candidate), "{checks}": str(root / "checks"),
                })
                if execution["error"] or execution["timed_out"] or execution["exit_code"] not in (0, 1):
                    status = "ERROR"
                else:
                    status = "PASS" if execution["exit_code"] == 0 else "FAIL"
                checks.append({"check_id": check["check_id"], "features": check["features"], "status": status, "execution": execution, "evidence_path": evidence_path})
                write_json(output / evidence_path / "result.json", checks[-1])
        verify(run)
        if hashlib.sha256((run / "seal.json").read_bytes()).hexdigest() != seal_digest:
            raise HarnessError("Seal changed during evaluation")
    except (HarnessError, OSError) as exc:
        error = str(exc)
        integrity = "UNVERIFIED"
    features = []
    for requirement in required_features:
        related = [c for c in checks if requirement in c["features"]]
        expected = [c for c in plan["checks"] if requirement in c["features"]]
        statuses = [c["status"] for c in related]
        if len(related) < len(expected):
            statuses.append("UNVERIFIED")
        features.append({"requirement": requirement, "status": "ERROR" if error else aggregate(statuses), "checks": [c["check_id"] for c in related]})
    result = {
        "schema_version": "1.0", "evaluation_id": identifier, "case_id": case.get("case_id", verification["case_id"]),
        "seal_sha256": seal_digest, "evaluator_version": __version__, "python_version": platform.python_version(),
        "status": "ERROR" if error else aggregate(([f["status"] for f in features] or ["UNVERIFIED"]) + [c["status"] for c in checks]),
        "integrity": integrity, "finished_at": now(), "backend": "trusted-local-command",
        "checks": checks, "features": features, "error": error,
        "verification_coverage": sum(f["status"] in ("PASS", "FAIL") for f in features) / len(features) if features else 0,
        "feature_pass_rate": sum(f["status"] == "PASS" for f in features) / len(features) if features else 0,
    }
    write_json(output / "result.json", result)
    (output / "report.md").write_text(render_report(result), encoding="utf-8")
    write_json(output / "state.json", {"status": "COMPLETED", "result": result["status"]})
    return {**result, "report_path": str(output / "report.md")}
