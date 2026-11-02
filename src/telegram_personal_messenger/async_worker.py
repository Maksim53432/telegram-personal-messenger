import asyncio
from concurrent.futures import Future
from queue import Empty, Queue
import threading
from typing import Any, Callable, Coroutine, TypeVar


T = TypeVar("T")


class AsyncWorker:
    def __init__(self) -> None:
        self._loop = asyncio.new_event_loop()
        self._ready = threading.Event()
        self._results: Queue[
            tuple[Callable[[Any], None], Any | Exception]
        ] = Queue()
        self._closed = False
        self._thread = threading.Thread(
            target=self._run_loop,
            name="telegram-async-worker",
            daemon=True,
        )
        self._thread.start()
        self._ready.wait()

    def _run_loop(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._ready.set()
        self._loop.run_forever()

        pending = asyncio.all_tasks(self._loop)
        for task in pending:
            task.cancel()
        if pending:
            self._loop.run_until_complete(
                asyncio.gather(*pending, return_exceptions=True)
            )
        self._loop.close()

    def submit(
        self,
        coro: Coroutine[Any, Any, T],
        callback: Callable[[T | Exception], None],
    ) -> None:
        if self._closed or not self._thread.is_alive():
            coro.close()
            raise RuntimeError("Async worker is closed.")

        future: Future[T] = asyncio.run_coroutine_threadsafe(coro, self._loop)
        future.add_done_callback(lambda completed: self._enqueue_result(completed, callback))

    def _enqueue_result(
        self,
        future: Future[T],
        callback: Callable[[T | Exception], None],
    ) -> None:
        try:
            result: T | Exception = future.result()
        except BaseException as exc:
            result = exc if isinstance(exc, Exception) else RuntimeError("Operation was cancelled.")
        self._results.put((callback, result))

    def drain(self) -> list[tuple[Callable[[Any], None], Any | Exception]]:
        results = []
        while True:
            try:
                results.append(self._results.get_nowait())
            except Empty:
                return results

    def close(self, timeout: float = 2.0) -> None:
        if self._closed:
            return
        self._closed = True
        if self._thread.is_alive():
            self._loop.call_soon_threadsafe(self._loop.stop)
            if threading.current_thread() is not self._thread:
                self._thread.join(timeout)
