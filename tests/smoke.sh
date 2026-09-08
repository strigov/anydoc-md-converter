#!/bin/zsh
# Интеграционный прогон на реальном движке: генерирует документы и конвертирует их
# установленным лаунчером (или тем, что в $ANYDOC_MD_LAUNCHER). OCR-часть — по установленному профилю.
set -euo pipefail
APP_DIR="${ANYDOC_MD_HOME:-$HOME/Library/Application Support/AnyDoc MD Converter}"
LAUNCHER="${ANYDOC_MD_LAUNCHER:-$APP_DIR/bin/anydoc-md}"
PROFILE="$(cat "$APP_DIR/profile.txt" 2>/dev/null || echo base)"
T="$(mktemp -d)"; trap 'rm -rf "$T"' EXIT
mkdir -p "$T/in/sub"
printf 'Заголовок\n\nАбзац текста.\n\n- один\n- два\n' > "$T/note.txt"
textutil -convert docx -output "$T/in/report.docx" "$T/note.txt"
textutil -convert rtf  -output "$T/in/sub/memo.rtf" "$T/note.txt"
cupsfilter "$T/note.txt" > "$T/in/report.pdf" 2>/dev/null
printf 'a,b\n1,2\n' > "$T/in/data.csv"
"$LAUNCHER" --no-update "$T/in"
for f in report.docx.md report.pdf.md data.md sub/memo.md; do
  [ -s "$T/in/$f" ] || { echo "НЕТ $f"; exit 1; }
done
grep -q 'anydoc-md: converted from "report.docx"' "$T/in/report.docx.md"
grep -q 'Абзац текста' "$T/in/report.pdf.md"
echo "base OK"

if [ "$PROFILE" = vision ] || [ "$PROFILE" = docling ]; then
  # скан: текстовый PDF → PNG (растр) → PDF без текстового слоя
  mkdir -p "$T/ocr"
  printf 'СКАН ДОКУМЕНТА\n\nРаспознанный абзац на русском языке. English words too.\n' > "$T/scan.txt"
  cupsfilter "$T/scan.txt" > "$T/scan-text.pdf" 2>/dev/null
  sips -s format png "$T/scan-text.pdf" --out "$T/ocr/scan.png" >/dev/null
  sips -s format pdf "$T/ocr/scan.png" --out "$T/ocr/scan.pdf" >/dev/null
  "$LAUNCHER" --no-update "$T/ocr/scan.pdf" | grep -q 'нужен OCR: 1'   # без OCR — пропуск
  "$LAUNCHER" --no-update --ocr vision "$T/ocr"
  grep -q '(ocr: vision)' "$T/ocr/scan.pdf.md" && grep -qi 'распознанный абзац' "$T/ocr/scan.pdf.md"
  grep -q '(ocr: vision)' "$T/ocr/scan.png.md"
  # вложенные картинки в docx/pptx
  FX="$(cd "$(dirname "$0")" && pwd)/fixtures"
  mkdir -p "$T/emb"; cp "$FX/embedded.docx" "$FX/embedded.pptx" "$T/emb/"
  "$LAUNCHER" --no-update --ocr vision "$T/emb"
  grep -q 'images: 1/1' "$T/emb/embedded.docx.md" && grep -q 'Ромашка' "$T/emb/embedded.docx.md"
  grep -q 'Распознанные изображения' "$T/emb/embedded.pptx.md"
  echo "vision OK (+embedded)"
fi
if [ "$PROFILE" = docling ]; then
  rm -f "$T/ocr"/*.md
  "$LAUNCHER" --no-update --ocr docling "$T/ocr/scan.pdf"
  grep -q '(ocr: docling)' "$T/ocr/scan.md" && grep -qi 'распознанный абзац' "$T/ocr/scan.md"
  echo "docling OK"
fi
echo "smoke OK ($PROFILE)"
