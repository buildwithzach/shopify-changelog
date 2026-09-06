import contextlib
from datetime import datetime, timezone
from email.utils import format_datetime
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / "shopify-changelog/scripts/shopify_updates.py"
spec = importlib.util.spec_from_file_location("shopify_updates", SCRIPT)
cli = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cli)


def feed(body="<p>Checkout discounts require API 2026-10.</p>", source="developer", slug="change", title="Checkout update"):
    host = "shopify.dev" if source == "developer" else "changelog.shopify.com"
    return f"""<rss><channel><item><title>{title}</title>
    <link>https://{host}/changelog/{slug}</link>
    <pubDate>{format_datetime(datetime.now(timezone.utc))}</pubDate>
    <category>Checkout</category><description><![CDATA[{body}]]></description>
    </item></channel></rss>""".encode()


class ArchiveTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "archive.sqlite3"
        self.db = cli.connect(self.path)

    def tearDown(self):
        self.db.close()
        self.temp.cleanup()

    def run_cli(self, *args):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            result = cli.main(["--db", str(self.path), *args])
        self.assertEqual(result, 0)
        return json.loads(output.getvalue())

    def test_repeat_sync_and_edits_preserve_history_and_update_search(self):
        raw = feed("<p>legacyToken</p>")
        self.assertEqual(cli.ingest(self.db, raw, "developer")["added"], 1)
        self.assertEqual(cli.ingest(self.db, raw, "developer")["added"], 0)
        self.assertEqual(self.db.execute("SELECT count(*) FROM revisions").fetchone()[0], 0)
        changed = feed("<p>replacementToken</p>")
        self.assertEqual(cli.ingest(self.db, changed, "developer")["updated"], 1)
        self.assertEqual(self.run_cli("search", "legacyToken", "--json")["total"], 0)
        rows = self.run_cli("search", "replacementToken", "--json")["results"]
        self.assertEqual(len(rows), 1)
        detail = self.run_cli("show", str(rows[0]["id"]), "--history", "--json")
        self.assertEqual(detail["history"][0]["entry"]["body"], "legacyToken")
        self.assertEqual(detail["body"], "replacementToken")

    def test_malformed_feed_does_not_damage_archive_or_freshness(self):
        cli.ingest(self.db, feed(), "developer")
        previous = dict(self.db.execute("SELECT * FROM feeds").fetchone())
        bad = feed().replace(b"</channel>", b"<item><title>Invalid item</title></item></channel>")
        with self.assertRaises(ValueError):
            cli.ingest(self.db, bad, "developer")
        self.assertEqual(self.db.execute("SELECT count(*) FROM entries").fetchone()[0], 1)
        self.assertEqual(dict(self.db.execute("SELECT * FROM feeds").fetchone()), previous)

    def test_text_links_unicode_and_original_html_are_preserved(self):
        body = '<h2>What changed?</h2><p>Plus &amp; café</p><p>Requires 2026-10.</p><a href="/docs/api">Docs</a><script>hidden()</script>'
        cli.ingest(self.db, feed(body), "developer")
        row = self.run_cli("show", "1", "--json")
        self.assertEqual(row["content_html"], body)
        self.assertIn("Plus & café\nRequires 2026-10.", row["body"])
        self.assertNotIn("hidden()", row["body"])
        self.assertEqual(row["links"], ["https://shopify.dev/docs/api"])

    def test_search_filtering_and_punctuation(self):
        cli.ingest(self.db, feed("<p>orderCreate tracking numbers</p>"), "developer")
        cli.ingest(self.db, feed("<p>Checkout discount</p>", source="merchant"), "merchant")
        self.assertEqual(self.run_cli("search", "orderCreate(tracking)", "--json")["total"], 1)
        self.assertEqual(self.run_cli("search", "discounts", "--source", "merchant", "--json")["total"], 1)
        self.assertEqual(self.run_cli("search", "discounts", "--source", "developer", "--json")["total"], 0)
        self.assertEqual(self.run_cli("search", "orderCreate discount", "--any", "--json")["total"], 2)
        self.assertEqual(self.run_cli("search", "tracking", "--since", "2099-01-01", "--json")["total"], 0)
        self.assertEqual(self.run_cli("recent", "--days", "1", "--limit", "1", "--json")["total"], 2)

    def test_feed_removal_retains_previously_seen_entries(self):
        cli.ingest(self.db, feed(slug="old"), "developer")
        cli.ingest(self.db, feed(slug="new"), "developer")
        report = self.run_cli("status", "--json")["feeds"][1]
        self.assertEqual(report["entries"], 2)
        self.assertEqual(report["last_feed_count"], 1)

    def test_new_install_archive_lives_outside_the_skill(self):
        data_root = Path(self.temp.name) / "shared-data"
        with patch.object(cli, "LEGACY_DB", Path(self.temp.name) / "missing.sqlite3"):
            with patch.dict(os.environ, {"XDG_DATA_HOME": str(data_root)}):
                self.assertEqual(cli.default_db(), data_root / "shopify-changelog/changelog.sqlite3")

    def test_legacy_archive_keeps_its_existing_location(self):
        with patch.object(cli, "LEGACY_DB", self.path):
            self.assertEqual(cli.default_db(), self.path)

    def test_recent_sort_prioritizes_new_announcements(self):
        old = feed(slug="old", title="Checkout discounts")
        tree = cli.ET.fromstring(old)
        tree.find("./channel/item/pubDate").text = "Mon, 01 Jan 2024 12:00:00 +0000"
        old = cli.ET.tostring(tree)
        cli.ingest(self.db, old, "developer")
        cli.ingest(self.db, feed(slug="new", title="New feature"), "developer")
        rows = self.run_cli("search", "checkout", "--sort", "recent", "--json")["results"]
        self.assertTrue(rows[0]["url"].endswith("/new"))

    def test_partial_network_failure_keeps_cache_and_reports_failure(self):
        cli.ingest(self.db, feed(source="merchant"), "merchant")
        old = dict(self.db.execute("SELECT * FROM feeds WHERE source='merchant'").fetchone())
        failure = subprocess.CalledProcessError(6, "curl", stderr=b"Could not resolve host")
        success = subprocess.CompletedProcess("curl", 0, stdout=feed(), stderr=b"")
        with patch.object(cli.subprocess, "run", side_effect=[failure, success]):
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                result = cli.main(["--db", str(self.path), "sync"])
        self.assertEqual(result, 1)
        self.assertEqual(dict(self.db.execute("SELECT * FROM feeds WHERE source='merchant'").fetchone()), old)
        self.assertEqual(self.db.execute("SELECT count(*) FROM entries").fetchone()[0], 2)

    def test_freshness_skips_download(self):
        cli.ingest(self.db, feed(), "developer")
        with patch.object(cli.subprocess, "run") as fetch:
            with contextlib.redirect_stdout(io.StringIO()):
                result = cli.main(["--db", str(self.path), "sync", "--source", "developer", "--if-stale", "24"])
        self.assertEqual(result, 0)
        fetch.assert_not_called()


if __name__ == "__main__":
    unittest.main()
