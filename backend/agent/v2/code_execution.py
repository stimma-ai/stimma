"""Thread boundary for agent Python; application resources stay on their loop.

This is responsiveness isolation, not a security sandbox or process isolation.
Cancellation is cooperative; this worker cannot forcibly terminate a thread.
"""
from __future__ import annotations

import asyncio
import concurrent.futures
import contextvars
import inspect
import threading
from functools import wraps


class SDKBridge:
    """Marshal async SDK methods, including returned sub-APIs, to the owner loop.

    Synchronous SDK methods operate on files/images or queue local state and stay
    in the worker. Only _gather stays async in the worker: its arguments are user
    coroutines, which must never be moved back onto the application loop.
    """

    def __init__(self, loop, resource_types):
        self.loop = loop
        self.resource_types = resource_types
        self._proxies = {}
        self._proxy_lock = threading.Lock()

    def wrap(self, value):
        if isinstance(value, self.resource_types):
            with self._proxy_lock:
                proxy = self._proxies.get(id(value))
                if proxy is None:
                    proxy = _SDKProxy(self, value)
                    self._proxies[id(value)] = proxy
                return proxy
        return value

    async def call(self, method, args, kwargs):
        async def invoke():
            return await method(*args, **kwargs)

        completed = concurrent.futures.Future()
        owner_task = []

        def finish(task):
            try:
                completed.set_result(task.result())
            except BaseException as error:
                completed.set_exception(error)

        def submit():
            coroutine = invoke()
            try:
                task = self.loop.create_task(coroutine)
            except BaseException as error:
                coroutine.close()
                completed.set_exception(error)
                return
            owner_task.append(task)
            task.add_done_callback(finish)

        def cancel():
            if owner_task:
                owner_task[0].cancel()

        # call_soon_threadsafe copies the caller's profile and gather context.
        self.loop.call_soon_threadsafe(submit)
        result = asyncio.wrap_future(completed)
        try:
            value = await asyncio.shield(result)
        except asyncio.CancelledError:
            self.loop.call_soon_threadsafe(cancel)
            # A cancellation request is not completion. Wait for application
            # cleanup before the worker/session/workspace can be released.
            while not result.done():
                try:
                    await asyncio.shield(result)
                except asyncio.CancelledError:
                    continue
                except Exception:
                    break
            if result.done() and not result.cancelled():
                result.exception()
            raise
        return self.wrap(value)


class _SDKProxy:
    __slots__ = ('__bridge', '__target')

    def __init__(self, bridge, target):
        object.__setattr__(self, '_SDKProxy__bridge', bridge)
        object.__setattr__(self, '_SDKProxy__target', target)

    def __setattr__(self, name, value):
        raise AttributeError('SDK resource attributes are read-only; use the SDK methods')

    def __dir__(self):
        return [name for name in dir(self.__target) if name not in {'session', '_builder'}]

    def __reduce_ex__(self, protocol):
        raise TypeError('Live SDK resources cannot be copied or pickled')

    def __repr__(self):
        return repr(self.__target)

    def __getattr__(self, name):
        if name.startswith('__'):
            raise AttributeError(name)
        if name in {'session', '_builder'}:
            raise AttributeError('Backend resources stay on the backend; use the SDK APIs')
        value = getattr(self.__target, name)
        if inspect.iscoroutinefunction(value) and name != '_gather':
            @wraps(value)
            async def call(*args, **kwargs):
                return await self.__bridge.call(value, args, kwargs)
            return call
        if callable(value) and not inspect.iscoroutinefunction(value):
            @wraps(value)
            def call(*args, **kwargs):
                return self.__bridge.wrap(value(*args, **kwargs))
            return call
        return self.__bridge.wrap(value)


class _CodeExecutor(concurrent.futures.ThreadPoolExecutor):
    """Private code pool: skip queued work after Stop, drain active jobs safely."""

    def __init__(self, worker):
        super().__init__(thread_name_prefix='stimma-agent-helper')
        self._worker = worker

    def submit(self, function, /, *args, **kwargs):
        def execute():
            if self._worker._stop.is_set():
                raise asyncio.CancelledError()
            return function(*args, **kwargs)

        return super().submit(execute)


async def _guard_code(coroutine):
    try:
        return await coroutine
    except (Exception, asyncio.CancelledError):
        raise
    except BaseException as error:
        raise RuntimeError(f'Agent code raised {type(error).__name__}: {error}') from error


class CodeWorker:
    """One execution with a private asyncio loop and inherited profile context.

    Cancellation is cooperative. Async work is cancelled; active synchronous
    Python/native work finishes before the workspace or session is released.
    We never inject exceptions into another thread or trace normal computation.
    """

    def __init__(self, function):
        self._function = function
        self._stop = threading.Event()
        self._loop = None
        self._task = None
        self._future = concurrent.futures.Future()
        context = contextvars.copy_context()
        self._thread = threading.Thread(target=lambda: context.run(self._run),
                                        name='stimma-agent-code', daemon=True)

    def _run(self):
        async def execute():
            self._loop = asyncio.get_running_loop()
            self._loop.set_default_executor(_CodeExecutor(self))
            self._task = asyncio.current_task()

            def task_factory(loop, coroutine, context=None):
                started = False

                async def guarded():
                    nonlocal started
                    started = True
                    return await _guard_code(coroutine)

                task = asyncio.Task(guarded(), loop=loop, context=context)
                def close_unstarted(_):
                    if not started:
                        coroutine.close()
                task.add_done_callback(close_unstarted)
                return task

            # Fatal exceptions in background tasks must not short-circuit
            # asyncio.run's task cleanup and executor drain.
            self._loop.set_task_factory(task_factory)
            if self._stop.is_set():
                raise asyncio.CancelledError()
            return await _guard_code(self._function())

        try:
            result = asyncio.run(execute())
        except BaseException as error:
            if not isinstance(error, (Exception, asyncio.CancelledError)):
                normalized = RuntimeError(f'Agent code raised {type(error).__name__}: {error}')
                normalized.__cause__ = error
                error = normalized
            self._future.set_exception(error)
        else:
            self._future.set_result(result)

    def start(self):
        self._thread.start()
        return asyncio.wrap_future(self._future)

    def stop(self):
        self._stop.set()
        loop, task = self._loop, self._task
        if loop is not None and task is not None and not loop.is_closed():
            try:
                loop.call_soon_threadsafe(task.cancel)
            except RuntimeError:
                pass  # The loop finished between the check and the callback.
