"""Помощник для запуска Tk-окон на втором мониторе в Mango.

В этой системе используется Wayland-композитор Mango 0.18.4. Второй монитор
называется ``HDMI-A-1`` и стоит справа от основного ``HDMI-A-2``. Окно
перемещается через IPC-команду ``mmsg dispatch tagmon,right client,<id>``.
Пока окно не подтвердило переезд, оно остаётся полностью прозрачным
(``-alpha 0``), поэтому не мешает игре на основном мониторе.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
import tkinter as tk
from dataclasses import dataclass


class SecondMonitorError(RuntimeError):
    pass


@dataclass(frozen=True)
class Monitor:
    name: str
    x: int
    y: int
    width: int
    height: int


@dataclass(frozen=True)
class Client:
    id: int
    pid: int
    title: str
    appid: str
    monitor: str
    tags: tuple[int, ...]
    x: int
    y: int
    width: int
    height: int


def mango_available() -> bool:
    return (
        "mango" in os.environ.get("XDG_CURRENT_DESKTOP", "").lower()
        and shutil.which("mmsg") is not None
    )


def list_monitors() -> list[Monitor]:
    payload = _mmsg_json("get", "all-monitors")
    monitors = []
    for item in payload.get("monitors", []):
        monitors.append(
            Monitor(
                name=str(item["name"]),
                x=int(item["x"]),
                y=int(item["y"]),
                width=int(item["width"]),
                height=int(item["height"]),
            )
        )
    if not monitors:
        raise SecondMonitorError("Mango не вернул список мониторов.")
    return monitors


def list_clients() -> list[Client]:
    payload = _mmsg_json("get", "all-clients")
    clients = []
    for item in payload.get("clients", []):
        clients.append(
            Client(
                id=int(item["id"]),
                pid=int(item["pid"]),
                title=str(item.get("title") or ""),
                appid=str(item.get("appid") or ""),
                monitor=str(item.get("monitor") or ""),
                tags=tuple(int(tag) for tag in item.get("tags", [])),
                x=int(item.get("x", 0)),
                y=int(item.get("y", 0)),
                width=int(item.get("width", 0)),
                height=int(item.get("height", 0)),
            )
        )
    return clients


def target_monitor() -> Monitor:
    """Второй монитор: самый правый из не-основных."""

    monitors = list_monitors()
    if len(monitors) < 2:
        raise SecondMonitorError("В системе найден только один монитор.")
    primary = min(monitors, key=lambda item: (item.x, item.y))
    candidates = [item for item in monitors if item.name != primary.name]
    return max(candidates, key=lambda item: item.x)


def primary_monitor() -> Monitor:
    return min(list_monitors(), key=lambda item: (item.x, item.y))


def place_tk_window(
    root: tk.Tk,
    *,
    show: bool = True,
    restore_focus: bool = True,
    timeout: float = 5.0,
) -> Client:
    """Перемещает окно текущего процесса на второй монитор.

    Окно должно быть создано с ``root.attributes("-alpha", 0.0)`` (или
    помощник сам выставит прозрачность). Пока монитор не подтверждён,
    окно не показывается.
    """

    if not mango_available():
        raise SecondMonitorError(
            "Mango/mmsg не обнаружен. Используй geometry или оконные правила."
        )

    target = target_monitor()
    try:
        root.attributes("-alpha", 0.0)
    except tk.TclError as error:
        raise SecondMonitorError(f"Не удалось включить прозрачность: {error}") from error
    root.update()

    try:
        client = _wait_for_client(os.getpid(), root.title(), timeout)
        if client.monitor != target.name:
            direction = "right" if target.x >= client.x else "left"
            _dispatch(f"tagmon,{direction}", client.id)
            client = _wait_for_client(
                os.getpid(),
                root.title(),
                timeout,
                expected_monitor=target.name,
            )
    finally:
        if restore_focus:
            try:
                _dispatch(f"focusmon,{primary_monitor().name}")
            except SecondMonitorError:
                pass

    if show:
        root.attributes("-alpha", 1.0)
        root.update()
    return client


def describe() -> str:
    monitors = list_monitors()
    target = target_monitor()
    return "\n".join(
        f"{monitor.name}: {monitor.width}x{monitor.height}+{monitor.x}+{monitor.y}"
        for monitor in monitors
    ) + f"\nЦель: {target.name}"


def _wait_for_client(
    pid: int,
    title: str,
    timeout: float,
    *,
    expected_monitor: str | None = None,
) -> Client:
    deadline = time.monotonic() + timeout
    last_error = ""
    while time.monotonic() < deadline:
        for client in list_clients():
            if client.pid != pid:
                continue
            if title and client.title != title:
                continue
            if expected_monitor and client.monitor != expected_monitor:
                last_error = f"окно пока на {client.monitor}"
                continue
            return client
        time.sleep(0.1)
    detail = f" ({last_error})" if last_error else ""
    raise SecondMonitorError(
        f"Не нашёл окно процесса {pid} с заголовком {title!r}{detail}."
    )


def _dispatch(arguments: str, client_id: int | None = None) -> None:
    command = ("dispatch", arguments)
    if client_id is not None:
        command = (*command, f"client,{client_id}")
    payload = _mmsg_json(*command)
    if not payload.get("success"):
        raise SecondMonitorError(f"mmsg dispatch {arguments}: {payload}")


def _mmsg_json(*args: str) -> dict:
    try:
        result = subprocess.run(
            ("mmsg", *args),
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise SecondMonitorError(f"mmsg недоступен: {error}") from error
    if result.returncode != 0:
        raise SecondMonitorError(result.stderr.strip() or "mmsg завершился с ошибкой.")
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise SecondMonitorError(f"mmsg вернул не JSON: {result.stdout[:120]}") from error
