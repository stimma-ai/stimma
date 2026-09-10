#!/usr/bin/env python3
"""Join speculative canary builds with their own run's required quality gate."""

import json
import os
import subprocess
import time
import urllib.request


def gate_result(jobs):
    gates = [job for job in jobs if job['name'].split(' / ')[-1] == 'Quality gate passed']
    if len(gates) > 1:
        raise RuntimeError('Ambiguous quality gate; refusing publication')
    if not gates or gates[0]['status'] != 'completed':
        return False
    if gates[0]['conclusion'] != 'success':
        raise RuntimeError(f"Quality gate {gates[0]['conclusion']}; refusing publication")
    return True


def main():
    repository = os.environ['GITHUB_REPOSITORY']
    run_id = os.environ['GITHUB_RUN_ID']
    attempt = os.environ['GITHUB_RUN_ATTEMPT']
    token = os.environ['GITHUB_TOKEN']
    base = os.environ.get('GITHUB_API_URL', 'https://api.github.com')

    def get(path):
        request = urllib.request.Request(f'{base}/repos/{repository}/{path}', headers={
            'Authorization': f'Bearer {token}',
            'Accept': 'application/vnd.github+json',
            'X-GitHub-Api-Version': '2022-11-28',
        })
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)

    commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip()
    # Push canaries must build the exact event commit, never a moving branch.
    if os.environ['GITHUB_EVENT_NAME'] == 'push' and commit != os.environ['GITHUB_SHA']:
        raise RuntimeError('Build does not match the triggering commit')
    deadline = time.monotonic() + 15 * 60
    print(f'Waiting for quality gate in run {run_id}, attempt {attempt}, commit {commit}', flush=True)
    while time.monotonic() < deadline:
        jobs = []
        page = 1
        while True:
            batch = get(f'actions/runs/{run_id}/attempts/{attempt}/jobs?per_page=100&page={page}')['jobs']
            jobs.extend(batch)
            if len(batch) < 100:
                break
            page += 1
        if gate_result(jobs):
            if os.environ['GITHUB_EVENT_NAME'] == 'push':
                latest = get('git/ref/heads/main')['object']['sha']
                if latest != commit:
                    raise RuntimeError('A newer main commit superseded this canary; refusing publication')
            print('Matching quality gate passed; publication permitted', flush=True)
            return
        time.sleep(5)
    raise TimeoutError('Quality gate did not complete; refusing publication')


if __name__ == '__main__':
    main()
