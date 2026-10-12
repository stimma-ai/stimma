"""Exercise the execution boundary through the real sandbox entry points."""
import asyncio
import threading
from contextvars import ContextVar
from pathlib import Path

import pytest

from agent.v2.code_execution import SDKBridge
from agent.v2.code_runtime import StimmaSDK
from agent.v2.tools.run_code import run_code
from agent.v2.tools.run_file import run_file


@pytest.mark.asyncio
@pytest.mark.parametrize('from_file', [False, True])
async def test_blocking_code_leaves_backend_responsive(session, test_chat, tmp_path, monkeypatch, from_file):
    entered, release = threading.Event(), threading.Event()
    backend_loop = asyncio.get_running_loop()
    backend_thread = threading.get_ident()
    calls = []

    # A synchronous numerical operation stands in for the costume nesting code.
    def blocking_operation(*args, **kwargs):
        calls.append(('code', threading.get_ident(), asyncio.get_running_loop()))
        entered.set()
        assert release.wait(3), 'backend never got a chance to release worker'
        return 1

    async def sdk_call(self, prompt, images=None):
        calls.append(('sdk', threading.get_ident(), asyncio.get_running_loop()))
        assert self.session is session
        # Exercise the actual AsyncSession, rather than only checking thread IDs.
        assert await self.session.get(type(test_chat), test_chat.id) is test_chat
        return 'SDK reached'

    monkeypatch.setattr('numpy.linalg.det', blocking_operation)
    monkeypatch.setattr(StimmaSDK, 'llm', sdk_call)
    code = "import numpy as np\nnp.linalg.det([[1]])\nprint(await stimma.llm('hello'))"
    if from_file:
        (tmp_path / 'compute.py').write_text(code)
        coro = run_file(file_path='compute.py', session=session, chat_id=test_chat.id, workspace_dir=tmp_path)
    else:
        coro = run_code(code=code, session=session, chat_id=test_chat.id, workspace_dir=tmp_path)
    task = asyncio.create_task(coro)
    try:
        for _ in range(200):
            if entered.is_set() or task.done():
                break
            await asyncio.sleep(.01)
        assert entered.is_set()
        assert not task.done(), 'blocking code ran on the backend loop'
        # The backend continues executing while the worker is synchronously blocked.
        assert await session.get(type(test_chat), test_chat.id) is test_chat
    finally:
        release.set()
    assert await asyncio.wait_for(task, 3) == 'SDK reached'
    assert calls[0][1] != backend_thread and calls[0][2] is not backend_loop
    assert calls[1][1:] == (backend_thread, backend_loop)


@pytest.mark.asyncio
async def test_bridge_nested_resources_context_and_exceptions():
    profile = ContextVar('test_profile', default='unset')
    backend_loop = asyncio.get_running_loop()
    events = []

    class Draft:
        def title(self):
            return 'local file state'

        async def save(self):
            events.append((asyncio.get_running_loop(), profile.get()))
            raise ValueError('save failed')

    class Packages:
        def new(self):
            return Draft()

        async def open(self):
            return Draft()

    proxy = SDKBridge(backend_loop, (Packages, Draft)).wrap(Packages())
    profile.set('kids')

    async def use_sdk():
        draft = proxy.new()
        assert draft.title() == 'local file state'
        for item in (draft, await proxy.open()):
            with pytest.raises(ValueError, match='save failed'):
                await item.save()

    await asyncio.to_thread(lambda: asyncio.run(use_sdk()))
    assert events == [(backend_loop, 'kids')] * 2




@pytest.mark.asyncio
async def test_cancel_propagates_to_backend_sdk_call(session, test_chat, tmp_path, monkeypatch):
    entered, cancelled = asyncio.Event(), asyncio.Event()

    async def blocked(self, prompt, images=None):
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            # Cancellation must wait for resource cleanup, not just request it.
            await asyncio.sleep(.05)
            cancelled.set()

    monkeypatch.setattr(StimmaSDK, 'llm', blocked)
    task = asyncio.create_task(run_code(code="await stimma.llm('wait')", session=session,
                                       chat_id=test_chat.id, workspace_dir=tmp_path))
    await asyncio.wait_for(entered.wait(), 3)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, 3)
    assert cancelled.is_set()


