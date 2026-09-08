"""Сбор входных файлов и вычисление путей вывода."""

from __future__ import annotations

import os
from collections import defaultdict
from pathlib import Path
from typing import Iterable

from .config import ZIP_EXTENSIONS
from .convert import Task


def _is_hidden_or_lock(p: Path) -> bool:
    n = p.name
    return n.startswith(".") or n.startswith("~$") or n.startswith(".~lock")


def collect_sources(inputs: Iterable[Path], extensions: tuple[str, ...], skip_dir_names: list[str],
                    mirror_suffix: str) -> list[tuple[Path, Path | None]]:
    """Возвращает список (файл, корень-папка-или-None). Корень нужен для режима mirror."""
    seen: set[Path] = set()
    out: list[tuple[Path, Path | None]] = []
    skip = set(skip_dir_names)

    def add(f: Path, root: Path | None) -> None:
        rp = f.resolve()
        if rp in seen:
            return
        seen.add(rp)
        out.append((f, root))

    for raw in inputs:
        p = Path(raw).expanduser()
        if p.is_dir():
            root = p
            for dirpath, dirnames, filenames in os.walk(p):
                d = Path(dirpath)
                # не заходим в скрытые, служебные и в наши же зеркальные папки
                dirnames[:] = sorted(
                    x for x in dirnames
                    if x not in skip and not x.startswith(".") and not x.endswith(mirror_suffix)
                )
                for fn in sorted(filenames):
                    f = d / fn
                    if _is_hidden_or_lock(f):
                        continue
                    if f.suffix.lower() in extensions and f.is_file():
                        add(f, root)
        elif p.is_file():
            if p.suffix.lower() in extensions and not _is_hidden_or_lock(p):
                add(p, None)
        # несуществующие пути молча пропускаем — вызывающий логирует список входов
    return out


def plan_tasks(sources: list[tuple[Path, Path | None]], output_mode: str, mirror_suffix: str,
               big_file_bytes: int, max_file_bytes: int,
               big_zip_bytes: int | None = None,
               image_extensions: tuple[str, ...] = ()) -> tuple[list[Task], list[tuple[Path, str]]]:
    """Строим задачи. Коллизии имён (report.docx + report.pdf) → report.docx.md / report.pdf.md."""
    skipped: list[tuple[Path, str]] = []
    if big_zip_bytes is None:
        big_zip_bytes = big_file_bytes

    def base_dst(src: Path, root: Path | None) -> Path:
        if output_mode == "mirror" and root is not None:
            mirror_root = root.with_name(root.name + mirror_suffix)
            return mirror_root / src.relative_to(root)
        return src

    # группируем по (папка вывода, stem без учёта регистра)
    groups: dict[tuple[Path, str], list[tuple[Path, Path]]] = defaultdict(list)
    for src, root in sources:
        dst_base = base_dst(src, root)
        groups[(dst_base.parent, dst_base.stem.lower())].append((src, dst_base))

    tasks: list[Task] = []
    for (_, _), items in groups.items():
        collide = len(items) > 1
        for src, dst_base in items:
            try:
                size = src.stat().st_size
            except OSError as exc:
                skipped.append((src, f"не читается: {exc}"))
                continue
            if max_file_bytes and size > max_file_bytes:
                skipped.append((src, f"слишком большой ({size // (1024 * 1024)} МБ > лимита)"))
                continue
            if size == 0:
                skipped.append((src, "пустой файл"))
                continue
            dst = dst_base.with_name(dst_base.name + ".md") if collide else dst_base.with_suffix(".md")
            ext = src.suffix.lower()
            threshold = big_zip_bytes if ext in ZIP_EXTENSIONS else big_file_bytes
            kind = "image" if ext in image_extensions else "doc"
            tasks.append(Task(src=src, dst=dst, big=size >= threshold, kind=kind))
    # большие файлы — в конец, чтобы мелочь не ждала
    tasks.sort(key=lambda t: (t.big, str(t.src)))
    return tasks, skipped
