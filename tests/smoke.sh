#!/bin/zsh
# Интеграционный прогон на реальном движке: генерирует документы и конвертирует их
# установленным лаунчером (или тем, что в $ANYDOC_MD_LAUNCHER).
set -euo pipefail
LAUNCHER="${ANYDOC_MD_LAUNCHER:-$HOME/Library/Application Support/AnyDoc MD Converter/bin/anydoc-md}"
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
echo "smoke OK"
