"""Job lifecycle regressions using a protocol-speaking fake and the jobs DB."""

import asyncio
from contextlib import asynccontextmanager

import pytest

from providers.base import ExecutionResult, ProviderStatus
from providers.jsonrpc import JsonRpcProvider, StdioProviderConfig, Transport


class FakeStpTransport(Transport):
    """An in-memory STP peer; requests and notifications use the real receiver."""

    def __init__(self):
        self.incoming = asyncio.Queue()
        self.executed = asyncio.Event()
        self.cancelled = asyncio.Event()
        self.answer_cancel = True
        self.connected = True

    @property
    def is_connected(self):
        return self.connected

    async def connect(self):
        self.connected = True

    async def disconnect(self):
        self.connected = False
        await self.incoming.put(None)

    async def receive(self):
        return await self.incoming.get()

    async def send(self, message):
        method = message['method']
        if method == 'tools.execute':
            self.executed.set()
            result = {'accepted': True}
        elif method == 'tools.cancel':
            self.cancelled.set()
            if not self.answer_cancel:
                return
            result = {'cancelled': True}
        else:
            raise AssertionError(method)
        await self.incoming.put({'jsonrpc': '2.0', 'id': message['id'], 'result': result})

    async def notify(self, method, **params):
        await self.incoming.put({'jsonrpc': '2.0', 'method': method, 'params': params})


@asynccontextmanager
async def stp_peer():
    peer = FakeStpTransport()
    provider = JsonRpcProvider(StdioProviderConfig(id='test-stalls', command='unused'))
    provider._transport = peer
    provider._status = ProviderStatus.CONNECTED
    provider._supports_cancel = True
    receiver = asyncio.create_task(provider._handle_messages())
    try:
        yield provider, peer
    finally:
        receiver.cancel()
        await asyncio.gather(receiver, return_exceptions=True)
        await peer.disconnect()


async def collect(provider, request_id='test-job'):
    return [item async for item in provider.execute('render', {}, request_id=request_id)]


@pytest.mark.asyncio
async def test_silent_provider_expires_and_receives_cancel(monkeypatch):
    monkeypatch.setattr('providers.jsonrpc.EXECUTION_IDLE_TIMEOUT', 0.03, raising=False)
    async with stp_peer() as (provider, peer):
        results = await asyncio.wait_for(collect(provider), 0.5)
        assert peer.cancelled.is_set()
        assert not results[-1].success
        assert 'without an update' in results[-1].error
        assert not provider._pending_executions
        assert await provider.ping()  # A healthy connection does not prove job liveness.


@pytest.mark.asyncio
async def test_each_progress_message_renews_provider_idle_timeout(monkeypatch):
    monkeypatch.setattr('providers.jsonrpc.EXECUTION_IDLE_TIMEOUT', 0.1, raising=False)
    async with stp_peer() as (provider, peer):
        task = asyncio.create_task(collect(provider))
        try:
            await peer.executed.wait()
            for _ in range(5):
                await asyncio.sleep(0.03)
                await peer.notify('tools.progress', request_id='test-job', progress=0.1)
            await peer.notify('tools.result', request_id='test-job', success=False, error='Finished test')
            results = await asyncio.wait_for(task, 0.5)
            assert len(results) == 6
            assert results[-1].error == 'Finished test'
            assert not peer.cancelled.is_set()
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize('supports_cancel', [True, False])
async def test_cancel_wakes_execution_before_remote_reply(supports_cancel):
    async with stp_peer() as (provider, peer):
        provider._supports_cancel = supports_cancel
        peer.answer_cancel = False
        execution = asyncio.create_task(collect(provider))
        cancel = None
        try:
            await peer.executed.wait()
            cancel = asyncio.create_task(provider.cancel_execution('test-job'))
            results = await asyncio.wait_for(execution, 0.5)
            assert isinstance(results[-1], ExecutionResult)
            assert results[-1].error == 'Generation cancelled'
            assert not provider._pending_executions
        finally:
            for task in (execution, cancel):
                if task:
                    task.cancel()
            await asyncio.gather(*(t for t in (execution, cancel) if t), return_exceptions=True)