@pytest.mark.asyncio
async def test_nested_sdk_code_reuses_workspace_lease(session, test_chat, tmp_path, monkeypatch):
    async def nested(self, prompt, images=None):
        return await run_code(code="print('nested run')", session=self.session,
                              chat_id=self.chat_id, workspace_dir=self.workspace_dir)

    monkeypatch.setattr(StimmaSDK, 'llm', nested)
    result = await asyncio.wait_for(run_code(
        code="print(await stimma.llm('nested'))", session=session,
        chat_id=test_chat.id, workspace_dir=tmp_path,
    ), 3)
    assert result == 'nested run'


@pytest.mark.asyncio
async def test_cancel_native_call_keeps_workspace_until_worker_finishes(session, test_chat, tmp_path, monkeypatch):
    entered, release = threading.Event(), threading.Event()
    original = Path.cwd()

    def native(*args):
        entered.set()
        assert release.wait(3)

    monkeypatch.setattr('numpy.linalg.det', native)
    task = asyncio.create_task(run_code(code='import numpy as np\nnp.linalg.det([[1]])',
                                       session=session, chat_id=test_chat.id, workspace_dir=tmp_path))
    try:
        for _ in range(200):
            if entered.is_set():
                break
            await asyncio.sleep(.01)
        assert entered.is_set()
        task.cancel()
        await asyncio.sleep(.05)
        assert not task.done()
        assert Path.cwd() == tmp_path
    finally:
        release.set()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, 3)
    assert Path.cwd() == original




@pytest.mark.asyncio
async def test_progress_flushes_while_worker_is_blocked(session, test_chat, tmp_path, monkeypatch):
    entered, release = threading.Event(), threading.Event()
    flushed = asyncio.Event()
    backend_loop = asyncio.get_running_loop()

    def native(*args):
        entered.set()
        assert release.wait(3)

    async def flush(self):
        assert asyncio.get_running_loop() is backend_loop
        pending = self._progress_trackers[0]._take_pending()
        assert pending['display_data']['current'] == 1
        flushed.set()

    async def finalize(self, reason='completed'):
        assert asyncio.get_running_loop() is backend_loop

    monkeypatch.setattr('numpy.linalg.det', native)
    monkeypatch.setattr(StimmaSDK, '_flush_progress', flush)
    monkeypatch.setattr(StimmaSDK, '_finalize_progress', finalize)
    task = asyncio.create_task(run_code(code="""
import numpy as np
progress = stimma.progress(3)
progress.update(1)
np.linalg.det([[1]])
print('done')
""", session=session, chat_id=test_chat.id, workspace_dir=tmp_path))
    try:
        await asyncio.wait_for(flushed.wait(), 2)
        assert entered.is_set() and not task.done()
    finally:
        release.set()
    assert await asyncio.wait_for(task, 3) == 'done'




@pytest.mark.asyncio
async def test_show_during_display_drain_is_not_lost(session, test_chat, tmp_path, monkeypatch):
    copied, appended = threading.Event(), threading.Event()
    shown = []
    errors = []
    sdk = StimmaSDK(session=session, chat_id=test_chat.id, workspace_dir=tmp_path,
                    project_workspace_dir=None, interrupt_checker=None)

    class SnapshotList(list):
        def __iter__(self):
            snapshot = list(super().__iter__())
            copied.set()
            # Reproduce the old snapshot/clear gap. With the lock, the append
            # waits until the drain finishes and remains for the next flush.
            appended.wait(.1)
            return iter(snapshot)

    async def autosave(self, paths):
        return []

    async def show(**kwargs):
        shown.extend(kwargs['media_ids'])

    monkeypatch.setattr(StimmaSDK, '_auto_save_paths', autosave)
    monkeypatch.setattr('agent.v2.code_runtime.show_tool', show)
    sdk._pending_display_calls = SnapshotList()
    sdk.show(media_id=1, role='final')

    def enqueue():
        try:
            assert copied.wait(3)
            sdk.show(media_id=2, role='final')
            appended.set()
        except BaseException as error:
            errors.append(error)

    worker = threading.Thread(target=enqueue, daemon=True)
    worker.start()
    await sdk.flush()
    assert await asyncio.to_thread(appended.wait, 3)
    await asyncio.to_thread(worker.join, 3)
    assert not errors
    await sdk.flush()
    assert shown == [1, 2]






