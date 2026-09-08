"""Конфигурация: ~/Library/Application Support/AnyDoc MD Converter/config.json."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from . import APP_NAME

# Расширения, которые понимает anydoc 0.2.x (без OCR: PDF только текстовые).
SUPPORTED_EXTENSIONS: tuple[str, ...] = (
    ".doc", ".docx", ".docm",
    ".ppt", ".pps", ".pot", ".pptx", ".pptm", ".ppsx", ".ppsm",
    ".xls", ".xlsx", ".xlsm", ".xlsb",
    ".odt", ".ods", ".odp",
    ".rtf", ".epub", ".csv", ".pdf",
)

ZIP_EXTENSIONS: frozenset[str] = frozenset({
    ".docx", ".docm", ".pptx", ".pptm", ".ppsx", ".ppsm", ".xlsx", ".xlsm", ".xlsb",
    ".odt", ".ods", ".odp", ".epub",
})

DEFAULTS: dict[str, Any] = {
    # Куда класть .md:
    #   "beside" — рядом с исходником (report.docx -> report.md);
    #   "mirror" — для папки Docs создаётся соседняя Docs_md с той же структурой.
    "output_mode": "beside",
    "mirror_suffix": "_md",
    # Что делать, если .md уже существует:
    #   "if_newer" — перезаписать, только если исходник новее И файл создан нами;
    #   "never"    — никогда не трогать существующий;
    #   "always"   — перезаписывать всегда (но чужой .md без нашей метки всё равно не трогаем,
    #                 если только не overwrite_foreign=true).
    "overwrite": "if_newer",
    "overwrite_foreign": False,
    # Параллелизм: "auto" или число. auto = min(cap, physical_cores//2, RAM_GB//4), >=1,
    # и ещё вдвое меньше, если система уже нагружена.
    "max_workers": "auto",
    "max_workers_cap": 4,
    # Файлы крупнее этого порога (МБ) конвертируются строго по одному (не параллельно).
    "big_file_mb": 40,
    # Отдельный порог для zip-контейнеров (docx/xlsx/pptx/odt/ods/odp/epub): они сжаты
    # ~10x, и 9-мегабайтный xlsx при разборе съедает около 1 ГБ.
    "big_zip_file_mb": 6,
    # Ниже этого уровня свободной памяти (kern.memorystatus_level, %) новые задачи не выдаются.
    "memory_floor_percent": 12,
    # Максимальный размер файла (МБ), больше — пропускаем с записью в лог. 0 = без лимита.
    "max_file_mb": 500,
    "extensions": list(SUPPORTED_EXTENSIONS),
    "skip_dir_names": [".git", "node_modules", ".Trash", "__MACOSX", ".venv", "venv"],
    # Добавлять в начало .md HTML-комментарий с меткой и путём исходника (нужен для
    # безопасной перезаписи; markdown-рендеры его не показывают).
    "source_marker": True,
    # Уведомления macOS (osascript).
    "notifications": True,
    # Показывать диалог с кнопкой «Открыть лог», если были ошибки.
    "error_dialog": True,
    # OCR (версия 0.2): "none" | "vision" (встроенный OCR macOS) | "docling" (структура + Vision).
    # Применяется только к PDF, которые anydoc не смог прочитать сам, и к картинкам.
    "ocr_backend": "none",
    # Рабочих процессов для OCR: "auto" = 2 для vision, 1 для docling.
    "ocr_workers": "auto",
    "ocr_languages": ["ru-RU", "en-US"],
    # Разрешение рендера страниц PDF для Vision, dpi.
    "ocr_dpi": 200,
    # Картинки, которые берём в OCR-режимах (в режиме none игнорируются).
    "image_extensions": [".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp", ".heic"],
    # Автообновление firecrawl-anydoc: проверка не чаще раза в N дней, после конвертации.
    "auto_update": True,
    "update_interval_days": 7,
}


def app_dir() -> Path:
    env = os.environ.get("ANYDOC_MD_HOME")
    if env:
        return Path(env)
    return Path.home() / "Library" / "Application Support" / APP_NAME


def log_dir() -> Path:
    env = os.environ.get("ANYDOC_MD_LOGS")
    if env:
        return Path(env)
    return Path.home() / "Library" / "Logs" / "anydoc-md"


def config_path() -> Path:
    return app_dir() / "config.json"


def load_config(path: Path | None = None) -> dict[str, Any]:
    cfg = dict(DEFAULTS)
    p = path or config_path()
    if p.is_file():
        try:
            user = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise SystemExit(f"config.json повреждён ({p}): {exc}") from exc
        if not isinstance(user, dict):
            raise SystemExit(f"config.json должен содержать объект: {p}")
        for key, value in user.items():
            if key in cfg:
                cfg[key] = value
    cfg["extensions"] = _norm_ext(cfg["extensions"])
    cfg["image_extensions"] = _norm_ext(cfg["image_extensions"])
    return cfg


def _norm_ext(items) -> tuple[str, ...]:
    return tuple(e.lower() if e.startswith(".") else "." + e.lower() for e in items)


def write_default_config(path: Path | None = None) -> Path:
    p = path or config_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    if not p.exists():
        p.write_text(json.dumps(DEFAULTS, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return p