@pytest.mark.asyncio
async def test_agent_wait_uses_provider_progress_without_ui(
    generation_queue, generation_db_session, test_provider, output_folder,
):
    from agent.jobs import wait_for_jobs
    from providers.test_provider import TestToolConfig
    from tests.helpers.generation import create_generation_job

    tool_id = 'text-to-image:test-model'
    test_provider.configure_tool(tool_id, TestToolConfig(
        delay_per_stage=0.2, should_fail=True, fail_at_progress=1.0,
        fail_message='Finished progress test',
    ))
    ws = generation_queue._websocket_manager
    generation_queue._websocket_manager = None
    worker = None
    try:
        async with generation_db_session() as session:
            job = await create_generation_job(session, folder_path=output_folder)
            worker = asyncio.create_task(generation_queue._process_job(job, 'default'))
            _, errors, _, _ = await asyncio.wait_for(
                wait_for_jobs([job.id], session, poll_interval=0.02, timeout=0.35), 3,
            )
            await worker
            assert errors == [f'Job {job.id}: Finished progress test']
    finally:
        generation_queue._websocket_manager = ws
        test_provider.configure_tool(tool_id, TestToolConfig())
        if worker:
            worker.cancel()
            await asyncio.gather(worker, return_exceptions=True)


@pytest.mark.asyncio
async def test_agent_wait_does_not_expire_queued_work(generation_queue, generation_db_session):
    from agent.jobs import wait_for_jobs
    from database import GenerationJob
    from tests.helpers.generation import create_generation_job

    async with generation_db_session() as session:
        job = await create_generation_job(session)
        waiter = asyncio.create_task(wait_for_jobs([job.id], session, poll_interval=0.01, timeout=0.05))
        try:
            await asyncio.sleep(0.15)
            assert not waiter.done()
            async with generation_db_session() as update_session:
                stored = await update_session.get(GenerationJob, job.id)
                from tests.helpers.media import create_media_item
                media = await create_media_item(update_session)
                stored.status = 'completed'
                stored.result_media_id = media.id
                await update_session.commit()
            assert (await asyncio.wait_for(waiter, 1))[0] == [media.id]
        finally:
            waiter.cancel()
            await asyncio.gather(waiter, return_exceptions=True)


@pytest.mark.asyncio
async def test_agent_stall_cancels_job_and_provider(generation_queue, generation_db_session, test_provider):
    from agent.jobs import wait_for_jobs
    from tests.helpers.generation import create_generation_job

    async with generation_db_session() as session:
        job = await create_generation_job(session, status='processing')
        _, errors, cancelled, _ = await asyncio.wait_for(
            wait_for_jobs([job.id], session, poll_interval=0.01, timeout=0.05), 1,
        )
    assert cancelled == 0  # Stall is an error, not a user cancellation.
    assert 'was cancelled' in errors[0]
    assert (await generation_queue.get_job(job.id))['status'] == 'cancelled'
    db = generation_queue._get_db('default')
    assert f'job-{db.db_guid}-{job.id}' in test_provider._cancelled_requests


@pytest.mark.asyncio
@pytest.mark.parametrize('client', ['agent', 'manual-tool-view', 'forever-tool-view'])
async def test_restart_preserves_and_runs_submitted_jobs(
    generation_queue, generation_db_session, output_folder, client,
):
    from tests.helpers.generation import create_generation_job

    async with generation_db_session() as session:
        job = await create_generation_job(session, generator_instance_id=client, folder_path=output_folder)
    await generation_queue.cleanup_stale_jobs()
    assert (await generation_queue.get_job(job.id))['status'] == 'queued'
    await generation_queue._process_job(job, 'default')
    await generation_queue._await_finalizers()
    assert (await generation_queue.get_job(job.id))['status'] == 'completed'


@pytest.mark.asyncio
@pytest.mark.parametrize('interrupted_status', ['processing', 'assigned', 'queued'])
async def test_restart_settles_partial_batch_and_keeps_terminal_rows(
    generation_queue, generation_db_session, output_folder, mock_ws, interrupted_status,
):
    import json
    from database import GenerationJob, Asset
    from sqlalchemy import select
    from tests.helpers.generation import create_generation_job
    from tests.helpers.media import create_media_item

    batch_id = f'restart-batch-{interrupted_status}'
    async with generation_db_session() as session:
        media = await create_media_item(session)
        first = await create_generation_job(session, status='completed', result_media_id=media.id, folder_path=output_folder)
        first.batch_id = batch_id
        first.batch_total = 2
        second = await create_generation_job(session, status=interrupted_status)
        second.batch_id = batch_id
        if interrupted_status == 'queued':
            # A one-shot flow's temporary workspace and run are gone at restart.
            second.parameters = json.dumps({'_ephemeral_run_id': 'expired-run'})
            second.output_disposition = 'ephemeral'
        await session.commit()
    await generation_queue._handle_batch_job_completion(first, media, 'default')
    mock_ws.clear()
    await generation_queue.cleanup_stale_jobs()
    assert (await generation_queue.get_job(second.id))['status'] == 'failed'
    events = mock_ws.get_broadcasts('batch_completed')
    event = next(data for _, data in events if data['batch_id'] == batch_id)
    assert (event['completed'], event['failed'], event['total'], event['status']) == (1, 1, 2, 'partial')
    assert event['result_asset_id'] is not None
    async with generation_db_session() as session:
        assert await session.get(GenerationJob, first.id) is not None
        assert await session.scalar(select(Asset).where(Asset.id == event['result_asset_id'])) is not None


