"""Оркестрация: пул процессов, ограничение параллелизма, лог, уведомления."""

from __future__ import annotations

import logging
import multiprocessing as mp
import os
import subprocess
import sys
import time
from concurrent.futures import FIRST_COMPLETED, Future, ProcessPoolExecutor, wait
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from . import APP_NAME, VARIANT, __version__
from .config import log_dir
from .convert import Result, Task, convert_one, should_write
from .scan import collect_sources, plan_tasks
from .system import auto_workers, memory_level_percent

log = logging.getLogger("anydoc_md")

_BIG_LOCK = None  # инициализируется в рабочем процессе


def _worker_init(big_lock) -> None:  # noqa: ANN001
    global _BIG_LOCK
    _BIG_LOCK = big_lock
    try:
        os.nice(5)
    except OSError:
        pass


def _worker_run(task: Task, source_marker: bool) -> Result:
    if task.big and _BIG_LOCK is not None:
        with _BIG_LOCK:
            return convert_one(task, source_marker)
    return convert_one(task, source_marker)


class Summary:
    def __init__(self) -> None:
        self.ok = 0
        self.skipped = 0
        self.needs_ocr = 0
        self.errors = 0
        self.problems: list[tuple[Path, str]] = []
        self.started = time.monotonic()

    def add(self, r: Result) -> None:
        if r.status == "ok":
            self.ok += 1
        elif r.status == "skipped":
            self.skipped += 1
        elif r.status == "needs_ocr":
            self.needs_ocr += 1
            self.problems.append((r.src, r.detail))
        else:
            self.errors += 1
            self.problems.append((r.src, r.detail))

    @property
    def total(self) -> int:
        return self.ok + self.skipped + self.needs_ocr + self.errors

    def line(self) -> str:
        parts = [f"готово: {self.ok}"]
        if self.skipped:
            parts.append(f"пропущено: {self.skipped}")
        if self.needs_ocr:
            parts.append(f"нужен OCR: {self.needs_ocr}")
        if self.errors:
            parts.append(f"ошибок: {self.errors}")
        return ", ".join(parts) + f" за {time.monotonic() - self.started:.0f} с"


def setup_logging(verbose: bool) -> Path:
    d = log_dir()
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"run-{datetime.now():%Y%m%d-%H%M%S}-{os.getpid()}.log"
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s", "%H:%M:%S")
    fh = logging.FileHandler(path, encoding="utf-8")
    fh.setFormatter(fmt)
    log.addHandler(fh)
    if sys.stderr.isatty() or verbose:
        sh = logging.StreamHandler(sys.stderr)
        sh.setFormatter(logging.Formatter("%(message)s"))
        log.addHandler(sh)
    log.setLevel(logging.DEBUG if verbose else logging.INFO)
    latest = d / "latest.log"
    try:
        if latest.is_symlink() or latest.exists():
            latest.unlink()
        latest.symlink_to(path.name)
    except OSError:
        pass
    # уборка: держим не больше 50 логов
    try:
        old = sorted(d.glob("run-*.log"), key=lambda p: p.stat().st_mtime)[:-50]
        for p in old:
            p.unlink()
    except OSError:
        pass
    return path


