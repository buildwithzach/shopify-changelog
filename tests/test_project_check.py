import contextlib
from datetime import datetime, timezone
from email.utils import format_datetime
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / 'shopify-changelog/scripts'
spec = importlib.util.spec_from_file_location('cli_project_tests', SCRIPTS / 'shopify_updates.py')
cli = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cli)
project_check = cli.project_check


def announcement(slug, title, body, categories=('Admin GraphQL API', '2026-10')):
    cats = ''.join('<category>' + c + '</category>' for c in categories)
    return f'''<rss><channel><item><title>{title}</title>
    <link>https://shopify.dev/changelog/{slug}</link>
    <pubDate>{format_datetime(datetime.now(timezone.utc))}</pubDate>{cats}
    <description><![CDATA[{body}]]></description></item></channel></rss>'''.encode()


class ProjectTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / 'project'
        self.root.mkdir()
        self.db_path = Path(self.temp.name) / 'archive.sqlite3'
        self.db = cli.connect(self.db_path)

    def tearDown(self):
        self.db.close()
        self.temp.cleanup()

    def write(self, path, text):
        p = self.root / path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
        return p

    def app(self):
        self.write('package.json', json.dumps({'dependencies': {'@shopify/shopify-app-remix': '^3.0.0'}}))
        self.write('shopify.app.toml', '[webhooks]\napi_version = "2026-10"\n')
        self.write('app/shopify.ts', 'import {shopifyApp} from "@shopify/shopify-app-remix/server";\nconst apiVersion = "2026-07";\n')
        self.write('app/import.ts', 'await admin.graphql(`#graphql\nmutation Import { orderCreate(order: $order) { order { id } } }`);\n')

    def populate(self):
        cli.ingest(self.db, announcement('tracking', 'orderCreate tracking support',
                   '<p>orderCreate can accept multiple tracking numbers.</p><p>Available starting in API version 2026-10.</p>'), 'developer')
        cli.ingest(self.db, announcement('unrelated', 'New analytics capabilities', '<p>Analytics charts are updated.</p>'), 'developer')

    def test_scoped_versions_and_actionable_evidence(self):
        self.app()
        self.populate()
        profile = project_check.inspect_project(self.root)
        report = project_check.check_project(self.db, profile)
        finding = report['findings'][0]
        self.assertEqual(finding['match'], 'identifier')
        self.assertEqual(finding['identifiers'], ['orderCreate'])
        self.assertEqual(finding['project_evidence'][0]['path'], 'app/import.ts')
        self.assertEqual(finding['project_evidence'][0]['line'], 2)
        self.assertEqual([v['value'] for v in finding['version']['project_versions']], ['2026-07'])
        self.assertIn('precede', finding['version']['assessment'])
        self.assertEqual(finding['url'], 'https://shopify.dev/changelog/tracking')
        self.assertIn('2026-10', finding['release_conditions'][0])
        self.assertEqual(profile['dependencies'][0]['declared_version'], '^3.0.0')

    def test_webhook_version_does_not_establish_client_version(self):
        self.app()
        (self.root / 'app/shopify.ts').unlink()
        self.populate()
        report = project_check.check_project(self.db, project_check.inspect_project(self.root))
        self.assertEqual(report['findings'][0]['version']['project_versions'], [])
        self.assertIn('no comparable', report['findings'][0]['version']['assessment'])

    def test_task_focus_excludes_unrelated_topics(self):
        self.app()
        self.populate()
        report = project_check.check_project(self.db, project_check.inspect_project(self.root), task='Add tracking numbers to order imports')
        self.assertEqual(len(report['findings']), 1)
        self.assertEqual(report['findings'][0]['match'], 'identifier')

    def test_monorepo_version_does_not_cross_component(self):
        self.app()
        self.write('other/package.json', '{"dependencies":{"@shopify/admin-api-client":"1.0.0"}}')
        self.write('other/api.ts', 'const apiVersion = "2027-01";')
        self.populate()
        finding = project_check.check_project(self.db, project_check.inspect_project(self.root))['findings'][0]
        self.assertNotIn('2027-01', [v['value'] for v in finding['version']['project_versions']])

    def test_empty_archive_is_incomplete_not_clear(self):
        self.app()
        report = project_check.check_project(self.db, project_check.inspect_project(self.root))
        self.assertEqual(report['status'], 'incomplete')
        self.assertEqual(report['findings'], [])
        self.assertTrue(report['warnings'])

    def test_source_symlinks_and_dependencies_are_excluded(self):
        self.write('package.json', '{}')
        external = Path(self.temp.name) / 'external.ts'
        external.write_text('import x from "@shopify/shopify-api";')
        (self.root / 'external.ts').symlink_to(external)
        self.write('node_modules/x/index.ts', external.read_text())
        self.assertFalse(project_check.inspect_project(self.root)['is_shopify'])

    def test_scanner_does_not_classify_its_own_code_as_shopify_app(self):
        self.write('matcher.py', (SCRIPTS / 'project_check.py').read_text())
        self.assertFalse(project_check.inspect_project(self.root)['is_shopify'])

    def test_theme_and_extension_surfaces(self):
        self.write('layout/theme.liquid', '{{ content_for_layout }}')
        self.write('config/settings_schema.json', '[]')
        self.assertIn('liquid', project_check.inspect_project(self.root)['surfaces'])
        self.write('extensions/banner/shopify.extension.toml', 'api_version = "2026-07"\n[[extensions.targeting]]\ntarget = "purchase.checkout.block.render"')
        profile = project_check.inspect_project(self.root)
        self.assertIn('checkout', profile['surfaces'])
        self.assertEqual(profile['versions'][0]['scope'], 'extension')

    def test_scan_limits_are_visible(self):
        self.app()
        profile = project_check.inspect_project(self.root, max_files=1)
        self.assertFalse(profile['scan']['complete'])
        self.assertTrue(profile['scan']['warnings'])

    def hook(self, event, **extra):
        payload = {'cwd': str(self.root), 'hook_event_name': event, **extra}
        output = io.StringIO()
        with patch('sys.stdin', io.StringIO(json.dumps(payload))), contextlib.redirect_stdout(output):
            with patch.object(cli.subprocess, 'run', side_effect=AssertionError('Hooks must not run network commands')):
                self.assertEqual(cli.hook(self.db_path), 0)
        return output.getvalue()

    def test_hooks_inject_documented_context_offline_for_both_events(self):
        self.app()
        self.populate()
        for event in ('SessionStart', 'UserPromptSubmit'):
            response = json.loads(self.hook(event, prompt='Add order tracking'))
            self.assertEqual(response['hookSpecificOutput']['hookEventName'], event)
            self.assertIn('orderCreate', response['hookSpecificOutput']['additionalContext'])
            self.assertNotIn('decision', response)

    def test_non_shopify_hook_is_silent(self):
        self.write('package.json', '{"dependencies":{"react":"19"}}')
        self.assertEqual(self.hook('UserPromptSubmit', prompt='Build a page'), '')

    def test_unrelated_prompt_in_shopify_project_is_silent(self):
        self.app()
        self.assertEqual(self.hook('UserPromptSubmit', prompt='Make the heading blue'), '')

    def test_corrupt_archive_hook_does_not_block(self):
        self.app()
        missing_schema = Path(self.temp.name) / 'other.sqlite3'
        missing_schema.write_bytes(b'corrupted')
        with patch('sys.stdin', io.StringIO(json.dumps({'cwd': str(self.root), 'hook_event_name': 'SessionStart'}))):
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertEqual(cli.hook(missing_schema), 0)
        self.assertIn('could not complete', output.getvalue())

    def test_malformed_hook_payload_is_silent_and_non_blocking(self):
        with patch('sys.stdin', io.StringIO('not json')), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(cli.hook(self.db_path), 0)


if __name__ == '__main__':
    unittest.main()
