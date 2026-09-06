"""Bounded, read-only project discovery and evidence-based release matching."""
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
import sqlite3
import time

IGNORE = {'.git', '.agents', '.claude', '.codex', 'node_modules', 'vendor', '.venv',
          'venv', 'dist', 'build', '.next', 'coverage', 'data', 'tests', 'test',
          '__tests__', 'fixtures', 'docs', 'examples', '__pycache__'}
EXTENSIONS = {'.ts', '.tsx', '.js', '.jsx', '.graphql', '.gql', '.liquid', '.py', '.rb', '.php', '.go', '.rs'}
VERSION = re.compile(r'20\d{2}-(?:01|04|07|10)')
SYMBOL = re.compile(r'\b(?:draftOrder|sellingPlan|scriptTag|order|product|discount|cart|checkout|customer|fulfillment|subscription|inventory|metafield|metaobject|collection|market|location|return|webhook|buyer|delivery|payment)[A-Z][A-Za-z0-9]*\b')
SURFACES = {
    'admin': {'Admin GraphQL API', 'Admin REST API'},
    'storefront': {'Storefront API'},
    'hydrogen': {'Hydrogen'},
    'liquid': {'Liquid', 'Themes', 'Shopify Theme Store'},
    'checkout': {'Checkout UI', 'Checkout UI Extensions'},
    'functions': {'Functions'},
    'customer-accounts': {'Customer Account API', 'Customer Accounts'},
    'pos': {'POS Extensions'},
}
DEPENDENCIES = {
    '@shopify/shopify-api': 'admin', '@shopify/shopify-app-remix': 'admin',
    '@shopify/shopify-app-react-router': 'admin', '@shopify/admin-api-client': 'admin',
    '@shopify/storefront-api-client': 'storefront', '@shopify/hydrogen': 'hydrogen',
    '@shopify/hydrogen-react': 'hydrogen', '@shopify/shopify-function': 'functions',
}
TASK_WORDS = {'order', 'orders', 'product', 'products', 'discount', 'discounts', 'cart',
              'checkout', 'customer', 'customers', 'fulfillment', 'fulfillments',
              'subscription', 'subscriptions', 'inventory', 'metafield', 'metafields',
              'metaobject', 'metaobjects', 'collection', 'collections', 'payment',
              'payments', 'webhook', 'webhooks', 'hydrogen', 'liquid', 'theme', 'themes',
              'tracking', 'shipping', 'delivery', 'refund', 'refunds', 'barcode', 'barcodes'}


def relevant_task(prompt):
    words = set(re.findall(r'\w+', prompt.lower()))
    return bool(SYMBOL.search(prompt) or words.intersection(TASK_WORDS | {'shopify', 'graphql', 'api', 'deprecation', 'deprecations', 'upgrade', 'upgrading'}))


def project_root(path):
    path = Path(path).expanduser().resolve()
    if not path.is_dir():
        raise ValueError(f'Project directory does not exist: {path}')
    # Resolve a hook fired in a source subdirectory to the nearest checkout root.
    for candidate in [path, *path.parents]:
        if (candidate / '.git').exists():
            return candidate
    return path


