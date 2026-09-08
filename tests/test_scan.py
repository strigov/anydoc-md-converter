"""Юнит-тесты логики сканирования, именования и перезаписи (движок не нужен)."""
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from anydoc_md.config import SUPPORTED_EXTENSIONS, load_config  # noqa: E402
from anydoc_md.convert import Task, has_marker, marker_line, should_write  # noqa: E402
from anydoc_md.scan import collect_sources, plan_tasks  # noqa: E402

EXT = tuple(SUPPORTED_EXTENSIONS)
MB = 1024 * 1024


def touch(p: Path, data: bytes = b"x") -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    return p


def test_collect_walks_folders_and_skips_junk(tmp_path):
    touch(tmp_path / "a.docx")
    touch(tmp_path / "sub" / "b.PDF")
    touch(tmp_path / "sub" / "~$lock.docx")
    touch(tmp_path / ".hidden" / "c.docx")
    touch(tmp_path / "node_modules" / "d.docx")
    touch(tmp_path / "notes.txt")
    touch(tmp_path.with_name(tmp_path.name + "_md") / "old.docx")  # зеркало не сканируем
    got = collect_sources([tmp_path], EXT, ["node_modules"], "_md")
    names = sorted(str(f.relative_to(tmp_path)) for f, _ in got)
    assert names == ["a.docx", "sub/b.PDF"]
    assert all(root == tmp_path for _, root in got)


def test_collect_single_file_and_dedup(tmp_path):
    f = touch(tmp_path / "x.csv")
    got = collect_sources([f, f, tmp_path / "nope.docx"], EXT, [], "_md")
    assert [(p, r) for p, r in got] == [(f, None)]


def test_plan_beside_names_and_collisions(tmp_path):
    a = touch(tmp_path / "report.docx")
    b = touch(tmp_path / "report.pdf")
    c = touch(tmp_path / "solo.xlsx")
    tasks, skipped = plan_tasks([(a, tmp_path), (b, tmp_path), (c, tmp_path)], "beside", "_md", 40 * MB, 500 * MB)
    dst = {t.src.name: t.dst.name for t in tasks}
    assert dst == {"report.docx": "report.docx.md", "report.pdf": "report.pdf.md", "solo.xlsx": "solo.md"}
    assert skipped == []


def test_plan_mirror_tree(tmp_path):
    root = tmp_path / "Docs"
    a = touch(root / "sub" / "deep.odt")
    tasks, _ = plan_tasks([(a, root)], "mirror", "_md", 40 * MB, 500 * MB)
    assert tasks[0].dst == tmp_path / "Docs_md" / "sub" / "deep.md"


def test_plan_skips_empty_and_huge_and_flags_big(tmp_path):
    empty = touch(tmp_path / "e.docx", b"")
    big = touch(tmp_path / "big.pdf", b"x" * 10)
    huge = touch(tmp_path / "huge.pdf", b"x" * 100)
    tasks, skipped = plan_tasks([(empty, None), (big, None), (huge, None)], "beside", "_md", 5, 50)
    assert [t.src.name for t in tasks] == ["big.pdf"] and tasks[0].big
    assert sorted(s.name for s, _ in skipped) == ["e.docx", "huge.pdf"]


def test_should_write_policies(tmp_path):
    src = touch(tmp_path / "r.docx")
    dst = tmp_path / "r.md"
    t = Task(src, dst)
    assert should_write(t, "if_newer", False)[0]  # нет файла — пишем
    dst.write_text("# чужой файл\n")
    assert not should_write(t, "if_newer", False)[0]  # чужой .md без метки не трогаем
    assert not should_write(t, "always", False)[0]
    assert should_write(t, "always", True)[0]
    dst.write_text(marker_line(src) + "body\n")
    assert has_marker(dst)
    assert not should_write(t, "if_newer", False)[0]  # наш, но исходник не новее
    old = time.time() - 100
    os.utime(dst, (old, old))
    assert should_write(t, "if_newer", False)[0]  # исходник новее → перезапись
    assert not should_write(t, "never", True)[0]


def test_load_config_merges_and_normalizes(tmp_path):
    p = tmp_path / "config.json"
    p.write_text('{"max_workers": 2, "extensions": ["docx", ".PDF"], "unknown": 1}')
    cfg = load_config(p)
    assert cfg["max_workers"] == 2
    assert cfg["extensions"] == (".docx", ".pdf")
    assert "unknown" not in cfg and cfg["output_mode"] == "beside"


def test_plan_zip_threshold_is_separate(tmp_path):
    x = touch(tmp_path / "t.xlsx", b"x" * 10)
    pdf = touch(tmp_path / "t.pdf", b"x" * 10)
    tasks, _ = plan_tasks([(x, None), (pdf, None)], "beside", "_md", 100, 0, big_zip_bytes=5)
    big = {t.src.name: t.big for t in tasks}
    assert big == {"t.xlsx": True, "t.pdf": False}
