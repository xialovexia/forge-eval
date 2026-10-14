import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from forge_eval.core import HarnessError, prepare, read_json, seal, verify, write_json


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

    def test_preparation_does_not_read_baseline_contents_for_hashing(self):
        source = self.baseline / "main.py"
        source.chmod(0o755)
        nested = self.baseline / "nested"
        nested.mkdir()
        (nested / "data.txt").write_text("baseline data")
        read_bytes = Path.read_bytes
        workspace = self.run / "workspace"

        def read_without_baseline_hashing(path):
            if self.baseline in path.parents or workspace in path.parents:
                raise AssertionError("Preparation must not re-read baseline contents for hashing")
            return read_bytes(path)

        with patch.object(Path, "read_bytes", read_without_baseline_hashing):
            state = self.prepare()

        self.assertEqual((workspace / "main.py").read_text(), source.read_text())
        self.assertEqual((workspace / "main.py").stat().st_mode & 0o777, 0o755)
        self.assertEqual((workspace / "nested/data.txt").read_text(), "baseline data")
        self.assertFalse((self.run / "inputs/baseline-manifest.json").exists())
        self.assertNotIn("baseline-manifest.json", state["inputs"])

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

    def test_free_form_case_metadata_survives_the_lifecycle(self):
        case = read_json(self.case)
        case.update(schema_version="experiment", mode="自由探索", case_id="问候 / 实验", notes="Try an idea")
        case["required_features"] *= 2
        write_json(self.case, case)
        self.prepare()
        self.assertEqual(read_json(self.run / "inputs/case.json"), case)
        seal(self.run)
        self.assertEqual(verify(self.run)["case_id"], case["case_id"])

    def test_case_metadata_is_optional(self):
        write_json(self.case, {"notes": "No fixed case fields yet"})
        self.assertEqual(self.prepare()["case_id"], self.case.stem)
        seal(self.run)
        self.assertEqual(verify(self.run)["integrity"], "VERIFIED")

    def test_case_can_be_a_requirement_string(self):
        write_json(self.case, "Explore a greeting implementation")
        self.prepare()
        seal(self.run)
        self.assertEqual(verify(self.run)["integrity"], "VERIFIED")

    def test_intermediate_record_metadata_is_not_checked(self):
        self.prepare()
        state = read_json(self.run / "state.json")
        state.pop("schema_version")
        state.pop("case_id")
        state["notes"] = "operator annotation"
        write_json(self.run / "state.json", state)
        seal(self.run)
        record = read_json(self.run / "seal.json")
        record.update(schema_version="draft", kind="snapshot", case_id="another label", evaluation_status="operator note")
        write_json(self.run / "seal.json", record)
        self.assertEqual(verify(self.run)["integrity"], "VERIFIED")


if __name__ == "__main__":
    unittest.main()
