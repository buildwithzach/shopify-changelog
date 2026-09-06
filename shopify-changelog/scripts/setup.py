#!/usr/bin/env python3
"""Install Shopify changelog for Codex and/or Claude Code (macOS/Linux/WSL)."""
import argparse
import os
from pathlib import Path
import shutil
import sqlite3
import sys

INSTRUCTION_HEADING = "## Shopify development context"
INSTRUCTION_BLOCK = """## Shopify development context

When planning, implementing, debugging, or reviewing Shopify work that depends on current platform capabilities, API behavior, version compatibility, rollouts, or deprecations, automatically consult the installed `shopify-changelog` skill alongside official Shopify documentation. Select it from the task context; do not require me to name the skill or ask for a changelog check. Follow its refresh and search workflow, read relevant full entries, and verify applicability to the project's version and store context before using an announcement. Keep the check focused on the task, and mention findings when they affect the implementation or answer. Unrelated edits in a Shopify repository do not need a changelog check.
"""


def install(skill, home, codex_home, agent="both", auto_reference=False):
    targets = {home / ".local/bin/shopify-updates": skill / "scripts/shopify_updates.py"}
    instruction_files = []
    if agent in ("codex", "both"):
        targets[codex_home / "skills/shopify-changelog"] = skill
        instruction_files.append(codex_home / "AGENTS.md")
        if auto_reference and (codex_home / "AGENTS.override.md").exists():
            raise ValueError("AGENTS.override.md is active in your Codex user directory. "
                             "Add the Shopify instruction there manually; no files were changed.")
    if agent in ("claude", "both"):
        targets[home / ".claude/skills/shopify-changelog"] = skill
        instruction_files.append(home / ".claude/CLAUDE.md")
    for target, source in targets.items():
        if target.exists() or target.is_symlink():
            if not target.is_symlink() or target.resolve() != source.resolve():
                raise ValueError(f"Refusing to replace existing path: {target}")
    if auto_reference:
        for path in instruction_files:
            existing = path.read_text() if path.exists() else ""
            if INSTRUCTION_HEADING in existing and INSTRUCTION_BLOCK.strip() not in existing:
                raise ValueError(f"Existing Shopify instructions need review before updating: {path}")
    executable = skill / "scripts/shopify_updates.py"
    executable.chmod(executable.stat().st_mode | 0o111)
    for target, source in targets.items():
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.is_symlink():
            target.symlink_to(source, target_is_directory=source.is_dir())
        print(f"{target} -> {source}")
    if auto_reference:
        for path in instruction_files:
            existing = path.read_text() if path.exists() else ""
            if INSTRUCTION_BLOCK.strip() not in existing:
                path.parent.mkdir(parents=True, exist_ok=True)
                with path.open("a") as output:
                    output.write(("\n\n" if existing else "") + INSTRUCTION_BLOCK)
            print(f"Automatic Shopify task guidance installed: {path}")
    print("Start a new agent session. Run ~/.local/bin/shopify-updates sync to build the archive.")
    if not auto_reference:
        print("Global instructions unchanged. Add --auto-reference to install standing Shopify guidance.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--agent", choices=("codex", "claude", "both"), default="both")
    parser.add_argument("--auto-reference", action="store_true",
                        help="Append standing Shopify guidance to selected agents' user instruction files")
    args = parser.parse_args()
    try:
        if sys.version_info < (3, 9) or os.name == "nt":
            raise ValueError("Use Python 3.9+ on macOS, Linux, or Windows through WSL.")
        if not shutil.which("curl"):
            raise ValueError("curl is required. Install it before running setup.")
        with sqlite3.connect(":memory:") as db:
            db.execute("CREATE VIRTUAL TABLE check_fts USING fts5(text)")
        home = Path.home()
        codex_home = Path(os.environ.get("CODEX_HOME", str(home / ".codex"))).expanduser()
        install(Path(__file__).resolve().parents[1], home, codex_home, args.agent, args.auto_reference)
        return 0
    except (OSError, ValueError, sqlite3.Error) as exc:
        print(f"Setup failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
