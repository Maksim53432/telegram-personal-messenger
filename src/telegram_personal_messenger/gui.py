"""Графический клиент Telegram на Tkinter."""
import asyncio
import logging
import queue
import threading
import tkinter as tk
from tkinter import ttk, messagebox

logger = logging.getLogger(__name__)


class TgGui:
    def __init__(self, tg_client, loop: asyncio.AbstractEventLoop):
        self.tg = tg_client
        self.loop = loop
        self.current_chat_id = None
        self.chats: dict[int, str] = {}
        self._incoming_queue: queue.Queue = queue.Queue()

        self.root = tk.Tk()
        self.root.title("Telegram GUI Client")
        self.root.geometry("900x600")

        self._build_ui()
        self._poll_incoming()

    def _build_ui(self):
        left = ttk.Frame(self.root, width=250)
        left.pack(side=tk.LEFT, fill=tk.Y, padx=5, pady=5)
        left.pack_propagate(False)

        ttk.Label(left, text="Чаты", font=("Arial", 12, "bold")).pack(anchor="w")
        self.chat_list = tk.Listbox(left, exportselection=False)
        self.chat_list.pack(fill=tk.BOTH, expand=True)
        self.chat_list.bind("<<ListboxSelect>>", self._on_chat_select)

        right = ttk.Frame(self.root)
        right.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=5, pady=5)

        self.messages = tk.Text(right, state=tk.DISABLED, wrap=tk.WORD, bg="#f5f5f5")
        self.messages.pack(fill=tk.BOTH, expand=True)

        input_frame = ttk.Frame(right)
        input_frame.pack(fill=tk.X, pady=(5, 0))
        self.entry = ttk.Entry(input_frame)
        self.entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.entry.bind("<Return>", self._on_send)
        ttk.Button(input_frame, text="Отправить", command=self._on_send).pack(side=tk.RIGHT, padx=(5, 0))

        self.status = ttk.Label(self.root, text="Загрузка...", anchor="w")
        self.status.pack(side=tk.BOTTOM, fill=tk.X)

    def _run_async(self, coro, callback=None):
        def _task():
            future = asyncio.run_coroutine_threadsafe(coro, self.loop)
            try:
                result = future.result()
                if callback:
                    self.root.after(0, callback, result)
            except Exception as e:
                logger.exception("Async error")
                self.root.after(0, lambda: messagebox.showerror("Ошибка", str(e)))
        threading.Thread(target=_task, daemon=True).start()

    def load_chats(self):
        async def _load():
            return await self.tg.client.get_dialogs(limit=50)

        def _done(dialogs):
            self.chat_list.delete(0, tk.END)
            self.chats.clear()
            for d in dialogs:
                title = d.title or d.name or str(d.id)
                self.chats[d.id] = title
                self.chat_list.insert(tk.END, title)
            self.status.config(text=f"Загружено чатов: {len(dialogs)}")
            if dialogs:
                self.chat_list.selection_set(0)
                self._open_chat(dialogs[0].id)

        self._run_async(_load(), _done)

    def _on_chat_select(self, _event):
        sel = self.chat_list.curselection()
        if not sel:
            return
        title = self.chat_list.get(sel[0])
        for cid, t in self.chats.items():
            if t == title:
                self._open_chat(cid)
                break

    def _open_chat(self, chat_id):
        self.current_chat_id = chat_id

        async def _history():
            return await self.tg.client.get_messages(chat_id, limit=50)

        def _render(msgs):
            self.messages.config(state=tk.NORMAL)
            self.messages.delete("1.0", tk.END)
            for m in reversed(msgs):
                who = "Ты" if m.out else "Он"
                self.messages.insert(tk.END, f"[{who}] {m.text or '<медиа>'}\n")
            self.messages.config(state=tk.DISABLED)
            self.messages.see(tk.END)

        self._run_async(_history(), _render)

    def _on_send(self, _event=None):
        text = self.entry.get().strip()
        if not text or self.current_chat_id is None:
            return
        self.entry.delete(0, tk.END)

        async def _send():
            await self.tg.client.send_message(self.current_chat_id, text)

        def _done(_):
            self.messages.config(state=tk.NORMAL)
            self.messages.insert(tk.END, f"[Ты] {text}\n")
            self.messages.config(state=tk.DISABLED)
            self.messages.see(tk.END)

        self._run_async(_send(), _done)

    def _poll_incoming(self):
        try:
            while True:
                sender, text, chat_id = self._incoming_queue.get_nowait()
                if chat_id == self.current_chat_id:
                    self.messages.config(state=tk.NORMAL)
                    self.messages.insert(tk.END, f"[{sender}] {text}\n")
                    self.messages.config(state=tk.DISABLED)
                    self.messages.see(tk.END)
        except queue.Empty:
            pass
        self.root.after(200, self._poll_incoming)

    def push_incoming(self, sender: str, text: str, chat_id: int):
        self._incoming_queue.put((sender, text, chat_id))

    def run(self):
        self.root.mainloop()