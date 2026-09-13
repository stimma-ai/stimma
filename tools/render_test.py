#!/usr/bin/env python3
"""Build and test the real local renderer in an isolated temporary profile."""
import argparse
import json
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parent.parent
parser = argparse.ArgumentParser()
parser.add_argument('--docker', metavar='IMAGE')
args = parser.parse_args()
if args.docker:
    command = ['docker','run','--rm','--init','-i','--network=none',
               '--security-opt',f'seccomp={ROOT / "packaging/headless/render-seccomp.json"}',
               '-v',f'{ROOT / "backend/utils"}:/render:ro',
               '--entrypoint','/opt/stimma/render-python/bin/python',args.docker,
               '/render/headless_render_worker.py']
else:
    subprocess.run(['node','scripts/build.mjs'],cwd=ROOT/'electron',check=True)
    binary = subprocess.check_output(['node','-e',"console.log(require('electron'))"],cwd=ROOT/'electron',text=True).strip().splitlines()[-1]
    command = [binary,str(ROOT/'electron'),'--stimma-render-worker']
env = dict(os.environ,STIMMA_TEST_RENDER_COMMAND=json.dumps(command))
raise SystemExit(subprocess.call(['uv','run','--project','backend','pytest','backend/tests/test_local_render.py','-v'],cwd=ROOT,env=env))