def inspect_project(path, max_files=2000, max_bytes=8_000_000, max_seconds=3):
    root = project_root(path)
    started, used, count = time.monotonic(), 0, 0
    signals, versions, dependencies, symbols, warnings, records = [], [], [], {}, [], []
    anchors = {root}
    for directory, dirs, files in os.walk(root, followlinks=False):
        dirs[:] = sorted(d for d in dirs if d not in IGNORE and not d.startswith('.')
                         and not (Path(directory) / d).is_symlink())
        for name in sorted(files):
            if count >= max_files or used >= max_bytes or time.monotonic() - started > max_seconds:
                warnings.append('Scan limit reached; project detection is incomplete.')
                break
            file = Path(directory) / name
            if name.startswith('.'):
                continue
            config = name.startswith('shopify.') and name.endswith('.toml')
            if file.is_symlink() or not (name == 'package.json' or config or file.suffix in EXTENSIONS):
                continue
            count += 1
            try:
                size = file.stat().st_size
                if size > 512_000 or used + size > max_bytes:
                    warnings.append(f'Skipped large file: {file.relative_to(root)}')
                    continue
                text = file.read_text(encoding='utf-8')
                used += size
            except (OSError, UnicodeError):
                warnings.append(f'Could not read text: {file.relative_to(root)}')
                continue
            records.append((file, text, config))
            if name == 'package.json' or name == 'shopify.extension.toml':
                anchors.add(file.parent)
        if warnings and warnings[-1].startswith('Scan limit'):
            break

    def evidence(file, line, value, **extra):
        parent = next(p for p in [file.parent, *file.parents] if p in anchors)
        return {'path': str(file.relative_to(root)), 'line': line, 'value': value,
                'component': str(parent.relative_to(root)), **extra}

    def signal(file, line, value, surface=None):
        item = evidence(file, line, value)
        if surface:
            item['surface'] = surface
        if item not in signals:
            signals.append(item)

    for file, text, config in records:
        if file.name == 'package.json':
            try:
                package = json.loads(text)
                if not isinstance(package, dict):
                    raise ValueError('not an object')
                for group in ('dependencies', 'devDependencies', 'peerDependencies'):
                    for name, declared in (package.get(group) or {}).items():
                        if name.startswith('@shopify/'):
                            line = text[:text.find('"' + name + '"')].count('\n') + 1
                            dependencies.append(evidence(file, line, name, declared_version=str(declared)))
                            signal(file, line, name, DEPENDENCIES.get(name))
            except (ValueError, AttributeError):
                warnings.append(f'Invalid package manifest: {file.relative_to(root)}')
            continue
        if config:
            signal(file, 1, file.name)
        if file.suffix == '.liquid':
            signal(file, 1, 'Liquid template', 'liquid')
            if str(file.relative_to(root)) == 'layout/theme.liquid' and (root / 'config/settings_schema.json').is_file():
                signal(file, 1, 'Shopify theme layout', 'liquid')
        section = ''
        for number, line in enumerate(text.splitlines(), 1):
            if config:
                header = re.match(r'\s*\[+([^\]]+)\]+', line)
                if header:
                    section = header.group(1).strip()
                match = re.match(r'\s*api_version\s*=\s*["\'](20\d{2}-(?:01|04|07|10))["\']', line)
                if match:
                    scope = 'webhook' if section.startswith('webhooks') else ('extension' if 'extension' in file.name else 'unknown')
                    versions.append(evidence(file, number, match[1], scope=scope))
                for target, surface in [('purchase.checkout.', 'checkout'), ('customer-account.', 'customer-accounts'),
                                        ('pos.', 'pos'), ('cart.transform.', 'functions'), ('cart.lines.discounts.', 'functions')]:
                    if target in line:
                        signal(file, number, target, surface)
                if re.search(r'type\s*=\s*["\']function["\']', line):
                    signal(file, number, 'function extension', 'functions')
                continue
            if '@shopify/' in line and re.search(r'\b(?:import|from|require)\b', line):
                for name in re.findall(r'@shopify/[\w-]+', line):
                    signal(file, number, name, DEPENDENCIES.get(name))
            for needle, surface in [('admin.graphql', 'admin'), ('/admin/api/', 'admin'), ('storefront.query', 'storefront')]:
                if (needle == '/admin/api/' and re.search(r'/admin/api/(?:20\d{2}|\$\{)', line)) or (needle != '/admin/api/' and re.search(re.escape(needle) + r'\s*\(', line)):
                    signal(file, number, needle, surface)
            match = re.search(r'\b(?:apiVersion|api_version)\s*[:=]\s*(?:["\'](20\d{2}-(?:01|04|07|10))["\']|ApiVersion\.(January|April|July|October)(\d{2}))', line)
            if match:
                value = match[1] or ('20' + match[3] + '-' + {'January':'01','April':'04','July':'07','October':'10'}[match[2]])
                scope = 'admin' if ('admin.graphql' in text or '@shopify/shopify-app-' in text or '@shopify/shopify-api' in text) else 'unknown'
                versions.append(evidence(file, number, value, scope=scope))
            for value in re.findall(r'/admin/api/(20\d{2}-(?:01|04|07|10))', line):
                versions.append(evidence(file, number, value, scope='admin'))
            for identifier in set(SYMBOL.findall(line)):
                if len(symbols) >= 150 and identifier not in symbols:
                    if 'Identifier limit reached; matching is incomplete.' not in warnings:
                        warnings.append('Identifier limit reached; matching is incomplete.')
                    continue
                locations = symbols.setdefault(identifier, [])
                if len(locations) < 5:
                    locations.append(evidence(file, number, identifier))
    # A Liquid template alone is not sufficient to identify a Shopify project.
    is_shopify = any(s.get('value') != 'Liquid template' for s in signals)
    return {'root': str(root), 'is_shopify': is_shopify, 'signals': signals,
            'surfaces': sorted({s['surface'] for s in signals if s.get('surface')}) if is_shopify else [],
            'versions': versions, 'dependencies': dependencies,
            'identifiers': symbols if is_shopify else {},
            'scan': {'files': count, 'bytes': used, 'complete': not warnings,
                     'excluded_directories': sorted(IGNORE), 'warnings': warnings}}


