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
