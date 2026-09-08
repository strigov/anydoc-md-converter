"""Вложенные картинки офисных документов: извлечение из модели AnyDoc и сборка OCR-раздела."""

from __future__ import annotations

import struct
import tempfile
from dataclasses import dataclass
from pathlib import Path

# что умеет читать ImageIO/Vision и Docling; emf/wmf/svg — нет
OCR_MEDIA_TYPES: dict[str, str] = {
    "image/png": ".png", "image/jpeg": ".jpg", "image/jpg": ".jpg", "image/tiff": ".tif",
    "image/bmp": ".bmp", "image/gif": ".gif", "image/webp": ".webp", "image/heic": ".heic",
}
EMBEDDED_HEADING = "## Распознанные изображения"


@dataclass
class EmbeddedImage:
    index: int
    part: str
    media_type: str
    path: Path
    width: int
    height: int


def image_size(data: bytes) -> tuple[int, int] | None:
    """Размер по заголовку без декодирования: PNG, JPEG, GIF, BMP. Остальное — None."""
    try:
        if data[:8] == b"\x89PNG\r\n\x1a\n" and data[12:16] == b"IHDR":
            return struct.unpack(">II", data[16:24])
        if data[:6] in (b"GIF87a", b"GIF89a"):
            return struct.unpack("<HH", data[6:10])
        if data[:2] == b"BM" and len(data) >= 26:
            w, h = struct.unpack("<ii", data[18:26])
            return abs(w), abs(h)
        if data[:2] == b"\xff\xd8":
            i = 2
            n = len(data)
            while i + 4 <= n:
                if data[i] != 0xFF:
                    i += 1
                    continue
                marker = data[i + 1]
                if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
                    i += 2
                    continue
                seg_len = struct.unpack(">H", data[i + 2:i + 4])[0]
                if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                    if i + 9 > n:
                        return None
                    h, w = struct.unpack(">HH", data[i + 5:i + 9])
                    return w, h
                i += 2 + seg_len
    except (struct.error, IndexError):
        return None
    return None


def extract_images(path: Path, min_px: int, max_count: int) -> list[EmbeddedImage]:
    """Достаём картинки из модели документа AnyDoc во временную папку.
    Только для форматов с моделью документа (docx/pptx/xlsx/odt/…); для PDF модели нет."""
    import anydoc

    try:
        data = path.read_bytes()
        fmt = anydoc.format_from_bytes(data) or anydoc.format_from_path(path)
        if fmt in (None, "pdf", "csv"):
            return []
        doc = anydoc.to_document(data, fmt)
    except Exception:  # noqa: BLE001 — картинки не критичны, основной Markdown уже записан
        return []
    assets = list(getattr(doc, "assets", []) or [])
    if not assets:
        return []
    out: list[EmbeddedImage] = []
    tmp: Path | None = None
    seen: set[bytes] = set()
    for a in assets:
        ext = OCR_MEDIA_TYPES.get(str(a.media_type).lower())
        if not ext:
            continue
        blob = bytes(a.data)
        if len(blob) < 2048:
            continue
        size = image_size(blob)
        if size is not None and (size[0] < min_px or size[1] < min_px):
            continue
        digest = blob[:64] + len(blob).to_bytes(8, "big")  # дубликаты одной картинки
        if digest in seen:
            continue
        seen.add(digest)
        if tmp is None:
            tmp = Path(tempfile.mkdtemp(prefix="anydoc-md-img-"))
        idx = len(out) + 1
        p = tmp / f"{idx:03d}{ext}"
        p.write_bytes(blob)
        w, h = size or (0, 0)
        out.append(EmbeddedImage(idx, str(a.origin_part), str(a.media_type), p, w, h))
        if len(out) >= max_count:
            break
    return out


def demote_headings(text: str, by: int = 3) -> str:
    """Заголовки распознанного текста уводим ниже уровня «### Изображение N» (максимум ######)."""
    out = []
    in_code = False
    for line in text.splitlines():
        if line.lstrip().startswith("```"):
            in_code = not in_code
        if not in_code and line.startswith("#"):
            level = len(line) - len(line.lstrip("#"))
            if line[level:level + 1] == " ":
                line = "#" * min(6, level + by) + line[level:]
        out.append(line)
    return "\n".join(out)


def build_section(backend_name: str, results: list[tuple[EmbeddedImage, str]]) -> str:
    """Раздел в конец .md: по подразделу на картинку. results: (картинка, текст или '' если пусто)."""
    lines = [f"{EMBEDDED_HEADING} (OCR: {backend_name})", ""]
    for img, text in results:
        dims = f", {img.width}×{img.height}" if img.width else ""
        lines.append(f"### Изображение {img.index} — {img.part}{dims}")
        lines.append("")
        lines.append(demote_headings(text.strip()) if text.strip() else "_текст не распознан_")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def strip_previous_section(markdown: str) -> str:
    """Если файл уже содержит наш раздел (повторный прогон), убираем его."""
    pos = markdown.find("\n" + EMBEDDED_HEADING)
    return markdown[: pos + 1] if pos >= 0 else markdown
