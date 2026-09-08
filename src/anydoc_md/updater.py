"""Обновление движка firecrawl-anydoc через uv/pip внутри нашего venv."""

from __future__ import annotations

import fcntl
import json
import logging
import os
import subprocess
import sys
import time
from pathlib import Path

from .config import app_dir

log = logging.getLogger("anydoc_md")
PACKAGE = "firecrawl-anydoc"


def _state_path() -> Path:
    return app_dir() / "update-state.json"


def _lock_path() -> Path:
    return app_dir() / "engine.lock"


def engine_version() -> str:
    try:
        from importlib.metadata import version
        return version(PACKAGE)
    except Exception:  # noqa: BLE001
        return "не установлен"


def _uv() -> list[str] | None:
    for cand in (app_dir() / "tools" / "uv", Path.home() / ".local" / "bin" / "uv",
                 Path("/opt/homebrew/bin/uv"), Path("/usr/local/bin/uv")):
        if cand.is_file() and os.access(cand, os.X_OK):
            return [str(cand)]
    return None


def _pip_install_cmd(upgrade: bool) -> list[str]:
    py = sys.executable
    uv = _uv()
    if uv:
        cmd = uv + ["pip", "install", "--python", py]
        if upgrade:
            cmd.append("--upgrade")
        return cmd + [PACKAGE]
    cmd = [py, "-m", "pip", "install", "--disable-pip-version-check"]
    if upgrade:
        cmd.append("--upgrade")
    return cmd + [PACKAGE]


def update_now(*, quiet: bool = False) -> int:
    """Обновить движок. Держим файловый lock, чтобы не обновляться посреди чужой конвертации."""
    app_dir().mkdir(parents=True, exist_ok=True)
    before = engine_version()
    cmd = _pip_install_cmd(upgrade=True)
    with _lock_path().open("w") as lf:
        fcntl.flock(lf, fcntl.LOCK_EX)
        env = dict(os.environ, UV_PYTHON_INSTALL_DIR=str(app_dir() / "python"))
        proc = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=600)
    _state_path().write_text(json.dumps({"last_check": time.time(), "rc": proc.returncode}), encoding="utf-8")
    after = subprocess.run([sys.executable, "-c",
                            f"from importlib.metadata import version; print(version('{PACKAGE}'))"],
                           capture_output=True, text=True).stdout.strip() or "?"
    if proc.returncode != 0:
        msg = f"обновление не удалось (rc={proc.returncode}): {proc.stderr.strip()[-800:]}"
        log.error(msg)
        if not quiet:
            print(msg, file=sys.stderr)
        return proc.returncode
    msg = f"{PACKAGE}: {before} -> {after}" if before != after else f"{PACKAGE} {after}: уже последняя версия"
    log.info(msg)
    if not quiet:
        print(msg)
    return 0


def due(interval_days: int) -> bool:
    try:
        st = json.loads(_state_path().read_text(encoding="utf-8"))
        return time.time() - float(st.get("last_check", 0)) > interval_days * 86400
    except (OSError, ValueError):
        return True


def spawn_background_update() -> None:
    """Запускаем `python -m anydoc_md --update --quiet` отдельным процессом и не ждём."""
    try:
        subprocess.Popen([sys.executable, "-m", "anydoc_md", "--update", "--quiet"],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True, env=os.environ.copy())
        log.info("запущена фоновая проверка обновлений движка")
    except OSError as exc:
        log.warning("не удалось запустить фоновое обновление: %s", exc)


def hold_engine_lock():
    """Разделяемый lock на время конвертации: обновление подождёт, пока мы работаем."""
    app_dir().mkdir(parents=True, exist_ok=True)
    lf = _lock_path().open("a")
    fcntl.flock(lf, fcntl.LOCK_SH)
    return lf
