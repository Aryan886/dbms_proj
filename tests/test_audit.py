"""End-to-end: changes to trading records reaching the cloud are audited (spec story 44).

The bot (or the dashboard) changes strategy state and trade history in SQLite,
`sync once` runs as `sync_writer`, and `audit_log` shows who changed what and
when, with the old and new rows as JSON. The sync re-applies rows it has seen
before, so an upsert that changes nothing must not leave an audit entry.
"""
import sqlite3
import unittest
from datetime import datetime

import psycopg

from tests.support import pg_rows, run_cli, sqlite_rows
from tests.test_roles import as_role
from tests.test_sync import SyncTestBase


class AuditTriggerTest(SyncTestBase):
    def audit_since(self, after_id):
        return pg_rows(self.dsn, """SELECT table_name, op, actor, old_row, new_row FROM audit.audit_log
                                    WHERE audit_id > %s ORDER BY table_name, op""", (after_id,))

    def test_synced_trade_and_strategy_changes_are_audited_with_old_and_new_rows(self):
        mark = pg_rows(self.dsn, "SELECT coalesce(max(audit_id), 0) FROM audit.audit_log")[0][0]
        first, last = sqlite_rows(self.sqlite, "SELECT min(id), max(id) FROM dashboard_trade_history")[0]

        from server.dashboard_store import DashboardStore
        DashboardStore(str(self.sqlite)).set_strategy_status("nifty-options", running=False,
                                                              now=datetime(2026, 3, 27, 15, 20))
        conn = sqlite3.connect(self.sqlite)
        conn.execute("UPDATE dashboard_trade_history SET exit_reason = 'manual close' WHERE id = ?", (first,))
        conn.execute("DELETE FROM dashboard_trade_history WHERE id = ?", (last,))
        conn.execute("UPDATE dashboard_trade_history SET qty = qty WHERE id = ?", (first + 1,))  # no real change
        conn.commit()
        conn.close()

        run_cli("sync", "once", "--sqlite", self.sqlite, "--dsn", as_role(self.dsn, "sync_writer"))

        rows = self.audit_since(mark)
        self.assertEqual([r[:3] for r in rows], [
            ("dashboard_strategy_state", "UPDATE", "sync_writer"),
            ("dashboard_trade_history", "DELETE", "sync_writer"),
            ("dashboard_trade_history", "UPDATE", "sync_writer"),
        ])
        state, deleted, updated = rows
        self.assertEqual((state[3]["status"], state[4]["status"]), ("RUNNING", "STOPPED"))
        self.assertEqual((deleted[3]["id"], deleted[4]), (last, None))
        self.assertEqual((updated[3]["id"], updated[4]["id"]), (first, first))
        self.assertNotEqual(updated[3]["exit_reason"], "manual close")
        self.assertEqual(updated[4]["exit_reason"], "manual close")

    def test_sync_writer_cannot_rewrite_the_audit_trail(self):
        writer = as_role(self.dsn, "sync_writer")
        for query in ("DELETE FROM audit.audit_log", "UPDATE audit.audit_log SET actor = 'nobody'"):
            with psycopg.connect(writer) as conn:
                with self.assertRaises(psycopg.errors.InsufficientPrivilege, msg=query):
                    conn.execute(query)


if __name__ == "__main__":
    unittest.main()
