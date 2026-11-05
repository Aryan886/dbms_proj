# Project instructions for agents

Spec: [SPEC.md](SPEC.md). Work test-first in vertical slices (one failing test, then minimal code).
Tests run end-to-end through the `cloudsync` CLI against real SQLite and the Docker Postgres
(`docker compose up -d`, port 5433). Run them with `.venv/Scripts/python -m unittest discover -s tests -t .`

## Logbook (required)

The team presents `docs/logbook/` to the examiner, so keep it current as part of the work,
not as an afterthought:

- Each working day has its own file, `docs/logbook/day-NN.md`, created from
  `docs/logbook/_template.md`. Fill every section; write "none" rather than deleting one.
- While working, record each slice, decision, challenge (symptom → root cause → fix → how it
  was verified) and limitation in that day's file.
- Before ending a session, update the index and the decision register in
  `docs/logbook/README.md`, and carry open items forward.
- Only put numbers in the log that came from a real run, and name the artifact they came from.
- Mark each decision's owner: **Team** (the project owner chose), **Agent** (a default the
  agent picked) or **Spec**.
