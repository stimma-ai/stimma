"""Prune obsolete R2 release artifacts; production is never eligible."""

import argparse
import base64
import json
import os
import re
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import unquote, urljoin, urlsplit

RETENTION_DAYS = {'canary': 14, 'beta': 90}
KEEP_VERSIONS = {'canary': 3, 'beta': 1}
MANIFEST_NAMES = {
    'latest.json', 'download.json', 'latest.yml', 'latest-mac.yml',
    'latest-linux.yml', 'latest-linux-arm64.yml',
}
VERSION_PATTERN = r'\d+\.\d+\.\d+(?:-(?:(?:canary|beta)\.)?\d+)?'
VERSION_RE = re.compile(rf'^{VERSION_PATTERN}$')


def version_id(value, channel):
    if not isinstance(value, str) or not VERSION_RE.fullmatch(value):
        raise ValueError(f'Unrecognized {channel} release version: {value!r}')
    if ('-canary.' in value and channel != 'canary') or ('-beta.' in value and channel != 'beta'):
        raise ValueError('Release version belongs to another channel')
    # Old Electron builds used 1.2.3-4 alongside the 1.2.3-beta.4 alias.
    return tuple(map(int, re.findall(r'\d+', value)))


def artifact_group(key):
    parts = key.split('/')
    if len(parts) < 4 or parts[0] != 'stimma' or parts[1] not in RETENTION_DAYS:
        return None
    channel, platform = parts[1:3]
    if len(parts) > 4:
        value = parts[3]
    else:
        match = re.search(rf'(?<![\d.])({VERSION_PATTERN})(?!\d)', parts[3])
        if not match:
            return None
        value = match[1]
    try:
        return channel, platform, version_id(value, channel)
    except ValueError:
        return None


def inventory(client, bucket):
    objects = {}
    for page in client.get_paginator('list_objects_v2').paginate(Bucket=bucket, Prefix='stimma/'):
        for obj in page.get('Contents', []):
            key = obj['Key']
            if key in objects:
                raise RuntimeError('Duplicate object in paginated inventory; retry cleanup')
            objects[key] = obj
    return objects


def read_feeds(client, bucket, objects):
    """Read all live feed formats, including signed headless envelopes."""
    feeds = {}
    for key in sorted(objects):
        parts = key.split('/')
        if len(parts) != 4 or parts[1] not in RETENTION_DAYS or parts[3] not in MANIFEST_NAMES:
            continue
        response = client.get_object(Bucket=bucket, Key=key)
        body = response['Body']
        try:
            raw = body.read(1024 * 1024 + 1)
        finally:
            body.close()
        if len(raw) > 1024 * 1024:
            raise RuntimeError(f'Oversized release manifest: {key}')
        if key.endswith('.json'):
            manifest = json.loads(raw)
            if 'payload' in manifest:
                manifest = json.loads(base64.b64decode(manifest['payload'], validate=True))
        else:
            import yaml
            manifest = yaml.safe_load(raw)
        if not isinstance(manifest, dict):
            raise TypeError(f'Invalid release manifest: {key}')
        version_id(manifest.get('version'), parts[1])
        feeds[key] = {'etag': response['ETag'], 'manifest': manifest}
    return feeds


def feed_protection(feeds, objects):
    groups, keys = set(), set(feeds)

    def references(value):
        if isinstance(value, dict):
            for name, item in value.items():
                if name in ('url', 'path') and isinstance(item, str):
                    yield item
                else:
                    yield from references(item)
        elif isinstance(value, list):
            for item in value:
                yield from references(item)

    for key, feed in feeds.items():
        _, channel, platform, _ = key.split('/')
        manifest = feed['manifest']
        groups.add((channel, platform, version_id(manifest['version'], channel)))
        for ref in references(manifest):
            resolved = urlsplit(urljoin('https://release.invalid/' + key, ref))
            target = unquote(resolved.path).lstrip('/')
            if target not in objects:
                raise RuntimeError(f'Manifest references a missing artifact: {key} -> {target}')
            if not target.startswith(f'stimma/{channel}/{platform}/'):
                raise RuntimeError(f'Manifest references another release feed: {key} -> {target}')
            keys.add(target)
            group = artifact_group(target)
            if group:
                groups.add(group)
    return groups, keys


def plan_cleanup(objects, feeds, now):
    protected_groups, protected_keys = feed_protection(feeds, objects)
    groups = defaultdict(list)
    candidates = []
    unknown = []
    for key, obj in objects.items():
        if key.startswith('stimma/alpha/'):
            candidates.append(obj)
        else:
            group = artifact_group(key)
            if group:
                groups[group].append(obj)
            elif key not in protected_keys and key.startswith(('stimma/canary/', 'stimma/beta/')):
                unknown.append(key)
    platforms = {(c, p) for c, p, _ in groups}
    for channel, platform in platforms:
        # An absent/corrupt latest pointer must never turn into mass deletion.
        if f'stimma/{channel}/{platform}/latest.json' not in feeds:
            raise RuntimeError(f'Missing latest.json for {channel}/{platform}')
        versions = sorted({v for c, p, v in groups if (c, p) == (channel, platform)}, reverse=True)
        protected_groups.update((channel, platform, v) for v in versions[:KEEP_VERSIONS[channel]])
    for group, items in groups.items():
        channel, _, _ = group
        if group in protected_groups:
            continue
        if max(o['LastModified'] for o in items) < now - timedelta(days=RETENTION_DAYS[channel]):
            candidates.extend(items)
    return sorted(candidates, key=lambda o: o['Key']), sorted(unknown)


