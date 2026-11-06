"""Write guard: the bot's real database and repository are READ-ONLY to cloudsync.

Every code path that can write a file (open SQLite read-write, create a working
copy, write benchmark copies or a sandbox) calls `assert_writable` first. Read-
only paths (prep's source, bulk-load, reconcile, bench's source) open SQLite
with `mode=ro` and need no check.

Protected: the file named by SOURCE_DB and everything under BOT_REPO (falling
back to the documented locations when the variables are unset).
"""
import os
from pathlib import Path

_DEFAULT_BOT_REPO = r"C:\Users\aryan\Desktop\AlgoTrade"


def protected_roots() -> list[Path]:
    bot_repo = os.environ.get("BOT_REPO") or _DEFAULT_BOT_REPO
    source_db = os.environ.get("SOURCE_DB") or str(Path(bot_repo) / "db" / "trading_bot.db")
    return [Path(source_db).resolve(), Path(bot_repo).resolve()]


def is_protected(path) -> bool:
    p = Path(path).resolve()
    return any(p == root or root in p.parents for root in protected_roots())


def assert_writable(path, purpose: str) -> None:
    if is_protected(path):
        raise SystemExit(
            f"REFUSED: {purpose} would write to {Path(path).resolve()}, which is the bot's real database or "
            f"repository. cloudsync may only READ it. Work on the working copy (`cloudsync prep`) or a "
            f"throwaway sandbox (`cloudsync sandbox create NAME`).")
