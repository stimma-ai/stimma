#!/usr/bin/env python3
"""Use isolated, disposable test data on the runner workspace volume on provisioned Linux runners."""

import os
from pathlib import Path
import shutil
import stat
import sys
import tempfile


def _retry_with_writable_parent(func, path, exc_info):
    """Retry cleanup after tests leave a read-only path in their scratch tree."""
    del exc_info
    target = Path(path)
    target.parent.chmod(stat.S_IRWXU)
    if target.exists():
        target.chmod(stat.S_IRWXU)
    func(path)


if sys.argv[1:] == ['cleanup']:
    scratch = os.environ.get('STIMMA_CI_TEST_TMP')
    if scratch:
        path = Path(scratch)
        if path.parent != Path(os.environ['RUNNER_TEMP']) or not path.name.startswith('stimma-tests-'):
            raise SystemExit('Refusing unexpected test scratch path')
        try:
            shutil.rmtree(path, onerror=_retry_with_writable_parent)
        except FileNotFoundError:
            pass  # Cleanup is safe to repeat after cancellation or runner cleanup.
elif os.environ.get('STIMMA_PREPROVISIONED') == '1':
    scratch = Path(tempfile.mkdtemp(prefix='stimma-tests-', dir=os.environ['RUNNER_TEMP']))
    values = {'STIMMA_CI_TEST_TMP': scratch, 'TMPDIR': scratch,
              'XDG_DATA_HOME': scratch / 'data', 'XDG_CONFIG_HOME': scratch / 'config'}
    for path in values.values():
        path.mkdir(exist_ok=True)
    with open(os.environ['GITHUB_ENV'], 'a', encoding='utf-8') as output:
        for name, path in values.items():
            output.write(f'{name}={path}\n')
    print('Isolated test data on the runner workspace volume enabled.')
