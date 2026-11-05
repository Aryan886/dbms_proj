"""Prep: copy the bot's database to a working copy and study SQLite bloat.

The source is opened read-only and copied with SQLite's online backup API, so
the copy is consistent even if the bot is writing, and the original file is
never modified. Free pages are copied too, so the bloat survives into the copy
and can be measured before VACUUM rebuilds the file.
"""
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

WORKING_DB_NAME = "trading_bot.db"


def file_stats(db_path: Path) -> dict:
    conn = sqlite3.connect(db_path)
    try:
        page_size = conn.execute("PRAGMA page_size").fetchone()[0]
        page_count = conn.execute("PRAGMA page_count").fetchone()[0]
        freelist = conn.execute("PRAGMA freelist_count").fetchone()[0]
    finally:
        conn.close()
    return {
        "page_size": page_size,
        "page_count": page_count,
        "freelist_count": freelist,
        "free_page_pct": round(100.0 * freelist / page_count, 2) if page_count else 0.0,
        "file_size_bytes": Path(db_path).stat().st_size,
    }


def run(source: Path, workdir: Path) -> dict:
    workdir.mkdir(parents=True, exist_ok=True)
    artifacts = workdir / "artifacts"
    artifacts.mkdir(exist_ok=True)
    working = workdir / WORKING_DB_NAME
    if working.exists():
        working.unlink()

    src = sqlite3.connect(f"file:{source.resolve().as_posix()}?mode=ro", uri=True)
    dst = sqlite3.connect(working)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()

    before = file_stats(working)
    started = datetime.now(timezone.utc)
    conn = sqlite3.connect(working)
    try:
        conn.execute("VACUUM")
    finally:
        conn.close()
    elapsed = (datetime.now(timezone.utc) - started).total_seconds()
    after = file_stats(working)

    stats = {
        "source": str(source),
        "working_copy": str(working),
        "measured_at": started.isoformat(),
        "before_vacuum": before,
        "after_vacuum": after,
        "vacuum_seconds": round(elapsed, 3),
    }
    (artifacts / "prep_stats.json").write_text(json.dumps(stats, indent=2))
    return stats
