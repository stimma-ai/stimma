import base64
import importlib.util
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import UTC, datetime, timedelta
from pathlib import Path

spec = importlib.util.spec_from_file_location('release_cleanup', Path(__file__).parents[1] / 'release_cleanup.py')
cleanup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cleanup)
NOW = datetime(2026, 10, 19, tzinfo=UTC)


def obj(key, days=100, size=100):
    return {'Key': key, 'Size': size, 'LastModified': NOW - timedelta(days=days), 'ETag': '"etag"'}


def release(channel, number, days=100, platform='linux-x86_64'):
    version = f'1.0.1-{channel}.{number}'
    return obj(f'stimma/{channel}/{platform}/{version}/app.tar.gz', days)


def latest(channel, number, platform='linux-x86_64'):
    key = f'stimma/{channel}/{platform}/latest.json'
    return key, {'etag': '"feed"', 'manifest': {
        'version': f'1.0.1-{channel}.{number}',
        'platforms': {platform: {'url': f'https://updates.example/stimma/{channel}/{platform}/1.0.1-{channel}.{number}/app.tar.gz'}},
    }}


def plan(items, feeds):
    return cleanup.plan_cleanup({o['Key']: o for o in items}, dict(feeds), NOW)[0]


class Store:
    def __init__(self, items, feeds):
        self.objects = {o['Key']: o for o in items}
        self.feeds = dict(feeds)
        for key, feed in feeds:
            self.objects[key] = obj(key)
            self.objects[key]['ETag'] = feed['etag']
        self.deletions = []
        self.fail_delete = False
        self.changed_feed = False
        self.pages = 0

    def get_paginator(self, name):
        assert name == 'list_objects_v2'
        return self

    def paginate(self, **kwargs):
        self.pages += 1
        rows = [o for k, o in sorted(self.objects.items()) if k.startswith(kwargs['Prefix'])]
        # Force pagination so no test can accidentally rely on a single page.
        for index in range(0, len(rows), 2):
            yield {'Contents': rows[index:index + 2]}

    def get_object(self, Bucket, Key):
        feed = self.feeds[Key]
        return {'ETag': feed['etag'], 'Body': io.BytesIO(json.dumps(feed['manifest']).encode())}

    def head_object(self, **kwargs):
        return {'ETag': '"changed"' if self.changed_feed else self.objects[kwargs['Key']]['ETag']}

    def delete_objects(self, Bucket, Delete):
        self.deletions.extend(o['Key'] for o in Delete['Objects'])
        if self.fail_delete:
            return {'Errors': [{'Key': Delete['Objects'][0]['Key'], 'Code': 'AccessDenied'}]}
        for item in Delete['Objects']:
            del self.objects[item['Key']]
        return {'Deleted': Delete['Objects']}


