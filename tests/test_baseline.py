import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from forge_eval.cli import main
from forge_eval.core import HarnessError, inventory, prepare, read_json, seal, write_json
from forge_eval.evaluation import evaluate
from forge_eval.generation import generate


class BaselineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.repo = self.root / "source project"
        self.repo.mkdir()
        self.run = self.root / "run"
        self.git("init", "-q")
        self.git("symbolic-ref", "HEAD", "refs/heads/main")
        self.git("config", "user.name", "Fixture")
        self.git("config", "user.email", "fixture@example.invalid")
        self.git("config", "commit.gpgsign", "false")
        (self.repo / "greeting.py").write_text("def greet(name):\n    raise NotImplementedError\n")
        self.initial = self.commit("Initial project")
        (self.repo / "dependency.txt").write_text("needed before greeting implementation\n")
        self.before = self.commit("Prepare dependency")
        (self.repo / "greeting.py").write_text("def greet(name):\n    return 'Hello, ' + name + '!'\n")
        self.first_change = self.commit("Start greeting implementation")
        (self.repo / "greeting.py").write_text(
            "def greet(name):\n    if not name.strip(): raise ValueError('blank')\n"
            "    return 'Hello, ' + name + '!'\n"
        )
        self.last_change = self.commit("Reject blank names")
        self.document = self.root / "greeting.md"
        self.document.write_text("Implement greet(name), greeting non-empty names and rejecting blank names.\n")
        self.example = Path(__file__).resolve().parents[1] / "examples/hello"

    def git(self, *args):
        return subprocess.check_output(["git", "-C", str(self.repo), *args], stderr=subprocess.PIPE).decode().strip()

    def commit(self, message):
        self.git("add", ".")
        self.git("commit", "-qm", message)
        return self.git("rev-parse", "HEAD")

    def agent(self, selection=None, backend=None, exit_code=0, raw=None, delay=0):
        selection = selection if selection is not None else {
            "baseline_commit": self.before[:12],
            "change_commits": [self.first_change, self.last_change],
            "reason": "PRIVATE_ANALYSIS: both commits implement the documented task",
            "operator_notes": {"自由字段": True},
        }
        answer = raw if raw is not None else "Selected history:\n```json\n" + json.dumps(selection) + "\n```"
        script = self.root / ((backend or "command") + " agent.py")
        script.write_text(
            "#!/usr/bin/env python3\nimport json, os, subprocess, sys, time\nfrom pathlib import Path\n"
            "if '--version' in sys.argv: print('fixture-cli'); sys.exit(0)\n"
            "prompt = sys.argv[3] if '--profile' in sys.argv else sys.stdin.read()\n"
            "if '--dir' in sys.argv: assert Path(sys.argv[sys.argv.index('--dir') + 1]).resolve() == Path.cwd()\n"
            "resolving = prompt.startswith('Resolve the baseline')\n"
            "if resolving:\n"
            "    assert Path.cwd().resolve() != Path(" + repr(str(self.repo)) + ").resolve()\n"
            "    assert 'Implement greet(name)' in prompt\n"
            "    assert 'Start greeting implementation' in subprocess.check_output(['git', 'log', '--format=%s']).decode()\n"
            "    if '--allowedTools' in sys.argv: assert 'Bash' in sys.argv[sys.argv.index('--allowedTools') + 1]\n"
            "    Path('resolver-scratch.txt').write_text('not a baseline file')\n"
            "    time.sleep(" + repr(delay) + ")\n"
            "    answer = " + repr(answer) + "\n"
            "else:\n"
            "    assert 'PRIVATE_ANALYSIS' not in prompt\n"
            "    assert not Path('.git').exists()\n"
            "    if '--allowedTools' in sys.argv: assert 'Bash' not in sys.argv[sys.argv.index('--allowedTools') + 1]\n"
            "    Path('greeting.py').write_text(\"def greet(name):\\n    if not name.strip(): raise ValueError('blank')\\n    return 'Hello, ' + name + '!'\\n\")\n"
            "    answer = 'Implemented'\n"
            "backend = " + repr(backend) + "\n"
            "if backend == 'claude-code':\n"
            "    print(json.dumps({'type': 'result', 'subtype': 'success', 'is_error': False, 'result': answer}))\n"
            "elif backend == 'opencode':\n"
            "    print(json.dumps({'type': 'text', 'part': {'text': answer}}))\n"
            "    print(json.dumps({'type': 'step_finish', 'part': {'reason': 'stop'}}))\n"
            "else: print(answer)\n"
            "sys.exit(" + repr(exit_code) + ")\n"
        )
        script.chmod(0o755)
        config = {"backend": backend, "executable": str(script), "timeout_seconds": 10} if backend else {
            "argv": [sys.executable, str(script)], "timeout_seconds": 10,
        }
        path = self.root / ((backend or "command") + ".json")
        write_json(path, config)
        return path

    def resolve(self, config, **kwargs):
        return prepare(run_path=self.run, repo=self.repo, documents=[self.document],
                       agent_path=config, trusted_local=True, **kwargs)

    def test_document_driven_run_continues_through_existing_pipeline(self):
        config = self.agent()
        source_text = (self.repo / "greeting.py").read_text()
        (self.repo / "greeting.py").write_text("uncommitted local work")
        (self.repo / "local-only.txt").write_text("untracked")
        state = self.resolve(config, case_path=self.example / "case.json", checks_path=self.example / "checks")
        self.assertEqual(state["status"], "PREPARED")
        self.assertEqual(state["baseline"]["commit"], self.before)
        self.assertEqual(state["baseline"]["repository_head"], self.last_change)
        self.assertIn("NotImplementedError", (self.run / "workspace/greeting.py").read_text())
        self.assertTrue((self.run / "workspace/dependency.txt").exists())
        for name in (".git", "local-only.txt", "resolver-scratch.txt"):
            self.assertFalse((self.run / "workspace" / name).exists())
        self.assertEqual((self.repo / "greeting.py").read_text(), "uncommitted local work")
        self.assertEqual(self.git("show", "HEAD:greeting.py"), source_text.strip())
        self.assertEqual(self.git("rev-parse", "HEAD"), self.last_change)
        self.assertFalse((self.repo / "resolver-scratch.txt").exists())
        self.assertEqual(generate(self.run, True)["status"], "GENERATED")
        seal(self.run)
        self.assertEqual(evaluate(self.run, True)["status"], "PASS")
        record = read_json(self.run / "resolution/result.json")
        self.assertTrue(record["selection"]["operator_notes"]["自由字段"])
        self.assertTrue((self.run / "resolution/documents/0001-greeting.md").exists())

    def test_all_native_backends_resolve_then_generate_in_separate_invocations(self):
        for backend in ("claude-code", "opencode", "deepseek-harness"):
            with self.subTest(backend=backend):
                self.run = self.root / backend
                state = self.resolve(self.agent(backend=backend))
                self.assertEqual(state["baseline"]["commit"], self.before)
                self.assertEqual(read_json(self.run / "inputs/case.json")["requirement"], self.document.read_text())
                record = read_json(self.run / "resolution/result.json")
                self.assertEqual(record["backend"], backend)
                self.assertEqual(record["agent"]["cli_version"], "fixture-cli")
                self.assertEqual(generate(self.run, True)["status"], "GENERATED")
                self.assertNotIn("PRIVATE_ANALYSIS", (self.run / "generation/prompt.txt").read_text())

    def test_single_change_can_select_its_parent_without_a_baseline_field(self):
        state = self.resolve(self.agent({"change_commit": self.first_change, "notes": "single change"}))
        self.assertEqual(state["baseline"]["commit"], self.before)

    def test_merge_change_uses_target_branch_first_parent(self):
        self.git("checkout", "-qb", "target", self.before)
        (self.repo / "target-only.txt").write_text("unrelated mainline work")
        target = self.commit("Target branch work")
        self.git("merge", "--no-ff", "-m", "Merge greeting", "main")
        merge = self.git("rev-parse", "HEAD")
        state = self.resolve(self.agent({"change_commit": merge}))
        self.assertEqual(state["baseline"]["commit"], target)
        self.assertTrue((self.run / "workspace/target-only.txt").exists())
        self.assertIn("NotImplementedError", (self.run / "workspace/greeting.py").read_text())

    def test_export_preserves_blobs_modes_and_ignores_archive_attributes(self):
        self.git("checkout", "--detach", self.before)
        (self.repo / ".gitattributes").write_text("payload.bin export-ignore\nversion.txt export-subst\n")
        payload = bytes(range(256)) * 5000
        (self.repo / "payload.bin").write_bytes(payload)
        (self.repo / "version.txt").write_text("$Format:%H$\n")
        (self.repo / "empty").touch()
        executable = self.repo / "launch"
        executable.write_text("#!/bin/sh\nexit 0\n")
        executable.chmod(0o755)
        selected = self.commit("Snapshot files")
        self.git("checkout", "main")
        with patch("forge_eval.core.inventory", wraps=inventory) as inventories:
            self.resolve(self.agent({"baseline_commit": selected}))
        self.assertEqual([call.args[0] for call in inventories.call_args_list], [self.run / "inputs"])
        self.assertEqual((self.run / "workspace/payload.bin").read_bytes(), payload)
        self.assertEqual((self.run / "workspace/version.txt").read_text(), "$Format:%H$\n")
        self.assertEqual((self.run / "workspace/empty").stat().st_size, 0)
        self.assertEqual((self.run / "workspace/launch").stat().st_mode & 0o777, 0o755)
        self.assertFalse((self.run / "inputs/baseline-manifest.json").exists())

    def test_unresolved_match_retains_evidence_without_falling_back_to_head(self):
        config = self.agent({"baseline_commit": None, "change_commit": self.first_change,
                             "reason": "No matching implementation"})
        with self.assertRaisesRegex(HarnessError, "No matching implementation"):
            self.resolve(config)
        self.assertFalse((self.run / "workspace").exists())
        self.assertEqual(read_json(self.run / "state.json")["status"], "ERROR")
        self.assertEqual(read_json(self.run / "resolution/result.json")["status"], "FAILED")
        self.assertTrue((self.run / "resolution/agent/stdout.log").exists())

    def test_invalid_revision_and_root_change_fail_with_retained_decision(self):
        for name, selection in (("missing", {"baseline_commit": "missing-revision"}),
                                ("root", {"change_commit": self.initial})):
            with self.subTest(name=name):
                self.run = self.root / name
                with self.assertRaises(HarnessError):
                    self.resolve(self.agent(selection))
                self.assertEqual(read_json(self.run / "resolution/result.json")["selection"], selection)
                self.assertFalse((self.run / "workspace").exists())

    def test_failed_agent_cannot_publish_a_baseline(self):
        with self.assertRaisesRegex(HarnessError, "analysis failed"):
            self.resolve(self.agent(exit_code=1))
        record = read_json(self.run / "resolution/result.json")
        self.assertEqual(record["execution"]["exit_code"], 1)
        self.assertFalse((self.run / "workspace").exists())

    def test_timeout_retains_execution_evidence(self):
        config = self.agent(delay=10)
        command = read_json(config)
        command["timeout_seconds"] = 0.1
        write_json(config, command)
        with self.assertRaisesRegex(HarnessError, "analysis failed"):
            self.resolve(config)
        self.assertTrue(read_json(self.run / "resolution/result.json")["execution"]["timed_out"])

    def test_malformed_answer_retains_agent_output(self):
        with self.assertRaisesRegex(HarnessError, "did not return"):
            self.resolve(self.agent(raw="I did not select a commit."))
        self.assertIn("did not select", (self.run / "resolution/agent/stdout.log").read_text())

    def test_multiple_documents_and_optional_case(self):
        second = self.root / "validation.txt"
        second.write_text("Whitespace-only names must also fail. 中文")
        config = self.agent()
        prepare(repo=self.repo, run_path=self.run, documents=[self.document, second],
                agent_path=config, trusted_local=True)
        case = read_json(self.run / "inputs/case.json")
        self.assertEqual(case["case_id"], "greeting")
        self.assertIn(second.read_text(), case["requirement"])
        self.assertIn(second.read_text(), (self.run / "resolution/agent/prompt.txt").read_text())

    def test_case_alone_can_supply_the_change_description(self):
        state = prepare(case_path=self.example / "case.json", repo=self.repo, run_path=self.run,
                        agent_path=self.agent(), trusted_local=True)
        self.assertEqual(state["baseline"]["commit"], self.before)

    def test_resolution_needs_existing_trusted_local_opt_in(self):
        with self.assertRaisesRegex(HarnessError, "trusted-local"):
            prepare(repo=self.repo, run_path=self.run, documents=self.document, agent_path=self.agent())
        self.assertFalse(self.run.exists())

    def test_cli_aliases_prepare_a_run_directly(self):
        config = self.agent()
        for command in ("prepare", "resolve-baseline"):
            with self.subTest(command=command):
                run = self.repo / ".forge-eval" / command
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    code = main([command, "--repo", str(self.repo), "--document", str(self.document),
                                 "--agent-config", str(config), "--run", str(run), "--trusted-local"])
                self.assertEqual(code, 0)
                self.assertEqual(json.loads(output.getvalue())["status"], "PREPARED")
                self.assertTrue((run / "workspace/greeting.py").exists())

    def test_internal_links_are_materialized_and_submodules_remain_unsupported(self):
        self.git("checkout", "--detach", self.before)
        os.symlink("greeting.py", self.repo / "linked.py")
        (self.repo / "instructions").mkdir()
        (self.repo / "instructions/AGENTS.md").write_text("Project instructions\n")
        os.symlink("instructions", self.repo / "instructions-alias")
        os.symlink("linked.py", self.repo / "chained.py")
        linked = self.commit("Add link")
        self.git("checkout", "main")
        self.resolve(self.agent({"baseline_commit": linked}))
        self.assertEqual((self.run / "workspace/linked.py").read_text(),
                         (self.run / "workspace/greeting.py").read_text())
        self.assertFalse((self.run / "workspace/linked.py").is_symlink())
        self.assertEqual((self.run / "workspace/chained.py").read_text(),
                         (self.run / "workspace/greeting.py").read_text())
        self.assertEqual((self.run / "workspace/instructions-alias/AGENTS.md").read_text(), "Project instructions\n")
        seal(self.run)
        self.run = self.root / "submodule-run"
        self.git("update-index", "--add", "--cacheinfo", "160000," + self.before + ",vendor")
        self.git("commit", "-qm", "Add submodule entry")
        submodule = self.git("rev-parse", "HEAD")
        with self.assertRaisesRegex(HarnessError, "submodules"):
            self.resolve(self.agent({"baseline_commit": submodule}))

    def test_external_and_cyclic_links_are_not_followed(self):
        from forge_eval.baseline import materialize_links
        for name, links in (("escape", {Path("a"): "../outside"}),
                            ("cycle", {Path("a"): "b", Path("b"): "a"})):
            with self.subTest(name=name):
                root = self.root / name
                root.mkdir()
                with self.assertRaises(HarnessError):
                    materialize_links(root, links)


if __name__ == "__main__":
    unittest.main()
