"""Загрузка изображений для Tkinter (аватарки и медиа).

Tkinter умеет PNG/GIF нативно, а Telegram отдаёт в основном JPEG/WebP,
поэтому изображения прогоняются через Pillow. Если Pillow недоступен,
функции возвращают ``None`` — интерфейс переходит на fallback-инициалы.
"""

from __future__ import annotations

import io
import tkinter as tk
from pathlib import Path
from typing import Any


def load_photoimage(
    source: Path | str | bytes,
    *,
    size: int | None = None,
    circular: bool = False,
) -> tk.PhotoImage | None:
    """Преобразует файл изображения в ``tk.PhotoImage``.

    Для аватарок ``circular=True`` вырезает квадрат по центру и накладывает
    круглую маску. Для обычного медиа просто вписывает изображение в ``size``.
    """

    try:
        from PIL import Image, ImageDraw, ImageOps
    except Exception:
        return None

    try:
        image = Image.open(source)
        image = ImageOps.exif_transpose(image)
        image = image.convert("RGBA")

        if circular and size:
            image = _center_square(image).resize((size, size), Image.LANCZOS)
            mask = Image.new("L", (size, size), 0)
            ImageDraw.Draw(mask).ellipse((0, 0, size, size), fill=255)
            image.putalpha(mask)
        elif size:
            image.thumbnail((size, size), Image.LANCZOS)

        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        return tk.PhotoImage(data=buffer.getvalue())
    except Exception:
        return None


def _center_square(image: Any) -> Any:
    width, height = image.size
    side = min(width, height)
    left = (width - side) // 2
    top = (height - side) // 2
    return image.crop((left, top, left + side, top + side))
