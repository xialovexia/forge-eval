import json
import contextlib
import io
import shutil
import tempfile
import unittest
from pathlib import Path

from forge_eval.core import HarnessError, prepare, read_json, run_lock, seal, verify, write_json
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

    def test_unknown_feature_does_not_block_execution(self):
        path = self.example / "checks/plan.json"
        plan = read_json(path)
        plan["checks"][0]["features"] = ["Unknown requirement"]
        path.write_text(json.dumps(plan))
        self.prepare()
        generate(self.run, True)
        seal(self.run)
        result = evaluate(self.run, True)
        self.assertEqual(result["status"], "UNVERIFIED")
        self.assertEqual(result["verification_coverage"], 0.5)
        self.assertTrue(all(c["status"] == "PASS" for c in result["checks"]))

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

    def test_timeouts_are_consumed_without_a_format_gate(self):
        for index, timeout in enumerate(("10", 90000, None)):
            with self.subTest(timeout=timeout):
                self.run = self.root / ("timeout-run-%s" % index)
                self.set_checks(["{python}", "-c", "pass"], timeout)
                self.prepare()
                seal(self.run)
                self.assertEqual(evaluate(self.run, True)["status"], "PASS")

    def test_model_can_use_minimal_inputs_and_empty_arguments(self):
        feature = read_json(self.example / "case.json")["required_features"][0]
        write_json(self.example / "case.json", {"required_features": feature, "notes": "minimal input"})
        agent = read_json(self.example / "fixture-agent.json")
        write_json(self.example / "fixture-agent.json", agent["argv"])
        code = "import sys; from pathlib import Path; import greeting; raise SystemExit(0 if greeting.greet('Ada') == 'Hello, Ada!' and sys.argv[1] == '' and Path(sys.argv[2].split('=', 1)[1]).is_file() else 1)"
        write_json(self.example / "checks/plan.json", [{
            "check_id": "问候 / 实验",
            "features": feature + "  ",
            "argv": ["{python}", "-c", code, "", "--checks={checks}/check_greeting.py"],
            "notes": "extra fields are allowed",
        }])
        self.prepare()
        self.assertEqual(generate(self.run, True)["status"], "GENERATED")
        seal(self.run)
        result = evaluate(self.run, True)
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["checks"][0]["check_id"], "问候 / 实验")

    def test_shell_commands_and_a_single_check_are_supported(self):
        write_json(self.example / "case.json", {"required_features": "Writes a marker"})
        write_json(self.example / "fixture-agent.json", "printf generated > marker.txt")
        write_json(self.example / "checks/plan.json", {
            "command": "test \"$(cat marker.txt)\" = generated",
            "features": "Writes a marker",
            "description": "single shell check",
        })
        self.prepare()
        generated = generate(self.run, True)
        self.assertEqual(generated["status"], "GENERATED")
        self.assertTrue(generated["execution"]["shell"])
        seal(self.run)
        result = evaluate(self.run, True)
        self.assertEqual(result["status"], "PASS")
        self.assertTrue(result["checks"][0]["execution"]["shell"])

    def test_duplicate_free_form_check_names_have_independent_evidence(self):
        path = self.example / "checks/plan.json"
        plan = read_json(path)
        for check in plan["checks"]:
            check["check_id"] = "../相同 / 名称"
            check["features"] *= 2
        write_json(path, plan)
        self.prepare()
        generate(self.run, True)
        seal(self.run)
        result = evaluate(self.run, True)
        self.assertEqual(result["status"], "PASS")
        self.assertEqual([c["check_id"] for c in result["checks"]], ["../相同 / 名称"] * 2)
        paths = [c["evidence_path"] for c in result["checks"]]
        self.assertEqual(len(set(paths)), 2)
        output = Path(result["report_path"]).parent
        report = Path(result["report_path"]).read_text()
        for path in paths:
            self.assertTrue((output / path / "stdout.log").exists())
            self.assertIn(path + "/stdout.log", report)

    def test_missing_feature_declarations_do_not_break_reporting(self):
        write_json(self.example / "case.json", {"requirement": "Explore the implementation"})
        self.prepare()
        generate(self.run, True)
        seal(self.run)
        result = evaluate(self.run, True)
        self.assertEqual(result["status"], "UNVERIFIED")
        self.assertEqual(result["features"], [])
        self.assertEqual(result["verification_coverage"], 0)
        self.assertEqual(result["feature_pass_rate"], 0)
        self.assertTrue(all(c["status"] == "PASS" for c in result["checks"]))

    def test_unusable_command_records_an_execution_error(self):
        write_json(self.example / "fixture-agent.json", {"notes": "No executable command yet"})
        self.prepare()
        result = generate(self.run, True)
        self.assertEqual(result["status"], "GENERATION_FAILED")
        self.assertIsNotNone(result["execution"]["error"])
        self.assertTrue((self.run / "generation/result.json").exists())
        self.assertTrue((self.run / "generation/stderr.log").exists())

    def test_unmapped_check_errors_are_visible_in_the_overall_result(self):
        path = self.example / "checks/plan.json"
        plan = read_json(path)
        plan["checks"].append({"argv": ["{python}", "-c", "raise SystemExit(2)"], "features": "New idea"})
        write_json(path, plan)
        self.prepare()
        generate(self.run, True)
        seal(self.run)
        result = evaluate(self.run, True)
        self.assertEqual(result["status"], "ERROR")
        self.assertTrue(all(f["status"] == "PASS" for f in result["features"]))

    def test_generation_and_evaluation_ignore_record_format_metadata(self):
        self.prepare()
        state = read_json(self.run / "state.json")
        state.update(schema_version="trial", case_id="operator label", notes="extra metadata")
        write_json(self.run / "state.json", state)
        self.assertEqual(generate(self.run, True)["status"], "GENERATED")
        seal(self.run)
        record = read_json(self.run / "seal.json")
        for key in ("schema_version", "kind", "case_id", "evaluation_status"):
            record.pop(key)
        write_json(self.run / "seal.json", record)
        self.assertEqual(evaluate(self.run, True)["status"], "PASS")


if __name__ == "__main__":
    unittest.main()