@pytest.mark.asyncio
async def test_sdk_discovery_and_namespace_identity(session, test_chat, tmp_path):
    result = await run_code(code="""
print('library' in dir(stimma))
print('save' in dir(stimma.library))
print(stimma.library is stimma.library)
print(stimma.packages is stimma.packages)
try:
    getattr(stimma, 'session')
except AttributeError:
    print('session stays on backend')
""", session=session, chat_id=test_chat.id, workspace_dir=tmp_path)
    assert result == 'True\nTrue\nTrue\nTrue\nsession stays on backend'


@pytest.mark.asyncio
async def test_owner_cancel_at_worker_completion_is_not_swallowed(session, test_chat, tmp_path, monkeypatch):
    from agent.v2.code_execution import CodeWorker

    owner = asyncio.current_task()
    original_start = CodeWorker.start

    def start(self):
        future = original_start(self)
        future.add_done_callback(lambda _: owner.cancel())
        return future

    monkeypatch.setattr(CodeWorker, 'start', start)
    with pytest.raises(asyncio.CancelledError):
        await run_code(code='await asyncio.sleep(.6)', session=session,
                       chat_id=test_chat.id, workspace_dir=tmp_path,
                       interrupt_checker=lambda: True)


@pytest.mark.asyncio
async def test_bridge_reports_owner_task_submission_failure():
    loop = asyncio.get_running_loop()

    class RejectingOwner:
        def call_soon_threadsafe(self, callback):
            loop.call_soon_threadsafe(callback)

        def create_task(self, coroutine):
            raise RuntimeError('owner rejects new tasks')

    async def operation():
        raise AssertionError('operation must not start')

    bridge = SDKBridge(RejectingOwner(), ())
    with pytest.raises(RuntimeError, match='owner rejects new tasks'):
        await asyncio.wait_for(bridge.call(operation, (), {}), 1)


@pytest.mark.asyncio
@pytest.mark.parametrize('execution', ['direct', 'helper', 'to_thread', 'run_in_executor'])
async def test_stop_drains_active_sync_work_without_blocking_backend(session, test_chat, tmp_path, monkeypatch, execution):
    entered, release = threading.Event(), threading.Event()
    original = Path.cwd()

    def computation(*args):
        entered.set()
        assert release.wait(3)

    monkeypatch.setattr('numpy.linalg.det', computation)
    if execution == 'helper':
        library = tmp_path / 'skill-lib'
        library.mkdir()
        (library / 'compute_review_helper.py').write_text(
            'import numpy as np\ndef compute():\n    np.linalg.det([[1]])\n')
        monkeypatch.setattr('agent.v2.stimpacks.get_stimpack_lib_modules',
                            lambda _: {'compute_review_helper': library})
        code = 'from compute_review_helper import compute\ncompute()'
    else:
        invocation = {'direct': 'compute()', 'to_thread': 'await asyncio.to_thread(compute)',
                      'run_in_executor': 'await asyncio.get_running_loop().run_in_executor(None, compute)'}[execution]
        code = f'import numpy as np\nimport asyncio\ndef compute():\n    np.linalg.det([[1]])\n{invocation}'
    task = asyncio.create_task(run_code(code=code, session=session, chat_id=test_chat.id,
                                       workspace_dir=tmp_path, interrupt_checker=entered.is_set))
    try:
        for _ in range(200):
            if entered.is_set():
                break
            await asyncio.sleep(.01)
        assert entered.is_set()
        # Pass the Stop poll interval. Cancellation must not release cwd while
        # synchronous code still uses it, but the backend remains responsive.
        await asyncio.sleep(.6)
        assert not task.done()
        assert Path.cwd() == tmp_path
        assert await session.get(type(test_chat), test_chat.id) is test_chat
    finally:
        release.set()
    assert await asyncio.wait_for(task, 3) == 'Error: execution interrupted by user'
    assert Path.cwd() == original


