"""OCR + структура через Docling (IBM) с OCR-движком macOS Vision (ocrmac).

Docling делает анализ разметки страницы (заголовки, таблицы, порядок чтения) и вызывает Vision
только для областей без текстового слоя. Модели (~1 ГБ) докачиваются при установке
(docling-tools models download) либо при первом запуске. Тяжёлый: PyTorch, 2–4 ГБ памяти,
поэтому runner держит для него ровно один рабочий процесс.
"""

from __future__ import annotations

import os
from pathlib import Path

from . import OcrError

_CONVERTER = None  # кэш на процесс: модели грузятся один раз


class DoclingBackend:
    name = "docling"

    def __init__(self, languages: list[str]) -> None:
        self.languages = languages
        try:
            import docling  # noqa: F401
            import ocrmac  # noqa: F401
        except ImportError as exc:
            raise OcrError(f"Docling недоступен: {exc}. Переустанови с профилем Docling.") from exc

    def _converter(self):
        global _CONVERTER
        if _CONVERTER is not None:
            return _CONVERTER
        os.environ.setdefault("OMP_NUM_THREADS", "4")
        os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
        from docling.datamodel.base_models import InputFormat
        from docling.datamodel.pipeline_options import OcrMacOptions, PdfPipelineOptions
        from docling.document_converter import DocumentConverter, ImageFormatOption, PdfFormatOption

        models = os.environ.get("ANYDOC_MD_MODELS")
        opts = PdfPipelineOptions(artifacts_path=models) if models and Path(models).is_dir() else PdfPipelineOptions()
        opts.do_ocr = True
        opts.ocr_options = OcrMacOptions(lang=self.languages)
        opts.do_table_structure = True
        opts.table_structure_options.do_cell_matching = True
        _CONVERTER = DocumentConverter(format_options={
            InputFormat.PDF: PdfFormatOption(pipeline_options=opts),
            InputFormat.IMAGE: ImageFormatOption(pipeline_options=opts),
        })
        return _CONVERTER

    def _convert(self, path: Path) -> str:
        from docling.datamodel.base_models import ConversionStatus

        try:
            result = self._converter().convert(str(path), raises_on_error=False)
        except Exception as exc:  # noqa: BLE001
            raise OcrError(f"Docling: {type(exc).__name__}: {exc}") from exc
        if result.status not in (ConversionStatus.SUCCESS, ConversionStatus.PARTIAL_SUCCESS):
            errs = "; ".join(str(e.error_message) for e in (result.errors or [])[:3])
            raise OcrError(f"Docling не сконвертировал ({result.status.value}): {errs or 'без подробностей'}")
        md = result.document.export_to_markdown()
        if not md.strip():
            raise OcrError("Docling вернул пустой документ")
        return md

    def pdf_to_markdown(self, path: Path, ocr_pages: list[int]) -> str:
        return self._convert(path)

    def image_to_markdown(self, path: Path) -> str:
        return self._convert(path)
