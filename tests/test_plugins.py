"""Exercise the actual distributable from a relocated cache and unrelated cwd."""

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from forge_eval.core import inventory


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("build_plugin", ROOT / "scripts/build_plugin.py")
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


class PluginTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="forge plugin test ")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        built = builder.build(self.root / "build")
        self.plugin = self.root / "relocated cache/forge-eval"
        self.plugin.parent.mkdir()
        shutil.move(str(built), self.plugin)
        self.workspace = self.root / "user project"
        self.workspace.mkdir()
        self.launcher = self.plugin / "skills/forge-eval/scripts/forge_eval.py"
        self.run = self.workspace / ".forge-eval/runs/hello"
        self.before = inventory(self.plugin)

    def command(self, *arguments, expected=0, extra_env=None):
        env = dict(os.environ)
        env.pop("PYTHONPATH", None)
        env.update(extra_env or {})
        result = subprocess.run(
            [sys.executable, str(self.launcher), *arguments], cwd=self.workspace,
            env=env, capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(result.returncode, expected, result.stderr + result.stdout)
        return json.loads(result.stdout if expected != 1 else result.stderr)

    def prepare(self, agent=True, checks=True):
        example = self.plugin / "examples/hello"
        arguments = ["prepare", "--case", str(example / "case.json"),
                     "--baseline", str(example / "baseline"),
                     "--run", ".forge-eval/runs/hello"]
        if agent:
            arguments.extend(["--agent-config", str(example / "fixture-agent.json")])
        if checks:
            arguments.extend(["--checks", str(example / "checks")])
        return self.command(*arguments)

    def test_relocated_plugin_runs_full_lifecycle_without_install_or_cache_writes(self):
        info = self.command("doctor")
        self.assertEqual(Path(info["cwd"]), self.workspace)
        self.assertEqual(Path(info["core_path"]), self.plugin / "src/forge_eval")
        self.assertEqual(self.prepare()["status"], "PREPARED")
        self.assertEqual(self.command("generate", "--run", str(self.run), "--trusted-local")["status"], "GENERATED")
        self.command("seal", "--run", str(self.run))
        self.assertEqual(self.command("verify", "--run", str(self.run))["integrity"], "VERIFIED")
        result = self.command("evaluate", "--run", str(self.run), "--trusted-local")
        self.assertEqual(result["status"], "PASS")
        self.assertTrue(Path(result["report_path"]).is_file())
        before_inspect = inventory(self.run)
        summary = self.command("inspect", "--run", str(self.run))
        self.assertEqual(summary["generation"]["status"], "GENERATED")
        self.assertEqual(summary["evaluations"][0]["result"]["status"], "PASS")
        self.assertEqual(inventory(self.run), before_inspect)
        self.assertEqual(inventory(self.plugin), self.before)

    def test_host_session_candidate_does_not_claim_external_generation(self):
        self.prepare(agent=False)
        (self.run / "workspace/greeting.py").write_text(
            "def greet(name):\n    if not name.strip():\n        raise ValueError('blank')\n"
            "    return 'Hello, ' + name + '!'\n", encoding="utf-8")
        self.command("seal", "--run", str(self.run))
        self.assertEqual(self.command("evaluate", "--run", str(self.run), "--trusted-local")["status"], "PASS")
        self.assertIsNone(self.command("inspect", "--run", str(self.run))["generation"])

    def test_inspection_distinguishes_historical_pass_and_current_tampering(self):
        self.prepare()
        self.command("generate", "--run", str(self.run), "--trusted-local")
        self.command("seal", "--run", str(self.run))
        self.command("evaluate", "--run", str(self.run), "--trusted-local")
        (self.run / "artifacts/candidate/greeting.py").write_text("tampered")
        result = self.command("inspect", "--run", str(self.run))
        self.assertEqual(result["integrity"], "UNVERIFIED")
        self.assertIn("digests", result["integrity_error"])
        self.assertEqual(result["evaluations"][0]["result"]["status"], "PASS")

    def test_inspection_reports_missing_frozen_inputs(self):
        self.prepare()
        shutil.rmtree(self.run / "inputs")
        result = self.command("inspect", "--run", str(self.run))
        self.assertEqual(result["integrity"], "UNVERIFIED")

    def test_inspection_reports_a_removed_seal(self):
        self.prepare()
        self.command("seal", "--run", str(self.run))
        (self.run / "seal.json").unlink()
        result = self.command("inspect", "--run", str(self.run))
        self.assertEqual(result["integrity"], "UNVERIFIED")
        self.assertIn("seal.json", result["integrity_error"])

    def test_trust_requirement_and_unsuccessful_exit_codes_survive_launcher(self):
        self.prepare(checks=False)
        denied = self.command("generate", "--run", str(self.run), expected=1)
        self.assertIn("trusted-local", denied["error"])
        self.command("generate", "--run", str(self.run), "--trusted-local")
        self.command("seal", "--run", str(self.run))
        result = self.command("evaluate", "--run", str(self.run), "--trusted-local", expected=3)
        self.assertEqual(result["status"], "UNVERIFIED")

    def test_prepared_and_incomplete_evaluations_are_inspectable(self):
        self.prepare()
        (self.run / ".controller.lock").write_text("{}")
        evaluation = self.run / "evaluations/interrupted"
        evaluation.mkdir(parents=True)
        (evaluation / "state.json").write_text('{"status":"EVALUATING"}')
        before = inventory(self.run)
        result = self.command("inspect", "--run", str(self.run))
        self.assertTrue(result["controller_locked"])
        self.assertEqual(result["integrity"], "NOT_SEALED")
        self.assertIsNone(result["evaluations"][0]["result"])
        self.assertEqual(inventory(self.run), before)

    def test_doctor_detects_claude_session_without_launching_it(self):
        info = self.command("doctor", extra_env={"CLAUDECODE": "1"})
        self.assertTrue(info["claude_code_session"])
        self.assertFalse(info["authentication_checked"])

    def test_package_has_shared_runtime_and_matching_host_manifests(self):
        manifests = [json.loads((self.plugin / name).read_text()) for name in (
            "plugin.json", ".claude-plugin/plugin.json", ".codex-plugin/plugin.json")]
        self.assertEqual({manifest["name"] for manifest in manifests}, {"forge-eval"})
        self.assertEqual({manifest["version"] for manifest in manifests}, {"0.1.0-alpha.1"})
        for manifest in manifests[1:]:
            self.assertEqual((self.plugin / manifest["skills"]).resolve(), self.plugin / "skills")
        for name in (".git", ".forge-eval", ".venv", "tests", "scripts", "dist"):
            self.assertFalse((self.plugin / name).exists(), name)
        codex_marketplace = json.loads((self.plugin / ".agents/plugins/marketplace.json").read_text())
        self.assertEqual(codex_marketplace["plugins"][0]["source"]["path"], "./")

    def test_build_refuses_existing_output(self):
        with self.assertRaisesRegex(ValueError, "already exists"):
            builder.build(self.plugin)
        self.assertEqual(inventory(self.plugin), self.before)

    def test_build_rejects_links_before_creating_output(self):
        source = self.root / "linked source"
        shutil.copytree(self.plugin, source)
        (source / "skills/outside").symlink_to(self.workspace, target_is_directory=True)
        output = self.root / "rejected"
        with self.assertRaisesRegex(ValueError, "links"):
            builder.build(output, source=source)
        self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
