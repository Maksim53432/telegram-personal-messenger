# Telegram Personal Messenger Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Build a local Windows desktop app that sends one Telegram personal-account message per explicit Send-button press to one selected person.

**Architecture:** Tkinter renders the UI on the main thread. A Telethon client and its asyncio event loop run on a background worker; a small controller validates inputs and queues operations, and a result queue returns outcomes to the UI without blocking it. Account credentials are read from a local ignored `.env`; the Telethon session stays in the user's `%LOCALAPPDATA%` directory.

**Tech Stack:** Python 3.12 or newer, Tkinter, `Telethon==1.45.0`, `python-dotenv==1.2.4`, standard-library `unittest`.

**Spec:** `docs/superpowers/specs/2026-10-10-telegram-personal-messenger-design.md`

## Global Constraints

- Python 3.12 or newer.
- Use Tkinter for the Windows window.
- Pin `Telethon==1.45.0` and `python-dotenv==1.2.4`.
- One explicit Send-button press starts one app-level send attempt; never retry the send RPC automatically.
- Do not add application-level send-count, cooldown, schedule, or recipient limits; do not bypass Telegram's own restrictions.
- Allow personal user accounts only; recipient must resolve to one person, not a group or channel.
- Resolve recipients from existing dialogs or an exact `@username`; do not persist recipient history.
- Store `.env` outside version control; include `.env.example` with empty values. Store the Telethon session under `%LOCALAPPDATA%`, not in the project.
- Never log message text, usernames, API credentials, login codes, 2FA passwords, or session contents.
- Keep Telegram network I/O off the Tkinter main thread.
- Send user text as plain text (`parse_mode=None`) so Markdown/HTML punctuation stays literal; do not split oversized messages, surface Telegram's rejection instead.
- No bot, bulk send, background schedule, send history, Telegram Desktop UI automation, or `.exe` packaging in v1.

## Review Focus

- Empty or whitespace-only message → show validation and make no Telegram send call.
- Invalid or unresolved `@username`, or selected non-user peer → show a readable error and make no send call.
- Invalid login code or required 2FA password → remain in the correct login state without logging the entered secret.
- RPC rejection versus network timeout → show a clear failure or an “outcome unknown” state; preserve fields and never auto-retry.
- A second click while a send is pending → ignore it until the current attempt resolves, so one in-flight click cannot fan out into multiple requests.

---

## File Structure

- Create `.gitignore` — ignore `.env`, Python cache, and Telethon session artifacts if accidentally created under the project.
- Create `.env.example` — document empty `TELEGRAM_API_ID` and `TELEGRAM_API_HASH` values only.
- Create `requirements.txt` — pin Telethon and python-dotenv as specified.
- Create `pyproject.toml` — configure editable installation for the `src/` package and declare Python 3.12+ plus the pinned runtime dependencies.
- Create `README.md` — Windows setup, where to obtain Telegram API credentials, how to log in, test with a consenting recipient, and explain Telegram restrictions.
- Create `app.py` — process entry point and settings/service/window wiring.
- Create `src/telegram_personal_messenger/__init__.py` — package marker.
- Create `src/telegram_personal_messenger/config.py` — settings dataclass, `.env` loading, validation, and LocalAppData session path.
- Create `src/telegram_personal_messenger/models.py` — `Recipient` and `SendOutcome` dataclasses/types.
- Create `src/telegram_personal_messenger/telegram_service.py` — Telethon adapter: login, dialog listing, exact username resolution, one-message send, and safe error mapping.
- Create `src/telegram_personal_messenger/async_worker.py` — dedicated asyncio thread and thread-safe result queue.
- Create `src/telegram_personal_messenger/controller.py` — input validation, pending-send guard, and UI-facing operation results.
- Create `src/telegram_personal_messenger/ui.py` — Tkinter login, recipient selection/search, message entry, send action, and visible states.
- Create `tests/test_config.py` — configuration and secret-safe validation tests.
- Create `tests/test_models.py` — message/recipient validation tests.
- Create `tests/test_telegram_service.py` — Telethon adapter behavior using a fake client.
- Create `tests/test_controller.py` — one-send-per-click, validation, and pending-state tests.
- Create `tests/test_async_worker.py` — worker result delivery and shutdown tests.
- Create `tests/test_ui.py` — Russian status copy and recipient-label behavior tests.

