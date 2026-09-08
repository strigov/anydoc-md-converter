"""OCR через встроенный в macOS Vision framework (PyObjC). Полностью офлайн.

PDF: страницы из списка ocr_pages рендерятся через Quartz и распознаются Vision, остальные
берутся текстом через PDFKit. Картинки: ImageIO → Vision. Выход — текст абзацами (структуру
Vision не размечает; для заголовков/таблиц нужен бэкенд docling).
"""

from __future__ import annotations

import statistics
from pathlib import Path

from . import OcrError


class VisionBackend:
    name = "vision"

    def __init__(self, languages: list[str], dpi: int = 200) -> None:
        self.languages = languages
        self.dpi = dpi
        try:
            import Quartz  # noqa: F401
            import Vision  # noqa: F401
        except ImportError as exc:
            raise OcrError(f"Vision недоступен: {exc}. Переустанови с профилем OCR.") from exc

    # ---------- публичный контракт ----------
    def pdf_to_markdown(self, path: Path, ocr_pages: list[int]) -> str:
        import Quartz
        from Foundation import NSURL

        url = NSURL.fileURLWithPath_(str(path))
        cg = Quartz.CGPDFDocumentCreateWithURL(url)
        if cg is None:
            raise OcrError("Quartz не открыл PDF")
        n = Quartz.CGPDFDocumentGetNumberOfPages(cg)
        if n == 0:
            raise OcrError("в PDF нет страниц")
        ocr_set = set(ocr_pages) if ocr_pages else set(range(1, n + 1))

        pdfkit_doc = Quartz.PDFDocument.alloc().initWithURL_(url)
        parts: list[str] = []
        for i in range(1, n + 1):
            if i in ocr_set:
                image = self._render_page(cg, i)
                text = self._recognize(image)
                src = "OCR"
            else:
                page = pdfkit_doc.pageAtIndex_(i - 1) if pdfkit_doc is not None else None
                text = (page.string() or "") if page is not None else ""
                text = _normalize_text_layer(text)
                src = "текст"
            body = text.strip()
            if n > 1:
                parts.append(f"<!-- страница {i} ({src}) -->\n\n{body}\n" if body else f"<!-- страница {i} ({src}): пусто -->\n")
            else:
                parts.append(body + "\n")
        return "\n".join(parts)

    def image_to_markdown(self, path: Path) -> str:
        import Quartz
        from Foundation import NSURL

        src = Quartz.CGImageSourceCreateWithURL(NSURL.fileURLWithPath_(str(path)), None)
        if src is None:
            raise OcrError("ImageIO не открыл изображение")
        count = Quartz.CGImageSourceGetCount(src) or 1
        parts = []
        for i in range(count):  # многостраничный TIFF
            image = Quartz.CGImageSourceCreateImageAtIndex(src, i, None)
            if image is None:
                continue
            text = self._recognize(self._flatten(image)).strip()
            parts.append((f"<!-- страница {i + 1} (OCR) -->\n\n" if count > 1 else "") + text + "\n")
        return "\n".join(parts) if parts else ""

    # ---------- внутренности ----------
    def _render_page(self, cg, index: int):
        import Quartz

        page = Quartz.CGPDFDocumentGetPage(cg, index)
        box = Quartz.CGPDFPageGetBoxRect(page, Quartz.kCGPDFMediaBox)
        rotation = Quartz.CGPDFPageGetRotationAngle(page) % 360
        pw, ph = box.size.width, box.size.height
        if rotation in (90, 270):
            pw, ph = ph, pw
        scale = self.dpi / 72.0
        # ограничим сторону 5000 px: 200 dpi для A0 не нужно, а память экономит
        longest = max(pw, ph) * scale
        if longest > 5000:
            scale *= 5000 / longest
        w, h = max(1, int(pw * scale)), max(1, int(ph * scale))
        cs = Quartz.CGColorSpaceCreateDeviceRGB()
        ctx = Quartz.CGBitmapContextCreate(None, w, h, 8, w * 4, cs, Quartz.kCGImageAlphaNoneSkipLast)
        if ctx is None:
            raise OcrError(f"не удалось создать bitmap {w}x{h}")
        Quartz.CGContextSetRGBFillColor(ctx, 1, 1, 1, 1)
        Quartz.CGContextFillRect(ctx, Quartz.CGRectMake(0, 0, w, h))
        transform = Quartz.CGPDFPageGetDrawingTransform(page, Quartz.kCGPDFMediaBox,
                                                         Quartz.CGRectMake(0, 0, w, h), 0, True)
        Quartz.CGContextConcatCTM(ctx, transform)
        Quartz.CGContextSetInterpolationQuality(ctx, Quartz.kCGInterpolationHigh)
        Quartz.CGContextDrawPDFPage(ctx, page)
        return Quartz.CGBitmapContextCreateImage(ctx)

    def _flatten(self, image):
        """Кладём картинку на белый фон (прозрачные PNG Vision читает плохо) и увеличиваем мелкие:
        длинная сторона не меньше 2000 px, не больше 5000."""
        import Quartz

        w0, h0 = Quartz.CGImageGetWidth(image), Quartz.CGImageGetHeight(image)
        if not w0 or not h0:
            return image
        longest = max(w0, h0)
        scale = 1.0
        if longest < 2000:
            scale = min(2000 / longest, 3.0)
        elif longest > 5000:
            scale = 5000 / longest
        w, h = max(1, int(w0 * scale)), max(1, int(h0 * scale))
        cs = Quartz.CGColorSpaceCreateDeviceRGB()
        ctx = Quartz.CGBitmapContextCreate(None, w, h, 8, w * 4, cs, Quartz.kCGImageAlphaNoneSkipLast)
        if ctx is None:
            return image
        Quartz.CGContextSetRGBFillColor(ctx, 1, 1, 1, 1)
        Quartz.CGContextFillRect(ctx, Quartz.CGRectMake(0, 0, w, h))
        Quartz.CGContextSetInterpolationQuality(ctx, Quartz.kCGInterpolationHigh)
        Quartz.CGContextDrawImage(ctx, Quartz.CGRectMake(0, 0, w, h), image)
        return Quartz.CGBitmapContextCreateImage(ctx)

    def _recognize(self, image) -> str:
        import Vision

        req = Vision.VNRecognizeTextRequest.alloc().init()
        req.setRecognitionLevel_(Vision.VNRequestTextRecognitionLevelAccurate)
        req.setUsesLanguageCorrection_(True)
        if self.languages:
            req.setRecognitionLanguages_(self.languages)
        if hasattr(req, "setAutomaticallyDetectsLanguage_"):
            req.setAutomaticallyDetectsLanguage_(True)
        handler = Vision.VNImageRequestHandler.alloc().initWithCGImage_options_(image, None)
        ok, err = handler.performRequests_error_([req], None)
        if not ok:
            raise OcrError(f"Vision: {err}")
        lines = []
        for obs in req.results() or []:
            cands = obs.topCandidates_(1)
            if not cands:
                continue
            bb = obs.boundingBox()  # нормализованные координаты, origin слева-снизу
            lines.append((bb.origin.y + bb.size.height, bb.origin.x, bb.size.height, cands[0].string()))
        return _lines_to_paragraphs(lines)


