from collections.abc import Callable

from .models import Recipient, SendOutcome, validate_message


class MessengerController:
    def __init__(self, service, worker, on_state: Callable[[str, str], None]) -> None:
        self._service = service
        self._worker = worker
        self._on_state = on_state
        self._pending = False

    @property
    def pending(self) -> bool:
        return self._pending

    def send(self, recipient: Recipient | None, text: str) -> None:
        if self._pending:
            return
        if recipient is None:
            self._on_state("failed", "Choose a recipient before sending.")
            return
        try:
            message = validate_message(text)
        except ValueError as exc:
            self._on_state("failed", str(exc))
            return

        self._pending = True
        self._on_state("sending", "Sending…")

        async def operation() -> SendOutcome:
            return await self._service.send_message(recipient, message)

        def on_complete(result: SendOutcome | Exception) -> None:
            self._pending = False
            if isinstance(result, Exception):
                self._on_state(
                    "failed",
                    "Could not send the message. Check the connection and try again.",
                )
            elif isinstance(result, SendOutcome):
                self._on_state(result.kind, result.message)
            else:
                self._on_state("failed", "Could not send the message.")

        try:
            self._worker.submit(operation(), on_complete)
        except Exception:
            self._pending = False
            self._on_state("failed", "Could not start the send operation.")
