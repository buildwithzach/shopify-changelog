import contextlib
import importlib.util
import io
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("setup_skill", ROOT / "shopify-changelog/scripts/setup.py")
setup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(setup)


class SetupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.home = Path(self.temp.name) / "user"
        self.codex = self.home / ".codex"
        self.skill = Path(self.temp.name) / "source/skill"
        shutil.copytree(ROOT / "shopify-changelog", self.skill,
                        ignore=shutil.ignore_patterns("data", "__pycache__"))

    def tearDown(self):
        self.temp.cleanup()

    def install(self, **kwargs):
        with contextlib.redirect_stdout(io.StringIO()):
            setup.install(self.skill, self.home, self.codex, **kwargs)

    def test_selected_agent_only_and_no_implicit_instruction_changes(self):
        self.codex.mkdir(parents=True)
        rules = self.codex / "AGENTS.md"
        rules.write_text("Keep my instructions.\n")
        self.install(agent="codex")
        self.assertEqual(rules.read_text(), "Keep my instructions.\n")
        self.assertFalse((self.home / ".claude").exists())
        command = self.home / ".local/bin/shopify-updates"
        result = subprocess.run([str(command), "--db", str(self.home / "test.sqlite3"), "status", "--json"],
                                check=True, capture_output=True, text=True)
        self.assertIn('"entries": 0', result.stdout)

    def test_auto_reference_is_idempotent_and_preserves_existing_text(self):
        self.codex.mkdir(parents=True)
        rules = self.codex / "AGENTS.md"
        rules.write_text("Existing rules.\n")
        self.install(auto_reference=True)
        self.install(auto_reference=True)
        self.assertTrue(rules.read_text().startswith("Existing rules.\n"))
        self.assertEqual(rules.read_text().count(setup.INSTRUCTION_HEADING), 1)
        self.assertTrue((self.home / ".claude/CLAUDE.md").exists())
        self.assertEqual((self.codex / "skills/shopify-changelog").resolve(), self.skill.resolve())

    def test_conflict_does_not_make_partial_install(self):
        self.codex.mkdir(parents=True)
        rules = self.codex / "AGENTS.md"
        rules.write_text(setup.INSTRUCTION_HEADING + "\nCustom policy.\n")
        with self.assertRaises(ValueError):
            self.install(auto_reference=True)
        self.assertFalse((self.home / ".local").exists())
        self.assertFalse((self.home / ".claude").exists())
        self.assertIn("Custom policy.", rules.read_text())

    def test_unrelated_destination_is_not_replaced(self):
        target = self.codex / "skills/shopify-changelog"
        target.mkdir(parents=True)
        with self.assertRaises(ValueError):
            self.install()
        self.assertTrue(target.is_dir())
        self.assertFalse(target.is_symlink())
        self.assertFalse((self.home / ".local").exists())

    def test_override_is_detected_before_instruction_install(self):
        self.codex.mkdir(parents=True)
        (self.codex / "AGENTS.override.md").write_text("Active rules")
        with self.assertRaises(ValueError):
            self.install(auto_reference=True)
        self.assertFalse((self.home / ".local").exists())


if __name__ == "__main__":
    unittest.main()
