# DBMS Concepts & Learning Guide: CloudSync Project

A study and reference guide breaking down the database systems concepts used in the CDC (Change Data Capture) and replication engine, along with key topics to study independently.

---

## 1. Core DBMS Concepts Used in the Project

### A. Write-Ahead Logging (WAL) vs. Rollback Journals
* **Rollback Journal (`DELETE` mode):**
  * When writing, SQLite acquires an exclusive file lock (`EXCLUSIVE`), preventing any readers from accessing the database.
  * Readers holding a `SHARED` lock prevent writers from committing, leading to high write latencies and lock timeouts (`database is locked`).
* **Write-Ahead Log (`WAL` mode):**
  * Readers read from a snapshot (the base file plus WAL frames), while writers append new transactions to the end of the `-wal` file.
  * Concurrency benefit: readers do not block writers, and writers do not block readers. Write latency drops dramatically (from ~1,200 ms down to ~1 ms).

---

### B. Change Data Capture (CDC) via Triggers
* **Trigger Mechanics:**
  * Uses `AFTER INSERT`, `AFTER UPDATE`, and `AFTER DELETE` triggers on tracked tables to populate an internal changelog table (`_changelog`).
* **Lightweight Changelog Design:**
  * Stores row pointers `(table, pk, op, seq)` rather than full row snapshots.
  * Full row data is fetched at sync time, keeping storage overhead low and naturally compacting repeated updates.
* **Trigger Gotchas:**
  * In SQLite, `INSERT OR REPLACE` deletes conflicting rows without firing standard `DELETE` triggers unless `PRAGMA recursive_triggers` is active. The engine relies on the subsequent `INSERT` trigger with the same primary key to reconcile the row.

---

### C. Concurrency Control & ACID Guarantees
* **Snapshot Isolation on Read:**
  * Changelog entries and source table rows are read within a single SQLite read transaction to guarantee a point-in-time snapshot that never blocks writer processes.
* **Atomic Multi-Operation Commits:**
  * Deletes, upserts, cursor advances (`sync_state.last_seq`), and batch audit logs (`sync_batches`) are bundled into a **single Postgres transaction**. Either the entire batch syncs or none of it does.
* **Crash Recovery & Exactly-Once Semantics:**
  * **Mid-Batch Failure:** If the process dies before commit, Postgres rolls back completely; the SQLite cursor remains uncommitted and replays cleanly.
  * **Post-Commit Failure:** If the process dies after commit but before SQLite changelog pruning, the next run recognizes previously acknowledged entries via `sync_state` and prunes them safely.
* **Sequence Monotonicity (`AUTOINCREMENT`):**
  * `_changelog.seq` uses `INTEGER PRIMARY KEY AUTOINCREMENT`. Without `AUTOINCREMENT`, pruning the table completely would reset row IDs to 1, causing new changes to sort below `last_seq` and be skipped.

---

### D. Idempotency, Compaction & Upserts
* **Operation Compaction:**
  * Within a batch, multiple updates to the same `(table, pk)` collapse into the row's latest state. Multiple updates turn into one upsert; a deleted row turns into a single delete.
* **Upsert Strategies (`ON CONFLICT`):**
  * Postgres `INSERT ... ON CONFLICT (id) DO UPDATE` is used for primary-key-based tables.
  * Tables identified by natural keys (e.g., market candles) employ a **delete-before-reapply** pattern to avoid stale natural key collisions when source IDs shift.

---

### E. Schema Evolution & Drift Detection
* **Catalog Introspection:**
  * Live table column definitions are read using SQLite's `PRAGMA table_info` and hashed into a schema fingerprint.
* **Circuit Breaker on Drift:**
  * Before syncing a batch, the engine checks the table's live fingerprint against stored schema fingerprints in Postgres.
  * If a column is added or altered, **only that specific table is paused**, allowing other tables to continue syncing without corrupting target schemas. Resuming requires an explicit migration.

---

### F. Performance & Database Maintenance
* **Pipelined Execution vs. Savepoints:**
  * Executing bulk deletes via `executemany` reduced batch latency from ~3 s down to ~160 ms per 1,000 changes by eliminating individual round-trips and savepoint overheads.
* **Compaction and Cloning:**
  * Database size reduction and space reclamation via `VACUUM`.
  * Fast test isolation using Postgres template databases (`CREATE DATABASE ... TEMPLATE`) for throwaway sandbox environments.

---

## 2. Self-Study Syllabus & Checklist for Teammates

### Module 1: SQLite Internals & Storage Engines
- [ ] Read the SQLite documentation on [WAL mode](https://sqlite.org/wal.html):
  - How `-wal` (write-ahead log) and `-shm` (shared memory index) files work.
  - Checkpointing mechanisms (`PASSIVE`, `FULL`, `RESTART`, `TRUNCATE`).
- [ ] Understand SQLite locking states:
  - `UNLOCKED` → `SHARED` → `RESERVED` → `PENDING` → `EXCLUSIVE`.
  - How `busy_timeout` works when waiting for lock acquisition.
- [ ] SQLite Triggers & Row IDs:
  - Difference between `INTEGER PRIMARY KEY` (rowid alias) and `AUTOINCREMENT` (monotonically increasing via `sqlite_sequence`).
  - Trigger evaluation lifecycle (`BEFORE`, `AFTER`, `INSTEAD OF`) and recursion limits.

### Module 2: Transaction Isolation & Relational Guarantees
- [ ] Standard SQL Isolation Levels:
  - `READ UNCOMMITTED`, `READ COMMITTED`, `REPEATABLE READ`, `SERIALIZABLE`.
  - Read anomalies: Dirty Reads, Non-Repeatable Reads, Phantom Reads, and Write Skew.
- [ ] PostgreSQL Locking & Atomicity:
  - Table vs. row-level locks (`SELECT ... FOR UPDATE`, `FOR SHARE`).
  - Explicit advisory locks (`pg_try_advisory_lock`) for process-level mutual exclusion.
  - Multi-operation atomicity within single `BEGIN ... COMMIT` blocks.

### Module 3: Change Data Capture (CDC) & Distributed Replication
- [ ] CDC Architecture Patterns:
  - **Trigger-based CDC** (what we used): Pros (database-agnostic, easy DDL tracking) vs. Cons (write amplification on source tables).
  - **Log-based CDC**: Reading database binary logs/WALs directly (e.g., Debezium, Postgres Logical Replication Slots).
- [ ] Streaming Semantics:
  - *At-least-once* vs. *At-most-once* vs. *Effectively exactly-once* delivery.
  - Designing idempotent write sinks (using upserts and primary/natural key deduplication).

### Module 4: Schema Migration & Data Pipeline Reliability
- [ ] Schema Drift & Evolution:
  - Forward and backward compatibility rules for data pipelines.
  - System catalog querying in PostgreSQL (`information_schema.columns`, `pg_catalog`) and SQLite (`PRAGMA table_info`).
- [ ] Robust Network & Ingestion Loops:
  - Implementing exponential back-off with jitter for target database disconnects.
  - Fault injection testing (simulating hard process crashes via `os._exit` / `kill -9` at specific boundaries).