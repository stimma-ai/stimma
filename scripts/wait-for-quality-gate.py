#!/usr/bin/env python3
"""Join speculative builds with their own run/attempt's publication gate."""

import json
import os
import subprocess
import time
import urllib.request


def gate_result(jobs, required='Quality gate passed'):
    gates = [job for job in jobs if job['name'].split(' / ')[-1] == required]
    if len(gates) > 1:
        raise RuntimeError('Ambiguous publication gate; refusing publication')
    if not gates or gates[0]['status'] != 'completed':
        return False
    if gates[0]['conclusion'] != 'success':
        raise RuntimeError(f"Publication gate {required}: {gates[0]['conclusion']}; refusing publication")
    return True


def check_source(event_name, ref, commit, event_commit, latest_main=None):
    if event_name == 'push' and commit != event_commit:
        raise RuntimeError('Build does not match the triggering commit')
    if event_name == 'push' and ref == 'refs/heads/main' and latest_main != commit:
        raise RuntimeError('A newer main commit superseded this canary; refusing publication')


def main():
    repository = os.environ['GITHUB_REPOSITORY']
    run_id = os.environ['GITHUB_RUN_ID']
    attempt = os.environ['GITHUB_RUN_ATTEMPT']
    token = os.environ['GITHUB_TOKEN']
    required = os.environ.get('STIMMA_PUBLICATION_GATE') or 'Quality gate passed'
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
    event, ref = os.environ['GITHUB_EVENT_NAME'], os.environ['GITHUB_REF']
    # All push builds must use the exact event commit. Only main canaries
    # are superseded by a newer main commit; release branches/tags are not.
    check_source(event, ref, commit, os.environ['GITHUB_SHA'], latest_main=commit)
    deadline = time.monotonic() + 15 * 60
    print(f'Waiting for {required} in run {run_id}, attempt {attempt}, commit {commit}', flush=True)
    while time.monotonic() < deadline:
        jobs = []
        page = 1
        while True:
            batch = get(f'actions/runs/{run_id}/attempts/{attempt}/jobs?per_page=100&page={page}')['jobs']
            jobs.extend(batch)
            if len(batch) < 100:
                break
            page += 1
        if gate_result(jobs, required):
            latest = get('git/ref/heads/main')['object']['sha'] if event == 'push' and ref == 'refs/heads/main' else None
            check_source(event, ref, commit, os.environ['GITHUB_SHA'], latest_main=latest)
            print('Matching publication gate passed; publication permitted', flush=True)
            return
        time.sleep(5)
    raise TimeoutError(f'Publication gate {required} did not complete; refusing publication')


if __name__ == '__main__':
    main()