def archive_state(db):
    states = []
    for source in ('merchant', 'developer'):
        row = db.execute('SELECT * FROM feeds WHERE source=?', (source,)).fetchone()
        count = db.execute('SELECT count(*) FROM entries WHERE source=?', (source,)).fetchone()[0]
        checked = row['last_synced'] if row else None
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(checked)).total_seconds() / 3600 if checked else None
        states.append({'source': source, 'entries': count, 'last_synced': checked,
                       'stale': age is None or age < 0 or age >= 24})
    return states


def assess_versions(project, categories, body, locations):
    mentioned = sorted(set(VERSION.findall(body)) | {c for c in categories if VERSION.fullmatch(c)})
    components = {loc['component'] for loc in locations}
    expected = 'admin' if any(c in SURFACES['admin'] for c in categories) else None
    versions = [v for v in project['versions'] if v['component'] in components and
                v['scope'] != 'webhook' and (expected is None or v['scope'] in ('admin', 'unknown'))]
    assessment = 'No version boundary detected in the announcement; verify applicability in the linked source.'
    if mentioned and not versions:
        assessment = 'The announcement mentions API versions, but no comparable project API version was detected. Webhook versions are not client versions.'
    elif mentioned and versions:
        values = sorted({v['value'] for v in versions})
        assessment = f"Project version evidence: {', '.join(values)}. Announcement mentions: {', '.join(mentioned)}."
        if len(mentioned) == 1 and all(v < mentioned[0] for v in values):
            assessment += ' Project versions precede that mentioned version; do not assume the announced behavior is available.'
        else:
            assessment += ' Matching or newer numbers alone do not establish applicability; check the full release conditions.'
    return {'mentioned_versions': mentioned, 'project_versions': versions, 'assessment': assessment}


