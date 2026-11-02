import unittest

from telegram_personal_messenger.controller import MessengerController
from telegram_personal_messenger.models import Recipient, SendOutcome


class FakeWorker:
    def __init__(self):
        self.submissions = []

    def submit(self, coro, callback):
        self.submissions.append((coro, callback))
        coro.close()

    def complete(self, index, result):
        _, callback = self.submissions[index]
        callback(result)


class FakeService:
    async def send_message(self, recipient, text):
        return SendOutcome("sent", "Message sent.")


class ControllerTests(unittest.TestCase):
    def make_controller(self):
        worker = FakeWorker()
        states = []
        controller = MessengerController(
            FakeService(),
            worker,
            on_state=lambda state, message: states.append((state, message)),
        )
        return controller, worker, states

    def test_one_click_submits_one_send_and_ignores_pending_second_click(self):
        controller, worker, _ = self.make_controller()
        recipient = Recipient(7, "Alex", "alex")

        controller.send(recipient, "hello")
        controller.send(recipient, "hello")

        self.assertEqual(len(worker.submissions), 1)

    def test_click_after_previous_send_completes_is_not_rate_limited(self):
        controller, worker, _ = self.make_controller()
        recipient = Recipient(7, "Alex", "alex")

        controller.send(recipient, "hello")
        worker.complete(0, SendOutcome("sent", "Message sent."))
        controller.send(recipient, "hello")

        self.assertEqual(len(worker.submissions), 2)

    def test_empty_message_submits_nothing(self):
        controller, worker, _ = self.make_controller()

        controller.send(Recipient(7, "Alex", "alex"), "  ")

        self.assertEqual(worker.submissions, [])

    def test_missing_recipient_submits_nothing(self):
        controller, worker, _ = self.make_controller()

        controller.send(None, "hello")

        self.assertEqual(worker.submissions, [])

    def test_worker_error_clears_pending_without_retry(self):
        controller, worker, states = self.make_controller()
        recipient = Recipient(7, "Alex", "alex")

        controller.send(recipient, "hello")
        worker.complete(0, RuntimeError("private failure details"))
        controller.send(recipient, "hello")

        self.assertEqual(len(worker.submissions), 2)
        self.assertNotIn("private failure details", str(states))
        self.assertEqual(states[-1][0], "sending")

    def test_unknown_outcome_is_reported_without_automatic_retry(self):
        controller, worker, states = self.make_controller()

        controller.send(Recipient(7, "Alex", "alex"), "hello")
        worker.complete(0, SendOutcome("unknown", "Delivery result is unknown."))

        self.assertEqual(len(worker.submissions), 1)
        self.assertEqual(states[-1], ("unknown", "Delivery result is unknown."))


if __name__ == "__main__":
    unittest.main()