def notify(title: str, message: str, subtitle: str = "") -> None:
    if sys.platform != "darwin":
        return
    def q(s: str) -> str:
        return s.replace("\\", "\\\\").replace('"', '\\"')
    script = f'display notification "{q(message)}" with title "{q(title)}"'
    if subtitle:
        script += f' subtitle "{q(subtitle)}"'
    try:
        subprocess.run(["/usr/bin/osascript", "-e", script], capture_output=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        pass


def error_dialog(title: str, message: str, log_path: Path) -> None:
    if sys.platform != "darwin":
        return
    def q(s: str) -> str:
        return s.replace("\\", "\\\\").replace('"', '\\"')
    script = (
        f'set r to display dialog "{q(message)}" with title "{q(title)}" '
        f'buttons {{"OK", "Открыть лог"}} default button "OK" with icon caution\n'
        f'if button returned of r is "Открыть лог" then\n'
        f'  do shell script "open -a Console " & quoted form of "{q(str(log_path))}"\n'
        f'end if'
    )
    try:
        subprocess.Popen(["/usr/bin/osascript", "-e", script],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    except OSError:
        pass


def _wait_for_memory(floor: int) -> None:
    """Если ядро говорит, что памяти мало — ждём, не выдавая новые задачи (макс. ~2 мин)."""
    if floor <= 0:
        return
    waited = 0.0
    while waited < 120:
        level = memory_level_percent()
        if level is None or level >= floor:
            return
        if waited == 0:
            log.warning("мало свободной памяти (%s%% < %s%%) — притормаживаю", level, floor)
        time.sleep(2)
        waited += 2


def run(inputs: Iterable[Path], cfg: dict[str, Any], *, dry_run: bool = False,
        quick_action: bool = False, verbose: bool = False) -> Summary:
    log_path = setup_logging(verbose)
    log.info("%s %s (%s), python %s", APP_NAME, __version__, VARIANT, sys.version.split()[0])
    inputs = [Path(p) for p in inputs]
    for p in inputs:
        log.info("вход: %s%s", p, "" if p.exists() else "  (НЕ НАЙДЕН)")

    mb = 1024 * 1024
    sources = collect_sources(inputs, cfg["extensions"], cfg["skip_dir_names"], cfg["mirror_suffix"])
    tasks, pre_skipped = plan_tasks(sources, cfg["output_mode"], cfg["mirror_suffix"],
                                    int(cfg["big_file_mb"] * mb), int(cfg["max_file_mb"] * mb),
                                    int(cfg["big_zip_file_mb"] * mb))
    summary = Summary()
    for src, why in pre_skipped:
        log.warning("пропуск %s — %s", src, why)
        summary.add(Result(src, src, "skipped", why))

    todo: list[Task] = []
    for t in tasks:
        ok, why = should_write(t, cfg["overwrite"], cfg["overwrite_foreign"])
        if ok:
            todo.append(t)
        else:
            log.info("пропуск %s — %s", t.src, why)
            summary.add(Result(t.src, t.dst, "skipped", why))

    log.info("найдено файлов: %d, к конвертации: %d", len(tasks) + len(pre_skipped), len(todo))
    if not todo:
        if cfg["notifications"] and quick_action:
            msg = "Подходящих файлов нет" if summary.total == 0 else f"Все {summary.total} уже актуальны или пропущены"
            notify(APP_NAME, msg, "Нечего конвертировать")
        log.info("итог: %s", summary.line())
        return summary

    if dry_run:
        for t in todo:
            print(f"[dry-run] {t.src} -> {t.dst}{'  (большой)' if t.big else ''}")
        print(f"[dry-run] к конвертации: {len(todo)}, пропущено: {summary.skipped}")
        return summary

    if cfg["max_workers"] == "auto":
        workers, reason = auto_workers(int(cfg["max_workers_cap"]))
    else:
        workers, reason = max(1, int(cfg["max_workers"])), "из config.json"
    workers = min(workers, len(todo))
    log.info("рабочих процессов: %d (%s)", workers, reason)

    if cfg["notifications"] and quick_action and len(todo) > 3:
        notify(APP_NAME, f"Файлов: {len(todo)}, потоков: {workers}", "Конвертирую…")

    ctx = mp.get_context("spawn")
    big_lock = ctx.Lock()
    floor = int(cfg["memory_floor_percent"])
    source_marker = bool(cfg["source_marker"])
    pending: set[Future] = set()
    it = iter(todo)
    done_count = 0
    next_progress = time.monotonic() + 30

    with ProcessPoolExecutor(max_workers=workers, mp_context=ctx,
                             initializer=_worker_init, initargs=(big_lock,),
                             max_tasks_per_child=64) as pool:
        exhausted = False
        while pending or not exhausted:
            while not exhausted and len(pending) < workers * 2:
                _wait_for_memory(floor)
                try:
                    t = next(it)
                except StopIteration:
                    exhausted = True
                    break
                pending.add(pool.submit(_worker_run, t, source_marker))
            if not pending:
                break
            finished, pending = wait(pending, return_when=FIRST_COMPLETED)
            for f in finished:
                try:
                    r: Result = f.result()
                except Exception as exc:  # noqa: BLE001 — упал рабочий процесс целиком
                    r = Result(Path("?"), Path("?"), "error", f"рабочий процесс упал: {type(exc).__name__}: {exc}")
                summary.add(r)
                done_count += 1
                if r.status == "ok":
                    log.info("ok   %s -> %s (%.0f КБ, %.2f с)", r.src, r.dst.name, r.size / 1024, r.seconds)
                elif r.status == "needs_ocr":
                    log.warning("OCR  %s — %s", r.src, r.detail)
                else:
                    log.error("ERR  %s — %s", r.src, r.detail)
            if time.monotonic() > next_progress:
                next_progress = time.monotonic() + 30
                log.info("прогресс: %d/%d", done_count, len(todo))
                if cfg["notifications"] and quick_action:
                    notify(APP_NAME, f"{done_count} из {len(todo)}", "Конвертирую…")

    log.info("итог: %s", summary.line())
    if quick_action and cfg["notifications"]:
        where = "рядом с исходниками" if cfg["output_mode"] == "beside" else f"в папках *{cfg['mirror_suffix']}"
        notify(APP_NAME, summary.line(), f"Markdown {where}")
    if quick_action and cfg["error_dialog"] and summary.problems:
        head = summary.problems[:8]
        lines = [f"• {src.name} — {why}" for src, why in head]
        if len(summary.problems) > len(head):
            lines.append(f"… и ещё {len(summary.problems) - len(head)} (см. лог)")
        error_dialog(APP_NAME, summary.line() + "\n\n" + "\n".join(lines), log_path)
    return summary
