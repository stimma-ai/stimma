#!/usr/bin/env python3
"""Use isolated, disposable RAM-backed test data on provisioned Linux runners."""

import os
from pathlib import Path
import shutil
import sys
import tempfile

if sys.argv[1:] == ['cleanup']:
    scratch = os.environ.get('STIMMA_CI_TEST_TMP')
    if scratch:
        path = Path(scratch)
        if path.parent != Path('/dev/shm') or not path.name.startswith('stimma-tests-'):
            raise SystemExit('Refusing unexpected test scratch path')
        shutil.rmtree(path)
elif os.environ.get('STIMMA_PREPROVISIONED') == '1':
    scratch = Path(tempfile.mkdtemp(prefix='stimma-tests-', dir='/dev/shm'))
    values = {'STIMMA_CI_TEST_TMP': scratch, 'TMPDIR': scratch,
              'XDG_DATA_HOME': scratch / 'data', 'XDG_CONFIG_HOME': scratch / 'config'}
    for path in values.values():
        path.mkdir(exist_ok=True)
    with open(os.environ['GITHUB_ENV'], 'a', encoding='utf-8') as output:
        for name, path in values.items():
            output.write(f'{name}={path}\n')
    print('Isolated RAM-backed test data enabled.')
