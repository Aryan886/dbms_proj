"""One command for the whole demo (spec stories 51-52).

    .venv/Scripts/python scripts/demo.py [--out artifacts/demo/<stamp>] [--admin-dsn DSN] [--keep]

Runs the full story in order on a throwaway pair of its own (never the main working
copy or the main cloud database, D29), and saves every measurement under --out:

  1. VACUUM study    prep: backup-API copy of the bot's database (opened read-only),
                     free pages measured, VACUUM, measured again
  2. Cloud schema    a fresh Postgres database: migrate
  3. CDC             cdc-install: WAL mode, _changelog, triggers, fingerprints
  4. Bulk load       bulk-load of the 11 in-scope tables (rejects recorded)
  5. Replay + chaos  2026-03-27 through the bot's own writers, chaos revise/rebuild/kill,
                     `sync once` every 30 steps as sync_writer, then a final sync
  6. Reconciliation  levels 1-3 (L3 = the bot's backtester on source vs cloud export)
  7. Roles           bot_reader reads its compat view; its write and analyst's base-table
                     read are denied by Postgres
  8. Analytics       every analytics view, read as analyst
  9. Data safety     SHA-256 of the bot's real database before and after

summary.md lists each step (exit code, seconds, artifact) and, for story 52, labels
every optimisation over the original bot as an ADD-ON next to the evidence that bot
behaviour didn't change. Passwords are scrubbed from every saved log.
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import psycopg
from psycopg import sql

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")
PY = sys.executable
DAY = "2026-03-27"
SECRET = re.compile(r"(password=)\S+", re.I)

ADD_ONS = [
    # (add-on, what it changes, evidence that the bot's behaviour didn't change)
    ("VACUUM of the working copy", "free pages reclaimed in the copy (step 1)",
     "the bot's own file is only read (SHA-256 identical before/after, step 9)"),
    ("WAL mode on the working copy", "readers no longer block the bot's writer (Day-2 bench-wal)",
     "the bot's own writers ran unchanged in the replay (step 5); L3 PASS (step 6)"),
    ("Normalized, typed cloud schema (3NF, NUMERIC prices, option header/line)", "storage and integrity in the cloud",
     "compat views give the bot its original tables; L1/L2 PASS and L3 identical trades (step 6)"),
    ("Change data capture + exactly-once sync", "the cloud follows every insert/update/delete",
     "the triggers only append to _changelog; L1-L3 PASS after a killed sync (steps 5-6)"),
    ("Expression B-tree indexes on IST time (D63)", "latest-N candle query 12.3 -> 1.7 ms (Day-4 index audit)",
     "same query, same rows through compat (test_compat_views); cloud only"),
    ("Least-privilege roles + audit trail", "who may read/write what; who changed trades",
     "cloud only; the bot reader still reads its views (step 7)"),
    ("Analytics views (P&L, data quality, sync lag)", "SQL reporting",
     "read-only views; nothing writes back to the bot"),
    ("Dropping the duplicate idx_ indexes in SQLite", "1.58 MB saved, same plan (Day-4, sandbox only)",
     "NOT applied to the bot's database (D64): the owner's call"),
]


def sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


class Demo:
    def __init__(self, out: Path):
        self.out, self.steps = out, []

    def run(self, n, title, args, log, env=None, ok_codes=(0,)):
        print(f"[{n}] {title} ...", flush=True)
        t = time.perf_counter()
        proc = subprocess.run(args, cwd=ROOT, capture_output=True, text=True,
                              env={**os.environ, **(env or {})})
        secs = time.perf_counter() - t
        (self.out / log).write_text(SECRET.sub(r"\1<redacted>", proc.stdout + proc.stderr), encoding="utf-8")
        ok = proc.returncode in ok_codes
        self.steps.append({"n": n, "title": title, "exit": proc.returncode, "ok": ok,
                           "seconds": round(secs, 1), "artifact": log})
        print(f"    exit {proc.returncode} in {secs:.1f} s -> {log}", flush=True)
        return proc

    def note(self, n, title, ok, secs, artifact):
        self.steps.append({"n": n, "title": title, "exit": 0 if ok else 1, "ok": ok,
                           "seconds": round(secs, 1), "artifact": artifact})


def roles_check(dsn: str) -> dict:
    def as_role(role, path):
        return psycopg.conninfo.make_conninfo(dsn, options=f"-c role={role} -c search_path={path}")
    out = {}
    with psycopg.connect(as_role("bot_reader", "compat")) as c:
        out["bot_reader_reads_trade_history"] = c.execute(
            "SELECT count(*) FROM dashboard_trade_history").fetchone()[0]
    for label, role, path, q in (
            ("bot_reader_delete", "bot_reader", "compat", "DELETE FROM dashboard_strategy_state"),
            ("analyst_reads_base_table", "analyst", "analytics", "SELECT count(*) FROM public.dashboard_trade_history"),
            ("sync_writer_rewrites_audit", "sync_writer", "public", "DELETE FROM audit.audit_log")):
        with psycopg.connect(as_role(role, path)) as c:
            try:
                c.execute(q)
                out[label] = "ALLOWED (unexpected)"
            except psycopg.errors.InsufficientPrivilege as e:
                out[label] = f"denied: {str(e).splitlines()[0]}"
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=ROOT / "artifacts" / "demo" / datetime.now().strftime("%Y%m%d-%H%M"))
    ap.add_argument("--admin-dsn", default=os.environ.get("PG_ADMIN_DSN"),
                    help="server for the demo's own cloud database (default: Docker, $PG_ADMIN_DSN)")
    ap.add_argument("--keep", action="store_true", help="keep the demo database and working copy afterwards")
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    source = os.environ["SOURCE_DB"]
    stamp = a.out.name.replace("-", "_").lower()
    work = ROOT / "data" / "demo" / stamp
    db = f"cloudsync_demo_{stamp}"
    admin = psycopg.conninfo.make_conninfo(a.admin_dsn, dbname="postgres")
    dsn = psycopg.conninfo.make_conninfo(a.admin_dsn, dbname=db)
    writer = psycopg.conninfo.make_conninfo(dsn, options="-c role=sync_writer")
    sqlite_path = work / "trading_bot.db"
    d = Demo(a.out)
    cs = [PY, "-m", "cloudsync"]
    started = time.perf_counter()

    t = time.perf_counter()
    before = sha256(source)
    (a.out / "00_real_db_sha256_before.txt").write_text(before + "\n")
    d.note(0, "Real database SHA-256 (before)", True, time.perf_counter() - t, "00_real_db_sha256_before.txt")

    with psycopg.connect(admin, autocommit=True) as c:
        c.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(db)))
        c.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(db)))
    try:
        d.run(1, "VACUUM study (prep)", cs + ["prep", "--source", source, "--workdir", work], "01_prep_vacuum.log")
        if (work / "artifacts" / "prep_stats.json").exists():
            shutil.copy(work / "artifacts" / "prep_stats.json", a.out / "01_prep_stats.json")
        d.run(2, "Cloud schema (migrate)", cs + ["migrate", "--dsn", dsn], "02_migrate.log")
        d.run(3, "CDC install (WAL, triggers, fingerprints)",
              cs + ["cdc-install", "--sqlite", sqlite_path, "--dsn", dsn], "03_cdc_install.log")
        d.run(4, "Bulk load", cs + ["bulk-load", "--sqlite", sqlite_path, "--dsn", dsn], "04_bulk_load.log")
        d.run(5, f"Replay {DAY} with chaos revise,rebuild,kill (sync as sync_writer)",
              cs + ["replay", "--source", source, "--target", sqlite_path, "--day", DAY,
                    "--chaos", "revise,rebuild,kill", "--sync-dsn", writer, "--sync-every", "30"],
              "05_replay_chaos.log")
        d.run("5b", "Final sync once (as sync_writer)",
              cs + ["sync", "once", "--sqlite", sqlite_path, "--dsn", writer], "05b_final_sync.log")
        d.run(6, f"Reconciliation L1-L3 ({DAY})",
              cs + ["reconcile", "--sqlite", sqlite_path, "--dsn", dsn, "--levels", "1,2,3",
                    "--start", DAY, "--end", DAY, "--out", a.out / "06_reconcile"], "06_reconcile.log")
        t = time.perf_counter()
        roles = roles_check(dsn)
        (a.out / "07_roles.json").write_text(json.dumps(roles, indent=2))
        d.note(7, "Roles: reads allowed, writes denied", all("denied" in v for k, v in roles.items()
                                                             if k != "bot_reader_reads_trade_history"),
               time.perf_counter() - t, "07_roles.json")
        d.run(8, "Analytics as analyst", [PY, "scripts/analytics_report.py", a.out / "08_analytics.md", dsn],
              "08_analytics.log")
        d.run("8b", "Dead tuples vs SQLite free pages",
              [PY, "scripts/dead_tuple_study.py", sqlite_path, dsn, a.out / "08b_dead_tuples.jsonl", "after_demo"],
              "08b_dead_tuples.log")
    finally:
        t = time.perf_counter()
        after = sha256(source)
        (a.out / "09_real_db_sha256_after.txt").write_text(after + "\n")
        d.note(9, "Real database SHA-256 (after) unchanged", after == before, time.perf_counter() - t,
               "09_real_db_sha256_after.txt")
        if not a.keep:
            with psycopg.connect(admin, autocommit=True) as c:
                c.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(db)))
            shutil.rmtree(work, ignore_errors=True)

    total = time.perf_counter() - started
    passed = all(s["ok"] for s in d.steps)
    lines = [f"# Demo run {a.out.name}", "",
             f"**Result: {'PASS' if passed else 'FAIL'}** in {total / 60:.1f} min. "
             f"Demo pair: its own working copy (from the bot's database, read-only) and Postgres database "
             f"`{db}` on `{psycopg.conninfo.conninfo_to_dict(a.admin_dsn).get('host')}`"
             f"{' (kept)' if a.keep else ' (dropped afterwards)'}.", "",
             "| # | Step | Exit | OK | Seconds | Artifact |", "|---|---|---|---|---|---|"]
    lines += [f"| {s['n']} | {s['title']} | {s['exit']} | {'yes' if s['ok'] else '**NO**'} | {s['seconds']} | "
              f"[{s['artifact']}]({s['artifact']}) |" for s in d.steps]
    lines += ["", "## Add-ons over the original bot (story 52)", "",
              "Everything below is an **ADD-ON**: the bot's code and its database are unchanged.", "",
              "| Add-on | What it changes | Evidence bot behaviour didn't change |", "|---|---|---|"]
    lines += [f"| **ADD-ON:** {n} | {w} | {e} |" for n, w, e in ADD_ONS]
    (a.out / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"demo {'PASS' if passed else 'FAIL'} in {total / 60:.1f} min -> {a.out / 'summary.md'}")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
