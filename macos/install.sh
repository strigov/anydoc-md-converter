#!/bin/zsh
# Установка AnyDoc MD Converter (версия без OCR) для текущего пользователя macOS.
#   • движок firecrawl-anydoc в изолированном venv:
#       ~/Library/Application Support/AnyDoc MD Converter/
#   • Quick Action в Finder: ~/Library/Services/<Название>.workflow
#   • CLI: ~/.local/bin/anydoc-md (симлинк)
# Повторный запуск = обновление (движок, скрипты, workflow). Ничего в системе не меняет,
# sudo не нужен. Python ≥3.10 приносится через uv (если в системе подходящего нет).
set -euo pipefail

HERE="$(cd "$(dirname "$0")/.." && pwd)"
APP_NAME="AnyDoc MD Converter"
APP_DIR="${ANYDOC_MD_HOME:-$HOME/Library/Application Support/$APP_NAME}"
SERVICES_DIR="$HOME/Library/Services"
MENU_TITLE="${ANYDOC_MD_MENU_TITLE:-Конвертировать в Markdown (без OCR)}"
PY_VERSION="${ANYDOC_MD_PYTHON:-3.12}"
PACKAGE="firecrawl-anydoc"

bold() { printf '\033[1m%s\033[0m\n' "$*"; }
step() { printf '\n\033[1;34m==>\033[0m \033[1m%s\033[0m\n' "$*"; }
die()  { printf '\033[1;31mОшибка:\033[0m %s\n' "$*" >&2; exit 1; }

[ "$(uname -s)" = "Darwin" ] || die "этот установщик только для macOS"
[ -d "$HERE/src/anydoc_md" ] || die "не найден $HERE/src/anydoc_md — запускай из папки проекта"

step "Папка приложения: $APP_DIR"
mkdir -p "$APP_DIR/bin" "$APP_DIR/lib" "$APP_DIR/tools" "$APP_DIR/python"

# ---------- 1. Python ≥3.10: сначала uv, иначе системный ----------
UV=""
for c in "$APP_DIR/tools/uv" "$HOME/.local/bin/uv" /opt/homebrew/bin/uv /usr/local/bin/uv "$(command -v uv 2>/dev/null || true)"; do
  [ -n "$c" ] && [ -x "$c" ] && UV="$c" && break
done
if [ -z "$UV" ]; then
  step "Скачиваю uv (менеджер Python) в $APP_DIR/tools"
  if curl -LsSf https://astral.sh/uv/install.sh | env UV_UNMANAGED_INSTALL="$APP_DIR/tools" sh >/dev/null 2>&1; then
    UV="$APP_DIR/tools/uv"
  else
    echo "  uv скачать не удалось — попробую системный python3 ≥ 3.10"
  fi
fi

export UV_PYTHON_INSTALL_DIR="$APP_DIR/python"
VENV="$APP_DIR/venv"
VENV_PY="$VENV/bin/python"

find_system_python() {
  local c
  for c in python3.13 python3.12 python3.11 python3.10 python3 \
           /opt/homebrew/bin/python3 /usr/local/bin/python3 \
           /Library/Frameworks/Python.framework/Versions/3.1[0-9]/bin/python3; do
    c="$(command -v "$c" 2>/dev/null || echo "$c")"
    [ -x "$c" ] || continue
    if "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null; then
      echo "$c"; return 0
    fi
  done
  return 1
}

step "Виртуальное окружение: $VENV"
if [ -n "$UV" ]; then
  echo "  uv: $("$UV" --version)"
  "$UV" venv -q --allow-existing --python "$PY_VERSION" "$VENV" \
    || "$UV" venv -q --allow-existing --python ">=3.10" "$VENV" \
    || die "uv не смог создать venv (нет сети для загрузки Python $PY_VERSION?)"
else
  SYS_PY="$(find_system_python)" || die "нет Python ≥ 3.10 и не удалось скачать uv. Поставь Python с python.org или brew install python@3.12 и запусти снова."
  echo "  python: $SYS_PY ($("$SYS_PY" --version))"
  [ -x "$VENV_PY" ] || "$SYS_PY" -m venv "$VENV"
fi
[ -x "$VENV_PY" ] || die "venv не создан: $VENV_PY"
echo "  $("$VENV_PY" --version) → $VENV_PY"

