# Запуск окон и тестов на втором мониторе

## Что установлено

- Wayland-композитор: **Mango 0.18.4** (`XDG_CURRENT_DESKTOP=mango`);
- Xwayland: `:1` (Tkinter работает через него);
- мониторы:
  - `HDMI-A-2` — основной, 2560×1440, позиция `0,0`;
  - `HDMI-A-1` — второй, 1920×1080, позиция `2560,360`.

Настройки Mango лежат в `~/.config/mango/cfg/`:

- `monitors.conf` — расположение мониторов;
- `placement.conf` — правила «какое приложение на каком мониторе»;
- `rules.conf` — плавающие окна, fullscreen и прочее.

Применять изменения в конфиге:

```bash
mmsg dispatch reload_config
```

## Как Mango управляет окнами

Обычные `wmctrl`, `xdotool` и `xwininfo` в системе не установлены. Вместо них
используется IPC-утилита `mmsg`:

```bash
mmsg get all-monitors
mmsg get all-clients
mmsg get client <id>
```

Перемещение конкретного окна на монитор справа:

```bash
mmsg dispatch tagmon,right client,<id>
```

Возврат фокуса игре на основном мониторе:

```bash
mmsg dispatch focusmon,HDMI-A-2
```

Важно: `tagmon` переключает фокус на перемещённое окно, поэтому после него
нужно вернуть фокус на `HDMI-A-2`, иначе игра перестанет принимать ввод.

## Постоянное правило (если нужно всегда)

В `~/.config/mango/cfg/placement.conf`:

```ini
window_rule = monitor:HDMI-A-1, tags:4, app_id:^Tpmuitest$
```

`app_id` для Tk-окна задаётся через `tk.Tk(className="TpmUiTest")` и в Mango
виден как `Tpmuitest`. Тег `4` — активный тег второго монитора; при необходимости
замени его. После правки: `mmsg dispatch reload_config`.

## Безопасный запуск UI-теста

В репозитории есть помощник `tools/second_monitor.py` и готовый smoke-тест:

```bash
python tools/ui_smoke_second_monitor.py --seconds 4
```

Что он делает:

1. создаёт Tk-окно с `-alpha 0` — оно невидимо;
2. ждёт появления окна в `mmsg get all-clients` по PID и заголовку;
3. при необходимости выполняет `tagmon,right`;
4. проверяет, что окно действительно на `HDMI-A-1`;
5. возвращает фокус на `HDMI-A-2` (игру);
6. только после этого делает окно видимым;
7. закрывает окно через заданное число секунд.

Окно не должно появиться на основном мониторе: до подтверждения переезда
прозрачность остаётся нулевой. Если Mango или `mmsg` недоступны, помощник
завершится с ошибкой, не показывая окно.

## Обычные unit-тесты

Они не открывают видимых окон и запускаются headless:

```bash
python -m unittest discover -v
```