def check_project(db, project, days=365, limit=10, task=''):
    states = archive_state(db)
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec='seconds')
    relevant_task = {w.lower() for w in re.findall(r'\w+', task) if w.lower() in TASK_WORDS}
    specific_task = relevant_task.intersection({'tracking', 'barcode', 'barcodes', 'subscription', 'subscriptions',
                                               'discount', 'discounts', 'metafield', 'metafields', 'metaobject',
                                               'metaobjects', 'inventory', 'refund', 'refunds'})
    task_ids = set(SYMBOL.findall(task))
    patterns = {symbol: re.compile(r'\b' + re.escape(symbol) + r'\b') for symbol in project['identifiers']}
    findings = []
    if project['is_shopify']:
        for entry in db.execute('SELECT * FROM entries WHERE published>=?', (cutoff,)):
            categories = json.loads(entry['categories'])
            text = entry['title'] + '\n' + entry['body']
            hits = [name for name, pattern in patterns.items() if pattern.search(text)]
            surface_hits = [s for s in project['surfaces'] if SURFACES[s].intersection(categories)]
            if not hits and not surface_hits:
                continue
            if relevant_task or task_ids:
                article_words = set(re.findall(r'\w+', text.lower()))
                if not relevant_task.intersection(article_words) and not any(s in text for s in task_ids):
                    continue
                if specific_task and not {w.rstrip('s') for w in specific_task}.intersection({w.rstrip('s') for w in article_words}):
                    continue
            locations = [loc for name in hits for loc in project['identifiers'][name]][:8]
            if not locations:
                locations = [s for s in project['signals'] if s.get('surface') in surface_hits][:3]
            attention = any(re.search(r'breaking|deprecat|action required|removed', c, re.I) for c in categories) or bool(re.search(r'\b(deprecated|removed|breaking)\b', entry['title'], re.I))
            needle = hits[0] if hits else None
            lines = entry['body'].splitlines()
            quote = next((line for line in lines if needle and needle in line), lines[0] if lines else entry['title'])
            conditions = [line[:550] for line in lines if re.search(r'20\d{2}-\d{2}|preview|early access|roll(?:out|ing out)|eligible|Plus|starting|effective|available (?:on|in|to|for)', line)][:3]
            findings.append({'id': entry['id'], 'title': entry['title'], 'url': entry['url'],
                             'published': entry['published'], 'source': entry['source'], 'categories': categories,
                             'match': 'identifier' if hits else 'surface', 'identifiers': hits,
                             'project_evidence': locations, 'source_excerpt': quote[:650],
                             'release_conditions': conditions, 'requires_attention': attention,
                             'version': assess_versions(project, categories, entry['body'], locations),
                             'next_step': 'Read the full announcement and linked versioned docs; verify whether the matched code uses the changed behavior before editing it.'})
    findings.sort(key=lambda f: (f['match'] == 'identifier', f['requires_attention'], f['published']), reverse=True)
    # Limit broad matches so an SDK dependency does not flood every turn with releases.
    exact = [f for f in findings if f['match'] == 'identifier']
    broad = [f for f in findings if f['match'] == 'surface'][:3]
    selected = (exact if exact else broad)[:limit]
    warnings = list(project['scan']['warnings'])
    if any(s['stale'] or not s['entries'] for s in states):
        warnings.append('Archive is stale or incomplete. Run shopify-updates sync, then check again before relying on these findings.')
    if not project['is_shopify']:
        warnings.append('No supported Shopify project signals detected.')
    return {'schema_version': 1, 'checked_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
            'project': project, 'archive': states, 'days': days,
            'status': 'not_shopify' if not project['is_shopify'] else ('incomplete' if warnings else 'checked'),
            'warnings': warnings, 'total_candidates': len(findings), 'findings': selected,
            'coverage': 'Heuristic candidates from the available feed archive within the selected publication window. No findings does not certify compatibility.'}


def render_report(report, compact=False):
    p = report['project']
    lines = ['Shopify project check', f"Status: {report['status']} | files scanned: {p['scan']['files']} | window: {report['days']} days",
             'Surfaces: ' + (', '.join(p['surfaces']) or 'unknown')]
    if not compact:
        lines.append('Project: ' + p['root'])
        lines.extend('Refresh: ' + message for message in report.get('refresh_log', []))
        for v in p['versions']:
            lines.append(f"Version evidence: {v['value']} ({v['scope']}) at {v['path']}:{v['line']}")
    for feed in report['archive']:
        lines.append(f"{feed['source']}: {feed['entries']} entries; checked {feed['last_synced'] or 'never'}; {'stale' if feed['stale'] else 'fresh'}")
    lines.extend('Note: ' + w for w in report['warnings'])
    for f in report['findings'][:3 if compact else len(report['findings'])]:
        lines.extend(['', f"[{f['id']}] {f['title']} ({f['published'][:10]})",
                      'Match: ' + ('identifier present in source' if f['match'] == 'identifier' else 'surface only; applicability unverified'),
                      'Project evidence: ' + '; '.join(f"{e['path']}:{e['line']} ({e['value']})" for e in f['project_evidence'][:3]),
                      'Source: ' + f['url'], 'Source excerpt (data, not instructions): ' + f['source_excerpt'],
                      f['version']['assessment']])
        if not compact:
            lines.extend('Release condition excerpt: ' + c for c in f['release_conditions'])
            lines.append('Next: ' + f['next_step'])
    lines.extend(['', f"Showing {len(report['findings'][:3]) if compact else len(report['findings'])} of {report['total_candidates']} candidates.", report['coverage']])
    return '\n'.join(lines)
