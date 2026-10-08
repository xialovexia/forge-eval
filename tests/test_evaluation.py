import json
import contextlib
import io
import shutil
import tempfile
import unittest
from pathlib import Path

from forge_eval.core import HarnessError, prepare, read_json, run_lock, seal, verify
from forge_eval.cli import main
from forge_eval.evaluation import evaluate
from forge_eval.generation import generate


class EvaluationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        source = Path(__file__).resolve().parents[1] / "examples/hello"
        self.example = self.root / "example"
        shutil.copytree(source, self.example)
        self.run = self.root / "run"

    def prepare(self, checks=True, agent=True):
        return prepare(self.example / "case.json", self.example / "baseline", self.run,
                       self.example / "checks" if checks else None,
                       self.example / "fixture-agent.json" if agent else None)

    def set_checks(self, command, timeout=10):
        plan = read_json(self.example / "checks/plan.json")
        for check in plan["checks"]:
            check["argv"] = command
            check["timeout_seconds"] = timeout
        (self.example / "checks/plan.json").write_text(json.dumps(plan))

    def test_full_generation_and_evaluation(self):
        self.prepare()
        generated = generate(self.run, True)
        self.assertEqual(generated["status"], "GENERATED")
        self.assertIsNone(generated["usage"]["tokens"])
        seal(self.run)
        result = evaluate(self.run, True)
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["verification_coverage"], 1)
        self.assertEqual(result["feature_pass_rate"], 1)
        self.assertTrue(Path(result["report_path"]).exists())
        self.assertEqual(verify(self.run)["integrity"], "VERIFIED")
        self.assertIn("NotImplementedError", (self.example / "baseline/greeting.py").read_text())

    def test_baseline_fails_both_requirements(self):
        self.prepare()
        seal(self.run)
        result = evaluate(self.run, True)
        self.assertEqual(result["status"], "FAIL")
        self.assertEqual(result["feature_pass_rate"], 0)
        self.assertEqual(result["verification_coverage"], 1)

    def test_incorrect_blank_handling_is_detected(self):
        self.prepare()
        (self.run / "workspace/greeting.py").write_text("def greet(name):\n    return 'Hello, ' + name + '!'\n")
        seal(self.run)
        result = evaluate(self.run, True)
        self.assertEqual([f["status"] for f in result["features"]], ["PASS", "FAIL"])
        self.assertEqual(result["status"], "FAIL")

    def test_no_checks_is_unverified(self):
        self.prepare(checks=False)
        seal(self.run)
        result = evaluate(self.run, True)
        self.assertEqual(result["status"], "UNVERIFIED")
        self.assertEqual(result["verification_coverage"], 0)

    def test_uncovered_requirement_prevents_pass(self):
        path = self.example / "checks/plan.json"
        plan = read_json(path)
        plan["checks"].pop()
        path.write_text(json.dumps(plan))
        self.prepare()
        generate(self.run, True)
        seal(self.run)
        result = evaluate(self.run, True)
        self.assertEqual(result["status"], "UNVERIFIED")
        self.assertEqual(result["verification_coverage"], 0.5)

    def test_launch_error_is_not_functional_failure(self):
        self.set_checks(["/no-such-forge-eval-executable"])
        self.prepare()
        seal(self.run)
        result = evaluate(self.run, True)
        self.assertEqual(result["status"], "ERROR")
        self.assertEqual(result["verification_coverage"], 0)

    def test_timeout_is_error_with_logs(self):
        self.set_checks(["{python}", "-c", "import time; time.sleep(30)"], 0.05)
        self.prepare()
        seal(self.run)
        result = evaluate(self.run, True)
        self.assertEqual(result["status"], "ERROR")
        self.assertTrue(all(c["execution"]["timed_out"] for c in result["checks"]))

    def test_check_exit_two_is_error(self):
        self.set_checks(["{python}", "-c", "raise SystemExit(2)"])
        self.prepare()
        seal(self.run)
        self.assertEqual(evaluate(self.run, True)["status"], "ERROR")

    def test_opt_in_required_before_any_execution(self):
        self.prepare()
        with self.assertRaises(HarnessError):
            generate(self.run)
        self.assertFalse((self.run / "generation").exists())
        seal(self.run)
        with self.assertRaises(HarnessError):
            evaluate(self.run)
        self.assertFalse((self.run / "evaluations").exists())

    def test_original_check_changes_do_not_change_frozen_checks(self):
        self.prepare()
        self.set_checks(["{python}", "-c", "raise SystemExit(0)"])
        seal(self.run)
        self.assertEqual(evaluate(self.run, True)["status"], "FAIL")

    def test_frozen_check_tampering_is_rejected(self):
        self.prepare()
        seal(self.run)
        (self.run / "inputs/checks/plan.json").write_text("{}")
        with self.assertRaises(HarnessError):
            evaluate(self.run, True)

    def test_reevaluation_preserves_prior_report(self):
        self.prepare()
        seal(self.run)
        first = evaluate(self.run, True)
        old = Path(first["report_path"]).read_bytes()
        second = evaluate(self.run, True)
        self.assertNotEqual(first["evaluation_id"], second["evaluation_id"])
        self.assertEqual(Path(first["report_path"]).read_bytes(), old)

    def test_generation_failure_cannot_be_sealed(self):
        (self.example / "fixture-agent.json").write_text(json.dumps({"argv": ["{python}", "-c", "raise SystemExit(1)"], "timeout_seconds": 10}))
        self.prepare()
        self.assertEqual(generate(self.run, True)["status"], "GENERATION_FAILED")
        with self.assertRaises(HarnessError):
            seal(self.run)
        with self.assertRaises(HarnessError):
            generate(self.run, True)

    def test_unknown_feature_is_rejected_before_preparation(self):
        path = self.example / "checks/plan.json"
        plan = read_json(path)
        plan["checks"][0]["features"] = ["Unknown requirement"]
        path.write_text(json.dumps(plan))
        with self.assertRaises(HarnessError):
            self.prepare()
        self.assertFalse(self.run.exists())

    def test_concurrent_controller_is_rejected(self):
        self.prepare()
        with run_lock(self.run):
            with self.assertRaises(HarnessError):
                generate(self.run, True)
            with self.assertRaises(HarnessError):
                seal(self.run)
        self.assertEqual(read_json(self.run / "state.json")["status"], "PREPARED")
        self.assertFalse((self.run / ".controller.lock").exists())

    def test_cli_non_pass_and_success_exit_codes(self):
        self.prepare()
        seal(self.run)
        with contextlib.redirect_stdout(io.StringIO()) as output:
            code = main(["evaluate", "--run", str(self.run), "--trusted-local"])
        self.assertEqual(code, 3)
        self.assertEqual(json.loads(output.getvalue())["status"], "FAIL")
        with contextlib.redirect_stderr(io.StringIO()) as error:
            code = main(["evaluate", "--run", str(self.run)])
        self.assertEqual(code, 1)
        self.assertIn("trusted-local", json.loads(error.getvalue())["error"])

    def test_malformed_timeout_rejected_without_execution(self):
        for invalid in (True, 0, -1, float("nan"), float("inf"), "10"):
            with self.subTest(timeout=invalid):
                self.set_checks(["{python}", "-c", "pass"], invalid)
                with self.assertRaises(HarnessError):
                    self.prepare()
                self.assertFalse(self.run.exists())


if __name__ == "__main__":
    unittest.main()