def summary(objects):
    result = {}
    for channel in ('alpha', 'canary', 'beta', 'production'):
        selected = [o for o in objects if o['Key'].startswith(f'stimma/{channel}/')]
        result[channel] = {'objects': len(selected), 'bytes': sum(o['Size'] for o in selected)}
    return result


def same_object(left, right):
    return all(left.get(k) == right.get(k) for k in ('ETag', 'Size', 'LastModified'))


def execute(client, bucket, *, apply=False, report_path=None, now=None):
    now = now or datetime.now(UTC)
    if apply and report_path is None:
        raise ValueError('--report is required with --apply')
    objects = inventory(client, bucket)
    feeds = read_feeds(client, bucket, objects)
    candidates, unknown = plan_cleanup(objects, feeds, now)
    report = {
        'started_at': now.isoformat(), 'apply': apply,
        'policy_days': {'alpha': 0, **RETENTION_DAYS, 'production': None},
        'before': summary(objects.values()), 'eligible': summary(candidates),
        'protected_feeds': {k: v['manifest']['version'] for k, v in feeds.items()},
        'unknown_preserved': unknown,
        'candidates': [{'key': o['Key'], 'bytes': o['Size']} for o in candidates],
        'deleted': [], 'errors': [], 'verified': False,
    }

    def save_report():
        if report_path:
            Path(report_path).write_text(json.dumps(report, indent=2) + '\n')

    save_report()
    print(json.dumps({'apply': apply, 'eligible': report['eligible'], 'unknown_preserved': len(unknown)}, indent=2))
    if not apply:
        return report
    try:
        # Re-list and re-plan immediately before deletion. Newly overwritten
        # objects and newly pinned releases cannot enter the original plan.
        current = inventory(client, bucket)
        current_feeds = read_feeds(client, bucket, current)
        current_candidates, _ = plan_cleanup(current, current_feeds, now)
        eligible_now = {o['Key'] for o in current_candidates}
        candidates = [o for o in candidates if o['Key'] in eligible_now and same_object(o, current[o['Key']])]
        for offset in range(0, len(candidates), 500):
            # Publishers advance feeds monotonically. Abort on *any* change
            # during a sweep, rather than relying on that implementation detail.
            for key, feed in current_feeds.items():
                if client.head_object(Bucket=bucket, Key=key)['ETag'] != feed['etag']:
                    raise RuntimeError('A release feed changed during cleanup; retry with a fresh plan')
            batch = candidates[offset:offset + 500]
            if any(not o['Key'].startswith(('stimma/alpha/', 'stimma/canary/', 'stimma/beta/')) for o in batch):
                raise RuntimeError('Refusing deletion outside disposable release channels')
            response = client.delete_objects(Bucket=bucket, Delete={
                'Objects': [{'Key': o['Key']} for o in batch], 'Quiet': False,
            })
            report['deleted'].extend(o['Key'] for o in response.get('Deleted', []))
            report['errors'].extend(response.get('Errors', []))
            save_report()
            if response.get('Errors') or {o['Key'] for o in response.get('Deleted', [])} != {o['Key'] for o in batch}:
                raise RuntimeError('R2 did not confirm every requested deletion; inspect the report')
        remaining = inventory(client, bucket)
        for key, obj in objects.items():
            if key.startswith('stimma/production/') and (key not in remaining or not same_object(obj, remaining[key])):
                raise RuntimeError('Production inventory changed during cleanup')
        if set(report['deleted']) & remaining.keys():
            raise RuntimeError('Deleted keys remain in the bucket')
        # Validate live feeds and all their referenced payloads after deletion.
        feed_protection(read_feeds(client, bucket, remaining), remaining)
        report['after'] = summary(remaining.values())
        report['verified'] = True
    except Exception as exc:
        report['errors'].append(str(exc))
        raise
    finally:
        save_report()
    print(json.dumps({'deleted_objects': len(report['deleted']), 'after': report['after'], 'verified': True}, indent=2))
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true', help='Delete eligible objects (default: dry run)')
    parser.add_argument('--report', type=Path, help='Write a JSON plan and deletion receipt; required with --apply')
    args = parser.parse_args()
    if args.apply and not args.report:
        parser.error('--report is required with --apply')
    settings = {name: ''.join(os.environ.get(name, '').split()) for name in (
        'R2_BUCKET', 'R2_S3_ENDPOINT', 'AWS_ACCESS_KEY_ID', 'AWS_SECRET_ACCESS_KEY',
    )}
    if not all(settings.values()):
        parser.error('R2_BUCKET, R2_S3_ENDPOINT and AWS credentials are required')
    endpoint = urlsplit(settings['R2_S3_ENDPOINT'])
    if endpoint.scheme != 'https' or not re.fullmatch(r'[a-f0-9]{32}\.r2\.cloudflarestorage\.com', endpoint.netloc):
        parser.error('R2_S3_ENDPOINT must be an HTTPS R2 S3 endpoint')
    import boto3
    from botocore.config import Config
    client = boto3.client('s3', endpoint_url=settings['R2_S3_ENDPOINT'], region_name='auto',
                          aws_access_key_id=settings['AWS_ACCESS_KEY_ID'],
                          aws_secret_access_key=settings['AWS_SECRET_ACCESS_KEY'],
                          config=Config(retries={'mode': 'standard', 'max_attempts': 5},
                                        request_checksum_calculation='when_required',
                                        response_checksum_validation='when_required'))
    execute(client, settings['R2_BUCKET'], apply=args.apply, report_path=args.report)


if __name__ == '__main__':
    main()
