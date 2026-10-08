import json
import os
import tempfile
import unittest
from pathlib import Path

from forge_eval.core import HarnessError, prepare, read_json, seal, validate_case, verify


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.baseline = self.root / "baseline"
        self.baseline.mkdir()
        (self.baseline / "main.py").write_text("print('baseline')\n")
        self.case = self.root / "case.json"
        self.case.write_text(json.dumps({
            "schema_version": "1.0", "case_id": "sample", "mode": "contract",
            "requirement": "Implement a greeting", "required_features": ["Returns a greeting"],
        }))
        self.run = self.root / "run"

    def prepare(self):
        return prepare(self.case, self.baseline, self.run)

    def test_full_lifecycle_keeps_baseline_and_sealed_copy_independent(self):
        self.prepare()
        (self.run / "workspace/main.py").write_text("print('candidate')\n")
        seal(self.run)
        self.assertEqual(verify(self.run)["evaluation_status"], "NOT_EVALUATED")
        self.assertEqual((self.baseline / "main.py").read_text(), "print('baseline')\n")
        (self.run / "workspace/main.py").write_text("changed after sealing")
        self.assertEqual(verify(self.run)["integrity"], "VERIFIED")

    def test_candidate_tampering_fails(self):
        self.prepare()
        seal(self.run)
        (self.run / "artifacts/candidate/main.py").write_text("tampered")
        with self.assertRaises(HarnessError):
            verify(self.run)

    def test_unexpected_candidate_file_fails(self):
        self.prepare()
        seal(self.run)
        (self.run / "artifacts/candidate/extra").write_text("unexpected")
        with self.assertRaises(HarnessError):
            verify(self.run)

    def test_input_tampering_prevents_sealing(self):
        self.prepare()
        (self.run / "inputs/case.json").write_text("{}")
        with self.assertRaises(HarnessError):
            seal(self.run)

    def test_existing_run_and_resealing_are_rejected(self):
        self.prepare()
        with self.assertRaises(HarnessError):
            self.prepare()
        seal(self.run)
        with self.assertRaises(HarnessError):
            seal(self.run)

    def test_git_history_is_not_copied(self):
        history = self.baseline / ".git"
        history.mkdir()
        (history / "secret").write_text("hidden history")
        self.prepare()
        self.assertFalse((self.run / "workspace/.git").exists())

    def test_symlink_is_rejected(self):
        (self.baseline / "outside").symlink_to(self.case)
        with self.assertRaises(HarnessError):
            self.prepare()
        self.assertFalse(self.run.exists())

    def test_run_inside_baseline_is_rejected(self):
        with self.assertRaises(HarnessError):
            prepare(self.case, self.baseline, self.baseline / "run")

    def test_executable_mode_tampering_fails(self):
        self.prepare()
        seal(self.run)
        candidate = self.run / "artifacts/candidate/main.py"
        os.chmod(candidate, candidate.stat().st_mode ^ 0o100)
        with self.assertRaises(HarnessError):
            verify(self.run)

    def test_case_rejects_unsupported_modes_and_unknown_fields(self):
        case = read_json(self.case)
        case["mode"] = "strict_holdout"
        with self.assertRaises(HarnessError):
            validate_case(case)
        case["mode"] = "contract"
        case["hidden_gold"] = "/private/reference"
        with self.assertRaises(HarnessError):
            validate_case(case)


if __name__ == "__main__":
    unittest.main()
