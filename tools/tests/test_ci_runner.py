import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('ci_runner', ROOT / 'scripts/ci_runner.py')
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)
COMMIT = 'a' * 40


def archive(path, name='action/action.yml'):
    with tarfile.open(path, 'w:gz') as target:
        member = tarfile.TarInfo(name)
        content = b'name: example\nruns: {using: node24, main: index.js}\n'
        member.size = len(content)
        target.addfile(member, io.BytesIO(content))


class RunnerChecks(unittest.TestCase):
    def test_native_binary_executes_and_probe_leaves_no_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            temporary, cache = Path(tmp) / 'temp', Path(tmp) / 'cache'
            self.assertEqual(runner.check_runner(temporary, cache),
                             {'temporary_executables': True, 'cache_writable': True})
            self.assertEqual(list(temporary.iterdir()), [])
            self.assertEqual(list(cache.iterdir()), [])

    def test_noexec_is_an_actionable_failure_not_a_shell_false_positive(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(runner.subprocess, 'run', side_effect=PermissionError):
            with self.assertRaisesRegex(RuntimeError, 'mount with exec'):
                runner.check_runner(Path(tmp) / 'temp', Path(tmp) / 'cache')

    def test_configured_tool_directories_are_checked_as_well_as_download_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tools = root / 'persistent-uv-tools'
            with patch.dict(os.environ, {'UV_TOOL_DIR': str(tools)}, clear=True):
                runner.check_runner(root / 'temp', root / 'cache')
                self.assertTrue(tools.is_dir())
                self.assertEqual(list(tools.iterdir()), [])
                tools.rmdir()
                tools.write_text('invalid tool directory')
                with self.assertRaises(FileExistsError):
                    runner.check_runner(root / 'temp', root / 'cache')

    def test_scratch_cleanup_is_repeatable_but_refuses_unrelated_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            scratch = root / 'stimma-tests-owned'
            scratch.mkdir()
            env = {**os.environ, 'RUNNER_TEMP': str(root), 'STIMMA_CI_TEST_TMP': str(scratch)}
            command = ['python3', str(ROOT / 'scripts/ci-test-scratch.py'), 'cleanup']
            for _ in range(2):
                subprocess.run(command, env=env, check=True, capture_output=True)
            valuable = root / 'valuable'
            valuable.mkdir()
            env['STIMMA_CI_TEST_TMP'] = str(valuable)
            result = subprocess.run(command, env=env, capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertTrue(valuable.is_dir())


class ActionCache(unittest.TestCase):
    def test_prewarming_uses_only_immutable_workflow_references(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'workflow.yml').write_text('\n'.join([
                f'      - uses: actions/setup-node@{COMMIT} # v4',
                '      - uses: actions/checkout@main',
                '      - uses: ./.github/actions/local',
                f'        uses: actions/setup-node@{COMMIT}',
            ]))
            self.assertEqual(runner.workflow_actions(root), [('actions/setup-node', COMMIT)])

    def test_only_real_action_manager_records_supply_cache_keys(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / 'Worker_1.log'
            entry = f"Check if action archive 'actions/setup-node@{COMMIT}' already exists in cache"
            log.write_text('\n'.join([
                f'[2026-01-01 INFO ActionManager] {entry}',
                f'[2026-01-01 INFO ProcessInvoker] {entry}',
                f"[2026-01-01 INFO ActionManager] Check if action archive '../escape@{COMMIT}'",
                "[2026-01-01 INFO ActionManager] Check if action archive 'actions/checkout@main'",
            ]))
            self.assertEqual(runner.resolved_actions(log), [('actions/setup-node', COMMIT)])

    def test_success_is_atomic_and_reruns_never_download_the_same_archive(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp)
            calls = []

            def download(repo, commit, destination, deadline):
                calls.append((repo, commit))
                self.assertFalse((cache / 'actions_checkout' / f'{COMMIT}.tar.gz').exists())
                archive(destination)

            actions = [('actions/checkout', COMMIT)]
            self.assertEqual(runner.warm_actions(actions, cache, download=download), {'reused': 0, 'downloaded': 1})
            self.assertEqual(runner.warm_actions(actions, cache, download=download), {'reused': 1, 'downloaded': 0})
            self.assertEqual(calls, actions)
            self.assertEqual(list(cache.rglob('.action-cache-*')), [])

    def test_corrupt_cache_is_repaired_from_the_official_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp)
            folder = cache / 'actions_checkout'
            folder.mkdir()
            target = folder / f'{COMMIT}.tar.gz'
            target.write_bytes(b'corrupt')
            target.with_suffix('.json').write_text(json.dumps({'sha256': 'wrong'}))
            runner.warm_actions([('actions/checkout', COMMIT)], cache,
                                download=lambda repo, commit, destination, deadline: archive(destination))
            runner.validate_archive(target)
            self.assertEqual(runner.digest(target), json.loads(target.with_suffix('.json').read_text())['sha256'])

    def test_timeout_and_unsafe_archives_never_create_a_cache_entry(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp)

            def interrupted(repo, commit, destination, deadline):
                destination.write_bytes(b'partial')
                raise TimeoutError()

            with self.assertRaises(TimeoutError):
                runner.warm_actions([('actions/checkout', COMMIT)], cache, download=interrupted)
            with self.assertRaises(ValueError):
                runner.warm_actions([('actions/checkout', COMMIT)], cache,
                                    download=lambda repo, commit, destination, deadline: archive(destination, '../outside'))
            self.assertEqual(list(cache.rglob('*.tar.gz')), [])
            self.assertEqual(list(cache.rglob('.action-cache-*')), [])

    def test_maintenance_errors_cannot_fail_a_successful_job(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'Worker_1.log').write_text(
                f"[2026-01-01 INFO ActionManager] Check if action archive 'actions/checkout@{COMMIT}'")
            with patch.object(runner, 'warm_actions', side_effect=TimeoutError), patch('sys.stdout', new=io.StringIO()) as output:
                self.assertEqual(runner.main(['cache-actions', '--logs', tmp, '--cache', str(root / 'cache')]), 0)
                self.assertIn('::warning::', output.getvalue())


if __name__ == '__main__':
    unittest.main()
