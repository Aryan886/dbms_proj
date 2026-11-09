# Index audit: the bot's query shapes on the compat views

Median execution time of 5 `EXPLAIN (ANALYZE, BUFFERS)` runs, in ms. Each variant's indexes are created in a transaction and rolled back.

| Query | baseline | brin_ts | btree_ts | btree_ist_expr | brin_ist_expr |
|---|---|---|---|---|---|
| latest 200 candles of the last day (fetch_market_data) | 12.271 | 12.229 | 12.351 | 1.693 | 5.814 |
| full-range candles for a backtest (data_provider) | 162.229 | 158.81 | 154.898 | 158.563 | 155.713 |
| latest option snapshot time | 394.474 | 384.624 | 398.159 | 407.54 | 408.863 |
| latest option snapshot rows | 7.87 | 7.884 | 8.165 | 7.848 | 7.956 |
| latest delta snapshot time | 150.215 | 151.051 | 149.381 | 149.883 | 148.927 |
| latest delta snapshot rows (get_current_delta_from_cache) | 175.917 | 170.617 | 168.648 | 0.132 | 3.246 |

## Index sizes

| Variant | Index | Bytes |
|---|---|---|
| brin_ts | audit_candles_brin | 24,576 |
| brin_ts | audit_chain_brin | 24,576 |
| brin_ts | audit_delta_brin | 24,576 |
| btree_ts | audit_candles_ts | 1,384,448 |
| btree_ts | audit_chain_ts | 16,384 |
| btree_ts | audit_delta_ts | 2,678,784 |
| btree_ist_expr | audit_candles_ist | 1,384,448 |
| btree_ist_expr | audit_chain_ist | 16,384 |
| btree_ist_expr | audit_delta_ist | 2,678,784 |
| brin_ist_expr | audit_candles_brin_ist | 24,576 |
| brin_ist_expr | audit_chain_brin_ist | 24,576 |
| brin_ist_expr | audit_delta_brin_ist | 24,576 |

## Plans (scan nodes)

**latest 200 candles of the last day (fetch_market_data)**
- baseline: Index Scan using candle_indicators_pkey on candle_indicators; Seq Scan on candles; Seq Scan on instruments (buffers hit 1663, read 0, rows 200)
- brin_ts: Index Scan using candle_indicators_pkey on candle_indicators; Seq Scan on candles; Seq Scan on instruments (buffers hit 1663, read 0, rows 200)
- btree_ts: Index Scan using candle_indicators_pkey on candle_indicators; Seq Scan on candles; Seq Scan on instruments (buffers hit 1663, read 0, rows 200)
- btree_ist_expr: Index Scan using audit_candles_ist on candles; Index Scan using candle_indicators_pkey on candle_indicators; Index Scan using instruments_symbol_key on instruments (buffers hit 1137, read 0, rows 200)
- brin_ist_expr: Bitmap Heap Scan on candles; Bitmap Index Scan using audit_candles_brin_ist; Index Scan using candle_indicators_pkey on candle_indicators; Index Scan using instruments_pkey on instruments (buffers hit 1282, read 0, rows 200)

**full-range candles for a backtest (data_provider)**
- baseline: Index Scan using candle_indicators_pkey on candle_indicators; Index Scan using instruments_symbol_key on instruments; Seq Scan on candles (buffers hit 98168, read 0, rows 32543)
- brin_ts: Index Scan using candle_indicators_pkey on candle_indicators; Index Scan using instruments_symbol_key on instruments; Seq Scan on candles (buffers hit 98168, read 0, rows 32543)
- btree_ts: Index Scan using candle_indicators_pkey on candle_indicators; Index Scan using instruments_symbol_key on instruments; Seq Scan on candles (buffers hit 98168, read 0, rows 32543)
- btree_ist_expr: Index Scan using candle_indicators_pkey on candle_indicators; Index Scan using instruments_symbol_key on instruments; Seq Scan on candles (buffers hit 98168, read 0, rows 32543)
- brin_ist_expr: Index Scan using candle_indicators_pkey on candle_indicators; Index Scan using instruments_symbol_key on instruments; Seq Scan on candles (buffers hit 98168, read 0, rows 32543)