# ---------- 2. Движок ----------
step "Устанавливаю/обновляю $PACKAGE"
if [ -n "$UV" ]; then
  "$UV" pip install -q --python "$VENV_PY" --upgrade "$PACKAGE" || die "uv pip install $PACKAGE не удался"
else
  "$VENV_PY" -m pip install -q --disable-pip-version-check --upgrade pip "$PACKAGE" || die "pip install $PACKAGE не удался"
fi
ENGINE_VER="$("$VENV_PY" -c "from importlib.metadata import version; print(version('$PACKAGE'))")"
echo "  $PACKAGE $ENGINE_VER"

# ---------- 3. Наши скрипты ----------
step "Копирую скрипты конвертера"
rm -rf "$APP_DIR/lib/anydoc_md"
cp -R "$HERE/src/anydoc_md" "$APP_DIR/lib/anydoc_md"
find "$APP_DIR/lib" -name '__pycache__' -type d -prune -exec rm -rf {} +
cp "$HERE/bin/anydoc-md" "$APP_DIR/bin/anydoc-md"
chmod 755 "$APP_DIR/bin/anydoc-md"
cp "$HERE/macos/quick-action.py" "$APP_DIR/tools/quick-action.py"
cp "$HERE/macos/uninstall.sh" "$APP_DIR/tools/uninstall.sh"
chmod 755 "$APP_DIR/tools/quick-action.py" "$APP_DIR/tools/uninstall.sh"
ANYDOC_MD_HOME="$APP_DIR" "$APP_DIR/bin/anydoc-md" --init-config >/dev/null
echo "  конфиг: $APP_DIR/config.json"

# ---------- 4. Quick Action ----------
step "Quick Action в Finder: «$MENU_TITLE»"
mkdir -p "$SERVICES_DIR"
PREV_TITLE_FILE="$APP_DIR/installed-workflow.txt"
if [ -f "$PREV_TITLE_FILE" ]; then
  PREV="$(cat "$PREV_TITLE_FILE")"
  if [ -n "$PREV" ] && [ "$PREV" != "$MENU_TITLE" ] && [ -d "$SERVICES_DIR/$PREV.workflow" ]; then
    rm -rf "$SERVICES_DIR/$PREV.workflow"; echo "  удалён старый «$PREV»"
  fi
fi
rm -rf "$SERVICES_DIR/$MENU_TITLE.workflow"
/usr/bin/python3 "$HERE/macos/quick-action.py" "$SERVICES_DIR" "$MENU_TITLE" "$APP_DIR/bin/anydoc-md" >/dev/null
printf '%s' "$MENU_TITLE" > "$PREV_TITLE_FILE"
/System/Library/CoreServices/pbs -update >/dev/null 2>&1 || true
/System/Library/CoreServices/pbs -flush >/dev/null 2>&1 || true
echo "  $SERVICES_DIR/$MENU_TITLE.workflow"

# ---------- 5. CLI-симлинк ----------
mkdir -p "$HOME/.local/bin"
ln -sf "$APP_DIR/bin/anydoc-md" "$HOME/.local/bin/anydoc-md"

# ---------- 6. Самопроверка ----------
step "Самопроверка"
T="$(mktemp -d)"
printf 'a,b\n1,2\n' > "$T/probe.csv"
if ANYDOC_MD_HOME="$APP_DIR" "$APP_DIR/bin/anydoc-md" --no-update "$T/probe.csv" >/dev/null 2>&1 && grep -q '| a | b |' "$T/probe.md"; then
  echo "  csv → md: OK"
else
  rm -rf "$T"; die "пробная конвертация не удалась, см. ~/Library/Logs/anydoc-md/latest.log"
fi
rm -rf "$T"
ANYDOC_MD_HOME="$APP_DIR" "$APP_DIR/bin/anydoc-md" --version | sed 's/^/  /'

printf '\n'
bold "Готово. Как пользоваться:"
cat <<TXT
  • Finder → правый клик по файлам или папкам → Быстрые действия → «$MENU_TITLE».
    (Если пункта нет: Системные настройки → Основные → Расширения → Finder → включить.)
  • Терминал: anydoc-md ПАПКА_ИЛИ_ФАЙЛ …   (симлинк в ~/.local/bin; добавь его в PATH, если нужно)
  • Настройки: $APP_DIR/config.json
  • Логи: ~/Library/Logs/anydoc-md/latest.log
  • При первом запуске macOS может спросить доступ к «Документам»/«Рабочему столу» — разреши.
TXT
