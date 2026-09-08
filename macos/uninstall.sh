#!/bin/zsh
# Удаление AnyDoc MD Converter. Ключ --keep-config оставляет config.json, --keep-logs — логи.
set -u
APP_NAME="AnyDoc MD Converter"
APP_DIR="${ANYDOC_MD_HOME:-$HOME/Library/Application Support/$APP_NAME}"
SERVICES_DIR="$HOME/Library/Services"
KEEP_CONFIG=0; KEEP_LOGS=0
for a in "$@"; do
  case "$a" in
    --keep-config) KEEP_CONFIG=1 ;;
    --keep-logs) KEEP_LOGS=1 ;;
  esac
done

TITLES=("Конвертировать в Markdown (без OCR)" "Конвертировать в Markdown (OCR: Vision)" "Конвертировать в Markdown (OCR: Docling)")
if [ -f "$APP_DIR/installed-workflow.txt" ]; then
  while IFS= read -r t; do [ -n "$t" ] && TITLES+=("$t"); done < "$APP_DIR/installed-workflow.txt"
fi
[ -n "${ANYDOC_MD_MENU_TITLE:-}" ] && TITLES+=("$ANYDOC_MD_MENU_TITLE")
for t in "${TITLES[@]}"; do
  [ -d "$SERVICES_DIR/$t.workflow" ] && rm -rf "$SERVICES_DIR/$t.workflow" && echo "удалён Quick Action «$t»"
done
/System/Library/CoreServices/pbs -update >/dev/null 2>&1 || true

[ -L "$HOME/.local/bin/anydoc-md" ] && rm -f "$HOME/.local/bin/anydoc-md" && echo "удалён ~/.local/bin/anydoc-md"

if [ -d "$APP_DIR" ]; then
  if [ "$KEEP_CONFIG" = 1 ] && [ -f "$APP_DIR/config.json" ]; then
    cp "$APP_DIR/config.json" "$HOME/anydoc-md-config.backup.json"
    echo "config.json сохранён в ~/anydoc-md-config.backup.json"
  fi
  rm -rf "$APP_DIR" && echo "удалена папка $APP_DIR"
fi
if [ "$KEEP_LOGS" = 0 ] && [ -d "$HOME/Library/Logs/anydoc-md" ]; then
  rm -rf "$HOME/Library/Logs/anydoc-md" && echo "удалены логи ~/Library/Logs/anydoc-md"
fi
echo "Готово."
