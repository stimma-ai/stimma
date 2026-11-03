"""Transient request failures retry over real local HTTP connections."""
import asyncio
import json
from contextlib import asynccontextmanager
from email.utils import formatdate
from time import time

import httpx
import pytest

import llm_http


@asynccontextmanager
async def provider(replies):
    requests = []
    tasks = set()

    async def handle(reader, writer):
        task = asyncio.current_task()
        tasks.add(task)
        try:
            head = await reader.readuntil(b'\r\n\r\n')
            length = next(int(line.split(b':')[1]) for line in head.split(b'\r\n') if line.lower().startswith(b'content-length:'))
            requests.append(json.loads(await reader.readexactly(length)))
            reply = replies[min(len(requests) - 1, len(replies) - 1)]
            if callable(reply):
                reply = reply(head)
            if reply == 'disconnect':
                return
            if reply == 'timeout':
                await asyncio.sleep(1)
                return
            status, body, headers = reply
            data = json.dumps(body).encode()
            headers = {**headers, 'Content-Length': str(len(data)), 'Connection': 'close'}
            wire_headers = ''.join(f'{k}: {v}\r\n' for k, v in headers.items())
            writer.write(f'HTTP/1.1 {status} Reply\r\n{wire_headers}\r\n'.encode() + data)
            await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()
            tasks.discard(task)

    server = await asyncio.start_server(handle, '127.0.0.1', 0)
    try:
        port = server.sockets[0].getsockname()[1]
        yield f'http://127.0.0.1:{port}/v1', requests
    finally:
        server.close()
        await server.wait_closed()
        for task in list(tasks):
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


SUCCESS = (200, {'choices': [{'message': {'content': 'Done'}, 'finish_reason': 'stop'}]}, {})


async def complete(url, **kwargs):
    return await llm_http.acompletion(model='test', api_key='dummy', api_base=url,
                                     messages=[{'role': 'user', 'content': 'Hello'}], **kwargs)


@pytest.fixture
def delays(monkeypatch):
    waits = []
    sleep = asyncio.sleep

    async def fast_sleep(delay):
        waits.append(delay)
        await sleep(0)

    monkeypatch.setattr(asyncio, 'sleep', fast_sleep)
    return waits


@pytest.mark.parametrize('status', [408, 429, 500, 502, 503, 504, 529])
async def test_transient_http_retries_identical_request(status, delays):
    async with provider([(status, {'error': {'type': 'overloaded_error'}}, {}), SUCCESS]) as (url, requests):
        response = await complete(url)
    assert response.choices[0].message.content == 'Done'
    assert len(requests) == 2 and requests[0] == requests[1]
    assert 0.5 <= delays[0] <= 1


@pytest.mark.parametrize('kind', [None, 'openai', 'anthropic', 'chatgpt'])
async def test_retry_limit_across_transports(kind, delays):
    async with provider([(503, {'error': 'overloaded'}, {})]) as (url, requests):
        with pytest.raises(httpx.HTTPStatusError):
            await complete(url, provider_kind=kind)
    assert len(requests) == 3
    assert len(delays) == 2
    assert 0.5 <= delays[0] <= 1 and 1 <= delays[1] <= 2


@pytest.mark.parametrize('status,body', [
    (400, {'error': 'invalid request'}), (401, {}), (403, {}), (404, {}),
    (429, {'error': {'type': 'quota_exceeded'}}),
    (429, {'error': {'code': 'insufficient_quota'}}),
    (503, {'error': {'type': 'upstream_error', 'upstream_status': 400}}),
    (503, {'error': {'type': 'upstream_error', 'upstream_message': 'credit balance too low'}}),
    (503, {'error': {'upstream_metadata': {'code': 'content_filter'}}}),
    (503, {'error': {'type': 'insufficient_balance'}}),
    (503, {'error': {'type': 'subscription_error'}}),
])
async def test_permanent_errors_never_retry(status, body, delays):
    async with provider([(status, body, {})]) as (url, requests):
        with pytest.raises((httpx.HTTPStatusError, llm_http.QuotaExceededError, llm_http.EntitlementError)):
            await complete(url)
    assert len(requests) == 1 and not delays


