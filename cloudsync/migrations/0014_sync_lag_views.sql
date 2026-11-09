-- Pipeline health (spec story 50): changelog backlog, last applied sequence
-- number, apply latency per batch and rejected rows over time.
--
-- The changelog lives in SQLite, so Postgres can't count it. The sync records
-- it instead: backlog_after is the number of changelog entries of the active
-- tables still waiting after this batch, read in the same SQLite snapshot as
-- the batch and committed with it. NULL for batches synced before this column.

ALTER TABLE sync_batches ADD COLUMN backlog_after integer CHECK (backlog_after >= 0);

CREATE VIEW analytics.sync_batch_log AS
SELECT batch_id, first_seq, last_seq, entries, upserts, deletes, rejected, tables,
       started_at, committed_at, latency_ms, max_lag_ms, backlog_after
FROM public.sync_batches;

CREATE VIEW analytics.sync_table_state AS
SELECT f.source_table,
       coalesce(s.last_seq, 0)  AS last_seq,
       s.updated_at             AS last_applied_at,
       f.status,
       coalesce(r.rejected, 0)  AS rejected_rows
FROM public.schema_fingerprints f
LEFT JOIN public.sync_state s ON s.source_table = f.source_table
LEFT JOIN (SELECT source_table, count(*) AS rejected FROM public.rejected_rows GROUP BY source_table) r
       ON r.source_table = f.source_table;

CREATE VIEW analytics.rejected_rows_by_day AS
SELECT source_table, (rejected_at AT TIME ZONE 'Asia/Kolkata')::date AS day, violated_constraint,
       count(*) AS rejected
FROM public.rejected_rows
GROUP BY source_table, day, violated_constraint;

CREATE VIEW analytics.sync_lag_by_hour AS
SELECT date_trunc('hour', committed_at AT TIME ZONE 'Asia/Kolkata')  AS hour,
       count(*)                                                     AS batches,
       sum(entries)                                                 AS entries,
       sum(upserts)                                                 AS upserts,
       sum(deletes)                                                 AS deletes,
       sum(rejected)                                                AS rejected,
       percentile_cont(0.5)  WITHIN GROUP (ORDER BY latency_ms)     AS latency_p50_ms,
       percentile_cont(0.95) WITHIN GROUP (ORDER BY latency_ms)     AS latency_p95_ms,
       max(latency_ms)                                              AS latency_max_ms,
       max(max_lag_ms)                                              AS lag_max_ms,
       (array_agg(backlog_after ORDER BY batch_id DESC))[1]         AS backlog_at_end
FROM public.sync_batches
GROUP BY 1;
