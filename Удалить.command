#!/bin/zsh
# Двойной клик в Finder → удаление AnyDoc MD Converter.
cd "$(dirname "$0")" || exit 1
/bin/zsh macos/uninstall.sh
printf '\nНажми Enter, чтобы закрыть окно. '; read -r _
