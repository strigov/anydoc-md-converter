"""Конвертация одного файла (выполняется в рабочем процессе) и правила именования."""

from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

MARKER_PREFIX = "<!-- anydoc-md: converted from "
_MARKER_RE = re.compile(r'^<!-- anydoc-md: converted from "(.*)" -->\r?\n?')


@dataclass
class Task:
    src: Path
    dst: Path
    big: bool = False


@dataclass
class Result:
    src: Path
    dst: Path
    status: str  # ok | skipped | needs_ocr | error
    detail: str = ""
    seconds: float = 0.0
    size: int = 0
    extra: dict = field(default_factory=dict)


def marker_line(src: Path) -> str:
    name = src.name.replace('"', "'")
    return f'{MARKER_PREFIX}"{name}" -->\n'


def has_marker(path: Path) -> bool:
    """Файл создан нами? Читаем только первую строку."""
    try:
        with path.open("rb") as fh:
            head = fh.read(512)
    except OSError:
        return False
    return head.startswith(MARKER_PREFIX.encode("utf-8"))


def should_write(task: Task, overwrite: str, overwrite_foreign: bool) -> tuple[bool, str]:
    """Решаем, писать ли dst. Возвращаем (писать?, причина-для-лога)."""
    dst = task.dst
    if not dst.exists():
        return True, ""
    if overwrite == "never":
        return False, "уже существует (overwrite=never)"
    ours = has_marker(dst)
    if not ours and not overwrite_foreign:
        return False, "уже существует .md без метки anydoc-md — не трогаем"
    if overwrite == "always":
        return True, ""
    # if_newer
    try:
        if task.src.stat().st_mtime > dst.stat().st_mtime + 1:
            return True, ""
    except OSError:
        return True, ""
    return False, "актуален (исходник не новее)"


def convert_one(task: Task, source_marker: bool) -> Result:
    """Вызывается в отдельном процессе. Не бросает исключений — всё в Result."""
    import anydoc  # импорт здесь, чтобы главный процесс мог работать и без движка

    t0 = time.monotonic()
    try:
        size = task.src.stat().st_size
    except OSError as exc:
        return Result(task.src, task.dst, "error", f"не читается: {exc}")

    try:
        markdown = anydoc.to_markdown(task.src)  # ocr="reject" — версия без OCR
    except anydoc.NeedsOcrError as exc:
        pages = getattr(exc, "pages", None) or []
        shown = ", ".join(map(str, pages[:20])) + (" …" if len(pages) > 20 else "")
        return Result(task.src, task.dst, "needs_ocr",
                      f"нужен OCR (страницы: {shown or '?'})", time.monotonic() - t0, size)
    except anydoc.EncryptedError:
        return Result(task.src, task.dst, "error", "зашифрован / защищён паролем", time.monotonic() - t0, size)
    except anydoc.UnsupportedError as exc:
        return Result(task.src, task.dst, "error", f"формат не поддерживается: {exc}", time.monotonic() - t0, size)
    except anydoc.ResourceLimitError as exc:
        limit = getattr(exc, "limit", None) or "?"
        return Result(task.src, task.dst, "error",
                      f"слишком большой/сложный для движка (лимит {limit}) — разбей документ на части",
                      time.monotonic() - t0, size)
    except anydoc.MalformedError as exc:
        return Result(task.src, task.dst, "error", f"повреждён или нечитаем: {exc}", time.monotonic() - t0, size)
    except anydoc.ConvertError as exc:
        return Result(task.src, task.dst, "error", f"{type(exc).__name__}: {exc}", time.monotonic() - t0, size)
    except MemoryError:
        return Result(task.src, task.dst, "error", "не хватило памяти", time.monotonic() - t0, size)
    except OSError as exc:
        return Result(task.src, task.dst, "error", f"ошибка чтения: {exc}", time.monotonic() - t0, size)
    except Exception as exc:  # noqa: BLE001 — рабочий процесс не должен падать
        return Result(task.src, task.dst, "error", f"неожиданно: {type(exc).__name__}: {exc}", time.monotonic() - t0, size)

    if not markdown.endswith("\n"):
        markdown += "\n"
    if source_marker:
        markdown = marker_line(task.src) + markdown

    tmp = task.dst.with_name(task.dst.name + ".anydoc-tmp")
    try:
        task.dst.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(markdown, encoding="utf-8")
        os.replace(tmp, task.dst)
    except OSError as exc:
        try:
            tmp.unlink()
        except OSError:
            pass
        return Result(task.src, task.dst, "error", f"не удалось записать {task.dst.name}: {exc}", time.monotonic() - t0, size)

    return Result(task.src, task.dst, "ok", "", time.monotonic() - t0, size,
                  {"chars": len(markdown)})