## Interfaces

- `config.load_settings(env_path: Path, env: Mapping[str, str] | None = None) -> Settings`; `Settings` has `api_id: int`, `api_hash: str`, and `session_path: Path`.
- `models.Recipient` has `id: int`, `display_name: str`, and `username: str | None`. The service caches Telethon entities internally by ID; UI code never builds or persists Telethon peer objects.
- `models.SendOutcome` has `kind: Literal["sent", "failed", "unknown"]` and a user-safe `message: str`; it never includes credentials, user message contents, or raw stack traces.
- `TelegramService.is_authorized() -> bool` checks whether the LocalAppData session is already authenticated so the UI can skip login on later launches.
- `TelegramService.disconnect() -> None` cleanly closes the Telethon client during window shutdown.
- `TelegramService.request_login_code(phone: str) -> None` sends the login code request.
- `TelegramService.sign_in_code(phone: str, code: str) -> Literal["authenticated", "password_required"]` handles the code and reports the 2FA state.
- `TelegramService.sign_in_password(password: str) -> None` completes 2FA without retaining the password.
- `TelegramService.list_recipients() -> list[Recipient]` returns only individual user dialogs.
- `TelegramService.resolve_username(username: str) -> Recipient` resolves a complete username, normalizing an optional leading `@`.
- `TelegramService.send_message(recipient: Recipient, text: str) -> SendOutcome` makes one send call and maps success, definite rejection, and ambiguous transport failure.
- `AsyncWorker.submit(coro: Coroutine[Any, Any, T], callback: Callable[[T | Exception], None]) -> None` runs the coroutine on its event loop and enqueues its outcome; callbacks are drained and executed by the Tkinter main thread.
- `MessengerController.send(recipient: Recipient | None, text: str) -> None` validates, blocks duplicate in-flight sends, then submits exactly one service call. UI status updates are delivered through an injected callback.
- `ui.recipient_label(recipient: Recipient) -> str` formats the selected person for display; `ui.status_message(state: str, message: str) -> str` maps send outcomes to Russian user-facing copy.

---

### Task 1: Project scaffold and secure configuration

**Files:**
- Create: `.gitignore`
- Create: `.env.example`
- Create: `requirements.txt`
- Create: `pyproject.toml`
- Create: `src/telegram_personal_messenger/__init__.py`
- Create: `src/telegram_personal_messenger/config.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Consumes: none.
- Produces: `Settings` and `load_settings(env_path, env=None)` exactly as defined above.

- [x] **Step 1: Write failing settings tests and the minimal package scaffold**

```python
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from telegram_personal_messenger.config import load_settings

class ConfigTests(unittest.TestCase):
    def test_loads_valid_credentials_and_local_session_path(self):
        with TemporaryDirectory() as local_app_data:
            settings = load_settings(
                Path("unused.env"),
                {"TELEGRAM_API_ID": "12345", "TELEGRAM_API_HASH": "a" * 32, "LOCALAPPDATA": local_app_data},
            )
        self.assertEqual(settings.api_id, 12345)
        self.assertEqual(settings.api_hash, "a" * 32)
        self.assertIn("TelegramPersonalMessenger", str(settings.session_path))

    def test_rejects_missing_credentials_without_echoing_values(self):
        with self.assertRaisesRegex(ValueError, "TELEGRAM_API_ID") as error:
            load_settings(Path("unused.env"), {"LOCALAPPDATA": r"C:\\Temp"})
        self.assertNotIn("secret", str(error.exception))
