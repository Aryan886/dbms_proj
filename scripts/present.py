"""Presenter script: the examiner demo, one segment at a time.

    # 1. Before the presentation (about 17 min): build and keep a demo pair
    .venv/Scripts/python scripts/present.py prepare

    # 2. In front of the examiner: walk through the segments, Enter between steps
    .venv/Scripts/python scripts/present.py live

    # 3. Afterwards: drop the demo pair
    .venv/Scripts/python scripts/present.py cleanup

`prepare` runs scripts/demo.py --keep: a fresh copy of the source database (opened
read-only) and its own Postgres database, with the whole pipeline run and every
measurement saved under artifacts/demo/<stamp>/. The source defaults to the main working
copy, data/trading_bot.db (D75): the bot's own database lost its vix_data on 2026-11-11, so
the Level-3 backtest can't run from it. `--source "$SOURCE_DB"` uses the bot's database again. `live` then works on that kept pair only.
It never touches the bot's database, the main working copy (data/trading_bot.db) or the
main cloud database. The slow parts (VACUUM, bulk load, PITR on RDS) are shown from the
recorded artifacts, and the rest runs live in seconds.

Options for `live`:
  --run DIR       a kept demo run (default: the newest artifacts/demo/* that was kept)
  --only 3,4      run just these segments (handy for rehearsing one member's part)
  --auto          don't wait for Enter (dry run / rehearsal check)
Everything `live` prints is also saved to <run>/live/present_<time>.log.
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import psycopg
from psycopg import sql

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")
from cloudsync.guard import assert_writable, is_protected  # noqa: E402
from demo import roles_check  # noqa: E402  (same role checks as the one-command demo)

PY = sys.executable
DEMO_ROOT = ROOT / "artifacts" / "demo"
DAY5 = ROOT / "artifacts" / "day5"
REAL_SHA_FILE = ROOT / "artifacts" / "day2" / "rebuild" / "real_db_sha256.txt"
_SECRETS = (re.compile(r"(password=)\S+", re.I), re.compile(r"(://[^:/@\s]+:)[^@\s]+@"))


def scrub(text: str) -> str:
    for pat in _SECRETS:
        text = pat.sub(lambda m: m.group(1) + "***" + ("@" if m.group(0).endswith("@") else ""), text)
    return text
FAULT_EXIT_CODE = 75  # cloudsync/sync.py

# ---------- terminal output ----------
BOLD, DIM, GREEN, RED, CYAN, YELLOW, RESET = ("\033[1m", "\033[2m", "\033[32m", "\033[31m", "\033[36m",
                                              "\033[33m", "\033[0m")
ANSI = re.compile(r"\033\[[0-9;]*m")


class Tee:
    """Print to the console and keep a plain-text copy for the log."""

    def __init__(self, path: Path):
        self.f = open(path, "w", encoding="utf-8")
        self.out = sys.stdout

    def write(self, s):
        self.out.write(s)
        self.f.write(ANSI.sub("", s))

    def flush(self):
        self.out.flush()
        self.f.flush()


AUTO = False


def pause(msg="Enter = next step"):
    if AUTO:
        print(f"{DIM}  [{msg}]{RESET}")
        return
    input(f"{DIM}  [{msg}] {RESET}")


def banner(n, title, topic, minutes):
    print(f"\n{BOLD}{CYAN}{'=' * 78}\n  {n}. {title}   (~{minutes} min)\n  Syllabus topic: {topic}\n{'=' * 78}{RESET}")


def say(*lines):
    print(f"{YELLOW}  SAY:{RESET}")
    for line in lines:
        print(f"{YELLOW}   - {line}{RESET}")


def step(text):
    print(f"\n{BOLD}  > {text}{RESET}")


def ok(text, passed=True):
    print(f"  {GREEN + 'PASS' if passed else RED + 'FAIL'}{RESET}  {text}")


def table(rows, headers):
    rows = [[("" if v is None else str(v)) for v in r] for r in rows]
    widths = [max(len(h), *(len(r[i]) for r in rows)) if rows else len(h) for i, h in enumerate(headers)]
    print("    " + "  ".join(h.ljust(w) for h, w in zip(headers, widths)))
    print("    " + "  ".join("-" * w for w in widths))
    for r in rows:
        print("    " + "  ".join(v.ljust(w) for v, w in zip(r, widths)))


DISPLAY = {}  # long values shown short on screen, e.g. the demo DSN -> "<demo dsn>"


def short(a) -> str:
    a = str(a)
    if a in DISPLAY:
        return DISPLAY[a]
    return a.replace(str(ROOT) + os.sep, "").replace("\\", "/")


def cloudsync(args, env=None, tail=12):
    """Run one cloudsync CLI command and show it, like typing it in a terminal."""
    shown = " ".join(short(a) for a in args)
    print(f"{DIM}    $ cloudsync {scrub(shown)}{RESET}")
    if env:
        print(f"{DIM}      (with {' '.join(f'{k}={v}' for k, v in env.items())}){RESET}")
    t = time.perf_counter()
    proc = subprocess.run([PY, "-m", "cloudsync", *[str(a) for a in args]], cwd=ROOT, capture_output=True,
                          text=True, env={**os.environ, **(env or {})})
    out = scrub((proc.stdout + proc.stderr).strip())
    lines = out.splitlines()
    for line in (lines[-tail:] if tail else []):
        print(f"    | {line}")
    print(f"{DIM}    exit {proc.returncode} in {time.perf_counter() - t:.1f} s{RESET}")
    return proc


def sha256(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# ---------- the kept demo pair ----------
class Pair:
    def __init__(self, run: Path, admin_dsn: str):
        stamp = run.name.replace("-", "_").lower()  # same naming as scripts/demo.py
        self.run = run
        self.sqlite = ROOT / "data" / "demo" / stamp / "trading_bot.db"
        self.db = f"cloudsync_demo_{stamp}"
        self.dsn = psycopg.conninfo.make_conninfo(admin_dsn, dbname=self.db)
        self.writer = psycopg.conninfo.make_conninfo(self.dsn, options="-c role=sync_writer")
        self.admin = psycopg.conninfo.make_conninfo(admin_dsn, dbname="postgres")
        DISPLAY.update({self.dsn: '"<demo dsn>"', self.writer: '"<demo dsn as sync_writer>"'})

    def pg(self, **kw):
        return psycopg.connect(self.dsn, **kw)

    def lite(self):
        assert_writable(self.sqlite, "the live demo")  # never the bot's database
        conn = sqlite3.connect(self.sqlite, isolation_level=None, timeout=30)
        conn.row_factory = sqlite3.Row
        return conn

    def sync(self, env=None):
        return cloudsync(["sync", "once", "--sqlite", self.sqlite, "--dsn", self.writer], env=env, tail=6)


def latest_kept_run() -> Path | None:
    runs = sorted((p for p in DEMO_ROOT.glob("*") if (p / "summary.md").exists()
                   and "(kept)" in (p / "summary.md").read_text(encoding="utf-8")), key=lambda p: p.name)
    return runs[-1] if runs else None


def cloud_candle(p: Pair, cid):
    with p.pg() as c:
        return c.execute('SELECT "timestamp", open, high, low, close FROM compat.market_data_1m WHERE id = %s',
                         (cid,)).fetchone()


def pending(lite, table_name="market_data_1m"):
    return lite.execute("SELECT seq, table_name, pk, op FROM _changelog WHERE table_name = ? ORDER BY seq",
                        (table_name,)).fetchall()


def last_seq(p: Pair, table_name="market_data_1m"):
    with p.pg() as c:
        r = c.execute("SELECT last_seq FROM sync_state WHERE source_table = %s", (table_name,)).fetchone()
        return r[0] if r else 0


# ---------- segments ----------
def seg_problem(p: Pair):
    banner(1, "The problem", "storage internals (pages, free list, VACUUM)", 2)
    say("The bot writes to a 2.5 GB SQLite file. ~40 bot files use it by table name, so we can't change it.",
        "Most of that file is empty pages. Deletes don't shrink a SQLite file, only VACUUM does.",
        "No FKs, symbols repeated as text on every row, 2,050 duplicate groups in delta_cache.")
    stats_file = p.run / "01_prep_stats.json"
    stats = json.loads(stats_file.read_text())
    if stats["before_vacuum"]["freelist_count"] == 0:  # demo built from an already-vacuumed copy
        stats_file = DAY5 / "demo_rehearsal" / "01_prep_stats.json"
        stats = json.loads(stats_file.read_text())
    b, a = stats["before_vacuum"], stats["after_vacuum"]
    step(f"Measured on a copy of the bot's 2.5 GB database ({stats_file.relative_to(ROOT).as_posix()})")
    table([["before VACUUM", f"{b['file_size_bytes']:,}", f"{b['page_count']:,}", f"{b['freelist_count']:,}",
            f"{b['free_page_pct']} %"],
           ["after VACUUM", f"{a['file_size_bytes']:,}", f"{a['page_count']:,}", f"{a['freelist_count']:,}",
            f"{a['free_page_pct']} %"]], ["", "file bytes", "pages", "free pages", "free"])
    print(f"    VACUUM took {stats['vacuum_seconds']} s. Real data is about {a['file_size_bytes'] / 1e6:.0f} MB.")
    pause()


def seg_normalization(p: Pair):
    banner(2, "Normalized cloud schema", "ER model, functional dependencies, 3NF, keys", 3)
    say("Open docs/normalization.md: the FD analysis and the before/after ER diagrams.",
        "Walk one FD: (instrument, ts) -> spot_price, so option snapshots split into a header and lines (D5).",
        "Four identical candle tables became one `candles` table with a timeframe column.",
        "Symbols and contracts live once, in master tables, referenced by foreign keys.")
    with p.pg() as c:
        step("Base tables in the cloud database, with row counts")
        names = [r[0] for r in c.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public' "
            "AND table_type = 'BASE TABLE' AND table_name NOT IN ('schema_version') ORDER BY table_name")]
        table([[n, f"{c.execute(sql.SQL('SELECT count(*) FROM {}').format(sql.Identifier(n))).fetchone()[0]:,}"]
               for n in names], ["table", "rows"])
        step("Foreign keys: orphan rows are impossible")
        table(c.execute("""
            SELECT conrelid::regclass, confrelid::regclass, pg_get_constraintdef(oid)
            FROM pg_constraint WHERE contype = 'f' AND connamespace = 'public'::regnamespace
            ORDER BY 1, 2""").fetchall(), ["table", "references", "definition"])
    pause()


def seg_constraints(p: Pair):
    banner(3, "Integrity constraints and the quarantine", "CHECK, NOT NULL, FK; rejected by the database", 3)
    say("Postgres decides what's invalid, not Python (D11). Python only routes the failure.",
        "A rejected row is kept in rejected_rows with the constraint it broke, so nothing is silently lost.")
    with p.pg() as c:
        step("Insert an impossible candle (high 90, low 110) straight into Postgres")
        try:
            with c.transaction():
                c.execute("""INSERT INTO candles (instrument_id, timeframe, ts, source_id, open, high, low, close)
                             SELECT id, '1m', now(), -1, 100, 90, 110, 100 FROM instruments LIMIT 1""")
            print(f"  {RED}unexpected: the insert was accepted{RESET}")
        except psycopg.errors.CheckViolation as e:
            ok(f"rejected by Postgres: {str(e).splitlines()[0]}")
        step("What the bulk load quarantined (rejected_rows)")
        table(c.execute("SELECT source_table, violated_constraint, count(*) FROM rejected_rows "
                        "GROUP BY 1, 2 ORDER BY 1, 2").fetchall(), ["source table", "constraint", "rows"])
        print("    delta_cache: 2,050 duplicate groups on the natural key. The highest source id wins (D10),")
        print("    the rest are kept here instead of being dropped.")
    pause()

    step("Now the bot writes a bad candle (close above high) into SQLite, and we sync")
    lite = p.lite()
    row = lite.execute("SELECT id, high, close FROM market_data_1m ORDER BY id DESC LIMIT 1").fetchone()
    cid, high, close = row["id"], row["high"], row["close"]
    lite.execute("UPDATE market_data_1m SET close = ? WHERE id = ?", (high + 50, cid))
    print(f"    SQLite accepted close = {high + 50} for candle id {cid} (high is {high}). SQLite has no CHECK here.")
    p.sync()
    with p.pg() as c:
        rej = c.execute("SELECT source_pk, violated_constraint FROM rejected_rows "
                        "WHERE source_table = 'market_data_1m' AND source_pk = %s", (str(cid),)).fetchall()
    ok(f"the cloud quarantined it: {rej}", bool(rej))
    pause()
    step("The bot corrects the row, and we sync again")
    lite.execute("UPDATE market_data_1m SET close = ? WHERE id = ?", (close, cid))
    p.sync()
    with p.pg() as c:
        left = c.execute("SELECT count(*) FROM rejected_rows WHERE source_table = 'market_data_1m' "
                         "AND source_pk = %s", (str(cid),)).fetchone()[0]
    ok(f"corrected row left the quarantine and is back in the cloud: {cloud_candle(p, cid)}",
       left == 0 and cloud_candle(p, cid) is not None)
    lite.close()
    pause()


def seg_cdc(p: Pair):
    banner(4, "Change capture and crash safety", "triggers, transactions (atomicity), recovery, idempotence", 4)
    say("AFTER INSERT/UPDATE/DELETE triggers in SQLite log (table, pk, op, seq) into _changelog.",
        "The sync reads a batch, applies it AND moves the cursor in ONE Postgres transaction.",
        "So a crash leaves the cloud fully before or fully after a batch. Never half.")
    lite = p.lite()
    row = lite.execute("SELECT id, low, high, close FROM market_data_1m ORDER BY id DESC LIMIT 1 OFFSET 1").fetchone()
    cid, low, high, close = row["id"], row["low"], row["high"], row["close"]

    step(f"The bot updates candle {cid} in SQLite (close {close} -> {low})")
    lite.execute("UPDATE market_data_1m SET close = ? WHERE id = ?", (low, cid))
    print("    The trigger captured it in _changelog:")
    table([tuple(r) for r in pending(lite)], ["seq", "table", "pk", "op"])
    print(f"    Cloud before sync: {cloud_candle(p, cid)}")
    step("sync once")
    p.sync()
    ok(f"cloud after sync: {cloud_candle(p, cid)}", float(cloud_candle(p, cid)[4]) == float(low))
    print(f"    _changelog entries left for market_data_1m: {len(pending(lite))} (pruned after Postgres acknowledged)")
    pause()

    step(f"Now crash the sync in the middle of a batch (candle {cid}: close -> {high})")
    lite.execute("UPDATE market_data_1m SET close = ? WHERE id = ?", (high, cid))
    seq_before = last_seq(p)
    proc = p.sync(env={"CLOUDSYNC_FAULT": "mid_batch:1"})
    ok(f"the sync process died (exit {proc.returncode}, like kill -9)", proc.returncode == FAULT_EXIT_CODE)
    after = cloud_candle(p, cid)
    ok(f"cloud unchanged: close = {after[4]} (still {low}); cursor last_seq {seq_before} -> {last_seq(p)}",
       float(after[4]) == float(low) and last_seq(p) == seq_before)
    print(f"    The change is still waiting in SQLite: {len(pending(lite))} entry, nothing lost.")
    pause()
    step("Restart the sync: it resumes from the cursor")
    p.sync()
    ok(f"cloud now: close = {cloud_candle(p, cid)[4]}; applied exactly once", float(cloud_candle(p, cid)[4]) == float(high))
    lite.execute("UPDATE market_data_1m SET close = ? WHERE id = ?", (close, cid))  # put the candle back
    p.sync()
    print(f"    (candle {cid} restored to close = {close} and synced)")
    lite.close()
    say("Also built: exponential backoff when the network drops, schema-drift pause per table,",
        "and a replay simulator with chaos (revise, rebuild, kill) that ran in `prepare` (05_replay_chaos.log).")
    pause()


def seg_roles(p: Pair):
    banner(5, "Least privilege", "GRANT/REVOKE, roles, schemas as a security boundary", 1)
    say("bot_reader: only the compatibility views. analyst: only the analytics views.",
        "sync_writer: writes data tables but can't rewrite the audit log.")
    step("Each role tries what it should and shouldn't do")
    res = roles_check(p.dsn)
    for k, v in res.items():
        ok(f"{k}: {v}", "ALLOWED" not in str(v))
    pause()


def seg_indexing(p: Pair):
    banner(6, "Indexing and concurrency", "B-tree / expression indexes, query plans, WAL, locking", 3)
    say("The bot asks for its latest 200 candles by IST time. The views expose ts AT TIME ZONE 'Asia/Kolkata',",
        "so a plain index on ts can't be used. An expression index on that same expression can (D63).")
    with p.pg() as c:
        last = c.execute("SELECT max(\"timestamp\") FROM compat.market_data_1m WHERE symbol = 'NIFTY50'").fetchone()[0]
        start = last.replace(hour=9, minute=15, second=0)
        q = ("EXPLAIN (ANALYZE, COSTS OFF) SELECT * FROM compat.market_data_1m WHERE symbol = %s "
             "AND \"timestamp\" >= %s AND \"timestamp\" <= %s ORDER BY \"timestamp\" DESC LIMIT 200")
        args = ("NIFTY50", start, last)

        def plan(label):
            c.execute(q, args)  # warm the cache so both runs compare fairly
            lines = [r[0] for r in c.execute(q, args)]
            nodes = [ln.strip() for ln in lines if "Scan" in ln][:3]
            exe = next(ln for ln in lines if ln.startswith("Execution Time"))
            print(f"    {label}: {exe}")
            for n in nodes:
                print(f"      {n}")
            return float(exe.split(":")[1].split()[0])

        step("EXPLAIN ANALYZE with the expression index")
        with_idx = plan("with candles_ist_ts")
        step("Same query with the index dropped, inside a transaction we roll back (DDL is transactional)")
        with c.transaction(force_rollback=True):
            c.execute("DROP INDEX candles_ist_ts")
            without = plan("without the index")
        print(f"    {without:.2f} ms -> {with_idx:.2f} ms. Index restored by the rollback: "
              f"{c.execute('SELECT count(*) FROM pg_indexes WHERE indexname = %s', ('candles_ist_ts',)).fetchone()[0] == 1}")
    pause()

    say("SQLite: in rollback-journal mode a reader blocks the writer. WAL lets the bot write while we read.")
    step("Live WAL vs rollback-journal benchmark (3 s per mode, on copies of the demo SQLite)")
    out = p.run / "live" / "bench_wal"
    cloudsync(["bench-wal", "--sqlite", p.sqlite, "--out", out, "--seconds", 3], tail=0)
    md = (out / "wal_benchmark.md").read_text(encoding="utf-8").splitlines()
    for line in md:
        if line.startswith("|"):
            print(f"    {line}")
    print("    Recorded 10 s run (Day 2, artifacts/day2/wal_benchmark.md): 16 writes in delete mode vs 1,569 in WAL.")
    pause()


def seg_recovery(p: Pair):
    banner(7, "Point-in-time recovery on AWS RDS", "backup and recovery, WAL archiving, PITR", 2)
    say("RDS keeps snapshots plus the write-ahead log, so it can rebuild the database at any second.",
        "We fingerprinted one trading day, deleted it, and restored RDS to a moment before the delete.",
        "A restore takes 10-20 minutes, so this is the recorded run from Day 5.")
    pitr = DAY5 / "pitr"
    snap = json.loads((pitr / "01_snapshot_sandbox.json").read_text())
    dele = json.loads((pitr / "02_delete_day.json").read_text())
    step(f"Fingerprint of {dele['day']} taken (server time {snap['server_time']})")
    step(f"Deleted at {dele['committed_at']}: {sum(dele['deleted'].values()):,} rows")
    table([[k, f"{v:,}"] for k, v in dele["deleted"].items()], ["table", "rows deleted"])
    for f, label, expect in (
            ("03_verify_damaged_sandbox.json", "after the delete, the day no longer matches its fingerprint", False),
            ("04_verify_restored_sandbox.json", "restored instance: every table identical to the fingerprint", True),
            ("06_verify_live_sandbox_after.json", "the database we didn't restore is still damaged", False)):
        r = json.loads((pitr / f).read_text())
        ok(f"{label}  (verify {'PASS' if r['passed'] else 'FAIL'}, {f})", r["passed"] == expect)
    print("    Watch out in the console: enter the restore time in the time zone the field shows (Day 5 lesson).")
    pause()


def seg_proof(p: Pair):
    banner(8, "Proof it all works", "consistency checking, end-to-end correctness", 2)
    say("Level 1: row counts (sqlite = postgres + rejected). Level 2: per-day sums, min and max.",
        "Level 3: the bot's own backtester on SQLite vs on data exported from Postgres, trades diffed.")
    step("Levels 1-2, live, after everything we just changed")
    cloudsync(["reconcile", "--sqlite", p.sqlite, "--dsn", p.dsn, "--levels", "1,2",
               "--out", p.run / "live" / "reconcile"], tail=0)
    rep = json.loads((p.run / "live" / "reconcile" / "reconciliation.json").read_text())
    for lvl, r in rep["levels"].items():
        ok(f"level {lvl}: {sum(t['passed'] for t in r['tables'].values())}/{len(r['tables'])} tables",
           r["passed"])
    step("Level 3 from `prepare` (the backtest takes about a minute)")
    l3 = json.loads((p.run / "06_reconcile" / "reconciliation.json").read_text())["levels"]["3"]
    ok(f"source: {l3['source']['num_trades']} trades, P&L {l3['source']['total_pnl']:.2f} | "
       f"cloud: {l3['cloud']['num_trades']} trades, P&L {l3['cloud']['total_pnl']:.2f} | "
       f"differences: {sum(len(v) for v in l3['trade_diff'].values())}", l3["passed"])
    step("Our tools never wrote the bot's real database")
    before = (p.run / "00_real_db_sha256_before.txt").read_text().split()[0]
    now = sha256(os.environ["SOURCE_DB"])
    ok(f"SHA-256 now = SHA-256 before `prepare` ({now[:16]}...)", now == before)
    reference = REAL_SHA_FILE.read_text().split()[0]
    if now != reference:
        print(f"    {YELLOW}Note: differs from the Day-2 reference {reference[:16]}... The file was rewritten outside")
        print(f"    this project (last modified {datetime.fromtimestamp(os.path.getmtime(os.environ['SOURCE_DB'])):%Y-%m-%d %H:%M}), before `prepare` started.{RESET}")
    pause()


def seg_finding(p: Pair):
    banner(9, "An honest finding", "distributed measurement, clocks", 1)
    say("On RDS our sync-lag view showed NEGATIVE latency: a change arriving before it was made.",
        "Cause: the lag compared the laptop's clock with the RDS server's clock, and they differed by ~1.5 s.",
        "Fix: measure both ends on one clock. Lesson: distributed timings need a single clock.")
    for line in (DAY5 / "dead_tuples" / "clock_skew.txt").read_text().splitlines():
        if line.strip():
            print(f"    {scrub(line)}")
    say("Thank you. Questions?")
    pause("Enter = end")


SEGMENTS = [seg_problem, seg_normalization, seg_constraints, seg_cdc, seg_roles, seg_indexing, seg_recovery,
            seg_proof, seg_finding]


# ---------- commands ----------
def cmd_prepare(a):
    out = DEMO_ROOT / datetime.now().strftime("%Y%m%d-%H%M")
    args = [PY, "scripts/demo.py", "--keep", "--out", str(out), "--source", str(a.source)]
    if a.admin_dsn:
        args += ["--admin-dsn", a.admin_dsn]
    print(f"Building the demo pair (about 17 min) -> {out}")
    code = subprocess.run(args, cwd=ROOT).returncode
    if code != 0:
        print(f"\nprepare FAILED: see {out.relative_to(ROOT).as_posix()}/summary.md (the pair is kept for inspection)")
    else:
        print(f"\nReady. Next: .venv/Scripts/python scripts/present.py live --run {out.relative_to(ROOT).as_posix()}")
    return code


def cmd_live(a):
    global AUTO
    AUTO = a.auto
    run = a.run or latest_kept_run()
    if not run or not (run / "summary.md").exists():
        raise SystemExit("No kept demo run found. Run `scripts/present.py prepare` first.")
    p = Pair(run.resolve(), a.admin_dsn)
    if is_protected(p.sqlite) or not p.sqlite.exists():
        raise SystemExit(f"Demo working copy missing: {p.sqlite}. Run `prepare` again.")
    try:
        with p.pg() as c:
            c.execute("SELECT 1")
    except psycopg.OperationalError as e:
        raise SystemExit(f"Can't reach the demo database {p.db} (is Docker up? `docker compose up -d`): {e}")
    (run / "live").mkdir(exist_ok=True)
    log = run / "live" / f"present_{datetime.now():%Y%m%d-%H%M%S}.log"
    sys.stdout = Tee(log)
    only = {int(x) for x in a.only.split(",")} if a.only else None
    print(f"{BOLD}AlgoTrade: SQLite -> PostgreSQL on AWS RDS{RESET}")
    print(f"{DIM}demo pair: {p.sqlite.relative_to(ROOT).as_posix()} + Postgres database {p.db}; "
          f"prepared run {run.relative_to(ROOT).as_posix()}{RESET}")
    started = time.perf_counter()
    for i, seg in enumerate(SEGMENTS, 1):
        if only is None or i in only:
            seg(p)
    print(f"\n{DIM}live demo finished in {(time.perf_counter() - started) / 60:.1f} min; log: "
          f"{log.relative_to(ROOT).as_posix()}{RESET}")
    sys.stdout.flush()
    return 0


def cmd_cleanup(a):
    run = a.run or latest_kept_run()
    if not run:
        raise SystemExit("No kept demo run found.")
    p = Pair(run.resolve(), a.admin_dsn)
    with psycopg.connect(p.admin, autocommit=True) as c:
        c.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(p.db)))
    assert_writable(p.sqlite.parent, "cleanup")
    shutil.rmtree(p.sqlite.parent, ignore_errors=True)
    s = run / "summary.md"
    s.write_text(s.read_text(encoding="utf-8").replace("(kept)", "(dropped after the presentation)"), encoding="utf-8")
    print(f"Dropped {p.db} and {p.sqlite.parent.relative_to(ROOT).as_posix()}. Artifacts kept in {run.relative_to(ROOT).as_posix()}.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["prepare", "live", "cleanup"])
    ap.add_argument("--run", type=Path, help="kept demo run directory (default: newest kept)")
    ap.add_argument("--admin-dsn", default=os.environ.get("PG_ADMIN_DSN"),
                    help="Postgres server holding the demo database (default: Docker, $PG_ADMIN_DSN)")
    ap.add_argument("--source", type=Path, default=ROOT / "data" / "trading_bot.db",
                    help="prepare: database to copy and replay from, read-only (default: data/trading_bot.db)")
    ap.add_argument("--only", help="comma-separated segment numbers, e.g. 3,4")
    ap.add_argument("--auto", action="store_true", help="don't wait for Enter")
    a = ap.parse_args()
    if a.run and not a.run.is_absolute():
        a.run = ROOT / a.run
    return {"prepare": cmd_prepare, "live": cmd_live, "cleanup": cmd_cleanup}[a.command](a)


if __name__ == "__main__":
    sys.exit(main())