class RetentionTests(unittest.TestCase):
    def test_alpha_removed_but_production_and_other_prefixes_are_never_candidates(self):
        keys = ['stimma/alpha/anything/latest.json', 'stimma/alpha/old/file',
                'stimma/production/platform/ancient/file', 'stimma/notes/index.json',
                'stimma/sandbox/old/file', 'stimma/alpha-other/file']
        self.assertEqual([o['Key'] for o in plan([obj(k) for k in keys], [])], keys[:2])

    def test_latest_three_canaries_survive_even_if_all_are_old(self):
        items = [release('canary', n) for n in range(1, 6)]
        self.assertEqual(plan(items, [latest('canary', 5)]), items[:2])

    def test_stale_feed_and_newer_uploaded_versions_are_both_protected(self):
        items = [release('canary', n) for n in range(1, 7)]
        self.assertEqual(plan(items, [latest('canary', 1)]), items[1:3])

    def test_latest_is_preserved_separately_on_each_platform(self):
        items = [release('canary', n, platform=p) for p in ('linux-x86_64', 'linux-aarch64') for n in range(1, 5)]
        feeds = [latest('canary', 4), latest('canary', 1, 'linux-aarch64')]
        self.assertEqual([o['Key'] for o in plan(items, feeds)], [items[0]['Key']])

    def test_canary_fourteen_days_and_beta_ninety_days(self):
        for channel, days in [('canary', 14), ('beta', 90)]:
            with self.subTest(channel=channel):
                items = [release(channel, 1, days + 1), release(channel, 2, days),
                         release(channel, 3, days - 1), release(channel, 4), release(channel, 5)]
                # Canary keeps the three newest versions in addition to age retention.
                self.assertEqual(plan(items, [latest(channel, 5)]), [items[0]] + ([items[3]] if channel == 'beta' else []))

    def test_new_object_in_old_group_keeps_entire_group(self):
        items = [release('canary', n) for n in range(1, 6)]
        recent = obj(items[0]['Key'] + '.sig', days=1)
        self.assertEqual(plan(items + [recent], [latest('canary', 5)]), [items[1]])

    def test_root_archives_blockmaps_and_legacy_aliases_share_version_group(self):
        prefix = 'stimma/beta/darwin-aarch64/'
        current = [obj(prefix + path) for path in ('1.0.1-beta.5/app.tar.gz', '1.0.1-5/app.dmg',
                   'Stimma Beta-1.0.1-beta.5-arm64.dmg', 'Stimma Beta-1.0.1-beta.5-arm64.dmg.blockmap')]
        old = obj(prefix + 'Stimma Beta-1.0.1-beta.1-arm64.dmg')
        self.assertEqual(plan(current + [old], [latest('beta', 5, 'darwin-aarch64')]), [old])

    def test_unknown_keys_preserved_and_missing_or_broken_feeds_abort(self):
        unknown = obj('stimma/canary/linux-x86_64/keep-me.txt')
        self.assertEqual(plan([unknown], []), [])
        with self.assertRaisesRegex(RuntimeError, 'Missing latest.json'):
            plan([release('canary', 1)], [])
        with self.assertRaisesRegex(RuntimeError, 'missing artifact'):
            plan([release('canary', 1)], [latest('canary', 2)])
        key, feed = latest('canary', 1)
        feed['manifest']['version'] = 'oops'
        with self.assertRaises(ValueError):
            plan([release('canary', 1)], [(key, feed)])

    def test_signed_headless_and_yaml_feeds_pin_different_versions(self):
        items = [release('canary', n) for n in range(1, 6)]
        store = Store(items, [latest('canary', 1)])
        key = 'stimma/canary/linux-x86_64/latest.json'
        manifest = store.feeds[key]['manifest']
        store.feeds[key]['manifest'] = {'payload': base64.b64encode(json.dumps(manifest).encode()).decode()}
        yaml_key = 'stimma/canary/linux-x86_64/latest-linux.yml'
        store.objects[yaml_key] = obj(yaml_key)
        original = store.get_object
        store.get_object = lambda **kw: ({'ETag': '"yaml"', 'Body': io.BytesIO(
            b'version: 1.0.1-canary.2\nfiles:\n  - url: 1.0.1-canary.2/app.tar.gz\n')}
            if kw['Key'] == yaml_key else original(**kw))
        feeds = cleanup.read_feeds(store, 'bucket', store.objects)
        self.assertEqual(plan(items, feeds.items()), [])

    def test_dry_run_never_deletes_and_apply_verifies_production_and_receipt(self):
        items = [obj('stimma/alpha/old/file'), obj('stimma/production/old/file')]
        store = Store(items, [])
        with redirect_stdout(io.StringIO()):
            cleanup.execute(store, 'bucket', now=NOW)
        self.assertEqual(store.deletions, [])
        with tempfile.TemporaryDirectory() as tmp, redirect_stdout(io.StringIO()):
            path = Path(tmp) / 'receipt.json'
            report = cleanup.execute(store, 'bucket', now=NOW, apply=True, report_path=path)
            self.assertTrue(json.loads(path.read_text())['verified'])
        self.assertEqual(report['deleted'], [items[0]['Key']])
        self.assertIn(items[1]['Key'], store.objects)

    def test_feed_change_or_delete_error_stops_sweep_and_records_failure(self):
        for failure in ('changed_feed', 'fail_delete'):
            store = Store([obj('stimma/alpha/old/file'), release('canary', 5)], [latest('canary', 5)])
            setattr(store, failure, True)
            with tempfile.TemporaryDirectory() as tmp, redirect_stdout(io.StringIO()):
                path = Path(tmp) / 'receipt.json'
                with self.assertRaises(RuntimeError):
                    cleanup.execute(store, 'bucket', now=NOW, apply=True, report_path=path)
                report = json.loads(path.read_text())
                self.assertTrue(report['errors'])
                self.assertFalse(report['verified'])
            if failure == 'changed_feed':
                self.assertEqual(store.deletions, [])

    def test_object_overwritten_between_plan_and_apply_is_preserved(self):
        key = 'stimma/alpha/old/file'
        store = Store([obj(key)], [])
        original = store.paginate

        def paginate(**kw):
            if store.pages == 1:
                store.objects[key] = {**store.objects[key], 'ETag': '"new"'}
            yield from original(**kw)

        store.paginate = paginate
        with tempfile.TemporaryDirectory() as tmp, redirect_stdout(io.StringIO()):
            cleanup.execute(store, 'bucket', now=NOW, apply=True, report_path=Path(tmp) / 'report.json')
        self.assertEqual(store.deletions, [])


if __name__ == '__main__':
    unittest.main()