```

Also create an empty `src/telegram_personal_messenger/__init__.py` and this minimal `pyproject.toml` so the src-layout package can be installed before each test run:

```toml
[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[project]
name = "telegram-personal-messenger"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = ["Telethon==1.45.0", "python-dotenv==1.2.4"]

[tool.setuptools.packages.find]
where = ["src"]
```

- [x] **Step 2: Install the scaffold and confirm the config test fails because the module is absent**

Run: `python -m pip install -e .` then `python -m unittest discover -s tests -p 'test_config.py' -v`  
Expected: installation succeeds and the test fails with `ModuleNotFoundError` for `telegram_personal_messenger.config`.

- [x] **Step 3: Implement the minimal config module**

```python
from dataclasses import dataclass
import os
from pathlib import Path
from typing import Mapping
from dotenv import dotenv_values

@dataclass(frozen=True)
class Settings:
    api_id: int
    api_hash: str
    session_path: Path

def load_settings(env_path: Path, env: Mapping[str, str] | None = None) -> Settings:
    values = dict(dotenv_values(env_path))
    values.update(dict(os.environ if env is None else env))
    raw_id = values.get("TELEGRAM_API_ID")
    api_hash = values.get("TELEGRAM_API_HASH")
    if not raw_id:
        raise ValueError("Set TELEGRAM_API_ID in the local .env file.")
    if not api_hash:
        raise ValueError("Set TELEGRAM_API_HASH in the local .env file.")
    try:
        api_id = int(raw_id)
    except (TypeError, ValueError) as exc:
        raise ValueError("TELEGRAM_API_ID must be an integer.") from exc
    local_app_data = values.get("LOCALAPPDATA") or os.getenv("LOCALAPPDATA")
    if not local_app_data:
        raise ValueError("Windows LOCALAPPDATA is unavailable.")
    session_path = Path(local_app_data) / "TelegramPersonalMessenger" / "account"
    session_path.parent.mkdir(parents=True, exist_ok=True)
    return Settings(api_id=api_id, api_hash=api_hash, session_path=session_path)
```

- [x] **Step 4: Add pinned dependencies and ignored secrets**

`requirements.txt` must contain exactly `Telethon==1.45.0` and `python-dotenv==1.2.4`. `.env.example` contains `TELEGRAM_API_ID=` and `TELEGRAM_API_HASH=` with no values. `.gitignore` ignores `.env`, `__pycache__/`, `*.py[cod]`, `.pytest_cache/`, and `*.session*`.

- [x] **Step 5: Run config tests and confirm they pass**

Run: `python -m unittest discover -s tests -p 'test_config.py' -v`  
Expected: all three tests PASS; neither failure text nor test output includes the API hash.

### Task 2: Recipient and send-result models

**Files:**
- Create: `src/telegram_personal_messenger/models.py`
- Test: `tests/test_models.py`

**Interfaces:**
- Consumes: `Settings` is not required.
- Produces: immutable `Recipient`, immutable `SendOutcome`, and `validate_message(text: str) -> str`.

- [x] **Step 1: Write failing tests for message and recipient models**

```python
import unittest
from telegram_personal_messenger.models import Recipient, SendOutcome, validate_message

class ModelTests(unittest.TestCase):
    def test_rejects_empty_or_whitespace_message(self):
        for text in ("", "   ", "\n\t"):
            with self.subTest(text=text), self.assertRaises(ValueError):
                validate_message(text)

    def test_preserves_valid_message_without_splitting(self):
        self.assertEqual(validate_message(" hello "), " hello ")

    def test_recipient_and_outcome_keep_only_safe_fields(self):
        recipient = Recipient(id=7, display_name="Alex", username="alex")
        result = SendOutcome(kind="unknown", message="Delivery result is unknown.")
        self.assertEqual(recipient.username, "alex")
        self.assertEqual(result.kind, "unknown")
```

- [x] **Step 2: Run model tests and confirm the import fails**

Run: `python -m unittest discover -s tests -p 'test_models.py' -v`  
Expected: FAIL with `ModuleNotFoundError`.

- [x] **Step 3: Implement immutable dataclasses and text validation**

```python
from dataclasses import dataclass
from typing import Literal

@dataclass(frozen=True)
class Recipient:
    id: int
    display_name: str
    username: str | None

@dataclass(frozen=True)
class SendOutcome:
    kind: Literal["sent", "failed", "unknown"]
    message: str

def validate_message(text: str) -> str:
    if not text.strip():
        raise ValueError("Enter a message before sending.")
    return text
```

- [x] **Step 4: Run model tests and confirm they pass**

Run: `python -m unittest discover -s tests -p 'test_models.py' -v`  
Expected: all model tests PASS; valid text is unchanged.

### Task 3: Telethon personal-account adapter

**Files:**
- Create: `src/telegram_personal_messenger/telegram_service.py`
- Test: `tests/test_telegram_service.py`

**Interfaces:**
- Consumes: `Settings`, `Recipient`, `SendOutcome`.
- Produces: `TelegramService(settings: Settings, client_factory=TelegramClient, user_type=telethon.tl.types.User)` and methods documented in the Interfaces section. The factory receives `(str(settings.session_path), settings.api_id, settings.api_hash, request_retries=0, flood_sleep_threshold=0)`; tests inject a fake factory and fake `user_type` without network access.

- [x] **Step 1: Write fake-client tests for login, recipient resolution, and send outcomes**

```python
import unittest
from telegram_personal_messenger.models import Recipient
from telegram_personal_messenger.telegram_service import TelegramService

from pathlib import Path
from telegram_personal_messenger.config import Settings

class FakeUser:
    id = 7
    first_name = "Alex"
    last_name = ""
    username = "alex"

class FakeDialog:
    def __init__(self, entity):
        self.entity = entity

class FakeClient:
    def __init__(self, entity):
        self.entity = entity
        self.send_calls = []
    async def get_dialogs(self):
        return [FakeDialog(self.entity)]
    async def get_entity(self, username):
        if username == "alex":
            return self.entity
        raise ValueError("unresolved")
    async def send_message(self, entity, text):
        self.send_calls.append((entity, text))

class ServiceTests(unittest.IsolatedAsyncioTestCase):
    def make_service(self, client):
        settings = Settings(12345, "x" * 32, Path("unused-session"))
        return TelegramService(
            settings,
            client_factory=lambda *args, **kwargs: client,
            user_type=FakeUser,
        )

    async def test_username_resolution_normalizes_at_prefix(self):
        client = FakeClient(FakeUser())
        service = self.make_service(client)
        recipient = await service.resolve_username("@alex")
        self.assertEqual(recipient, Recipient(7, "Alex", "alex"))

    async def test_dialogs_expose_only_individual_users(self):
        client = FakeClient(FakeUser())
        service = self.make_service(client)
        self.assertEqual(await service.list_recipients(), [Recipient(7, "Alex", "alex")])

    async def test_one_send_invokes_client_once(self):
        client = FakeClient(FakeUser())
        service = self.make_service(client)
        recipient = await service.resolve_username("alex")
        outcome = await service.send_message(recipient, "hello")
        self.assertEqual(outcome.kind, "sent")
        self.assertEqual(len(client.send_calls), 1)
```

- [x] **Step 2: Run the service tests and confirm they fail because the adapter is absent**

Run: `python -m unittest discover -s tests -p 'test_telegram_service.py' -v`  
Expected: FAIL with `ModuleNotFoundError`.

- [x] **Step 3: Implement the adapter with dependency injection**

Construct `TelegramClient` from `Settings.session_path`, `api_id`, and `api_hash`; pass `request_retries=0` and `flood_sleep_threshold=0` so Telethon does not silently retry or sleep-and-resend a send. Implement connect/disconnect, code request, code sign-in, 2FA sign-in, dialog conversion, exact username resolution, and a single `send_message` call with `parse_mode=None` so user text is plain and literal. Cache resolved individual-user entities in memory by `Recipient.id`; reject chats/channels. Map definite Telegram RPC errors to `failed`, transport timeouts with uncertain delivery to `unknown`, and successful RPC completion to `sent`. Never return or log raw exception text, credentials, or message bodies.

- [x] **Step 4: Add tests for invalid login, non-user peers, RPC rejection, and timeout**

Use fake-client exceptions. Assert invalid/non-user recipients never call `send_message`; assert a definite RPC rejection returns `failed`; assert an ambiguous timeout returns `unknown`; assert `send_message` call count stays one in each case.

- [x] **Step 5: Run the service tests and confirm they pass**

Run: `python -m unittest discover -s tests -p 'test_telegram_service.py' -v`  
Expected: all tests PASS without network access or real account credentials.

### Task 4: Async worker and send controller

**Files:**
- Create: `src/telegram_personal_messenger/async_worker.py`
- Create: `src/telegram_personal_messenger/controller.py`
- Test: `tests/test_async_worker.py`
- Test: `tests/test_controller.py`

**Interfaces:**
- Consumes: `TelegramService`, `Recipient`, `SendOutcome`, `validate_message`.
- Produces: `AsyncWorker.submit(coro, callback)`, `AsyncWorker.drain()`, `AsyncWorker.close()`, and `MessengerController.send(recipient, text)`.

- [x] **Step 1: Write failing worker and controller tests**

```python
import unittest
from telegram_personal_messenger.controller import MessengerController
from telegram_personal_messenger.models import Recipient, SendOutcome

class FakeWorker:
    def __init__(self):
        self.submissions = []
    def submit(self, coro, callback):
        self.submissions.append((coro, callback))
        coro.close()

class FakeService:
    async def send_message(self, recipient, text):
        return SendOutcome("sent", "Message sent.")

class ControllerTests(unittest.TestCase):
    def test_one_click_submits_one_send_and_ignores_pending_second_click(self):
        worker = FakeWorker()
        controller = MessengerController(FakeService(), worker, on_state=lambda state, message: None)
        recipient = Recipient(7, "Alex", "alex")
        controller.send(recipient, "hello")
        controller.send(recipient, "hello")
        self.assertEqual(len(worker.submissions), 1)

    def test_click_after_previous_send_completes_is_not_rate_limited(self):
        worker = FakeWorker()
        controller = MessengerController(FakeService(), worker, on_state=lambda state, message: None)
        recipient = Recipient(7, "Alex", "alex")
        controller.send(recipient, "hello")
        worker.submissions[0][1](SendOutcome("sent", "Message sent."))
        controller.send(recipient, "hello")
        self.assertEqual(len(worker.submissions), 2)

    def test_empty_message_submits_nothing(self):
        worker = FakeWorker()
        controller = MessengerController(FakeService(), worker, on_state=lambda state, message: None)
        controller.send(Recipient(7, "Alex", "alex"), "  ")
        self.assertEqual(worker.submissions, [])
```

Add this worker-thread test to `tests/test_async_worker.py`:

```python
import asyncio
import time
import unittest
from telegram_personal_messenger.async_worker import AsyncWorker

class AsyncWorkerTests(unittest.TestCase):
    def test_submit_delivers_result_to_main_thread_drain(self):
        worker = AsyncWorker()
        self.addCleanup(worker.close)
        results = []

        async def operation():
            await asyncio.sleep(0)
            return 7

        worker.submit(operation(), lambda value: results.append(value))
        deadline = time.monotonic() + 2
        while not results and time.monotonic() < deadline:
            for callback, value in worker.drain():
                callback(value)
            time.sleep(0.01)
        self.assertEqual(results, [7])
```

- [x] **Step 2: Run worker and controller tests and confirm imports fail**

Run: `python -m unittest discover -s tests -v`  
Expected: FAIL because the modules are absent.

- [x] **Step 3: Implement the worker with an asyncio thread and result queue**

Start one event loop in a daemon thread. `submit` schedules the coroutine with `asyncio.run_coroutine_threadsafe` and puts either the result or exception into a `queue.Queue`; `drain` returns queued callback/result pairs for execution on the Tkinter thread; `close` stops the loop and joins the thread without blocking the UI indefinitely.

- [x] **Step 4: Implement the controller state machine**

`send` rejects a missing recipient or invalid text locally, sets the pending state before queuing work, and submits one `service.send_message(recipient, text)` coroutine. The completion callback clears pending state and reports `sent`, `failed`, or `unknown`; while pending, further calls are ignored. Do not retry after an exception or timeout.

- [x] **Step 5: Test failure and timeout state transitions**

Assert a worker exception clears pending state, reports a safe error, and does not enqueue a second operation. Assert an `unknown` outcome stays visible as unknown and does not retry.

- [x] **Step 6: Run worker and controller tests and confirm they pass**

Run: `python -m unittest discover -s tests -v`  
Expected: all tests PASS; no test opens a real Telegram connection.

### Task 5: Tkinter window and end-to-end local verification

**Files:**
- Create: `app.py`
- Create: `src/telegram_personal_messenger/ui.py`
- Create: `README.md`
- Test: `tests/test_ui.py`

**Interfaces:**
- Consumes: settings, `TelegramService`, `AsyncWorker`, and `MessengerController`.
- Produces: `MessengerWindow(root, service, worker)` with login, dialog list, exact username lookup, message input, and send states. The window constructs its controller so it can bind the controller's status callback to its own widgets; `app.py` loads settings and constructs the service/worker/window.

- [x] **Step 1: Write failing tests for recipient labels and send-status copy**

```python
import unittest
from telegram_personal_messenger.models import Recipient
from telegram_personal_messenger.ui import recipient_label, status_message

class UiPresentationTests(unittest.TestCase):
    def test_recipient_label_shows_username_when_available(self):
        self.assertEqual(recipient_label(Recipient(7, "Alex", "alex")), "Alex (@alex)")
        self.assertEqual(recipient_label(Recipient(8, "No username", None)), "No username")

    def test_send_statuses_are_clear_russian_copy(self):
        self.assertEqual(status_message("sending", ""), "Отправляю…")
        self.assertEqual(status_message("sent", ""), "Сообщение отправлено.")
        self.assertIn("не повторяло", status_message("unknown", ""))
        self.assertEqual(status_message("failed", "Enter a message before sending."), "Сначала введи текст сообщения.")
```

- [x] **Step 2: Run the presentation tests and confirm the UI module is absent**

Run: `python -m unittest discover -s tests -p 'test_ui.py' -v`  
Expected: FAIL with `ModuleNotFoundError` for `telegram_personal_messenger.ui`.

- [x] **Step 3: Implement the empty, login, and ready window states**

Create a Tkinter window with labeled phone/code/2FA fields as needed, recipient search and selection, a multiline message field, one Send button, and a status label. Keep login secrets in masked/transient fields and clear them after use. On initial launch, show an actionable message if `.env` credentials are missing.

- [x] **Step 4: Connect UI actions through the async worker and controller**

Load dialogs and resolve usernames off the UI thread. Enable Send only when logged in, a person is selected, text is non-empty, and no send is pending. The click handler delegates to `MessengerController.send`; it never calls Telethon directly. Poll `AsyncWorker.drain()` with `root.after(50, ...)` and execute callbacks on the UI thread. On `WM_DELETE_WINDOW`, schedule `TelegramService.disconnect()` on the worker, then stop the worker after disconnect completes.

- [x] **Step 5: Add manual verification steps to README**

Document: copy `.env.example` to `.env`; enter API credentials locally; install the package with `python -m pip install -e .`; launch with `python app.py`; log into one's own account; first test in a self-controlled or consenting personal chat; verify one click sends one message; verify a second deliberate click sends a second message; verify errors preserve text; never share the `.env` or session file. State that Telegram native restrictions remain in force.

- [x] **Step 6: Run the complete automated test suite**

Run: `python -m unittest discover -s tests -v`  
Expected: all tests PASS; tests use fakes and do not require credentials or network access.

- [x] **Step 7: Launch the app and perform the manual UI check**

Run: `python app.py`  
Expected: a Windows window opens; missing credentials are explained safely; the window remains responsive during login and recipient selection; automated tests prove one click creates one send call and no automatic retry. The implementer does not send a live Telegram message; the user may perform the optional real-account check themselves with a consenting recipient.

## Execution Notes

- This workspace is not currently a Git repository, so the plan contains no commit steps. Do not initialize Git as part of implementation unless the user asks.
- Never ask the user to paste API credentials, login codes, 2FA passwords, or session files into the chat.
- Do not perform a live send during implementation without the user deliberately operating the app and choosing a consenting recipient.
