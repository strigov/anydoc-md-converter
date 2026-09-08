"""CLI: python -m anydoc_md [опции] ПУТЬ..."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import APP_NAME, VARIANT, __version__
from .config import config_path, load_config, write_default_config


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="anydoc-md",
        description=f"{APP_NAME} {__version__} ({VARIANT}): документы → Markdown на движке Firecrawl AnyDoc, без OCR.",
    )
    p.add_argument("paths", nargs="*", type=Path, help="файлы и/или папки (папки обходятся рекурсивно)")
    p.add_argument("--quick-action", action="store_true", help="режим Finder: уведомления и диалог об ошибках")
    p.add_argument("-n", "--dry-run", action="store_true", help="только показать, что будет сделано")
    p.add_argument("-v", "--verbose", action="store_true", help="подробный вывод")
    p.add_argument("--mode", choices=["beside", "mirror"], help="куда класть .md (переопределяет config)")
    p.add_argument("--overwrite", choices=["never", "if_newer", "always"], help="политика перезаписи")
    p.add_argument("-j", "--workers", type=int, help="число рабочих процессов (переопределяет auto)")
    p.add_argument("--ocr", choices=["none", "vision", "docling"],
                   help="OCR для сканов и картинок: vision (встроенный macOS) или docling (структура + Vision)")
    p.add_argument("--no-update", action="store_true", help="не запускать фоновую проверку обновлений")
    p.add_argument("--update", action="store_true", help="обновить движок firecrawl-anydoc и выйти")
    p.add_argument("--quiet", action="store_true", help="(с --update) без вывода")
    p.add_argument("--init-config", action="store_true", help="создать config.json со значениями по умолчанию")
    p.add_argument("--version", action="store_true", help="показать версии и выйти")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.version:
        from .updater import engine_version
        print(f"{APP_NAME} {__version__} ({VARIANT}); firecrawl-anydoc {engine_version()}; python {sys.version.split()[0]}")
        return 0
    if args.init_config:
        print(write_default_config())
        return 0
    if args.update:
        from .updater import update_now
        return update_now(quiet=args.quiet)

    cfg = load_config()
    if args.mode:
        cfg["output_mode"] = args.mode
    if args.overwrite:
        cfg["overwrite"] = args.overwrite
    if args.workers:
        cfg["max_workers"] = args.workers
    if args.ocr:
        cfg["ocr_backend"] = args.ocr
    if cfg["ocr_backend"] != "none":
        from .ocr import backend_available
        ok, why = backend_available(cfg["ocr_backend"])
        if not ok:
            msg = (f"OCR-бэкенд «{cfg['ocr_backend']}» не установлен ({why}). "
                   f"Запусти «Установить.command» и выбери профиль с OCR.")
            if args.quick_action:
                from .runner import notify
                notify(APP_NAME, msg, "OCR недоступен")
            print(msg, file=sys.stderr)
            return 2

    if not args.paths:
        build_parser().print_help()
        print(f"\nконфиг: {config_path()}", file=sys.stderr)
        return 2

    from .runner import run
    from .updater import due, hold_engine_lock, spawn_background_update

    lock = hold_engine_lock()
    try:
        summary = run(args.paths, cfg, dry_run=args.dry_run, quick_action=args.quick_action, verbose=args.verbose)
    finally:
        lock.close()

    if cfg["auto_update"] and not args.no_update and not args.dry_run and due(int(cfg["update_interval_days"])):
        spawn_background_update()

    if not args.quick_action:
        print(summary.line())
    return 1 if summary.errors and not args.quick_action else 0


if __name__ == "__main__":
    sys.exit(main())
