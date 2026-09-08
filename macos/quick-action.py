#!/usr/bin/env python3
"""Генерирует бандл Quick Action (Automator Services workflow) для Finder.

Использование: quick-action.py ВЫХОДНАЯ_ПАПКА "Название пункта меню" /путь/к/anydoc-md ["--ocr vision"]
Работает на системном python3 (3.9), сторонних модулей не требует.
"""
import plistlib
import sys
import uuid
from pathlib import Path


def build(out_dir: Path, menu_title: str, launcher: str, extra_args: str = "") -> Path:
    bundle = out_dir / f"{menu_title}.workflow"
    contents = bundle / "Contents"
    contents.mkdir(parents=True, exist_ok=True)

    script = f'''#!/bin/zsh
# Quick Action «{menu_title}» — AnyDoc MD Converter (версия без OCR).
# Finder → правый клик по файлам/папкам → Markdown рядом с исходниками.
# Движок лежит в ~/Library/Application Support/AnyDoc MD Converter (папка «Документы»
# службам Finder напрямую недоступна). Установка/обновление: «Установить.command».
LAUNCHER="{launcher}"
if [ ! -x "$LAUNCHER" ]; then
  /usr/bin/osascript -e 'display alert "AnyDoc MD Converter" message "Движок не установлен: нет '"$LAUNCHER"'. Запусти «Установить.command»." as warning' >/dev/null 2>&1
  exit 0
fi
"$LAUNCHER" --quick-action {extra_args} "$@" >/dev/null 2>&1
exit 0
'''

    action = {
        "AMAccepts": {"Container": "List", "Optional": True, "Types": ["com.apple.cocoa.string"]},
        "AMActionVersion": "2.0.3",
        "AMApplication": ["Automator"],
        "AMParameterProperties": {k: {} for k in ("COMMAND_STRING", "CheckedForUserDefaultShell", "inputMethod", "shell", "source")},
        "AMProvides": {"Container": "List", "Types": ["com.apple.cocoa.string"]},
        "ActionBundlePath": "/System/Library/Automator/Run Shell Script.action",
        "ActionName": "Run Shell Script",
        "ActionParameters": {
            "COMMAND_STRING": script,
            "CheckedForUserDefaultShell": True,
            "inputMethod": 1,  # 1 = «как аргументы» ($@)
            "shell": "/bin/zsh",
            "source": "",
        },
        "BundleIdentifier": "com.apple.RunShellScript",
        "CFBundleVersion": "2.0.3",
        "CanShowSelectedItemsWhenRun": False,
        "CanShowWhenRun": True,
        "Category": ["AMCategoryUtilities"],
        "Class Name": "RunShellScriptAction",
        "InputUUID": str(uuid.uuid4()).upper(),
        "Keywords": ["Shell", "Script", "Command", "Run", "Unix"],
        "OutputUUID": str(uuid.uuid4()).upper(),
        "UUID": str(uuid.uuid4()).upper(),
        "UnlocalizedApplications": ["Automator"],
        "arguments": {
            "0": {"default value": 0, "name": "inputMethod", "required": "0", "type": "0", "uuid": "0"},
            "1": {"default value": False, "name": "CheckedForUserDefaultShell", "required": "0", "type": "0", "uuid": "1"},
            "2": {"default value": "", "name": "source", "required": "0", "type": "0", "uuid": "2"},
            "3": {"default value": "", "name": "COMMAND_STRING", "required": "0", "type": "0", "uuid": "3"},
            "4": {"default value": "/bin/sh", "name": "shell", "required": "0", "type": "0", "uuid": "4"},
        },
        "isViewVisible": True,
        "location": "309.000000:253.000000",
        "nibPath": "/System/Library/Automator/Run Shell Script.action/Contents/Resources/Base.lproj/main.nib",
    }
    wflow = {
        "AMApplicationBuild": "528",
        "AMApplicationVersion": "2.10",
        "AMDocumentVersion": "2",
        "actions": [{"action": action, "isViewVisible": True}],
        "connectors": {},
        "workflowMetaData": {
            "applicationBundleIDsByPath": {},
            "applicationPaths": [],
            "inputTypeIdentifier": "com.apple.Automator.fileSystemObject",
            "outputTypeIdentifier": "com.apple.Automator.nothing",
            "presentationMode": 15,
            "processesInput": 0,
            "serviceApplicationBundleID": "com.apple.finder",
            "serviceApplicationPath": "/System/Library/CoreServices/Finder.app",
            "serviceInputTypeIdentifier": "com.apple.Automator.fileSystemObject",
            "serviceOutputTypeIdentifier": "com.apple.Automator.nothing",
            "serviceProcessesInput": 0,
            "systemImageName": "NSActionTemplate",
            "useAutomaticInputType": 0,
            "workflowTypeIdentifier": "com.apple.Automator.servicesMenu",
        },
    }
    info = {
        "NSServices": [{
            "NSBackgroundColorName": "background",
            "NSIconName": "NSActionTemplate",
            "NSMenuItem": {"default": menu_title},
            "NSMessage": "runWorkflowAsService",
            "NSRequiredContext": {"NSApplicationIdentifier": "com.apple.finder"},
            "NSSendFileTypes": ["public.item"],
        }]
    }
    with (contents / "document.wflow").open("wb") as fh:
        plistlib.dump(wflow, fh, sort_keys=True)
    with (contents / "Info.plist").open("wb") as fh:
        plistlib.dump(info, fh, sort_keys=True)
    return bundle


if __name__ == "__main__":
    if len(sys.argv) not in (4, 5):
        sys.exit(__doc__)
    print(build(Path(sys.argv[1]), sys.argv[2], sys.argv[3], sys.argv[4] if len(sys.argv) == 5 else ""))