@pytest.mark.asyncio
async def test_proxy_introspection_does_not_expose_backend_objects(session, test_chat, tmp_path):
    result = await run_code(code="""
import copy
for resource in [stimma, stimma.library, stimma.packages]:
    try:
        vars(resource)
    except TypeError:
        print('no raw dict')
    for copier in [copy.copy, copy.deepcopy]:
        try:
            copier(resource)
        except TypeError:
            print('live resource')
try:
    stimma.library = None
except AttributeError:
    print('resource attributes are read-only')
pkg = stimma.packages.new('Draft')
try:
    getattr(pkg, '_builder')
except AttributeError:
    print('no raw builder')
""", session=session, chat_id=test_chat.id, workspace_dir=tmp_path)
    assert result == ('no raw dict\nlive resource\nlive resource\n' * 3) + 'resource attributes are read-only\nno raw builder'


@pytest.mark.asyncio
async def test_stop_with_preexisting_cancel_count(session, test_chat, tmp_path):
    async def previously_cancelled():
        asyncio.current_task().cancel()
        try:
            await asyncio.sleep(0)
        except asyncio.CancelledError:
            pass
        return await run_code(code='await asyncio.sleep(.6)', session=session,
                              chat_id=test_chat.id, workspace_dir=tmp_path,
                              interrupt_checker=lambda: True)

    result = await asyncio.wait_for(asyncio.create_task(previously_cancelled()), 3)
    assert result == 'Error: execution interrupted by user'


@pytest.mark.asyncio
@pytest.mark.parametrize('fatal', [SystemExit, KeyboardInterrupt, GeneratorExit])
async def test_fatal_worker_exception_is_contained(session, test_chat, tmp_path, monkeypatch, fatal):
    def fail(*args):
        raise fatal('worker failed')

    monkeypatch.setattr('numpy.linalg.det', fail)
    try:
        result = await run_code(code='import numpy as np\nnp.linalg.det([[1]])',
                                session=session, chat_id=test_chat.id, workspace_dir=tmp_path)
    except BaseException as error:
        pytest.fail(f'Fatal exception escaped worker: {type(error).__name__}')
    assert result.startswith(f'Error: RuntimeError: Agent code raised {fatal.__name__}: worker failed')


@pytest.mark.asyncio
async def test_fatal_background_cleanup_still_drains_executor(monkeypatch):
    from agent.v2.code_execution import CodeWorker

    entered, release, finished = threading.Event(), threading.Event(), threading.Event()

    def background_work():
        entered.set()
        try:
            assert release.wait(3)
        finally:
            finished.set()

    async def fatal_cleanup():
        try:
            await asyncio.Event().wait()
        finally:
            raise SystemExit('background cleanup failed')

    async def code():
        asyncio.create_task(asyncio.to_thread(background_work))
        asyncio.create_task(fatal_cleanup())
        while not entered.is_set():
            await asyncio.sleep(.01)

    future = CodeWorker(code).start()
    try:
        for _ in range(200):
            if entered.is_set():
                break
            await asyncio.sleep(.01)
        assert entered.is_set()
        await asyncio.sleep(.05)
        assert not future.done(), 'completion published before executor cleanup'
    finally:
        release.set()
    try:
        await asyncio.wait_for(future, 3)
    except BaseException as error:
        pytest.fail(f'Fatal background exception escaped worker: {type(error).__name__}')
    assert finished.is_set()
