import importlib.util
import io
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

import yaml

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('gate', ROOT / 'scripts/wait-for-quality-gate.py')
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)


def workflow(name):
    return yaml.load((ROOT / '.github/workflows' / name).read_text(), Loader=yaml.BaseLoader)


def job(name='Quality gate / Quality gate passed', status='completed', conclusion='success'):
    return {'name': name, 'status': status, 'conclusion': conclusion}


@unittest.skipUnless(sys.platform == 'linux' and os.uname().machine == 'x86_64',
                     'static FFmpeg installer targets Linux x64')
class FFmpegSetupTests(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory()
        self.addCleanup(self.scratch.cleanup)
        self.root = Path(self.scratch.name)
        self.bin = self.root / 'bin'
        self.bin.mkdir()
        self.env = {**os.environ, 'HOME': str(self.root),
                    'PATH': str(self.bin) + os.pathsep + os.environ['PATH'],
                    'RUNNER_ENVIRONMENT': 'self-hosted', 'GITHUB_PATH': str(self.root / 'github-path')}
        self.script = str(ROOT / 'scripts/ci-install-ffmpeg.sh')
        metadata = subprocess.check_output(['bash', self.script, '--cache-metadata'], env=self.env, text=True)
        self.cache = Path(dict(line.split('=', 1) for line in metadata.splitlines())['path'])
        self.stub('ffmpeg', 'test -f "$HOME/system-ready"')
        self.stub('ffprobe', 'test -f "$HOME/system-ready"')
        self.stub('curl', 'echo download >> "$HOME/calls"; exit 22')
        self.stub('apt-get', 'echo apt >> "$HOME/calls"; touch "$HOME/system-ready"')
        self.stub('sudo', 'exec "$@"')

    def stub(self, name, body, directory=None):
        path = (directory or self.bin) / name
        path.write_text('#!/bin/sh\n' + body + '\n')
        path.chmod(0o755)

    def install(self):
        result = subprocess.run(['bash', self.script], env=self.env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        calls = self.root / 'calls'
        return calls.read_text().splitlines() if calls.exists() else []

    def test_cache_avoids_download_and_apt_and_exports_both_tools(self):
        self.env['RUNNER_ENVIRONMENT'] = 'github-hosted'
        self.cache.mkdir(parents=True)
        for binary in ['ffmpeg', 'ffprobe']:
            self.stub(binary, 'exit 0', self.cache)
        self.assertEqual(self.install(), [])
        self.assertEqual((self.root / 'github-path').read_text().strip(), str(self.cache))

    def test_preinstalled_tools_avoid_download_and_apt(self):
        (self.root / 'system-ready').touch()
        self.assertEqual(self.install(), [])
        self.assertFalse((self.root / 'github-path').exists())

    def test_missing_ffprobe_and_failed_download_fall_back_without_caching_apt(self):
        self.cache.mkdir(parents=True)
        self.stub('ffmpeg', 'exit 0', self.cache)
        self.assertEqual(self.install(), ['download', 'apt', 'apt'])
        self.assertFalse(self.cache.exists())
        self.assertFalse((self.root / 'github-path').exists())

    def test_checksum_failure_never_extracts_or_caches_download(self):
        self.stub('curl', 'while [ "$1" != --output ]; do shift; done; shift; echo corrupt > "$1"')
        self.stub('tar', 'echo extracted >> "$HOME/calls"; exit 1')
        self.assertEqual(self.install(), ['apt', 'apt'])
        self.assertFalse(self.cache.exists())


class PublicationTests(unittest.TestCase):
    def test_ci_workflows_use_the_same_tested_tool_versions(self):
        def walk(value):
            if isinstance(value, dict):
                if 'uses' in value:
                    yield value
                for child in value.values():
                    yield from walk(child)
            elif isinstance(value, list):
                for child in value:
                    yield from walk(child)

        pins = {'astral-sh/setup-uv@': ('version', '0.13.7'),
                'actions/setup-node@': ('node-version', '22.23.4'),
                'dtolnay/rust-toolchain@': ('toolchain', '1.99.1'),
                'denoland/setup-deno@': ('deno-version', 'v2.9.8')}
        for path in (ROOT / '.github/workflows').glob('*.yml'):
            for step in walk(workflow(path.name)):
                if not step['uses'].startswith('./'):
                    self.assertRegex(step['uses'], r'^[\w.-]+/[\w.-]+@[a-f0-9]{40}$')
                for prefix, (key, version) in pins.items():
                    if step['uses'].startswith(prefix):
                        with self.subTest(workflow=path.name, action=prefix):
                            self.assertEqual(step.get('with', {}).get(key), version)

    def test_every_quality_job_respects_the_trusted_pool_and_hosted_default(self):
        jobs = workflow('quality-gate.yml')['jobs']
        for name, config in jobs.items():
            with self.subTest(job=name):
                self.assertEqual(config['runs-on'], '${{ fromJSON(inputs.runs_on || \'"ubuntu-24.04"\') }}')
        for name in ['canary.yml', 'release.yml', 'build-desktop.yml']:
            self.assertIn('stimma-test', workflow(name)['jobs']['quality-gate']['with']['runs_on'])
        self.assertNotIn('runs_on', workflow('ci.yml')['jobs']['quality-gate']['with'])

    def test_prepared_browser_setup_never_installs_system_packages(self):
        action = yaml.load((ROOT / '.github/actions/setup-playwright/action.yml').read_text(), Loader=yaml.BaseLoader)
        install = action['runs']['steps'][0]['run']
        with tempfile.TemporaryDirectory() as tmp:
            stub = Path(tmp) / 'npx'
            stub.write_text('#!/bin/sh\nprintf "%s\\n" "$*"\n')
            stub.chmod(0o755)
            for prepared, expected in [('1', '--no-install playwright install chromium'),
                                       ('', '--no-install playwright install --with-deps chromium')]:
                with self.subTest(prepared=prepared):
                    result = subprocess.run(['bash', '-e', '-c', install], check=True,
                                            capture_output=True, text=True,
                                            env={**os.environ, 'PATH': tmp + os.pathsep + os.environ['PATH'],
                                                 'STIMMA_PREPROVISIONED': prepared})
                    self.assertEqual(result.stdout.strip(), expected)
        jobs = workflow('quality-gate.yml')['jobs']
        for name in ['frontend-tests', 'acceptance-tests']:
            steps = jobs[name]['steps']
            setup = next(s for s in steps if s.get('name') == 'Install Playwright Chromium')
            self.assertEqual(setup['uses'], './.github/actions/setup-playwright')
            self.assertTrue(any(s.get('name') == 'Prepare test scratch' for s in steps))
            cleanup = next(s for s in steps if s.get('name') == 'Clean test scratch')
            self.assertEqual(cleanup['if'], 'always()')

    def test_transient_api_failures_retry_then_return_the_actual_response(self):
        for error in [urllib.error.HTTPError('https://api.test', 500, 'temporary', {}, None),
                      urllib.error.HTTPError('https://api.test', 429, 'limited', {'Retry-After': '3'}, None),
                      urllib.error.URLError('connection reset'), TimeoutError('read timed out')]:
            with self.subTest(error=error), \
                    patch.object(gate.urllib.request, 'urlopen', side_effect=[error, io.StringIO('{"jobs": []}')]) as get, \
                    patch.object(gate.time, 'sleep') as sleep:
                self.assertEqual(gate.get_json('request', gate.time.monotonic() + 60), {'jobs': []})
                self.assertEqual(get.call_count, 2)
                sleep.assert_called_once()
                self.assertEqual(sleep.call_args.args[0], 3 if getattr(error, 'code', None) == 429 else 1)

    def test_permanent_or_malformed_api_responses_are_not_retried(self):
        for code in [401, 403, 404]:
            error = urllib.error.HTTPError('https://api.test', code, 'permanent', {}, None)
            with self.subTest(code=code), patch.object(gate.urllib.request, 'urlopen', side_effect=error) as get:
                with self.assertRaises(urllib.error.HTTPError):
                    gate.get_json('request', gate.time.monotonic() + 60)
                self.assertEqual(get.call_count, 1)
        with patch.object(gate.urllib.request, 'urlopen', return_value=io.StringIO('invalid')):
            with self.assertRaises(ValueError):
                gate.get_json('request', gate.time.monotonic() + 60)

    def test_api_retry_exhaustion_and_deadline_fail_closed(self):
        with patch.object(gate.urllib.request, 'urlopen', side_effect=urllib.error.URLError('offline')) as get, \
                patch.object(gate.time, 'sleep') as sleep:
            with self.assertRaisesRegex(TimeoutError, 'refusing publication'):
                gate.get_json('request', gate.time.monotonic() + 60)
            self.assertEqual(get.call_count, 5)
            self.assertEqual([call.args[0] for call in sleep.call_args_list], [1, 2, 4, 8])
        with patch.object(gate.urllib.request, 'urlopen') as get:
            with self.assertRaises(TimeoutError):
                gate.get_json('request', gate.time.monotonic() - 1)
            get.assert_not_called()

    def test_only_the_requested_gate_can_authorize_publication(self):
        self.assertFalse(gate.gate_result([job()], 'Release publication permitted'))
        self.assertTrue(gate.gate_result([job(), job('Release publication permitted')], 'Release publication permitted'))
        self.assertFalse(gate.gate_result([job(status='in_progress')]))
        self.assertFalse(gate.gate_result([]))

    def test_failed_cancelled_skipped_or_ambiguous_gate_never_publishes(self):
        for conclusion in ['failure', 'cancelled', 'skipped', 'timed_out', None]:
            with self.subTest(conclusion=conclusion), self.assertRaises(RuntimeError):
                gate.gate_result([job('Release publication permitted', conclusion=conclusion)], 'Release publication permitted')
        with self.assertRaises(RuntimeError):
            gate.gate_result([job(), job()])

    def test_release_branches_and_tags_are_not_superseded_by_main(self):
        for ref in ['refs/heads/release/1.2.3', 'refs/tags/v1.2.3', 'refs/tags/v1.2.3-beta.1']:
            gate.check_source('push', ref, 'release-sha', 'release-sha', latest_main='other-sha')
        gate.check_source('workflow_dispatch', 'refs/heads/main', 'requested-sha', 'workflow-sha')

    def test_pushes_match_the_exact_commit_and_main_canaries_cannot_publish_stale_builds(self):
        with self.assertRaisesRegex(RuntimeError, 'triggering commit'):
            gate.check_source('push', 'refs/tags/v1.2.3', 'wrong', 'right')
        with self.assertRaisesRegex(RuntimeError, 'superseded'):
            gate.check_source('push', 'refs/heads/main', 'old', 'old', latest_main='new')
        gate.check_source('push', 'refs/heads/main', 'same', 'same', latest_main='same')

    def test_every_publisher_waits_before_github_assets_and_r2_uploads(self):
        for name in ['release-macos.yml', 'release-windows.yml', 'linux-appimage.yml', 'headless-package.yml']:
            with self.subTest(workflow=name):
                data = workflow(name)
                self.assertEqual(data['on']['workflow_call']['inputs']['publication_gate']['default'], 'Quality gate passed')
                steps = next(iter(data['jobs'].values()))['steps']
                wait = next(i for i, s in enumerate(steps) if s.get('name') == 'Wait for matching quality gate')
                self.assertEqual(steps[wait]['if'], 'inputs.wait_for_quality_gate')
                self.assertEqual(steps[wait]['env']['STIMMA_PUBLICATION_GATE'], '${{ inputs.publication_gate }}')
                publishes = [i for i, s in enumerate(steps) if s.get('name', '').startswith('Publish ')]
                self.assertTrue(publishes)
                self.assertTrue(all(wait < i for i in publishes))

    def test_release_builds_overlap_tests_but_wait_for_tested_tag(self):
        jobs = workflow('release.yml')['jobs']
        self.assertEqual(jobs['quality-gate']['with']['runs_on'], '["self-hosted","linux","x64","stimma-test"]')
        self.assertEqual(jobs['release-ref']['needs'], ['release-meta', 'quality-gate'])
        for name in ['macos', 'windows', 'linux', 'linux-arm64', 'headless']:
            with self.subTest(job=name):
                build = jobs[name]
                self.assertEqual(build['needs'], 'release-meta')
                self.assertEqual(build['with']['ref'], '${{ needs.release-meta.outputs.ref }}')
                self.assertEqual(build['with']['version'], '${{ needs.release-meta.outputs.version }}')
                self.assertEqual(build['with']['publication_gate'], jobs['release-ref']['name'])
                self.assertEqual(build['with']['wait_for_quality_gate'], 'true')
                self.assertEqual(build['with']['publish_updates'], '${{ !inputs.validate_only }}')
                if name != 'headless':
                    self.assertEqual(build['with']['publish_github_release'], '${{ !inputs.validate_only }}')

    def test_version_preview_does_not_tag_and_actual_tag_requires_planned_version(self):
        jobs = workflow('release.yml')['jobs']
        preview = next(s for s in jobs['release-meta']['steps'] if s.get('id') == 'version')['run']
        self.assertIn('--dry-run', preview)
        final = next(s for s in jobs['release-ref']['steps'] if s.get('id') == 'release')['run']
        self.assertIn('--expected-tag "$tag"', final)
        self.assertIn('git rev-parse "$tag^{commit}"', final)
        self.assertIn('needs.quality-gate.result', jobs['release-ref']['if'])

    def test_manual_builds_pin_source_and_keep_external_prs_hosted(self):
        jobs = workflow('build-desktop.yml')['jobs']
        self.assertIn('stimma-test', jobs['quality-gate']['with']['runs_on'])
        for name in ['macos', 'windows', 'linux', 'linux-arm64']:
            self.assertEqual(jobs[name]['needs'], 'source')
            self.assertEqual(jobs[name]['with']['ref'], '${{ needs.source.outputs.ref }}')
            self.assertEqual(jobs[name]['with']['wait_for_quality_gate'], '${{ !inputs.skip_quality_gate }}')
        self.assertNotIn('runs_on', workflow('ci.yml')['jobs']['quality-gate']['with'])
        self.assertEqual(workflow('quality-gate.yml')['on']['workflow_call']['inputs']['runs_on']['default'], '"ubuntu-24.04"')

    def test_publication_requires_frontend_regressions_and_all_acceptance_lanes(self):
        jobs = workflow('quality-gate.yml')['jobs']
        final = jobs['passed']
        self.assertIn('frontend-tests', final['needs'])
        check = final['steps'][0]
        self.assertEqual(check['env']['FRONTEND'], '${{ needs.frontend-tests.result }}')
        self.assertIn('test "$FRONTEND" = success', check['run'])
        self.assertEqual(jobs['frontend-tests']['strategy']['matrix']['shard'], ['1', '2'])
        frontend = next(s for s in jobs['frontend-tests']['steps'] if s.get('name') == 'Run frontend regression tests')
        self.assertIn('--test-shard=${{ matrix.shard }}/2', frontend['run'])
        self.assertEqual(jobs['acceptance-tests']['strategy']['matrix']['lane'], ['desktop', 'phone-1', 'phone-2', 'phone-3'])
        phone = next(s for s in jobs['acceptance-tests']['steps'] if s.get('name') == 'Run phone lane (route audit)')
        self.assertIn('STIMMA_ACCEPTANCE_PHONE_SHARD="${LANE#phone-}/3"', phone['run'])

    def test_headless_workers_have_separate_capability_and_unique_docker_images(self):
        job = workflow('headless-package.yml')['jobs']['package']
        matrix = job['strategy']['matrix']['include']
        self.assertEqual(len(matrix), 2)
        for row in matrix:
            self.assertIn('stimma-headless', row['runs_on'])
            self.assertNotIn('stimma-build', row['runs_on'])
        self.assertIn('github.run_id', job['env']['BOOTSTRAP_IMAGE'])
        self.assertIn('github.run_attempt', job['env']['BOOTSTRAP_IMAGE'])
        self.assertFalse(any('apt-get' in s.get('run', '') for s in job['steps']))

    def test_cli_preview_is_read_only_even_with_uncommitted_changes(self):
        before = subprocess.check_output(['git', 'tag', '--list'], cwd=ROOT)
        cli = ROOT / 'tools/stimma'
        result = subprocess.run([str(cli), 'tag', 'beta', '99.98.97', '--dry-run'], check=False, cwd=ROOT,
                                capture_output=True, text=True, env={**os.environ, 'NO_COLOR': '1'})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertRegex(result.stdout.strip(), r'^v99\.98\.97-beta\.\d+$')
        mismatch = subprocess.run([str(cli), 'tag', 'beta', '99.98.97', '--dry-run', '--expected-tag', 'v99.98.97-beta.999999'],
                                  check=False, cwd=ROOT, capture_output=True, text=True)
        self.assertNotEqual(mismatch.returncode, 0)
        self.assertIn('Beta tags changed', mismatch.stderr)
        self.assertEqual(before, subprocess.check_output(['git', 'tag', '--list'], cwd=ROOT))

    def test_cli_creates_only_the_expected_tag_at_head_in_a_local_fixture(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo, origin = root / 'repo', root / 'origin.git'
            subprocess.run(['git', 'init', '--bare', str(origin)], check=True, capture_output=True)
            repo.mkdir()
            subprocess.run(['git', 'init', '-b', 'main'], cwd=repo, check=True, capture_output=True)
            for key, value in [('user.name', 'stimmant'), ('user.email', 'stimmant@stimma.ai'),
                               ('commit.gpgsign', 'false'), ('tag.gpgsign', 'false')]:
                subprocess.run(['git', 'config', key, value], cwd=repo, check=True)
            (repo / 'tools').mkdir()
            for name in ['stimma', 'stimma.ts', 'release-tags.ts']:
                shutil.copy2(ROOT / 'tools' / name, repo / 'tools' / name)
            subprocess.run(['git', 'add', '.'], cwd=repo, check=True)
            subprocess.run(['git', 'commit', '-m', 'Release tooling fixture'], cwd=repo, check=True, capture_output=True)
            subprocess.run(['git', 'remote', 'add', 'origin', str(origin)], cwd=repo, check=True)
            subprocess.run(['git', 'tag', '-a', 'v1.2.3-beta.1', '-m', 'Fixture'], cwd=repo, check=True)
            cli = repo / 'tools/stimma'
            args = [str(cli), 'tag', 'beta', '1.2.3']
            preview = subprocess.run([*args, '--dry-run'], cwd=repo, check=True, capture_output=True, text=True)
            self.assertEqual(preview.stdout.strip(), 'v1.2.3-beta.2')
            refused = subprocess.run([*args, '--expected-tag', 'v1.2.3-beta.3'], cwd=repo,
                                     check=False, capture_output=True, text=True)
            self.assertNotEqual(refused.returncode, 0)
            self.assertEqual(subprocess.check_output(['git', '--git-dir', str(origin), 'tag', '--list']), b'')
            created = subprocess.run([*args, '--expected-tag', 'v1.2.3-beta.2'], cwd=repo,
                                     check=False, capture_output=True, text=True)
            self.assertEqual(created.returncode, 0, created.stderr)
            expected = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=repo)
            actual = subprocess.check_output(['git', '--git-dir', str(origin), 'rev-parse', 'v1.2.3-beta.2^{commit}'])
            self.assertEqual(actual, expected)
            refused_again = subprocess.run([*args, '--expected-tag', 'v1.2.3-beta.2'], cwd=repo,
                                           check=False, capture_output=True, text=True)
            self.assertNotEqual(refused_again.returncode, 0)
            self.assertEqual(subprocess.check_output(['git', '--git-dir', str(origin), 'tag', '--list']), b'v1.2.3-beta.2\n')


if __name__ == '__main__':
    unittest.main()
