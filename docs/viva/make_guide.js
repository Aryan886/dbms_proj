const fs = require("fs");
const {
  Document, Packer, Paragraph, TextRun, HeadingLevel, Table, TableRow, TableCell, WidthType,
  ShadingType, BorderStyle, AlignmentType, LevelFormat, PageBreak, Footer, PageNumber,
  TableOfContents, Header,
} = require("docx");

const FONT = "Calibri";
const MONO = "Consolas";
const W = 9638; // A4 text width with 2 cm margins (DXA)

// ---------- helpers ----------
function runs(text, base = {}) {
  // **bold** and `code` inline markup
  const out = [];
  const re = /(\*\*[^*]+\*\*|`[^`]+`)/g;
  let last = 0, m;
  while ((m = re.exec(text))) {
    if (m.index > last) out.push(new TextRun({ text: text.slice(last, m.index), ...base }));
    const t = m[0];
    if (t.startsWith("**")) out.push(new TextRun({ text: t.slice(2, -2), bold: true, ...base }));
    else out.push(new TextRun({ text: t.slice(1, -1), font: MONO, size: 19, color: "8B1A1A", ...base }));
    last = m.index + t.length;
  }
  if (last < text.length) out.push(new TextRun({ text: text.slice(last), ...base }));
  return out;
}
const P = (t, opt = {}) => new Paragraph({ children: runs(t), spacing: { after: 100 }, ...opt });
const H1 = (t) => new Paragraph({ heading: HeadingLevel.HEADING_1, children: [new TextRun(t)], pageBreakBefore: true });
const H1n = (t) => new Paragraph({ heading: HeadingLevel.HEADING_1, children: [new TextRun(t)] });
const H2 = (t) => new Paragraph({ heading: HeadingLevel.HEADING_2, children: [new TextRun(t)] });
const H3 = (t) => new Paragraph({ heading: HeadingLevel.HEADING_3, children: [new TextRun(t)] });
const B = (t, lvl = 0) => new Paragraph({ numbering: { reference: "bul", level: lvl }, children: runs(t), spacing: { after: 60 } });
const N = (t, ref = "num") => new Paragraph({ numbering: { reference: ref, level: 0 }, children: runs(t), spacing: { after: 60 } });

const thin = { style: BorderStyle.SINGLE, size: 4, color: "BFBFBF" };
const borders = { top: thin, bottom: thin, left: thin, right: thin };

// Shaded box containing code lines. label = terminal name shown on top.
function code(label, lines) {
  const kids = [];
  if (label) kids.push(new Paragraph({ children: [new TextRun({ text: label, bold: true, size: 16, color: "FFFFFF", font: FONT })], spacing: { after: 40 } }));
  for (const l of lines) {
    kids.push(new Paragraph({ spacing: { after: 0, line: 260 }, children: [new TextRun({ text: l === "" ? " " : l, font: MONO, size: 18, color: label ? "FFFFFF" : "1F1F1F" })] }));
  }
  const fill = label ? (label.startsWith("PS") ? "012456" : label.startsWith("PG") ? "1E3A5F" : "2F3B2F") : "F2F2F2";
  return new Table({
    width: { size: W, type: WidthType.DXA }, columnWidths: [W],
    rows: [new TableRow({ children: [new TableCell({ borders, width: { size: W, type: WidthType.DXA }, shading: { fill, type: ShadingType.CLEAR, color: "auto" }, margins: { top: 100, bottom: 100, left: 140, right: 140 }, children: kids })] })],
  });
}
// Expected output box (light grey, monospace)
function out(lines) {
  const kids = [new Paragraph({ children: [new TextRun({ text: "Expected output (from the test run on 17 Nov 2026)", bold: true, size: 16, color: "595959" })], spacing: { after: 40 } })];
  for (const l of lines) kids.push(new Paragraph({ spacing: { after: 0, line: 250 }, children: [new TextRun({ text: l === "" ? " " : l, font: MONO, size: 17, color: "262626" })] }));
  return new Table({
    width: { size: W, type: WidthType.DXA }, columnWidths: [W],
    rows: [new TableRow({ children: [new TableCell({ borders, width: { size: W, type: WidthType.DXA }, shading: { fill: "F2F2F2", type: ShadingType.CLEAR, color: "auto" }, margins: { top: 80, bottom: 80, left: 140, right: 140 }, children: kids })] })],
  });
}
// Callout box
function note(kind, text) {
  const colors = { WARNING: ["FDECEA", "C0392B"], TIP: ["EAF4EA", "2E7D32"], NOTE: ["EAF1FB", "1F4E79"] };
  const [fill, edge] = colors[kind];
  const side = { style: BorderStyle.SINGLE, size: 24, color: edge };
  const paras = (Array.isArray(text) ? text : [text]).map((t, i) => new Paragraph({ spacing: { after: 40 }, children: i === 0 ? [new TextRun({ text: kind + ": ", bold: true, color: edge }), ...runs(t)] : runs(t) }));
  return new Table({
    width: { size: W, type: WidthType.DXA }, columnWidths: [W],
    rows: [new TableRow({ children: [new TableCell({ borders: { top: thin, bottom: thin, right: thin, left: side }, width: { size: W, type: WidthType.DXA }, shading: { fill, type: ShadingType.CLEAR, color: "auto" }, margins: { top: 80, bottom: 80, left: 160, right: 140 }, children: paras })] })],
  });
}
const gap = () => new Paragraph({ spacing: { after: 60 }, children: [] });

function table(headers, rows, widths) {
  const hdr = new TableRow({ tableHeader: true, children: headers.map((h, i) => new TableCell({ borders, width: { size: widths[i], type: WidthType.DXA }, shading: { fill: "1F4E79", type: ShadingType.CLEAR, color: "auto" }, margins: { top: 60, bottom: 60, left: 100, right: 100 }, children: [new Paragraph({ children: [new TextRun({ text: h, bold: true, color: "FFFFFF", size: 19 })] })] })) });
  const body = rows.map((r, ri) => new TableRow({ children: r.map((c, i) => new TableCell({ borders, width: { size: widths[i], type: WidthType.DXA }, shading: { fill: ri % 2 ? "F7F9FC" : "FFFFFF", type: ShadingType.CLEAR, color: "auto" }, margins: { top: 50, bottom: 50, left: 100, right: 100 }, children: [new Paragraph({ children: runs(c, { size: 19 }) })] })) }));
  return new Table({ width: { size: W, type: WidthType.DXA }, columnWidths: widths, rows: [hdr, ...body] });
}

// Viva Q&A block
function qa(pairs) {
  const items = [new Paragraph({ spacing: { before: 120, after: 60 }, children: [new TextRun({ text: "Viva questions the guide may ask here", bold: true, color: "7B3F00", size: 21 })] })];
  for (const [q, a] of pairs) {
    items.push(new Paragraph({ spacing: { after: 20 }, indent: { left: 200 }, children: [new TextRun({ text: "Q. ", bold: true, color: "7B3F00" }), ...runs(q, { bold: true })] }));
    items.push(new Paragraph({ spacing: { after: 100 }, indent: { left: 200 }, children: [new TextRun({ text: "A. ", bold: true, color: "2E7D32" }), ...runs(a)] }));
  }
  return items;
}
// "What it proves" line
const proves = (t) => new Paragraph({ spacing: { before: 80, after: 80 }, children: [new TextRun({ text: "What it proves: ", bold: true, color: "1F4E79" }), ...runs(t)] });

// A numbered check: title, steps (array of content), etc.
function check(id, title, parts) {
  return [H3(`${id}  ${title}`), ...parts];
}

// ---------- content ----------
const C = [];

// Title page
C.push(
  new Paragraph({ spacing: { before: 2400, after: 200 }, alignment: AlignmentType.CENTER, children: [new TextRun({ text: "cloudsync", size: 64, bold: true, color: "1F4E79" })] }),
  new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 200 }, children: [new TextRun({ text: "Live Verification Guide for the Project Guide", size: 36, color: "404040" })] }),
  new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 600 }, children: [new TextRun({ text: "Commands the guide can ask us to run, step by step, with expected output and viva answers", size: 24, italics: true, color: "595959" })] }),
  new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 80 }, children: [new TextRun({ text: "DBMS course project: SQLite to PostgreSQL sync for the AlgoTrade bot", size: 22 })] }),
  new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 80 }, children: [new TextRun({ text: "Level: second-year DBMS", size: 22 })] }),
  new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 80 }, children: [new TextRun({ text: "Runs on: our laptop, local Docker PostgreSQL 17 (port 5433), Windows PowerShell", size: 22 })] }),
  new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 80 }, children: [new TextRun({ text: "Every command in this document was run on 17 Nov 2026 on a throwaway sandbox.", size: 22, bold: true })] }),
);

C.push(new Paragraph({ children: [new PageBreak()] }), new Paragraph({ spacing: { after: 160 }, children: [new TextRun({ text: "Contents", size: 34, bold: true, color: "1F4E79" })] }), new TableOfContents("Contents", { hyperlink: true, headingStyleRange: "1-2" }));

// 1. How to use
C.push(H1("1. How to use this document"));
C.push(P("A guide who wants to check that we built the project ourselves will usually do three things: ask us to run something they choose, ask us to change something small and run it again, and ask **why** it behaves that way. This document prepares for all three. Each check has:"));
C.push(B("**Goal**: the DBMS idea being tested (constraints, transactions, indexes and so on)."));
C.push(B("**Commands**: exactly what to type, and in which terminal."));
C.push(B("**Expected output**: what the screen showed when we ran it. Row counts can drift a little if the working copy changes; error messages and plan shapes will not."));
C.push(B("**What it proves** and **viva questions**: the follow-up questions a guide is likely to ask, with short answers we should be able to give in our own words."));
C.push(H2("1.1 The three terminals"));
C.push(P("Open three terminal windows, all in the project folder `C:\\Users\\aryan\\DEV_Maxxing\\dbms_proj`. Each code box in this document is labelled with the terminal it belongs to:"));
C.push(table(["Label", "Terminal", "What runs there"], [
  ["**PS**", "Windows PowerShell", "`cloudsync` commands (sync, reconcile, benchmarks, tests), Docker"],
  ["**PG**", "psql inside the Docker Postgres container", "SQL on the cloud (PostgreSQL) side"],
  ["**LITE**", "sqlite3 shell", "SQL on the bot (SQLite) side"],
], [1200, 3300, 5138]));
C.push(gap());
C.push(P("Interactive `psql` and `sqlite3` shells are used for SQL on purpose: we type plain SQL with no PowerShell quoting problems, and the guide can read along or type their own query."));
C.push(H2("1.2 Golden rules (say these out loud if asked)"));
C.push(note("WARNING", [
  "Never run anything against the bot's real database (`C:\\Users\\aryan\\Desktop\\AlgoTrade\\db\\trading_bot.db`). It is read-only for this project, and `cloudsync` refuses writes to it with `REFUSED` (enforced in `cloudsync/guard.py`).",
  "Never experiment on the main working copy (`data\\trading_bot.db`) or the main cloud database. Every check in this document runs on a throwaway **sandbox** called `viva`, created in section 2 and dropped in section 6.",
  "In `.env`, `PG_DSN` points at **AWS RDS**. So always pass `--dsn $DSN` (the sandbox) to `sync` and `reconcile`, and always pass `--from-dsn` (local Docker) to `sandbox create` and `sandbox drop`. Without them the command uses RDS.",
]));
C.push(gap());
C.push(H2("1.3 Suggested order if the guide gives us 15 minutes"));
C.push(table(["Minutes", "Check", "Why this one"], [
  ["2", "A1 + B1 to B4 (schema, constraints)", "Fast, visual, every second-year topic"],
  ["2", "C1 + C2 (transactions)", "Atomicity and rollback are certain to be asked"],
  ["2", "F1 (roles) + G1 (audit trigger)", "GRANT/REVOKE and triggers"],
  ["2", "H1 (index with and without)", "Shows a real speed difference in a query plan"],
  ["4", "L1 + N1 (change capture and crash test)", "The core of our project: our own design, hard to fake"],
  ["3", "O1 (reconcile)", "End-to-end proof that the cloud copy matches"],
], [1100, 4200, 4338]));

// 2. Setup
C.push(H1("2. Before the guide arrives (about 5 minutes)"));
C.push(H2("2.1 Start Docker Postgres"));
C.push(P("Start Docker Desktop first and wait until it says it is running. Then:"));
C.push(code("PS  (PowerShell)", [
  "cd C:\\Users\\aryan\\DEV_Maxxing\\dbms_proj",
  "docker compose up -d",
  "docker compose ps",
]));
C.push(out(["NAME                   IMAGE         ...   STATUS          PORTS", "dbms_proj-postgres-1   postgres:17   ...   Up 10 seconds   0.0.0.0:5433->5432/tcp"]));
C.push(H2("2.2 Create the sandbox"));
C.push(P("This copies the main working copy (opened read-only) to `data\\sandboxes\\viva\\trading_bot.db` and clones the local Docker cloud database `algotrade` into a new database `algotrade_sbx_viva`. It takes about 5 seconds."));
C.push(code("PS", [
  ".venv\\Scripts\\python -m cloudsync sandbox create viva --from-dsn \"postgresql://postgres:postgres@localhost:5433/algotrade\"",
]));
C.push(out(["{", "  \"name\": \"viva\",", "  \"sqlite\": \"data\\\\sandboxes\\\\viva\\\\trading_bot.db\",", "  \"dsn\": \"user=postgres password=postgres dbname=algotrade_sbx_viva host=localhost port=5433\",", "  \"pg_database\": \"algotrade_sbx_viva\"", "}"]));
C.push(note("NOTE", "If it says the sandbox already exists, drop it first (section 6) and create it again. If it says the database is being accessed by other users, close any psql window connected to `algotrade` and stop the sync daemon if it is running."));
C.push(gap());
C.push(H2("2.3 Set two variables in the PS terminal"));
C.push(P("Every `cloudsync` command below uses these. Re-run these two lines if you open a new PowerShell window."));
C.push(code("PS", [
  "$DB  = \"data\\sandboxes\\viva\\trading_bot.db\"",
  "$DSN = \"postgresql://postgres:postgres@localhost:5433/algotrade_sbx_viva\"",
]));
C.push(H2("2.4 Open the PG and LITE terminals"));
C.push(code("PG  (second window)", [
  "cd C:\\Users\\aryan\\DEV_Maxxing\\dbms_proj",
  "docker compose exec postgres psql -U postgres -d algotrade_sbx_viva",
  "\\pset pager off",
  "\\timing on",
]));
C.push(code("LITE  (third window)", [
  "cd C:\\Users\\aryan\\DEV_Maxxing\\dbms_proj",
  "sqlite3 data\\sandboxes\\viva\\trading_bot.db",
  ".headers on",
  ".mode column",
]));
C.push(P("The prompt becomes `algotrade_sbx_viva=#` in PG and `sqlite>` in LITE. To leave them later: `\\q` in PG, `.quit` in LITE."));
C.push(H2("2.5 Smoke test (30 seconds)"));
C.push(code("PG", ["SELECT count(*) FROM candles WHERE timeframe = '1m';"]));
C.push(code("LITE", ["SELECT count(*) FROM market_data_1m;"]));
C.push(out(["Both print 32543. Same data on both sides: we are ready."]));

// 3. Postgres checks
C.push(H1("3. Cloud side: PostgreSQL checks (PG terminal)"));
C.push(P("Everything in this section is typed in the **PG** terminal unless a box says otherwise."));

C.push(H2("Group A. Look around the schema"));
C.push(...check("A1", "Schemas, tables and migrations", [
  P("**Goal:** show the database design is ours and was built in numbered steps."),
  code("PG", ["\\dn", "\\dt public.*", "SELECT version, name FROM schema_version ORDER BY version;", "\\d candles"]),
  out(["Schemas: analytics, audit, compat, public", "17 base tables in public (candles, instruments, option_contracts, rejected_rows, sync_state, ...)", "schema_version: 17 rows, 1 base_schema ... 17 backfill_source_tag", "", "\\d candles shows:", "  PRIMARY KEY (instrument_id, timeframe, ts)", "  candles_ist_ts btree (instrument_id, timeframe, (ts AT TIME ZONE 'Asia/Kolkata'))", "  CHECK candles_ohlc_close_in_range (close >= low AND close <= high)", "  CHECK candles_timeframe_check (timeframe IN ('1m','5m','15m','1h'))", "  FOREIGN KEY (instrument_id) REFERENCES instruments(id)"]),
  proves("the schema has keys, checks and foreign keys, and every change to it was applied by a numbered migration recorded in `schema_version`."),
  ...qa([
    ["Why four schemas?", "`public` holds the base tables. `compat` holds views shaped exactly like the bot's old SQLite tables. `analytics` holds reporting views for the analyst role. `audit` holds the audit log on its own, so no grant on `public` can ever reach it."],
    ["What is a migration and why number them?", "A migration is one SQL file that changes the schema. They live in `cloudsync/migrations/0001_...sql` to `0017_...sql`, each runs in its own transaction, and `schema_version` records which ones were applied, so every database can be brought to the same version and we know its exact history."],
    ["Why is the primary key of candles three columns?", "One candle exists per instrument, per timeframe, per minute. `(instrument_id, timeframe, ts)` is the natural key, so a duplicate candle is impossible."],
  ]),
]));

C.push(H2("Group B. Integrity constraints"));
C.push(P("The guide may give their own bad values. Any of these errors comes from PostgreSQL itself, not from our Python code."));
C.push(...check("B1", "CHECK constraint: an impossible candle", [
  code("PG", ["INSERT INTO candles (instrument_id, timeframe, ts, source_id, open, high, low, close)", "VALUES (1, '1m', now(), -1, 100, 90, 110, 100);"]),
  out(["ERROR:  new row for relation \"candles\" violates check constraint \"candles_ohlc_close_in_range\"", "DETAIL:  Failing row contains (1, 1m, ..., -1, 100.00, 90.00, 110.00, 100.00, null)."]),
]));
C.push(...check("B2", "CHECK on an allowed set of values", [
  code("PG", ["INSERT INTO candles (instrument_id, timeframe, ts, source_id, open, high, low, close)", "VALUES (1, '2m', now(), -1, 100, 110, 90, 100);", "", "UPDATE option_contracts SET option_type = 'XX' WHERE id = (SELECT min(id) FROM option_contracts);"]),
  out(["ERROR:  ... violates check constraint \"candles_timeframe_check\"", "ERROR:  ... violates check constraint \"option_contracts_option_type_check\""]),
]));
C.push(...check("B3", "FOREIGN KEY: child without a parent, and deleting a parent", [
  code("PG", ["INSERT INTO candles (instrument_id, timeframe, ts, source_id, open, high, low, close)", "VALUES (99, '1m', now(), -1, 100, 110, 90, 100);", "", "DELETE FROM instruments WHERE symbol = 'NIFTY50';"]),
  out(["ERROR:  insert or update on table \"candles\" violates foreign key constraint \"candles_instrument_id_fkey\"", "DETAIL:  Key (instrument_id)=(99) is not present in table \"instruments\".", "", "ERROR:  update or delete on table \"instruments\" violates foreign key constraint", "        \"option_contracts_instrument_id_fkey\" on table \"option_contracts\"", "DETAIL:  Key (id)=(1) is still referenced from table \"option_contracts\"."]),
]));
C.push(...check("B4", "PRIMARY KEY and NOT NULL", [
  code("PG", ["INSERT INTO candles SELECT * FROM candles WHERE timeframe = '1m' LIMIT 1;", "", "INSERT INTO instruments (symbol, kind) VALUES (NULL, 'index');"]),
  out(["ERROR:  duplicate key value violates unique constraint \"candles_pkey\"", "DETAIL:  Key (instrument_id, timeframe, ts)=(1, 1m, 2025-08-25 09:15:00+05:30) already exists.", "", "ERROR:  null value in column \"symbol\" of relation \"instruments\" violates not-null constraint"]),
  proves("the database itself rejects bad data, whoever writes it."),
  ...qa([
    ["Why put rules in the database instead of in Python?", "Every writer is checked, including a future program or a person typing SQL. The rule is in one place, and it cannot be skipped by a bug in application code."],
    ["What is the difference between PRIMARY KEY, UNIQUE and NOT NULL?", "PRIMARY KEY = UNIQUE + NOT NULL, one per table, used as the row's identity. UNIQUE allows NULLs and you can have several. NOT NULL only forbids missing values."],
    ["What happens to children when a parent is deleted?", "By default (NO ACTION / RESTRICT) the delete is refused, as B3 showed. We used ON DELETE CASCADE only for `candle_indicators`, because indicators have no meaning without their candle."],
    ["Why numeric(12,2) for prices and not float?", "numeric stores exact decimals; float can turn 0.1 into 0.1000000000000000055. Money and prices must be exact."],
    ["SQLite accepted these rows. Why?", "The bot's SQLite tables have no CHECK or FK constraints, and SQLite's typing is loose (SL and SH have no declared type). That is one of the problems the project fixes."],
  ]),
]));
C.push(...check("B5", "The quarantine table: nothing is silently lost", [
  code("PG", ["SELECT source_table, violated_constraint, count(*)", "FROM rejected_rows GROUP BY 1, 2 ORDER BY 1, 2;", "", "\\d rejected_rows"]),
  out([" source_table | violated_constraint  | count", "--------------+----------------------+-------", " delta_cache  | delta_snapshots_pkey |  2050"]),
  proves("the 2,050 duplicate groups found in the bot's `delta_cache` were kept, with the constraint they broke, instead of being dropped."),
  ...qa([
    ["Which duplicate did you keep?", "The row with the highest source id in each group. The rule is deterministic, so running the load again gives the same answer."],
    ["Why not just fail the load?", "One bad row would stop 350,000 good ones. Keeping it in `rejected_rows` (table, raw row as JSON, constraint, time) means every reject can be explained later. Level-1 reconcile counts them: sqlite = postgres + rejected."],
  ]),
]));

C.push(H2("Group C. Transactions"));
C.push(...check("C1", "BEGIN ... ROLLBACK undoes everything", [
  code("PG", ["BEGIN;", "SELECT count(*) AS before FROM candles WHERE timeframe = '1m';", "DELETE FROM candles WHERE timeframe = '1m' AND ts::date = '2026-03-27';", "SELECT count(*) AS during FROM candles WHERE timeframe = '1m';", "ROLLBACK;", "SELECT count(*) AS after FROM candles WHERE timeframe = '1m';"]),
  out(["before 32543", "DELETE 375", "during 32168", "ROLLBACK", "after  32543"]),
]));
C.push(...check("C2", "One failure aborts the whole transaction (atomicity)", [
  code("PG", ["BEGIN;", "INSERT INTO instruments (symbol, kind) VALUES ('TESTX', 'equity');", "INSERT INTO instruments (symbol, kind) VALUES ('TESTY', 'crypto');", "COMMIT;", "SELECT count(*) FROM instruments WHERE symbol IN ('TESTX', 'TESTY');"]),
  out(["INSERT 0 1", "ERROR:  new row for relation \"instruments\" violates check constraint \"instruments_kind_check\"", "ROLLBACK          <- COMMIT turned into ROLLBACK", " count", "-------", "     0           <- TESTX is gone too"]),
  proves("all or nothing. The good first insert was undone because the second one failed."),
  ...qa([
    ["Explain ACID with what we just saw.", "Atomicity: C2, both inserts or none. Consistency: the CHECK kept the data valid. Isolation: other sessions never saw the 375 deleted rows in C1. Durability: once COMMIT returns, the data survives a crash (it is in the write-ahead log)."],
    ["Why did COMMIT print ROLLBACK?", "After an error PostgreSQL marks the transaction aborted. Further commands are ignored, and COMMIT can only roll it back."],
    ["What isolation level are we using?", "Run `SHOW transaction_isolation;` and it prints `read committed`, the PostgreSQL default: each statement sees data committed before it started."],
    ["Where does the project use this?", "The sync applies a whole batch of changes AND moves its cursor (`sync_state.last_seq`) in one transaction. A crash leaves the cloud fully before or fully after the batch. Check N1 shows this live."],
  ]),
]));

C.push(H2("Group D. Normalization and joins"));
C.push(...check("D1", "One candles table instead of four", [
  code("PG", ["SELECT i.symbol, c.timeframe, count(*) AS candles,", "       min(c.ts)::date AS first_day, max(c.ts)::date AS last_day", "FROM candles c JOIN instruments i ON i.id = c.instrument_id", "GROUP BY 1, 2 ORDER BY 1, 2;"]),
  out([" symbol  | timeframe | candles | first_day  |  last_day", " NIFTY50 | 15m       |    3379 | 2025-06-30 | 2026-03-27", " NIFTY50 | 1h        |    1235 | ...        | 2026-03-27", " NIFTY50 | 1m        |   32543 | 2025-08-25 | 2026-03-27", " NIFTY50 | 5m        |    6311 | 2025-09-04 | 2026-03-27"]),
]));
C.push(...check("D2", "Option chain: header and line tables joined back together", [
  code("PG", ["SELECT oc.tradingsymbol, oc.strike, oc.option_type,", "       h.ts AT TIME ZONE 'Asia/Kolkata' AS ist, h.spot_price, s.ltp", "FROM option_snapshots s", "JOIN option_chain_snapshots h ON h.id = s.chain_snapshot_id", "JOIN option_contracts oc ON oc.id = s.contract_id", "ORDER BY h.ts DESC LIMIT 3;"]),
  out(["   tradingsymbol   | strike | option_type |         ist         | spot_price |   ltp", " NIFTY2640725550PE |  25550 | PE          | 2026-03-27 15:42:46 |   22819.60 |  2621.65", " NIFTY26MAR27500CE |  27500 | CE          | 2026-03-27 15:42:46 |   22819.60 |    0.575"]),
]));
C.push(...check("D3", "List every foreign key", [
  code("PG", ["SELECT conrelid::regclass AS tbl, confrelid::regclass AS refs, pg_get_constraintdef(oid)", "FROM pg_constraint", "WHERE contype = 'f' AND connamespace = 'public'::regnamespace", "ORDER BY 1, 2;"]),
  out(["13 rows, e.g.", " candles           | instruments | FOREIGN KEY (instrument_id) REFERENCES instruments(id)", " candle_indicators | candles     | FOREIGN KEY (instrument_id, timeframe, ts) REFERENCES candles(...) ON DELETE CASCADE", " option_snapshots  | option_chain_snapshots | FOREIGN KEY (chain_snapshot_id) REFERENCES ..."]),
  proves("the redesigned schema is in 3NF, with master tables referenced by foreign keys. The full FD analysis and ER diagrams are in `docs/normalization.md`."),
  ...qa([
    ["What normal form is the cloud schema in, and what did you fix?", "3NF. (1) The timeframe was hidden in four table names; now it is a column of one `candles` table. (2) In `option_data`, `tradingsymbol -> expiry, strike, option_type` was a transitive dependency, so contracts moved to `option_contracts`. (3) `(instrument, ts) -> spot_price` held for a whole option chain, so the chain became a header (`option_chain_snapshots`) with lines (`option_snapshots`)."],
    ["Define a transitive dependency.", "A -> B and B -> C where B is not a key, so A -> C goes through a non-key column. Example: id -> tradingsymbol -> strike. Storing strike on every row repeats it and allows contradictions."],
    ["Did you denormalize anything on purpose?", "Yes. The indicator values the bot wrote (Donchian, AO, SL/SH) are stored, not recomputed, because the strategy reads the stored values and SL/SH depend on history. A view (`dq_indicator_drift`) compares them with SQL-computed values."],
    ["What is a surrogate key vs a natural key?", "A surrogate is a made-up id (`instruments.id`); a natural key comes from the data (`symbol`). We use surrogates for joins and keep the natural key UNIQUE."],
  ]),
]));

C.push(H2("Group E. Views and window functions"));
C.push(...check("E1", "The bot's old table, served by a view", [
  code("PG", ["SELECT symbol, \"timestamp\", close FROM compat.market_data_1m", "ORDER BY \"timestamp\" DESC LIMIT 3;", "", "SET search_path = compat;", "SELECT count(*) FROM market_data_1m;      -- the bot's own table name works", "RESET search_path;"]),
  out([" symbol  |      timestamp      |  close", " NIFTY50 | 2026-03-27 15:29:00 |  22824.7", " ...", " count 32543"]),
]));
C.push(...check("E2", "Moving average with a window function", [
  code("PG", ["SELECT ts AT TIME ZONE 'Asia/Kolkata' AS ist, close,", "       round(avg(close) OVER (ORDER BY ts ROWS BETWEEN 4 PRECEDING AND CURRENT ROW), 2) AS sma5", "FROM candles WHERE instrument_id = 1 AND timeframe = '1m'", "ORDER BY ts DESC LIMIT 5;"]),
  out(["         ist         |  close   |   sma5", " 2026-03-27 15:29:00 | 22824.70 | 22819.46", " 2026-03-27 15:28:00 | 22825.10 | 22817.69"]),
]));
C.push(...check("E3", "Analytics: strategy P&L", [
  code("PG", ["SELECT * FROM analytics.strategy_pnl_summary;", "SELECT * FROM analytics.strategy_daily_pnl LIMIT 5;", "SELECT pg_get_viewdef('analytics.strategy_daily_pnl'::regclass, true);"]),
  out(["strategy_pnl_summary: 5 rows, e.g.", " nifty-options | backtest-backfill | 90 closed trades | 38 wins | win_rate 0.4222 | total_pnl 12620.00", "", "view definition ends with:", " sum(sum(pnl)) OVER (PARTITION BY strategy_id, source ORDER BY trade_day) AS cumulative_pnl"]),
  proves("views give the bot its old table shapes and give analysts ready-made reports, with logic in SQL."),
  ...qa([
    ["Does a view store data?", "No. A normal view is a saved query that runs each time it is read. (A materialized view would store the result; we did not need one.)"],
    ["Why do the compat views matter?", "About 40 files in the bot query SQLite by table name. With `search_path=compat` the same SQL runs unchanged on PostgreSQL. Level-3 reconcile proved it: the bot's own backtester gave the same trades on both."],
    ["Window function vs GROUP BY?", "GROUP BY collapses rows into one per group. A window function (`OVER (...)`) computes over a set of rows but keeps every row, which is what a moving average or running total needs."],
    ["Why quote \"timestamp\"?", "It is a type name in SQL, and the bot used it as a column name; double quotes make it an identifier."],
  ]),
]));

C.push(H2("Group F. Users, roles and privileges"));
C.push(...check("F1", "Each role can do only its job", [
  code("PG", ["\\du", "", "SET ROLE bot_reader;", "SELECT symbol, \"timestamp\", close FROM compat.market_data_1m ORDER BY \"timestamp\" DESC LIMIT 1;", "SELECT count(*) FROM candles;", "DELETE FROM candles WHERE false;", "RESET ROLE;", "", "SET ROLE analyst;", "SELECT strategy_id, total_pnl FROM analytics.strategy_pnl_summary;", "SELECT count(*) FROM compat.vix_data;", "RESET ROLE;", "", "SET ROLE sync_writer;", "SELECT count(*) FROM audit.audit_log;", "DELETE FROM audit.audit_log;", "RESET ROLE;", "", "\\dp compat.market_data_1m"]),
  out(["\\du: analyst, bot_reader, sync_writer -> Cannot login;  postgres -> Superuser", "bot_reader:  view works (1 row) | ERROR: permission denied for table candles (x2)", "analyst:     P&L works          | ERROR: permission denied for schema compat", "sync_writer: ERROR: permission denied for table audit_log (read and delete)", "\\dp: bot_reader=r/postgres   (r = SELECT only)"]),
  note("TIP", "If a later command says permission denied unexpectedly, you are still in a role: type `RESET ROLE;`."),
  proves("least privilege: reader, analyst and writer each get only what they need."),
  ...qa([
    ["What are GRANT and REVOKE?", "GRANT gives a privilege (SELECT, INSERT, UPDATE, DELETE, USAGE on a schema) to a role; REVOKE takes it back. Migration `0010_roles.sql` holds our grants."],
    ["Why are the roles NOLOGIN?", "They are group roles. No password is stored in a migration. A real login is made a member, or a connection sets `-c role=sync_writer`, which is how the sync connects."],
    ["How can the analyst read a view built on tables it has no rights to?", "A view runs with its owner's rights, so the analyst only needs SELECT on the view and USAGE on the `analytics` schema."],
    ["Why can't sync_writer read or delete the audit log?", "So the process that makes changes cannot hide them. It can only INSERT into the log (through the trigger)."],
  ]),
]));

C.push(H2("Group G. Triggers (audit log)"));
C.push(...check("G1", "An UPDATE writes an audit row by itself", [
  code("PG", ["SET ROLE sync_writer;", "UPDATE dashboard_trade_history SET exit_reason = 'viva-test' WHERE id = 1;", "RESET ROLE;", "", "SELECT audit_id, op, actor, login, changed_at,", "       old_row->>'exit_reason' AS old_reason, new_row->>'exit_reason' AS new_reason", "FROM audit.audit_log ORDER BY audit_id DESC LIMIT 1;", "", "UPDATE dashboard_trade_history SET exit_reason = 'TIME_EXIT' WHERE id = 1;   -- put it back", "\\d dashboard_trade_history"]),
  out([" audit_id |   op   |    actor    |  login   | ... | old_reason | new_reason", "      181 | UPDATE | sync_writer | postgres | ... | TIME_EXIT  | viva-test", "", "Triggers:", "  audit_update AFTER UPDATE ... FOR EACH ROW WHEN (old.* IS DISTINCT FROM new.*)", "  EXECUTE FUNCTION audit.log_row_change()"]),
  proves("triggers record who changed a trade, when, and the old and new row as JSON."),
  ...qa([
    ["BEFORE vs AFTER trigger?", "BEFORE runs before the row is written and can change or cancel it. AFTER runs once the row is written; right for logging, because it only logs changes that really happened."],
    ["Row-level vs statement-level?", "FOR EACH ROW fires once per changed row (we need each row's OLD and NEW). FOR EACH STATEMENT fires once per SQL statement."],
    ["Why the WHEN (OLD.* IS DISTINCT FROM NEW.*) condition?", "The sync re-applies rows as upserts. An update that changes nothing is not a change, so it is not logged."],
    ["actor vs login?", "`actor` is `current_user`, the role in effect (sync_writer); `login` is `session_user`, the account that connected (postgres)."],
  ]),
]));

C.push(H2("Group H. Indexes and query plans"));
C.push(...check("H1", "The same query with and without our index", [
  code("PG", ["EXPLAIN ANALYZE", "SELECT * FROM compat.market_data_1m", "WHERE symbol = 'NIFTY50' AND \"timestamp\" BETWEEN '2026-03-27 09:15' AND '2026-03-27 15:30'", "ORDER BY \"timestamp\" DESC LIMIT 200;", "", "BEGIN;", "DROP INDEX candles_ist_ts;", "EXPLAIN ANALYZE", "SELECT * FROM compat.market_data_1m", "WHERE symbol = 'NIFTY50' AND \"timestamp\" BETWEEN '2026-03-27 09:15' AND '2026-03-27 15:30'", "ORDER BY \"timestamp\" DESC LIMIT 200;", "ROLLBACK;", "", "\\di candles*"]),
  out(["With the index:", "  ->  Index Scan using candles_ist_ts on candles c ... rows=375", "  Execution Time: 3.991 ms", "", "Index dropped (inside the transaction):", "  ->  Seq Scan on candles c ... Rows Removed by Filter: 42668", "  Execution Time: 28.594 ms", "", "After ROLLBACK, \\di still lists candles_ist_ts: the DROP was undone."]),
  note("NOTE", "Times vary run to run (the first run is slower because the data is not cached yet). The plan change from Index Scan to Seq Scan is what matters. Run each query twice if the guide wants a fair timing."),
]));
C.push(...check("H2", "The optimizer chooses between index and full scan", [
  code("PG", ["EXPLAIN SELECT * FROM candles WHERE instrument_id = 1 AND timeframe = '1m' AND ts >= '2026-03-27';", "EXPLAIN SELECT * FROM candles WHERE close > 22000;"]),
  out(["Index Scan using candles_pkey on candles   (few rows, key columns used)", "Seq Scan on candles  Filter: (close > 22000)  (no index on close, most rows match)"]),
  proves("we can read query plans and explain why an index helps or not."),
  ...qa([
    ["Why an expression index and not a plain index on ts?", "The compat view returns `ts AT TIME ZONE 'Asia/Kolkata'` (the bot's IST time). A filter on that expression cannot use a plain index on `ts`, so we indexed the same expression (`candles_ist_ts`, migration 0016)."],
    ["What kind of index is it?", "A B-tree: a balanced tree with sorted keys, good for =, <, >, BETWEEN and ORDER BY."],
    ["EXPLAIN vs EXPLAIN ANALYZE?", "EXPLAIN shows the planned steps and estimated cost without running the query. EXPLAIN ANALYZE runs it and adds the real times and row counts."],
    ["Why can DROP INDEX be rolled back?", "In PostgreSQL most DDL is transactional, so it obeys BEGIN/ROLLBACK like data changes."],
    ["Why not index every column?", "Each index costs disk space and slows down every INSERT/UPDATE, which must also update the index. We removed duplicate indexes found in the bot's schema for that reason."],
  ]),
]));

C.push(H2("Group I. MVCC, dead tuples and VACUUM"));
C.push(...check("I1", "An UPDATE writes a new row version", [
  code("PG", ["SELECT xmin, ctid, id, exit_reason FROM dashboard_trade_history WHERE id = 1;", "UPDATE dashboard_trade_history SET exit_reason = exit_reason || '' WHERE id = 1;", "SELECT xmin, ctid, id, exit_reason FROM dashboard_trade_history WHERE id = 1;", "", "ANALYZE dashboard_trade_history;", "SELECT relname, n_live_tup, n_dead_tup FROM pg_stat_user_tables WHERE relname = 'dashboard_trade_history';", "VACUUM (VERBOSE) dashboard_trade_history;"]),
  out(["xmin and ctid both change after the UPDATE, e.g. (0,9) -> (0,10)", "n_dead_tup >= 1 before VACUUM", "VACUUM VERBOSE: tuples: N removed, ... remain"]),
  proves("PostgreSQL never overwrites a row in place; old versions become dead tuples that VACUUM cleans."),
  ...qa([
    ["What is MVCC?", "Multi-Version Concurrency Control. An UPDATE writes a new row version (new `ctid`, stamped with the writing transaction id in `xmin`) and the old one stays until no transaction can see it. Readers never block writers."],
    ["What does VACUUM do? VACUUM vs VACUUM FULL?", "VACUUM marks dead tuples' space as reusable (no lock on readers). VACUUM FULL rewrites the whole table to give space back to the OS, but locks the table. Autovacuum runs VACUUM in the background."],
    ["How is this like the SQLite file?", "The bot's SQLite file was 2.5 GB but about 96% free pages: deletes do not shrink the file, only VACUUM does. In PostgreSQL the equivalent is dead tuples. Our Day-5 study measured both."],
    ["Why run ANALYZE first?", "The sandbox is a fresh clone, so its statistics start at zero. ANALYZE refreshes them (the planner uses them too)."],
  ]),
]));

C.push(H2("Group J. Locking with two sessions (optional)"));
C.push(...check("J1", "A second writer waits for the first", [
  P("Open a fourth window and run the same `docker compose exec postgres psql -U postgres -d algotrade_sbx_viva` (call it **PG-2**)."),
  code("PG", ["BEGIN;", "UPDATE dashboard_trade_history SET exit_reason = exit_reason WHERE id = 1;", "-- do not commit yet"]),
  code("PG-2", ["UPDATE dashboard_trade_history SET exit_reason = exit_reason WHERE id = 1;", "-- this hangs"]),
  code("PG", ["SELECT pid, state, wait_event_type, wait_event, left(query, 50)", "FROM pg_stat_activity WHERE datname = current_database();", "COMMIT;      -- PG-2 finishes immediately"]),
  out(["pg_stat_activity shows the PG-2 session with wait_event_type = Lock, wait_event = transactionid", "After COMMIT in PG, PG-2 prints UPDATE 1"]),
  ...qa([
    ["Why did PG-2 wait?", "The first transaction holds a row-level lock on id 1 until it commits. A second writer on the same row must wait; writers on other rows and all readers do not."],
    ["What is a deadlock and what does PostgreSQL do?", "Two transactions each wait for a lock the other holds. PostgreSQL detects the cycle after about a second and cancels one of them with an error."],
  ]),
]));

// 4. SQLite side
C.push(H1("4. Bot side: SQLite checks (LITE terminal)"));
C.push(...check("K1", "Tables, WAL mode and free pages", [
  code("LITE", [".tables", "PRAGMA journal_mode;", "PRAGMA page_size;", "PRAGMA page_count;", "PRAGMA freelist_count;"]),
  out(["_changelog, market_data_1m, option_data, delta_cache, ... (the bot's tables plus our _changelog)", "wal", "4096", "21623", "0          <- the working copy was VACUUMed by `prep`"]),
]));
C.push(...check("K2", "Change-capture triggers that we generated", [
  code("LITE", ["SELECT count(*) FROM sqlite_master WHERE type = 'trigger';", "SELECT name FROM sqlite_master WHERE type = 'trigger' AND tbl_name = 'market_data_1m';", "SELECT sql FROM sqlite_master WHERE name = '_cdc_market_data_1m_del';", ".schema _changelog"]),
  out(["33     <- 3 triggers x 11 in-scope tables", "_cdc_market_data_1m_ins | _cdc_market_data_1m_upd | _cdc_market_data_1m_del", "CREATE TRIGGER \"_cdc_market_data_1m_del\" AFTER DELETE ON \"market_data_1m\" BEGIN", "  INSERT INTO _changelog (table_name, pk, op) VALUES ('market_data_1m', OLD.\"id\", 'D'); END", "CREATE TABLE _changelog (seq INTEGER PRIMARY KEY AUTOINCREMENT, table_name TEXT NOT NULL, pk NOT NULL,", "  op TEXT NOT NULL CHECK (op IN ('I','U','D')), changed_at TEXT ...)"]),
  proves("every insert, update and delete in the bot's tables is captured in `_changelog`, without changing any bot code."),
  ...qa([
    ["What is WAL mode and why switch to it?", "Write-Ahead Logging: changes go to a separate `-wal` file first and are merged into the main file later. Readers keep reading the old pages while a writer appends, so our sync reader never blocks the bot's writes. Check P1 measures it."],
    ["Why triggers and not \"rows newer than the last timestamp\"?", "A timestamp watermark misses UPDATEs of old rows (the bot revises candles) and DELETEs (the bot deletes and rebuilds). Triggers catch all three operations."],
    ["Why AUTOINCREMENT on seq?", "Without it SQLite may reuse numbers after the changelog is emptied, and a new change could get a seq below the cursor and be skipped. AUTOINCREMENT never reuses a value."],
    ["Who writes these triggers?", "`cloudsync cdc-install` generates them from each table's live column list (`cloudsync/cdc.py`), so a new table needs no hand-written SQL."],
  ]),
]));

// 5. End-to-end pipeline
C.push(H1("5. The pipeline end to end (all three terminals)"));
C.push(P("These checks are the strongest evidence that the work is ours: they use our own change capture, sync and crash recovery, and the guide can choose the values."));
C.push(...check("L1", "An UPDATE travels from SQLite to PostgreSQL", [
  N("Look at the newest candle in the cloud.", "numL1"),
  code("PG", ["SELECT id, \"timestamp\", close FROM compat.market_data_1m ORDER BY id DESC LIMIT 1;"]),
  N("Change it in SQLite, like the bot revising a candle. The trigger logs it.", "numL1"),
  code("LITE", ["UPDATE market_data_1m SET close = low WHERE id = (SELECT max(id) FROM market_data_1m);", "SELECT * FROM _changelog;"]),
  N("Sync once.", "numL1"),
  code("PS", [".venv\\Scripts\\python -m cloudsync sync once --sqlite $DB --dsn $DSN"]),
  N("Check both sides again.", "numL1"),
  code("PG", ["SELECT id, \"timestamp\", close FROM compat.market_data_1m ORDER BY id DESC LIMIT 1;"]),
  code("LITE", ["SELECT count(*) FROM _changelog;"]),
  out(["PG before: 28147739 | 2026-03-27 15:29:00 | 22824.7", "LITE: seq | market_data_1m | 28147739 | U", "PS:  { \"batches\": 1, \"entries\": 1, \"upserts\": 1, \"deletes\": 0, \"rejected\": 0, \"backlog\": 0 }", "PG after: 28147739 | 2026-03-27 15:29:00 | 22820.55", "LITE: 0   <- pruned only after PostgreSQL committed"]),
]));
C.push(...check("L2", "INSERT and DELETE too", [
  code("LITE", ["INSERT INTO signals (timestamp, symbol, signal, reason, confidence_score)", "VALUES ('2026-03-27 15:31:00', 'NIFTY50', 'BUY', 'viva test', 0.9);", "SELECT * FROM _changelog;"]),
  code("PS", [".venv\\Scripts\\python -m cloudsync sync once --sqlite $DB --dsn $DSN"]),
  code("PG", ["SELECT * FROM compat.signals WHERE reason = 'viva test';"]),
  code("LITE", ["DELETE FROM signals WHERE reason = 'viva test';"]),
  code("PS", [".venv\\Scripts\\python -m cloudsync sync once --sqlite $DB --dsn $DSN"]),
  code("PG", ["SELECT count(*) FROM compat.signals WHERE reason = 'viva test';"]),
  out(["_changelog: ... | signals | 193 | I", "sync: \"upserts\": 1", "PG: 193 | 2026-03-27 15:31:00 | NIFTY50 | BUY | viva test | 0.9", "sync: \"deletes\": 1", "PG: count 0"]),
  ...qa([
    ["What does sync once do, step by step?", "Read up to 1,000 changelog entries after the cursor; for each, read the current row from SQLite (or note it was deleted); upsert or delete it in PostgreSQL; move `sync_state.last_seq`; commit all of that as ONE transaction; then delete those entries from `_changelog`."],
    ["What is an upsert and why use it?", "`INSERT ... ON CONFLICT DO UPDATE`: insert, or update if the key exists. Applying the same change twice gives the same result (idempotent), so a replay after a crash makes no duplicates."],
    ["Why delete from _changelog only after the commit?", "If we deleted first and then crashed, the change would be lost. Deleting after means the worst case is applying it twice, which the upsert makes harmless."],
  ]),
]));
C.push(...check("M1", "A bad row from the bot goes to quarantine, then comes back", [
  code("LITE", ["UPDATE market_data_1m SET close = high + 50 WHERE id = (SELECT max(id) FROM market_data_1m);"]),
  code("PS", [".venv\\Scripts\\python -m cloudsync sync once --sqlite $DB --dsn $DSN"]),
  code("PG", ["SELECT source_table, source_pk, violated_constraint, raw_row->>'close' AS close", "FROM rejected_rows WHERE source_table = 'market_data_1m';"]),
  code("LITE", ["UPDATE market_data_1m SET close = low WHERE id = (SELECT max(id) FROM market_data_1m);"]),
  code("PS", [".venv\\Scripts\\python -m cloudsync sync once --sqlite $DB --dsn $DSN"]),
  code("PG", ["SELECT count(*) FROM rejected_rows WHERE source_table = 'market_data_1m';"]),
  out(["sync: \"rejected\": 1", " market_data_1m | 28147739 | candles_ohlc_close_in_range | 22878.45", "sync: \"rejected\": 0", "count 0   <- the corrected row left the quarantine and is in candles again"]),
  ...qa([
    ["SQLite accepted close above high. Who caught it?", "PostgreSQL's CHECK constraint. Python only catches the error and routes the row to `rejected_rows`; it does not decide what is valid."],
    ["A row breaks two rules. Which one is recorded?", "PostgreSQL stops at the first violation it finds, so one constraint name is stored. Try `signal = 'HOLD'` with `confidence_score = 1.7` in `signals`: one name comes back."],
  ]),
]));
C.push(...check("N1", "Crash in the middle of a batch: nothing lost, nothing doubled", [
  N("Make a change in SQLite.", "numN1"),
  code("LITE", ["UPDATE market_data_1m SET close = high WHERE id = (SELECT max(id) FROM market_data_1m);"]),
  N("Note the cloud value and the cursor.", "numN1"),
  code("PG", ["SELECT id, close FROM compat.market_data_1m ORDER BY id DESC LIMIT 1;", "SELECT last_seq FROM sync_state WHERE source_table = 'market_data_1m';"]),
  N("Run the sync with a fault injected half-way through batch 1. The process kills itself.", "numN1"),
  code("PS", ["$env:CLOUDSYNC_FAULT = \"mid_batch:1\"", ".venv\\Scripts\\python -m cloudsync sync once --sqlite $DB --dsn $DSN", "\"exit code: $LASTEXITCODE\"", "Remove-Item Env:CLOUDSYNC_FAULT"]),
  N("Check: the cloud and the cursor did not move, and the change is still waiting.", "numN1"),
  code("PG", ["SELECT id, close FROM compat.market_data_1m ORDER BY id DESC LIMIT 1;", "SELECT last_seq FROM sync_state WHERE source_table = 'market_data_1m';"]),
  code("LITE", ["SELECT * FROM _changelog;"]),
  N("Restart the sync normally. It resumes from the cursor and applies the change once.", "numN1"),
  code("PS", [".venv\\Scripts\\python -m cloudsync sync once --sqlite $DB --dsn $DSN"]),
  code("PG", ["SELECT id, close FROM compat.market_data_1m ORDER BY id DESC LIMIT 1;", "SELECT * FROM analytics.sync_batch_log ORDER BY batch_id DESC LIMIT 3;"]),
  out(["[22:13:29] FAULT INJECTED: dying at mid_batch of batch 1", "exit code: 75", "cloud close and last_seq: unchanged", "_changelog: still 1 entry", "after restart: \"upserts\": 1, cloud close = the new value, last_seq moved forward"]),
  note("WARNING", "Always run `Remove-Item Env:CLOUDSYNC_FAULT` after the crash run, or every later sync in that window crashes too."),
  proves("the batch and the cursor commit together, so a crash leaves the cloud fully before the batch, and the restart applies it exactly once."),
  ...qa([
    ["What did the crash leave half-done?", "Nothing. The upsert happened inside an open transaction; when the process died the connection dropped, and PostgreSQL rolled the transaction back."],
    ["Could the change be applied twice?", "It could be re-read (the changelog entry was not pruned), but the upsert is idempotent, and the cursor only moves in the same commit as the data."],
    ["What if the network is down instead?", "`sync once` retries with exponential back-off (`--max-retries`, starting at 0.5 s and doubling); the daemon backs off up to 30 s and resumes where it stopped."],
  ]),
]));
C.push(...check("O1", "Reconciliation: prove both sides match", [
  code("PS", [".venv\\Scripts\\python -m cloudsync reconcile --sqlite $DB --dsn $DSN --levels 1,2 --out data\\sandboxes\\viva\\reconcile", "Get-Content data\\sandboxes\\viva\\reconcile\\reconciliation.md -TotalCount 25"]),
  out(["reconciliation PASSED -> data\\sandboxes\\viva\\reconcile   (about 3 s)", "## Level 1 - row counts: PASS", "| market_data_1m | 32543 | 32543 | 0 | PASS |", "| delta_cache | 348109 | 346059 | 2050 | PASS |", "## Level 2 - per-day checksums: PASS", "| market_data_1m | close | 88 | 0 | PASS |"]),
]));
C.push(...check("O2", "Make reconcile FAIL on purpose, then repair it", [
  P("A good answer to \"is the PASS hard-coded?\". We damage one candle in the cloud only, reconcile finds the exact day, and a re-sync from SQLite repairs it."),
  code("PG", ["UPDATE candles SET close = close + 1", "WHERE timeframe = '1m' AND ts = (SELECT max(ts) FROM candles WHERE timeframe = '1m');"]),
  code("PS", [".venv\\Scripts\\python -m cloudsync reconcile --sqlite $DB --dsn $DSN --levels 1,2 --out data\\sandboxes\\viva\\reconcile_fail", "\"exit code: $LASTEXITCODE\""]),
  code("LITE", ["UPDATE market_data_1m SET close = close WHERE id = (SELECT max(id) FROM market_data_1m);   -- trigger re-queues the row"]),
  code("PS", [".venv\\Scripts\\python -m cloudsync sync once --sqlite $DB --dsn $DSN", ".venv\\Scripts\\python -m cloudsync reconcile --sqlite $DB --dsn $DSN --levels 1,2 --out data\\sandboxes\\viva\\reconcile_fixed"]),
  out(["reconciliation FAILED   exit code: 1", "## Level 2 - per-day checksums: FAIL", "| market_data_1m | close | 88 | 1 | FAIL |     <- 1 mismatched day out of 88", "sync: \"upserts\": 1", "reconciliation PASSED"]),
  ...qa([["Why did Level 1 still pass?", "The row count did not change, only a value. That is why Level 2 compares per-day sums too."]]),
  ...qa([
    ["What are the three levels?", "Level 1: row counts per table, sqlite = postgres + rejected. Level 2: per IST day, count, sum of close, min and max timestamp, so a mismatch points to one day. Level 3: export the compat views to a new SQLite, run the bot's unchanged backtester on both, and diff the trades (2 trades, P&L 637.50 both sides in the Day-6 run; takes about a minute, so we show it from `artifacts/demo/20261117-1435/06_reconcile/`)."],
    ["Why is delta_cache 348109 vs 346059 a PASS?", "The 2,050 duplicates are in `rejected_rows`, and 346,059 + 2,050 = 348,109."],
  ]),
]));
C.push(...check("P1", "WAL vs rollback-journal benchmark", [
  code("PS", [".venv\\Scripts\\python -m cloudsync bench-wal --sqlite $DB --out data\\sandboxes\\viva\\wal --seconds 3", "Get-Content data\\sandboxes\\viva\\wal\\wal_benchmark.md"]),
  out(["(about 15 s; works on copies of the sandbox file)", "| delete | 5   writes OK | write p50 1096.378 ms |", "| wal    | 375 writes OK | write p50    1.164 ms |"]),
  ...qa([["Why so few writes in delete mode?", "In rollback-journal mode a reader holds a shared lock on the whole file, and the writer must wait for it to finish. In WAL mode the writer appends to the -wal file while readers keep reading."]]),
]));
C.push(...check("Q1", "Automated tests", [
  code("PS", [".venv\\Scripts\\python -m unittest tests.test_roles tests.test_safety -v"]),
  out(["test_bot_reader_reads_the_compat_views_but_is_denied_writes ... ok", "test_commands_that_write_sqlite_refuse_the_real_database ... ok", "test_sandbox_experiment_leaves_the_main_working_copy_and_cloud_untouched ... ok", "Ran 6 tests in 34.9s", "OK"]),
  note("NOTE", [
    "The full suite is `.venv\\Scripts\\python -m unittest discover -s tests -t .` (59 tests, about 5 minutes). On Day 6 it gave 56 passes and 3 errors, all `AttributeError: module 'utils' has no attribute 'vix_fetcher'`, caused by changes in the bot's repository on 10 and 11 Nov. That is an open item in `docs/logbook/day-06.md`. If the guide asks for the full suite, say this before running it.",
    "Each test builds its own temporary SQLite (with the bot's own `create_tables`) and its own throwaway Postgres database, so tests never touch our data.",
  ]),
]));

// 6. Cleanup
C.push(H1("6. After the check: clean up"));
C.push(N("Close the PG and LITE shells: `\\q` and `.quit`.", "numClean"));
C.push(N("Drop the sandbox (both the SQLite copy and the Postgres clone).", "numClean"));
C.push(code("PS", [".venv\\Scripts\\python -m cloudsync sandbox drop viva --from-dsn \"postgresql://postgres:postgres@localhost:5433/algotrade\""]));
C.push(out(["{ \"dropped\": \"viva\", \"pg_database\": \"algotrade_sbx_viva\" }"]));
C.push(N("Show that the bot's real database was never written (this only reads the file).", "numClean"));
C.push(code("PS", ["(Get-FileHash C:\\Users\\aryan\\Desktop\\AlgoTrade\\db\\trading_bot.db -Algorithm SHA256).Hash.ToLower()", "Get-Content artifacts\\day6\\real_db_sha256.txt"]));
C.push(out(["The two hashes start with the same characters (a5b0a381... on 17 Nov)."]));
C.push(note("NOTE", "The Day-2 reference (`artifacts\\day2\\rebuild\\real_db_sha256.txt`, cf66a201...) no longer matches because the bot's database was rewritten outside this project on 11 Nov 2026 (see `docs/logbook/day-06.md`, section 4.2). Compare with the Day-6 hash, and be ready to explain why."));

// 7. Troubleshooting
C.push(H1("7. Troubleshooting"));
C.push(table(["Symptom", "Cause", "Fix"], [
  ["`error during connect` / cannot reach Docker", "Docker Desktop not running", "Start Docker Desktop, then `docker compose up -d`"],
  ["`sandbox viva already exists`", "Last session did not drop it", "Run the drop command in section 6, then create again"],
  ["`source database \"algotrade\" is being accessed by other users`", "A psql window or the sync daemon is connected to `algotrade`", "Close it (`\\q`) or stop the daemon, then retry"],
  ["`permission denied` on a normal query", "Still inside `SET ROLE`", "`RESET ROLE;`"],
  ["`current transaction is aborted, commands ignored`", "An error happened inside BEGIN", "`ROLLBACK;`"],
  ["`column \"timestamp\" does not exist` or syntax error near timestamp", "Missing double quotes", "Write `\"timestamp\"`"],
  ["Every sync exits with code 75", "`CLOUDSYNC_FAULT` still set", "`Remove-Item Env:CLOUDSYNC_FAULT`"],
  ["`sqlite3` is not recognised", "No sqlite3 on PATH", "Use `.venv\\Scripts\\python -c \"import sqlite3; c=sqlite3.connect(r'data\\sandboxes\\viva\\trading_bot.db'); print(c.execute('SELECT count(*) FROM _changelog').fetchall())\"`"],
  ["`database is locked` in LITE", "Another program holds a write transaction", "Finish or close it; WAL mode allows readers, but only one writer at a time"],
  ["A sync or reconcile goes to AWS (slow, asks for network)", "`--dsn` was left out, so `PG_DSN` (RDS) was used", "Always pass `--dsn $DSN`; check `$DSN` is set in this window"],
  ["Numbers differ slightly from this document", "Main working copy changed since 17 Nov", "Fine: constraint names, plan shapes and PASS/FAIL are what count"],
], [3000, 3000, 3638]));

// 8. Quick reference
C.push(H1("8. One-page quick reference"));
C.push(table(["#", "Guide asks", "Where", "Type this"], [
  ["A1", "Show your schema", "PG", "`\\dn`, `\\dt public.*`, `\\d candles`, `SELECT * FROM schema_version;`"],
  ["B1", "Insert invalid data", "PG", "`INSERT INTO candles (...) VALUES (1,'1m',now(),-1,100,90,110,100);`"],
  ["B3", "Show a foreign key", "PG", "insert with `instrument_id = 99`; `DELETE FROM instruments WHERE symbol='NIFTY50';`"],
  ["C1", "Show a rollback", "PG", "`BEGIN; DELETE ...; SELECT count(*) ...; ROLLBACK;`"],
  ["C2", "Show atomicity", "PG", "two inserts, second breaks a CHECK, then `COMMIT;`"],
  ["D1", "Show a join", "PG", "`candles JOIN instruments` grouped by symbol, timeframe"],
  ["E2", "Window function", "PG", "`avg(close) OVER (ORDER BY ts ROWS BETWEEN 4 PRECEDING AND CURRENT ROW)`"],
  ["F1", "Show access control", "PG", "`SET ROLE bot_reader; SELECT count(*) FROM candles; RESET ROLE;`"],
  ["G1", "Show a trigger", "PG", "update trade id 1 as sync_writer, read `audit.audit_log`"],
  ["H1", "Index benefit", "PG", "`EXPLAIN ANALYZE` the latest-candles query, `DROP INDEX` in a transaction, repeat, `ROLLBACK`"],
  ["I1", "MVCC / VACUUM", "PG", "`xmin, ctid` before/after update; `VACUUM (VERBOSE)`"],
  ["K1", "SQLite internals", "LITE", "`PRAGMA journal_mode; PRAGMA page_count; PRAGMA freelist_count;`"],
  ["K2", "Your triggers", "LITE", "`SELECT name FROM sqlite_master WHERE type='trigger';`"],
  ["L1", "Sync a change", "LITE, PS, PG", "UPDATE in LITE, `cloudsync sync once --sqlite $DB --dsn $DSN`, SELECT in PG"],
  ["N1", "Crash safety", "PS", "`$env:CLOUDSYNC_FAULT=\"mid_batch:1\"`, sync (exit 75), remove it, sync again"],
  ["O1", "Prove it matches", "PS", "`cloudsync reconcile --sqlite $DB --dsn $DSN --levels 1,2 --out ...`"],
  ["P1", "WAL benefit", "PS", "`cloudsync bench-wal --sqlite $DB --out ... --seconds 3`"],
  ["Q1", "Run your tests", "PS", "`python -m unittest tests.test_roles tests.test_safety -v`"],
], [600, 2000, 1300, 5738]));

// ---------- document ----------
const doc = new Document({
  creator: "cloudsync team",
  title: "cloudsync Live Verification Guide",
  styles: {
    default: { document: { run: { font: FONT, size: 21 } } },
    paragraphStyles: [
      { id: "Heading1", name: "Heading 1", basedOn: "Normal", next: "Normal", quickFormat: true, run: { font: FONT, size: 34, bold: true, color: "1F4E79" }, paragraph: { spacing: { before: 240, after: 160 }, keepNext: true, outlineLevel: 0 } },
      { id: "Heading2", name: "Heading 2", basedOn: "Normal", next: "Normal", quickFormat: true, run: { font: FONT, size: 27, bold: true, color: "2E75B6" }, paragraph: { spacing: { before: 280, after: 120 }, keepNext: true, outlineLevel: 1 } },
      { id: "Heading3", name: "Heading 3", basedOn: "Normal", next: "Normal", quickFormat: true, run: { font: FONT, size: 23, bold: true, color: "404040" }, paragraph: { spacing: { before: 220, after: 100 }, keepNext: true, outlineLevel: 2 } },
    ],
  },
  numbering: {
    config: [
      { reference: "bul", levels: [{ level: 0, format: LevelFormat.BULLET, text: "\u2022", alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 500, hanging: 260 } } } }, { level: 1, format: LevelFormat.BULLET, text: "\u25E6", alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 1000, hanging: 260 } } } }] },
      ...["num", "numL1", "numN1", "numClean"].map((r) => ({ reference: r, levels: [{ level: 0, format: LevelFormat.DECIMAL, text: "%1.", alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 500, hanging: 300 } } } }] })),
    ],
  },
  sections: [{
    properties: { page: { size: { width: 11906, height: 16838 }, margin: { top: 1134, bottom: 1134, left: 1134, right: 1134 } } },
    headers: { default: new Header({ children: [new Paragraph({ alignment: AlignmentType.RIGHT, children: [new TextRun({ text: "cloudsync: live verification guide", size: 16, color: "808080" })] })] }) },
    footers: { default: new Footer({ children: [new Paragraph({ alignment: AlignmentType.CENTER, children: [new TextRun({ text: "Page ", size: 16, color: "808080" }), new TextRun({ children: [PageNumber.CURRENT], size: 16, color: "808080" })] })] }) },
    children: C,
  }],
});

Packer.toBuffer(doc).then((buf) => { fs.writeFileSync(process.argv[2], buf); console.log("wrote", process.argv[2]); });
