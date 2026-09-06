#!/usr/bin/env python3
"""Install Shopify changelog for Codex and/or Claude Code (macOS/Linux/WSL)."""
import argparse
import json
import os
from pathlib import Path
import shutil
import shlex
import sqlite3
import sys

HOOK_LABEL = 'Shopify changelog project check'

INSTRUCTION_HEADING = "## Shopify development context"
INSTRUCTION_BLOCK = """## Shopify development context

When planning, implementing, debugging, or reviewing Shopify work that depends on current platform capabilities, API behavior, version compatibility, rollouts, or deprecations, automatically consult the installed `shopify-changelog` skill alongside official Shopify documentation. Select it from the task context; do not require me to name the skill or ask for a changelog check. Follow its refresh and search workflow, read relevant full entries, and verify applicability to the project's version and store context before using an announcement. Keep the check focused on the task, and mention findings when they affect the implementation or answer. Unrelated edits in a Shopify repository do not need a changelog check.
"""
LEGACY_INSTRUCTION_BLOCK = INSTRUCTION_BLOCK
INSTRUCTION_BLOCK = INSTRUCTION_BLOCK.replace('Follow its refresh and search workflow, read relevant full entries,',
    'Run its project-aware check for the current project (refreshing stale feeds), read relevant full entries,')


def prepare_hooks(skill, home, codex_home, agent):
    command = shlex.join([sys.executable, str(skill / 'scripts/shopify_updates.py'), 'hook'])
    paths = []
    if agent in ('codex', 'both'):
        paths.append(codex_home / 'hooks.json')
    if agent in ('claude', 'both'):
        paths.append(home / '.claude/settings.json')
    plans = []
    for path in paths:
        config = json.loads(path.read_text()) if path.exists() else {}
        if not isinstance(config, dict) or not isinstance(config.get('hooks', {}), dict):
            raise ValueError(f'Unexpected hooks configuration: {path}')
        hooks = config.setdefault('hooks', {})
        for event in ('SessionStart', 'UserPromptSubmit'):
            groups = hooks.get(event, [])
            if not isinstance(groups, list):
                raise ValueError(f'Unexpected {event} hooks in {path}')
            preserved = []
            for group in groups:
                if not isinstance(group, dict) or not isinstance(group.get('hooks'), list):
                    raise ValueError(f'Unexpected hook group in {path}')
                handlers = [h for h in group['hooks'] if not (isinstance(h, dict) and h.get('statusMessage') == HOOK_LABEL)]
                if handlers:
                    preserved.append({**group, 'hooks': handlers})
            hooks[event] = preserved + [{'hooks': [{'type': 'command', 'command': command,
                                                   'timeout': 8, 'statusMessage': HOOK_LABEL}]}]
        plans.append((path, json.dumps(config, indent=2) + '\n'))
    return plans


def write_hooks(plans):
    import tempfile
    for path, content in plans:
        if path.exists() and path.read_text() == content:
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        backup = path.with_name(path.name + '.shopify-changelog.bak')
        if path.exists() and not backup.exists():
            shutil.copy2(path, backup)
        with tempfile.NamedTemporaryFile(mode='w', dir=path.parent, delete=False) as tmp:
            tmp.write(content)
            temporary = Path(tmp.name)
        try:
            if path.exists():
                temporary.chmod(path.stat().st_mode & 0o777)
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)
        print(f'Installed project context hooks: {path}')


def install(skill, home, codex_home, agent="both", auto_reference=False, hooks=False):
    targets = {home / ".local/bin/shopify-updates": skill / "scripts/shopify_updates.py"}
    instruction_files = []
    if agent in ("codex", "both"):
        # Skills CLI installs here; Codex already discovers this universal location.
        if skill.resolve() != (home / '.agents/skills/shopify-changelog').resolve():
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
            if INSTRUCTION_HEADING in existing and INSTRUCTION_BLOCK.strip() not in existing and LEGACY_INSTRUCTION_BLOCK.strip() not in existing:
                raise ValueError(f"Existing Shopify instructions need review before updating: {path}")
    hook_plans = prepare_hooks(skill, home, codex_home, agent) if hooks else []
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
            if LEGACY_INSTRUCTION_BLOCK.strip() in existing:
                path.write_text(existing.replace(LEGACY_INSTRUCTION_BLOCK.strip(), INSTRUCTION_BLOCK.strip()))
            elif INSTRUCTION_BLOCK.strip() not in existing:
                path.parent.mkdir(parents=True, exist_ok=True)
                with path.open("a") as output:
                    output.write(("\n\n" if existing else "") + INSTRUCTION_BLOCK)
            print(f"Automatic Shopify task guidance installed: {path}")
    write_hooks(hook_plans)
    if hooks and agent in ('codex', 'both'):
        print('Codex: review and trust the new hooks with /hooks. Setup does not bypass hook trust or disabled-hook policies.')
    print("Start a new agent session. Run ~/.local/bin/shopify-updates sync to build the archive.")
    if not auto_reference:
        print("Global instructions unchanged. Add --auto-reference to install standing Shopify guidance.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--agent", choices=("codex", "claude", "both"), default="both")
    parser.add_argument("--auto-reference", action="store_true",
                        help="Append standing Shopify guidance to selected agents' user instruction files")
    parser.add_argument('--hooks', action='store_true', help='Install offline SessionStart/UserPromptSubmit context hooks; preserves existing hooks')
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
        install(Path(__file__).resolve().parents[1], home, codex_home, args.agent, args.auto_reference, args.hooks)
        return 0
    except (OSError, ValueError, sqlite3.Error) as exc:
        print(f"Setup failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
