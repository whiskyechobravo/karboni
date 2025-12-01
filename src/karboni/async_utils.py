import contextlib
import logging
from collections.abc import Awaitable, Callable
from functools import wraps
from types import TracebackType
from typing import ParamSpec, TypeVar

from anyio import CapacityLimiter, create_memory_object_stream
from anyio.streams.memory import MemoryObjectReceiveStream

P = ParamSpec("P")
T = TypeVar("T")

logger = logging.getLogger(__name__)


class RequestLimiter:
    """Limit the number of concurrent requests."""

    def __init__(self, max_concurrent_requests: int) -> None:
        self._current_limit = self._initial_limit = max_concurrent_requests
        self._capacity_limiter = CapacityLimiter(self._current_limit)
        self._backoff = False

    def reset_concurrency(self) -> None:
        self._current_limit = self._initial_limit
        self._capacity_limiter.total_tokens = self._initial_limit

    def start_backoff(self) -> None:
        """
        Reduce concurrency to 1.

        Already acquired tokens are not affected.

        If the caller needs a token to function, then it must retain its token
        in order to be able to end the backoff later.
        """
        if self._backoff:
            msg = "Backoff already in progress"
            raise RuntimeError(msg)
        self._backoff = True
        self._capacity_limiter.total_tokens = 1

    def end_backoff(self) -> None:
        """Restore concurrency."""
        if self._backoff is False:
            msg = "Backoff not in progress"
            raise RuntimeError(msg)
        self._backoff = False
        self._capacity_limiter.total_tokens = self._current_limit

    def is_backoff_active(self) -> bool:
        return self._backoff

    def reduce_concurrency(self) -> None:
        """Reduce concurrency by 20%."""
        logger.warning("Reducing concurrency to %d", self._current_limit)
        self._current_limit = max(1, self._current_limit * 4 // 5)
        if not self._backoff:
            self._capacity_limiter.total_tokens = self._current_limit

    async def acquire(self) -> None:
        await self._capacity_limiter.acquire()

    def release(self) -> None:
        with contextlib.suppress(RuntimeError):  # Don't care if hadn't borrowed a token.
            self._capacity_limiter.release()

    async def __aenter__(self) -> None:
        await self._capacity_limiter.acquire()

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        self._capacity_limiter.release()


def stream_result(
    func: Callable[P, Awaitable[T]],
) -> Callable[P, tuple[Callable[[], Awaitable[None]], MemoryObjectReceiveStream[T]]]:
    """
    Decorator that wraps an async function to capture its return value via a stream.

    This decorator changes the function's behavior:
    instead of being called directly, the decorated function returns a tuple of
    (task_wrapper, receive_stream) where:

    - task_wrapper: An async function suitable for use with start_soon()
    - receive_stream: A channel to receive the original function's return value

    Args:
        func: An async function to be decorated

    Returns:
        A wrapper function that when called returns (task_wrapper, receive_stream)

    Example:
        @capture_result
        async def worker(data):
            await asyncio.sleep(1)
            return f"Processed: {data}"

        async def main():
            task_func, receive_stream = worker("hello")

            async with anyio.create_task_group() as tg:
                tg.start_soon(task_func)
                result = await receive_stream.receive()
                print(result)  # "Processed: hello"

    Note:
        Each call to the decorated function creates an independent stream.
        Multiple tasks can be started with separate streams, and their results
        can be retrieved independently via their respective receive_streams.
    """

    @wraps(func)
    def wrapper(
        *args: P.args, **kwargs: P.kwargs
    ) -> tuple[Callable[[], Awaitable[None]], MemoryObjectReceiveStream[T]]:
        send_stream, receive_stream = create_memory_object_stream[T]()

        async def task_wrapper() -> None:
            result = await func(*args, **kwargs)
            await send_stream.send(result)

        return task_wrapper, receive_stream

    return wrapper
