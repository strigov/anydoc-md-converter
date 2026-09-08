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
    kind: str = "doc"  # doc | image


@dataclass
class Result:
    src: Path
    dst: Path
    status: str  # ok | skipped | needs_ocr | error
    detail: str = ""
    seconds: float = 0.0
    size: int = 0
    extra: dict = field(default_factory=dict)


def marker_line(src: Path, via: str = "") -> str:
    name = src.name.replace('"', "'")
    tail = f" (ocr: {via})" if via else ""
    return f'{MARKER_PREFIX}"{name}"{tail} -->\n'


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


def write_markdown(task: Task, markdown: str, source_marker: bool, via: str = "") -> str | None:
    """Атомарная запись. Возвращает текст ошибки или None."""
    if not markdown.endswith("\n"):
        markdown += "\n"
    if source_marker:
        markdown = marker_line(task.src, via) + markdown
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
        return f"не удалось записать {task.dst.name}: {exc}"
    return None


def convert_one(task: Task, source_marker: bool, embedded: dict | None = None) -> Result:
    """Быстрый путь через anydoc. Вызывается в отдельном процессе; не бросает исключений.
    embedded: {"min_px": int, "max_count": int} — извлечь вложенные картинки для последующего OCR."""
    import anydoc  # импорт здесь, чтобы главный процесс мог работать и без движка

    t0 = time.monotonic()
    try:
        size = task.src.stat().st_size
    except OSError as exc:
        return Result(task.src, task.dst, "error", f"не читается: {exc}")

    def fail(detail: str) -> Result:
        return Result(task.src, task.dst, "error", detail, time.monotonic() - t0, size)

    try:
        markdown = anydoc.to_markdown(task.src)  # ocr="reject": локально, без облака
    except anydoc.NeedsOcrError as exc:
        pages = list(getattr(exc, "pages", None) or [])
        shown = ", ".join(map(str, pages[:20])) + (" …" if len(pages) > 20 else "")
        return Result(task.src, task.dst, "needs_ocr", f"нужен OCR (страницы: {shown or '?'})",
                      time.monotonic() - t0, size, {"pages": pages})
    except anydoc.EncryptedError:
        return fail("зашифрован / защищён паролем")
    except anydoc.UnsupportedError as exc:
        return fail(f"формат не поддерживается: {exc}")
    except anydoc.ResourceLimitError as exc:
        limit = getattr(exc, "limit", None) or "?"
        return fail(f"слишком большой/сложный для движка (лимит {limit}) — разбей документ на части")
    except anydoc.MalformedError as exc:
        return fail(f"повреждён или нечитаем: {exc}")
    except anydoc.ConvertError as exc:
        return fail(f"{type(exc).__name__}: {exc}")
    except MemoryError:
        return fail("не хватило памяти")
    except OSError as exc:
        return fail(f"ошибка чтения: {exc}")
    except Exception as exc:  # noqa: BLE001 — рабочий процесс не должен падать
        return fail(f"неожиданно: {type(exc).__name__}: {exc}")

    err = write_markdown(task, markdown, source_marker)
    if err:
        return fail(err)
    extra: dict = {"chars": len(markdown)}
    if embedded:
        from .embedded import extract_images
        images = extract_images(task.src, int(embedded["min_px"]), int(embedded["max_count"]))
        if images:
            extra["images"] = images
    return Result(task.src, task.dst, "ok", "", time.monotonic() - t0, size, extra)


def convert_ocr(task: Task, backend, pages: list[int], source_marker: bool) -> Result:
    """Медленный путь: OCR-бэкенд (Vision или Docling). Вызывается в OCR-процессе."""
    from .ocr import OcrError

    t0 = time.monotonic()
    try:
        size = task.src.stat().st_size
    except OSError as exc:
        return Result(task.src, task.dst, "error", f"не читается: {exc}")
    try:
        if task.kind == "image":
            markdown = backend.image_to_markdown(task.src)
        else:
            markdown = backend.pdf_to_markdown(task.src, pages)
    except OcrError as exc:
        return Result(task.src, task.dst, "error", f"OCR ({backend.name}): {exc}", time.monotonic() - t0, size)
    except MemoryError:
        return Result(task.src, task.dst, "error", f"OCR ({backend.name}): не хватило памяти", time.monotonic() - t0, size)
    except Exception as exc:  # noqa: BLE001
        return Result(task.src, task.dst, "error", f"OCR ({backend.name}) неожиданно: {type(exc).__name__}: {exc}",
                      time.monotonic() - t0, size)
    if not markdown.strip():
        return Result(task.src, task.dst, "error", f"OCR ({backend.name}): текст не распознан", time.monotonic() - t0, size)
    err = write_markdown(task, markdown, source_marker, via=backend.name)
    if err:
        return Result(task.src, task.dst, "error", err, time.monotonic() - t0, size)
    return Result(task.src, task.dst, "ok", f"через OCR {backend.name}", time.monotonic() - t0, size,
                  {"chars": len(markdown), "ocr": backend.name})


def convert_embedded(task: Task, backend, images: list, source_marker: bool) -> Result:
    """OCR вложенных картинок уже сконвертированного документа; раздел дописывается в конец .md."""
    import shutil

    from .embedded import build_section, strip_previous_section
    from .ocr import OcrError

    t0 = time.monotonic()
    results = []
    failures = 0
    for img in images:
        try:
            text = backend.image_to_markdown(img.path)
        except (OcrError, Exception) as exc:  # noqa: BLE001
            text = ""
            failures += 1
            results.append((img, f"_ошибка OCR: {type(exc).__name__}: {exc}_"))
            continue
        results.append((img, text))
    try:
        shutil.rmtree(images[0].path.parent, ignore_errors=True)
    except (OSError, IndexError):
        pass
    try:
        current = task.dst.read_text(encoding="utf-8")
    except OSError as exc:
        return Result(task.src, task.dst, "error", f"не удалось перечитать {task.dst.name}: {exc}", time.monotonic() - t0)
    if current.startswith(MARKER_PREFIX):
        current = current.split("\n", 1)[1] if "\n" in current else ""
    current = strip_previous_section(current).rstrip() + "\n\n"
    recognized = sum(1 for _, t in results if t.strip() and not t.startswith("_"))
    via = f"{backend.name}, images: {recognized}/{len(images)}"
    err = write_markdown(task, current + build_section(backend.name, results), source_marker, via=via)
    if err:
        return Result(task.src, task.dst, "error", err, time.monotonic() - t0)
    detail = f"вложенных картинок: {len(images)}, распознано: {recognized}" + (f", ошибок OCR: {failures}" if failures else "")
    return Result(task.src, task.dst, "ok", detail, time.monotonic() - t0, 0,
                  {"ocr": backend.name, "images": len(images), "recognized": recognized})