@pytest.mark.asyncio
@pytest.mark.parametrize('error', ['Provider connection lost', 'Provider not connected', 'Provider disconnected'])
async def test_disconnect_retries_stop_after_three_attempts(
    generation_queue, generation_db_session, test_provider, output_folder, error,
):
    import json
    from database import GenerationJob
    from providers.test_provider import TestToolConfig
    from tests.helpers.generation import create_generation_job

    test_provider.configure_tool('text-to-image:test-model', TestToolConfig(
        should_fail=True, fail_at_progress=0.0, fail_message=error,
    ))
    try:
        async with generation_db_session() as session:
            job = await create_generation_job(session, folder_path=output_folder)
            job_id = job.id
        for expected in ('queued', 'queued', 'failed'):
            async with generation_db_session() as session:
                job = await session.get(GenerationJob, job_id)
            await generation_queue._process_job(job, 'default')
            stored = await generation_queue.get_job(job_id)
            assert stored['status'] == expected
            if expected == 'queued':
                await generation_queue.cleanup_stale_jobs()
        assert json.loads(stored['parameters'])['_disconnect_retries'] == 2
        assert '3 attempts' in stored['error']
    finally:
        test_provider.configure_tool('text-to-image:test-model', TestToolConfig())


@pytest.mark.asyncio
async def test_disconnect_cleanup_leaves_live_execution_to_worker(
    generation_queue, generation_db_session, test_provider, output_folder,
):
    import json
    from providers.test_provider import TestToolConfig
    from tests.helpers.generation import create_generation_job

    test_provider.configure_tool('text-to-image:test-model', TestToolConfig(
        delay_per_stage=0.2, should_fail=True, fail_at_progress=0.25,
        fail_message='Provider connection lost',
    ))
    async with generation_db_session() as session:
        job = await create_generation_job(session, folder_path=output_folder)
    worker = asyncio.create_task(generation_queue._process_job(job, 'default'))
    try:
        for _ in range(100):
            if (await generation_queue.get_job(job.id))['status'] == 'processing':
                break
            await asyncio.sleep(0.001)
        assert await generation_queue.requeue_jobs_for_backend('test') == 0
        await worker
        stored = await generation_queue.get_job(job.id)
        assert stored['status'] == 'queued'
        assert json.loads(stored['parameters'])['_disconnect_retries'] == 1
    finally:
        worker.cancel()
        await asyncio.gather(worker, return_exceptions=True)
        test_provider.configure_tool('text-to-image:test-model', TestToolConfig())
        await generation_queue.cancel_job(job.id)


@pytest.mark.asyncio
async def test_orphan_disconnect_retries_are_bounded_and_preserve_cancellation(
    generation_queue, generation_db_session,
):
    from database import GenerationJob
    from tests.helpers.generation import create_generation_job

    async with generation_db_session() as session:
        job = await create_generation_job(session, status='assigned')
    for expected in ('queued', 'queued', 'failed'):
        async with generation_db_session() as session:
            stored = await session.get(GenerationJob, job.id)
            stored.status = 'assigned'
            await session.commit()
        await generation_queue.requeue_jobs_for_backend('test')
        assert (await generation_queue.get_job(job.id))['status'] == expected
    async with generation_db_session() as session:
        cancelled = await create_generation_job(session, status='processing')
    await generation_queue.cancel_job(cancelled.id)
    await generation_queue._settle_disconnected_job(cancelled.id, 'default', 'Provider connection lost')
    assert (await generation_queue.get_job(cancelled.id))['status'] == 'cancelled'


@pytest.mark.asyncio
async def test_cancelled_assignment_cannot_start_again(generation_queue, generation_db_session):
    from tests.helpers.generation import create_generation_job

    async with generation_db_session() as session:
        job = await create_generation_job(session, status='assigned')
    await generation_queue.cancel_job(job.id)
    await generation_queue._process_job(job, 'default')
    assert (await generation_queue.get_job(job.id))['status'] == 'cancelled'
    assert ('default', job.id) not in generation_queue._executing_jobs
