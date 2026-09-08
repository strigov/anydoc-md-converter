#!/bin/zsh
# Двойной клик в Finder → установка/обновление AnyDoc MD Converter (спросит профиль: без OCR / Vision / Docling).
cd "$(dirname "$0")" || exit 1
/bin/zsh macos/install.sh
rc=$?
printf '\n[код завершения: %s] Нажми Enter, чтобы закрыть окно. ' "$rc"; read -r _
exit $rc
