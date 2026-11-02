import asyncio
import threading
import time
import unittest

from telegram_personal_messenger.async_worker import AsyncWorker


class AsyncWorkerTests(unittest.TestCase):
    def test_submit_delivers_result_to_main_thread_drain(self):
        worker = AsyncWorker()
        self.addCleanup(worker.close)
        main_thread_id = threading.get_ident()
        results = []

        async def operation():
            await asyncio.sleep(0)
            return 7

        worker.submit(operation(), lambda value: results.append((value, threading.get_ident())))
        deadline = time.monotonic() + 2
        while not results and time.monotonic() < deadline:
            for callback, value in worker.drain():
                callback(value)
            time.sleep(0.01)

        self.assertEqual(results, [(7, main_thread_id)])

    def test_submit_delivers_coroutine_exception(self):
        worker = AsyncWorker()
        self.addCleanup(worker.close)
        results = []

        async def operation():
            raise ValueError("safe test error")

        worker.submit(operation(), results.append)
        deadline = time.monotonic() + 2
        while not results and time.monotonic() < deadline:
            for callback, value in worker.drain():
                callback(value)
            time.sleep(0.01)

        self.assertEqual(len(results), 1)
        self.assertIsInstance(results[0], ValueError)
        self.assertEqual(str(results[0]), "safe test error")

    def test_closed_worker_rejects_new_operations(self):
        worker = AsyncWorker()
        worker.close()

        async def operation():
            return 1

        coro = operation()
        with self.assertRaisesRegex(RuntimeError, "closed"):
            worker.submit(coro, lambda value: None)
        self.assertTrue(coro.cr_frame is None)


if __name__ == "__main__":
    unittest.main()