**latest option snapshot time**
- baseline: Index Only Scan using option_snapshots_pkey on option_snapshots; Index Scan using instruments_symbol_key on instruments; Seq Scan on option_chain_snapshots; Seq Scan on option_contracts (buffers hit 1395377, read 3117, rows 1)
- brin_ts: Index Only Scan using option_snapshots_pkey on option_snapshots; Index Scan using instruments_symbol_key on instruments; Seq Scan on option_chain_snapshots; Seq Scan on option_contracts (buffers hit 1396049, read 2445, rows 1)
- btree_ts: Index Only Scan using option_snapshots_pkey on option_snapshots; Index Scan using instruments_symbol_key on instruments; Seq Scan on option_chain_snapshots; Seq Scan on option_contracts (buffers hit 1396721, read 1773, rows 1)
- btree_ist_expr: Index Only Scan using option_snapshots_pkey on option_snapshots; Index Scan using instruments_symbol_key on instruments; Seq Scan on option_chain_snapshots; Seq Scan on option_contracts (buffers hit 1397361, read 1133, rows 1)
- brin_ist_expr: Index Only Scan using option_snapshots_pkey on option_snapshots; Index Scan using instruments_symbol_key on instruments; Seq Scan on option_chain_snapshots; Seq Scan on option_contracts (buffers hit 1397813, read 681, rows 1)

**latest option snapshot rows**
- baseline: Index Scan using instruments_symbol_key on instruments; Index Scan using option_contracts_pkey on option_contracts; Index Scan using option_snapshots_pkey on option_snapshots; Seq Scan on option_chain_snapshots (buffers hit 8449, read 0, rows 2103)
- brin_ts: Index Scan using instruments_symbol_key on instruments; Index Scan using option_contracts_pkey on option_contracts; Index Scan using option_snapshots_pkey on option_snapshots; Seq Scan on option_chain_snapshots (buffers hit 8449, read 0, rows 2103)
- btree_ts: Index Scan using instruments_symbol_key on instruments; Index Scan using option_contracts_pkey on option_contracts; Index Scan using option_snapshots_pkey on option_snapshots; Seq Scan on option_chain_snapshots (buffers hit 8449, read 0, rows 2103)
- btree_ist_expr: Index Scan using instruments_symbol_key on instruments; Index Scan using option_contracts_pkey on option_contracts; Index Scan using option_snapshots_pkey on option_snapshots; Seq Scan on option_chain_snapshots (buffers hit 8449, read 0, rows 2103)
- brin_ist_expr: Index Scan using instruments_symbol_key on instruments; Index Scan using option_contracts_pkey on option_contracts; Index Scan using option_snapshots_pkey on option_snapshots; Seq Scan on option_chain_snapshots (buffers hit 8449, read 0, rows 2103)

**latest delta snapshot time**
- baseline: Index Only Scan using delta_snapshots_pkey on delta_snapshots; Index Scan using instruments_symbol_key on instruments; Seq Scan on option_contracts (buffers hit 13276, read 2925, rows 1)
- brin_ts: Index Only Scan using delta_snapshots_pkey on delta_snapshots; Index Scan using instruments_symbol_key on instruments; Seq Scan on option_contracts (buffers hit 13980, read 2221, rows 1)
- btree_ts: Index Only Scan using delta_snapshots_pkey on delta_snapshots; Index Scan using instruments_symbol_key on instruments; Seq Scan on option_contracts (buffers hit 14620, read 1581, rows 1)
- btree_ist_expr: Index Only Scan using delta_snapshots_pkey on delta_snapshots; Index Scan using instruments_symbol_key on instruments; Seq Scan on option_contracts (buffers hit 15260, read 941, rows 1)
- brin_ist_expr: Index Only Scan using delta_snapshots_pkey on delta_snapshots; Index Scan using instruments_symbol_key on instruments; Seq Scan on option_contracts (buffers hit 15712, read 489, rows 1)

**latest delta snapshot rows (get_current_delta_from_cache)**
- baseline: Index Scan using delta_snapshots_pkey on delta_snapshots; Index Scan using instruments_symbol_key on instruments; Seq Scan on option_contracts (buffers hit 109443, read 2765, rows 22)
- brin_ts: Index Scan using delta_snapshots_pkey on delta_snapshots; Index Scan using instruments_symbol_key on instruments; Seq Scan on option_contracts (buffers hit 110147, read 2061, rows 22)
- btree_ts: Index Scan using delta_snapshots_pkey on delta_snapshots; Index Scan using instruments_symbol_key on instruments; Seq Scan on option_contracts (buffers hit 110787, read 1421, rows 22)
- btree_ist_expr: Bitmap Heap Scan on option_contracts; Bitmap Index Scan using option_contracts_pkey; Index Scan using audit_delta_ist on delta_snapshots; Index Scan using instruments_pkey on instruments (buffers hit 95, read 0, rows 22)
- brin_ist_expr: Bitmap Heap Scan on delta_snapshots; Bitmap Heap Scan on option_contracts; Bitmap Index Scan using audit_delta_brin_ist; Bitmap Index Scan using option_contracts_pkey; Index Scan using instruments_pkey on instruments (buffers hit 208, read 0, rows 22)
