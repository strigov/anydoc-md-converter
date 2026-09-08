"""OCR-бэкенды. Контракт: backend.pdf_to_markdown(path, ocr_pages) и backend.image_to_markdown(path).

Оба возвращают Markdown-строку либо бросают OcrError. Бэкенд импортируется лениво — в главном
процессе тяжёлые зависимости (PyObjC, Docling) не загружаются вовсе.
"""

from __future__ import annotations

BACKENDS = ("none", "vision", "docling")
# картинки, которые принимаем в OCR-режимах
IMAGE_EXTENSIONS: tuple[str, ...] = (".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp", ".heic")


class OcrError(Exception):
    """Ошибка OCR-бэкенда, понятная пользователю."""


def get_backend(name: str, cfg: dict):
    if name == "vision":
        from .vision import VisionBackend
        return VisionBackend(languages=list(cfg.get("ocr_languages", ["ru-RU", "en-US"])),
                             dpi=int(cfg.get("ocr_dpi", 200)))
    if name == "docling":
        from .docling_backend import DoclingBackend
        return DoclingBackend(languages=list(cfg.get("ocr_languages", ["ru-RU", "en-US"])))
    raise OcrError(f"неизвестный OCR-бэкенд: {name}")


def backend_available(name: str) -> tuple[bool, str]:
    """Установлены ли зависимости бэкенда (без их полной инициализации)."""
    import importlib.util as iu
    if name == "none":
        return True, ""
    if name == "vision":
        missing = [m for m in ("Vision", "Quartz") if iu.find_spec(m) is None]
        return (not missing), ("нет PyObjC-модулей: " + ", ".join(missing) if missing else "")
    if name == "docling":
        missing = [m for m in ("docling", "ocrmac") if iu.find_spec(m) is None]
        return (not missing), ("нет пакетов: " + ", ".join(missing) if missing else "")
    return False, f"неизвестный бэкенд {name}"