@pytest.mark.parametrize('value,minimum,maximum', [('12', 12, 12), ('45', 45, 45), ('60', 60, 60), ('date', 38, 41)])
async def test_retry_after_seconds_and_date_wait_full_value(value, minimum, maximum, delays):
    if value == 'date':
        value = formatdate(time() + 40, usegmt=True)
    async with provider([(503, {}, {'Retry-After': value}), SUCCESS]) as (url, _):
        await complete(url)
    assert minimum <= delays[0] <= maximum


async def test_transport_disconnect_retries(monkeypatch):
    client = httpx.AsyncClient
    monkeypatch.setattr(llm_http.httpx, 'AsyncClient', lambda **kw: client(timeout=0.05))
    async with provider(['disconnect', SUCCESS]) as (url, requests):
        assert (await complete(url)).choices[0].message.content == 'Done'
    assert len(requests) == 2


async def test_cancel_during_backoff_is_immediate(monkeypatch):
    waiting = asyncio.Event()
    sleep = asyncio.sleep

    async def backoff(delay):
        waiting.set()
        await sleep(30)

    monkeypatch.setattr(asyncio, 'sleep', backoff)
    async with provider([(503, {}, {})]) as (url, requests):
        task = asyncio.create_task(complete(url))
        await asyncio.wait_for(waiting.wait(), 2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 0.2)
        assert len(requests) == 1


async def test_cloud_refresh_is_kept_across_transient_retries(monkeypatch, delays):
    from unittest.mock import AsyncMock
    monkeypatch.setattr('privacy_lockdown.is_stimma_service_url', lambda url: True)
    monkeypatch.setattr('privacy_lockdown.raise_if_enabled', lambda *args: None)
    refresh = AsyncMock(return_value='fresh-token')
    monkeypatch.setattr('firebase_auth.force_refresh_id_token', refresh)
    fresh_attempts = 0

    def reply(head):
        nonlocal fresh_attempts
        if b'Bearer fresh-token' not in head:
            return (401, {}, {})
        fresh_attempts += 1
        return (503, {}, {}) if fresh_attempts == 1 else SUCCESS

    async with provider([reply]) as (url, requests):
        assert (await complete(url)).choices[0].message.content == 'Done'
    refresh.assert_awaited_once()
    assert len(requests) == 3
    assert fresh_attempts == 2


@pytest.mark.parametrize('value', ['300', 'date'])
async def test_long_retry_after_surfaces_failure_without_retry(value, delays):
    if value == 'date':
        value = formatdate(time() + 300, usegmt=True)
    async with provider([(429, {}, {'Retry-After': value}), SUCCESS]) as (url, requests):
        with pytest.raises(httpx.HTTPStatusError):
            await complete(url)
    assert len(requests) == 1 and not delays


@pytest.mark.parametrize('kind', [None, 'openai', 'anthropic', 'chatgpt'])
async def test_read_timeout_is_not_retried_and_has_a_longer_deadline(kind, monkeypatch, delays):
    requests = []
    def respond(request):
        requests.append(request)
        raise httpx.ReadTimeout('Generation took too long.', request=request)
    client = httpx.AsyncClient
    monkeypatch.setattr(llm_http.httpx, 'AsyncClient', lambda **kw: client(**kw, transport=httpx.MockTransport(respond)))
    with pytest.raises((httpx.ReadTimeout, llm_http.LLMConnectionError)):
        await complete('https://model.example/v1', provider_kind=kind)
    assert len(requests) == 1 and not delays
    assert requests[0].extensions['timeout']['read'] == 600
    assert requests[0].extensions['timeout']['connect'] == 10


@pytest.mark.parametrize('kind', [None, 'openai', 'anthropic', 'chatgpt'])
@pytest.mark.parametrize('error_type', [httpx.ConnectError, httpx.ConnectTimeout, httpx.RemoteProtocolError])
async def test_connect_failures_and_disconnects_retry_across_transports(kind, error_type, monkeypatch, delays):
    requests = []
    def respond(request):
        requests.append(request)
        raise error_type('Connection failed.', request=request)
    client = httpx.AsyncClient
    monkeypatch.setattr(llm_http.httpx, 'AsyncClient', lambda **kw: client(**kw, transport=httpx.MockTransport(respond)))
    with pytest.raises((error_type, llm_http.LLMConnectionError)):
        await complete('https://model.example/v1', provider_kind=kind)
    assert len(requests) == 3 and len(delays) == 2
