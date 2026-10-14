import json
import tempfile
import unittest
from pathlib import Path

from forge_eval.claude import build_prompt, summarize_events
from forge_eval.core import prepare, read_json, seal, write_json
from forge_eval.evaluation import evaluate
from forge_eval.generation import generate


class ClaudeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.example = Path(__file__).resolve().parents[1] / "examples/hello"
        self.run = self.root / "run"

    def completed(self, usage=True):
        event = {"type": "result", "subtype": "success", "is_error": False, "result": "Implemented", "total_cost_usd": 0.01}
        if usage:
            event["usage"] = {"input_tokens": 100, "cache_read_input_tokens": 80, "cache_creation_input_tokens": 10, "output_tokens": 20}
        return event

    def fake(self, events, exit_code=0):
        executable = self.root / "fake claude"
        executable.write_text(
            "#!/usr/bin/env python3\nimport sys,json\nfrom pathlib import Path\n"
            "if '--version' in sys.argv:\n    print('claude-code test-fixture'); sys.exit(0)\n"
            "assert '--print' in sys.argv and '--verbose' in sys.argv\n"
            "assert sys.argv[sys.argv.index('--permission-mode')+1] == 'dontAsk'\n"
            "assert '--dangerously-skip-permissions' not in sys.argv\n"
            "assert 'Implement greet(name)' in sys.stdin.read()\n"
            "Path('greeting.py').write_text(\"def greet(name):\\n    if not name.strip():\\n        raise ValueError('blank')\\n    return 'Hello, ' + name + '!'\\n\")\n"
            "for event in " + repr(events) + ": print(json.dumps(event))\n"
            "sys.exit(" + str(exit_code) + ")\n"
        )
        executable.chmod(0o755)
        config = self.root / "agent.json"
        write_json(config, {"backend": "claude-code", "executable": str(executable), "timeout_seconds": 10, "notes": "extra metadata accepted"})
        prepare(self.example / "case.json", self.example / "baseline", self.run,
                self.example / "checks", config)

    def test_adapter_to_evaluation_with_fake_cli(self):
        self.fake([{"type": "system", "subtype": "init", "session_id": "fixture", "model": "fixture-model"},
                   {"type": "item.completed", "item": {"type": "agent_message", "text": "Implemented"}}, self.completed()])
        result = generate(self.run, True)
        self.assertEqual(result["status"], "GENERATED")
        self.assertEqual(result["backend"], "claude-code")
        self.assertEqual(result["usage"]["tokens"], 210)
        self.assertEqual(result["usage"]["cache_read_input_tokens"], 80)
        self.assertIsNone(result["usage"]["cost"])
        self.assertEqual(result["usage"]["estimated_cost_usd"], 0.01)
        self.assertEqual(result["agent"]["observed_model"], "fixture-model")
        self.assertEqual(result["agent"]["cli_version"], "claude-code test-fixture")
        self.assertEqual(result["agent"]["final_message"], "Implemented")
        self.assertIsNone(result["agent"]["requested_model"])
        self.assertIn("Public task specification", (self.run / "generation/prompt.txt").read_text())
        seal(self.run)
        self.assertEqual(evaluate(self.run, True)["status"], "PASS")

    def test_zero_exit_without_completion_is_failed(self):
        self.fake([{"type": "system", "subtype": "init"}])
        self.assertEqual(generate(self.run, True)["status"], "GENERATION_FAILED")

    def test_failed_event_overrides_completed_event(self):
        self.fake([self.completed(), {"type": "result", "subtype": "error_during_execution", "is_error": True, "errors": ["backend failure"]}])
        result = generate(self.run, True)
        self.assertEqual(result["status"], "GENERATION_FAILED")
        self.assertEqual(len(result["agent"]["errors"]), 1)

    def test_nonzero_exit_overrides_completed_event(self):
        self.fake([self.completed()], exit_code=1)
        self.assertEqual(generate(self.run, True)["status"], "GENERATION_FAILED")

    def test_missing_usage_is_unknown(self):
        self.fake([self.completed(usage=False)])
        result = generate(self.run, True)
        self.assertEqual(result["status"], "GENERATED")
        self.assertIsNone(result["usage"]["tokens"])

    def test_missing_executable_retains_error_evidence(self):
        config = self.root / "agent.json"
        write_json(config, {"backend": "claude-code", "executable": str(self.root / "missing")})
        prepare(self.example / "case.json", self.example / "baseline", self.run, agent_path=config)
        result = generate(self.run, True)
        self.assertEqual(result["status"], "GENERATION_FAILED")
        self.assertIsNotNone(result["execution"]["error"])
        self.assertIsNone(result["agent"]["cli_version"])

    def test_unknown_events_and_non_json_lines_do_not_break_parser(self):
        path = self.root / "events.jsonl"
        path.write_text('notice\n[]\n' + json.dumps({"type": "future.event"}) + '\n' + json.dumps(self.completed()) + '\n')
        summary = summarize_events(path)
        self.assertTrue(summary["completed"])
        self.assertEqual(summary["ignored_lines"], 2)

    def test_final_result_without_usage_does_not_reuse_old_usage(self):
        path = self.root / "events.jsonl"
        path.write_text('\n'.join(json.dumps(v) for v in [self.completed(), self.completed(False)]))
        self.assertIsNone(summarize_events(path)["usage"]["tokens"])

    def test_free_form_case_and_prompt_are_preserved(self):
        prompt = build_prompt({"requirement": "Keep {workspace} literal; $() is text", "ideas": ["中文"]})
        self.assertIn("{workspace}", prompt)
        self.assertIn("中文", prompt)
        self.assertIn('"some task"', build_prompt("some task"))

    def test_success_subtype_with_api_error_is_not_success(self):
        # Observed on the installed CLI when the network returned EPERM.
        result = self.completed()
        result.update(is_error=True, result="API Error: Unable to connect to API (EPERM)")
        self.fake([{"type": "system", "subtype": "api_retry"}, result])
        generated = generate(self.run, True)
        self.assertEqual(generated["status"], "GENERATION_FAILED")
        self.assertEqual(generated["agent"]["api_retries"], 1)
        self.assertTrue(generated["agent"]["is_error"])

    def test_last_result_is_not_added_to_cumulative_previous_result(self):
        path = self.root / "events.jsonl"
        path.write_text('\n'.join(json.dumps(v) for v in [self.completed(), self.completed()]))
        self.assertEqual(summarize_events(path)["usage"]["tokens"], 210)

    def test_missing_cache_usage_leaves_total_unknown(self):
        result = self.completed()
        del result["usage"]["cache_read_input_tokens"]
        path = self.root / "events.jsonl"
        path.write_text(json.dumps(result))
        self.assertIsNone(summarize_events(path)["usage"]["tokens"])


if __name__ == "__main__":
    unittest.main()
