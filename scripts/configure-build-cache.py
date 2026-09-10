#!/usr/bin/env python3
"""Keep compiler outputs outside the checkout's git-clean boundary."""

import os
from pathlib import Path

cache = Path.home() / '.cache' / 'stimma' / 'build'
cache.mkdir(parents=True, exist_ok=True)
# Personal runner account names must not appear in downstream CI logs.
print(f'::add-mask::{cache}', flush=True)
with open(os.environ['GITHUB_ENV'], 'a', encoding='utf-8') as output:
    output.write(f'STIMMA_BUILD_CACHE={cache}\n')
print('Persistent native build cache enabled; Cargo validates source and compiler fingerprints.')
