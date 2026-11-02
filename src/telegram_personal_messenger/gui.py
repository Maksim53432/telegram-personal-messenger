"""Графический клиент Telegram на Tkinter с поддержкой папок и архива."""
import asyncio
import logging
import queue
import threading
import tkinter as tk
from tkinter import ttk, messagebox

from telethon import functions
from telethon.tl.types import DialogFilter, DialogFilterDefault

logger = logging.getLogger(__name__)


class TgGui:
    def __init__(self, tg_client, loop: asyncio.AbstractEventLoop):
        self.tg = tg_client
        self.loop = loop
        self.current_chat_id = None
        self.all_dialogs = []  # Сырой список всех диалогов
        self.folders = {}      # id -> title (включая "All" и "Archive")
        self.current_folder_id = None
        self._incoming_queue: queue.Queue = queue.Queue()

        self.root = tk.Tk()
        self.root.title("Telegram GUI Client")
        self.root.geometry("1000x650")

        self._build_ui()
        self._poll_incoming()

    def _build_ui(self):
        # ── Панель вкладок (папок) сверху ──────────────────────────────
        self.folder_frame = ttk.Frame(self.root)
        self.folder_frame.pack(side=tk.TOP, fill=tk.X, padx=5, pady=(5, 0))
        
        self.folder_tabs = ttk.Notebook(self.folder_frame)
        self.folder_tabs.pack(fill=tk.X)
        self.folder_tabs.bind("<<NotebookTabChanged>>", self._on_folder_tab_changed)

        # ── Основная область ──────────────────────────────────────────
        main_frame = ttk.Frame(self.root)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # Левая панель — список чатов
        left = ttk.Frame(main_frame, width=280)
        left.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 5))
        left.pack_propagate(False)

        ttk.Label(left, text="Чаты", font=("Arial", 12, "bold")).pack(anchor="w")
        self.chat_list = tk.Listbox(left, exportselection=False)
        self.chat_list.pack(fill=tk.BOTH, expand=True)
        self.chat_list.bind("<<ListboxSelect>>", self._on_chat_select)

        # Правая панель — сообщения + ввод
        right = ttk.Frame(main_frame)
        right.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)

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

    # ── Асинхронные хелперы ──────────────────────────────────────────
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

    # ── Загрузка папок и диалогов ────────────────────────────────────
    def load_folders_and_chats(self):
        async def _load_all():
            # 1. Загружаем ВСЕ диалоги (и архивные, и обычные)
            dialogs = await self.tg.client.get_dialogs(limit=None)
            
            # 2. Загружаем список фильтров (папок) с сервера
            filters_result = await self.tg.client(functions.messages.GetDialogFiltersRequest())
            
            # 3. Собираем папки: Все, Архив + пользовательские
            folders = [{"id": 0, "title": "Все чаты", "filter": None}]
            folders.append({"id": 1, "title": "Архив", "filter": "archive"})
            
            for f in filters_result.filters:
                if isinstance(f, DialogFilter):
                    title = f.title if isinstance(f.title, str) else getattr(f.title, 'text', 'Без имени')
                    folders.append({"id": f.id, "title": title, "filter": f})
            
            return dialogs, folders

        def _done(data):
            self.all_dialogs, folder_list = data
            self.folders = {f["id"]: f["title"] for f in folder_list}
            
            # Очищаем вкладки
            for tab in self.folder_tabs.tabs():
                self.folder_tabs.forget(tab)
            
            # Создаём вкладки
            for f in folder_list:
                frame = ttk.Frame(self.folder_tabs)
                self.folder_tabs.add(frame, text=f["title"])
                # Сохраняем ID папки в атрибуте виджета
                frame.folder_id = f["id"]
                frame.folder_filter = f["filter"]
            
            # Выбираем первую вкладку ("Все чаты")
            if self.folder_tabs.tabs():
                self.folder_tabs.select(0)
                self._apply_folder_filter(0, None)
            
            self.status.config(text=f"Загружено: {len(self.all_dialogs)} чатов, {len(folder_list)} папок")

        self._run_async(_load_all(), _done)

    def _on_folder_tab_changed(self, _event):
        try:
            idx = self.folder_tabs.index(self.folder_tabs.select())
            tab_id = self.folder_tabs.tabs()[idx]
            tab_widget = self.root.nametowidget(tab_id)
            self._apply_folder_filter(tab_widget.folder_id, tab_widget.folder_filter)
        except Exception:
            pass

    def _apply_folder_filter(self, folder_id, folder_filter):
        """Фильтрует self.all_dialogs по выбранной папке и обновляет Listbox."""
        self.current_folder_id = folder_id
        self.chat_list.delete(0, tk.END)
        self.chats = {}  # chat_id -> title для текущей папки

        if folder_filter == "archive":
            # Архив: показываем только те, что в архиве
            visible = [d for d in self.all_dialogs if getattr(d, 'archived', False)]
        elif folder_filter is None:
            # "Все чаты": все неархивные
            visible = [d for d in self.all_dialogs if not getattr(d, 'archived', False)]
        else:
            # Пользовательская папка: применяем правила фильтра
            visible = self._filter_by_rules(self.all_dialogs, folder_filter)

        for d in visible:
            title = d.title or d.name or str(d.id)
            self.chats[d.id] = title
            self.chat_list.insert(tk.END, title)
        
        self.status.config(text=f"В папке '{self.folders.get(folder_id, '?')}': {len(visible)} чатов")
        
        if visible:
            self.chat_list.selection_set(0)
            self._open_chat(visible[0].id)

    def _filter_by_rules(self, dialogs, f: DialogFilter) -> list:
        """Применяет правила DialogFilter к списку диалогов."""
        result = []
        # Собираем ID для include/exclude (упрощённо, по entity.id)
        include_ids = set()
        for peer in f.include_peers:
            # peer может быть InputPeerUser, InputPeerChat, InputPeerChannel
            # Пытаемся вытащить user_id/chat_id/channel_id
            uid = getattr(peer, 'user_id', None) or getattr(peer, 'chat_id', None) or getattr(peer, 'channel_id', None)
            if uid:
                include_ids.add(uid)
        
        exclude_ids = set()
        for peer in f.exclude_peers:
            uid = getattr(peer, 'user_id', None) or getattr(peer, 'chat_id', None) or getattr(peer, 'channel_id', None)
            if uid:
                exclude_ids.add(uid)

        for d in dialogs:
            if getattr(d, 'archived', False):
                continue  # в пользовательских папках обычно не показываем архив (если не указано иное)
            if d.id in exclude_ids:
                continue
            
            # Если есть явные include_peers, проверяем только их
            if include_ids:
                if d.id in include_ids:
                    result.append(d)
                continue
            
            # Иначе применяем флаги типов (упрощённая логика)
            entity = d.entity
            is_user = d.is_user
            is_group = d.is_group
            is_channel = d.is_channel and not d.is_group
            
            if f.contacts and is_user and getattr(entity, 'contact', False):
                result.append(d)
            elif f.non_contacts and is_user and not getattr(entity, 'contact', False):
                result.append(d)
            elif f.groups and is_group:
                result.append(d)
            elif f.broadcasts and is_channel:
                result.append(d)
            elif f.bots and is_user and getattr(entity, 'bot', False):
                result.append(d)
        
        return result

    # ── Выбор чата и сообщения ───────────────────────────────────────
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

    # ── Входящие ─────────────────────────────────────────────────────
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