def _lines_to_paragraphs(lines: list[tuple[float, float, float, str]]) -> str:
    """Сначала группируем наблюдения в строки (ячейки таблицы стоят на одной высоте),
    внутри строки сортируем слева направо, затем склеиваем строки в абзацы по промежуткам."""
    if not lines:
        return ""
    heights = [h for _, _, h, _ in lines if h > 0]
    med_h = statistics.median(heights) if heights else 0.02
    lines.sort(key=lambda t: -t[0])
    rows: list[list[tuple[float, float, float, str]]] = []
    for item in lines:
        top, _x, h, _t = item
        if rows and abs(rows[-1][0][0] - top) < max(h, rows[-1][0][2]) * 0.5:
            rows[-1].append(item)
        else:
            rows.append([item])
    out: list[str] = []
    buf: list[str] = []
    table: list[list[str]] = []
    prev_top: float | None = None
    prev_h = med_h

    def flush_table() -> None:
        if not table:
            return
        if len(table) >= 2:
            width = max(len(r) for r in table)
            norm = [r + [""] * (width - len(r)) for r in table]
            out.append("\n".join(["| " + " | ".join(norm[0]) + " |", "|" + " --- |" * width]
                                 + ["| " + " | ".join(r) + " |" for r in norm[1:]]))
        else:
            out.append("  ".join(table[0]))
        table.clear()

    for row in rows:
        row.sort(key=lambda t: t[1])
        top = max(t[0] for t in row)
        h = max(t[2] for t in row)
        cells = [t[3].strip().replace("|", "/") for t in row]
        if len(cells) >= 2:
            # строка из нескольких фрагментов на одной высоте — похоже на строку таблицы
            if buf:
                out.append(" ".join(buf))
                buf = []
            table.append(cells)
            prev_top, prev_h = top, h
            continue
        flush_table()
        text = cells[0]
        if prev_top is not None:
            gap = prev_top - prev_h - top  # расстояние между низом прошлой строки и верхом этой
            if gap > med_h * 0.9 or (buf and text[:1].isupper() and buf[-1].rstrip().endswith((".", "!", "?", ":")) and gap > med_h * 0.4):
                out.append(" ".join(buf))
                buf = []
        if buf and buf[-1].endswith("-") and text[:1].islower():
            buf[-1] = buf[-1][:-1] + text
        else:
            buf.append(text)
        prev_top, prev_h = top, h
    if buf:
        out.append(" ".join(buf))
    flush_table()
    return "\n\n".join(p for p in out if p)


def _normalize_text_layer(text: str) -> str:
    """Текстовый слой из PDFKit: объединяем переносы строк внутри абзацев."""
    paras = []
    for block in text.replace("\r", "\n").split("\n\n"):
        s = " ".join(line.strip() for line in block.split("\n") if line.strip())
        if s:
            paras.append(s)
    return "\n\n".join(paras)
