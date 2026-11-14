#!/usr/bin/env python3
"""Notarize an archived signed canary without rewriting published updater files."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import plistlib
import re
import subprocess
import sys
import tempfile


def notarize(input_dir, output_dir):
    archives = list(Path(input_dir).glob('*.zip'))
    if len(archives) != 1:
        raise RuntimeError('Expected exactly one signed canary ZIP')
    archive = archives[0].resolve()
    output = Path(output_dir).resolve()
    output.mkdir(parents=True, exist_ok=True)
    credentials = [os.environ.get(key, '') for key in ('APPLE_ID', 'APPLE_PASSWORD', 'APPLE_TEAM_ID')]
    if not all(credentials):
        raise RuntimeError('Apple notarization credentials are required')
    auth = ['--apple-id', credentials[0], '--password', credentials[1], '--team-id', credentials[2]]

    def redact(text):
        for secret in sorted(credentials, key=len, reverse=True):
            text = text.replace(secret, '***')
        return text

    def run(args, timeout=300):
        try:
            result = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            # Never print a CalledProcessError/TimeoutExpired containing auth args.
            raise RuntimeError('Apple notarization command timed out; preserve the submission receipt to resume') from None
        return result.returncode, redact(result.stdout), redact(result.stderr)

    def apple(action, *args):
        formatting = [] if action == 'log' else ['--output-format', 'json']
        code, stdout, stderr = run(['xcrun', 'notarytool', action, *args, *auth, *formatting], 1000)
        (output / f'{action}.json').write_text(stdout)
        if code:
            raise RuntimeError(f'Apple {action} failed: {stderr[:500]}')
        try:
            return json.loads(stdout)
        except ValueError:
            raise RuntimeError(f'Apple {action} returned invalid JSON') from None

    with archive.open('rb') as fh:
        sha256 = hashlib.sha256()
        for chunk in iter(lambda: fh.read(1 << 20), b''):
            sha256.update(chunk)
        digest = sha256.hexdigest()
    receipt_path = output / 'receipt.json'
    receipt = json.loads(receipt_path.read_text()) if receipt_path.exists() else None
    if receipt and receipt['sha256'] != digest:
        raise RuntimeError('Saved notarization receipt belongs to a different archive')

    with tempfile.TemporaryDirectory(prefix='canary-notary-') as scratch:
        code, _, stderr = run(['ditto', '-x', '-k', str(archive), scratch])
        if code:
            raise RuntimeError(f'Cannot extract canary: {stderr[:500]}')
        apps = list(Path(scratch).glob('*.app'))
        if len(apps) != 1:
            raise RuntimeError('Expected exactly one canary app bundle')
        app = apps[0]
        with (app / 'Contents/Info.plist').open('rb') as fh:
            info = plistlib.load(fh)
        if info.get('CFBundleIdentifier') != 'ai.stimma.stimma.canary' or '-canary.' not in info.get('CFBundleShortVersionString', ''):
            raise RuntimeError('Deferred notarization accepts only canary app bundles')
        code, _, stderr = run(['codesign', '--verify', '--deep', '--strict', str(app)])
        if code:
            raise RuntimeError(f'Canary signature verification failed: {stderr[:500]}')

        if receipt is None:
            submission = apple('submit', str(archive))
            submission_id = submission.get('id', '')
            if not re.fullmatch(r'[0-9a-fA-F-]{36}', submission_id):
                raise RuntimeError('Apple returned no valid submission ID')
            receipt = {'id': submission_id, 'sha256': digest, 'version': info['CFBundleShortVersionString']}
            # Save before waiting: a failed wait can resume without resubmitting.
            receipt_path.write_text(json.dumps(receipt, indent=2) + '\n')
        try:
            accepted = apple('wait', receipt['id'], '--timeout', '15m')
            if accepted.get('status') != 'Accepted':
                raise RuntimeError('Apple did not accept the canary; see wait.json and log.json')
        except RuntimeError:
            try:
                apple('log', receipt['id'])
            except RuntimeError:
                pass
            raise

        for action in ('staple', 'validate'):
            code, _, stderr = run(['xcrun', 'stapler', action, str(app)])
            if code:
                raise RuntimeError(f'Stapler {action} failed: {stderr[:500]}')
        stapled = output / f'stapled-{archive.name}'
        code, _, stderr = run(['ditto', '-c', '-k', '--sequesterRsrc', '--keepParent', str(app), str(stapled)])
        if code:
            raise RuntimeError(f'Cannot archive stapled canary: {stderr[:500]}')
    print('Canary accepted and stapled. Published updater files remain unchanged.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input-dir', required=True)
    parser.add_argument('--output-dir', required=True)
    args = parser.parse_args()
    try:
        notarize(args.input_dir, args.output_dir)
    except (RuntimeError, OSError, ValueError, KeyError) as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
