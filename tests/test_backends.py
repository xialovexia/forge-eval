import json
import tempfile
import unittest
from pathlib import Path

from forge_eval.core import prepare, seal, write_json
from forge_eval.evaluation import evaluate
from forge_eval.generation import generate
from forge_eval.opencode import summarize_events


class BackendTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.run = self.root / "run"
        self.example = Path(__file__).resolve().parents[1] / "examples/hello"

    def finish(self, reason="stop", identifier="step-1"):
        return {"type": "step_finish", "sessionID": "test-session", "part": {
            "id": identifier, "reason": reason, "cost": 0.01,
            "tokens": {"total": 120, "input": 50, "output": 20, "reasoning": 5, "cache": {"read": 40, "write": 10}},
        }}

    def fixture(self, backend, events=None, exit_code=0):
        executable = self.root / "fake agent"
        body = "#!/usr/bin/env python3\nimport json,sys\nfrom pathlib import Path\n"
        body += "if '--version' in sys.argv:\n    print('test-cli'); sys.exit(0)\n"
        if backend == "opencode":
            body += "assert sys.argv[1:4] == ['run','--format','json']\nassert '--auto' not in sys.argv\n"
            body += "assert 'Implement greet(name)' in sys.stdin.read()\n"
        else:
            body += "assert sys.argv[1:3] == ['--profile','headless']\nassert 'Implement greet(name)' in sys.argv[3]\n"
        body += "Path('greeting.py').write_text(\"def greet(name):\\n    if not name.strip(): raise ValueError('blank')\\n    return 'Hello, ' + name + '!'\\n\")\n"
        body += "for event in " + repr(events or []) + ": print(json.dumps(event))\n" if backend == "opencode" else "print('Implementation complete')\n"
        body += "sys.exit(%s)\n" % exit_code
        executable.write_text(body)
        executable.chmod(0o755)
        config = {"backend": backend, "executable": str(executable), "timeout_seconds": 10}
        if backend == "deepseek-harness":
            config["launcher"] = [str(executable)]
        path = self.root / "agent.json"
        write_json(path, config)
        prepare(self.example / "case.json", self.example / "baseline", self.run, self.example / "checks", path)

    def parse(self, events):
        path = self.root / "events.jsonl"
        path.write_text('\n'.join(json.dumps(e) for e in events))
        return summarize_events(path)

    def test_opencode_end_to_end(self):
        self.fixture("opencode", [self.finish("tool-calls", "step-0"), self.finish()])
        result = generate(self.run, True)
        self.assertEqual(result["status"], "GENERATED")
        self.assertEqual(result["usage"]["tokens"], 240)
        self.assertEqual(result["usage"]["estimated_cost_usd"], 0.02)
        self.assertIsNone(result["usage"]["cost"])
        seal(self.run)
        self.assertEqual(evaluate(self.run, True)["status"], "PASS")

    def test_deepseek_end_to_end_without_invented_usage(self):
        self.fixture("deepseek-harness")
        result = generate(self.run, True)
        self.assertEqual(result["status"], "GENERATED")
        self.assertEqual(result["agent"]["final_message"], "Implementation complete")
        self.assertIsNone(result["usage"]["tokens"])
        self.assertIsNone(result["agent"]["observed_model"])
        seal(self.run)
        self.assertEqual(evaluate(self.run, True)["status"], "PASS")

    def test_deepseek_nonzero_exit_is_failed(self):
        self.fixture("deepseek-harness", exit_code=1)
        self.assertEqual(generate(self.run, True)["status"], "GENERATION_FAILED")

    def test_opencode_zero_exit_needs_terminal_step(self):
        self.fixture("opencode", [self.finish("tool-calls")])
        self.assertEqual(generate(self.run, True)["status"], "GENERATION_FAILED")

    def test_opencode_error_overrides_successful_step(self):
        self.fixture("opencode", [self.finish(), {"type": "error", "error": {"name": "ProviderError"}}])
        self.assertEqual(generate(self.run, True)["status"], "GENERATION_FAILED")

    def test_opencode_exit_failure_overrides_complete_events(self):
        self.fixture("opencode", [self.finish()], exit_code=1)
        self.assertEqual(generate(self.run, True)["status"], "GENERATION_FAILED")

    def test_duplicate_steps_do_not_double_count(self):
        result = self.parse([self.finish(), self.finish()])
        self.assertEqual(result["steps"], 1)
        self.assertEqual(result["usage"]["tokens"], 120)

    def test_new_unfinished_step_is_not_complete(self):
        result = self.parse([self.finish(), {"type": "step_start"}])
        self.assertFalse(result["completed"])

    def test_absent_reported_total_is_unknown(self):
        event = self.finish()
        del event["part"]["tokens"]["total"]
        result = self.parse([event])
        self.assertIsNone(result["usage"]["tokens"])
        self.assertEqual(result["usage"]["input_tokens"], 50)

    def test_missing_executable_retains_evidence_for_both_backends(self):
        for backend in ("opencode", "deepseek-harness"):
            with self.subTest(backend=backend):
                run = self.root / backend
                path = self.root / (backend + ".json")
                write_json(path, {"backend": backend, "executable": str(self.root / "absent")})
                prepare(self.example / "case.json", self.example / "baseline", run, agent_path=path)
                result = generate(run, True)
                self.assertEqual(result["status"], "GENERATION_FAILED")
                self.assertIsNotNone(result["execution"]["error"])
                self.assertTrue((run / "generation/prompt.txt").exists())

    def test_deepseek_prompt_is_literal_and_launcher_accepts_prefix_arguments(self):
        import sys
        script = self.root / "launcher.py"
        script.write_text(
            "import sys\n"
            "if '--version' in sys.argv: print('test-cli'); sys.exit(0)\n"
            "assert sys.argv[1:3] == ['--profile', 'headless']\n"
            "assert '{python}' in sys.argv[3] and '$()' in sys.argv[3]\n"
            "print('completed')\n"
        )
        case = self.root / "case.json"
        config = self.root / "agent.json"
        write_json(case, {"requirement": "Keep {python} and $() literal"})
        write_json(config, {"backend": "deepseek-harness", "launcher": [sys.executable, str(script)]})
        prepare(case, self.example / "baseline", self.run, agent_path=config)
        result = generate(self.run, True)
        self.assertEqual(result["status"], "GENERATED")
        self.assertFalse(result["execution"]["shell"])


if __name__ == "__main__":
    unittest.main()
