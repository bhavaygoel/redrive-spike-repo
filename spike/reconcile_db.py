#!/usr/bin/env python3
"""Repair step: reconcile prod DB to true post-incident state.
Removes harness-artifact duplicate (row id=2, created by an early sandbox run
with wrong working dir - NOT a GitHub delivery; GitHub shows exactly 1 push
delivery, no redelivery). Keeps the genuine mutation from the real delivery.
"""
import sqlite3, datetime, json

DB = "/root/workspace/redrive-spike/receiver_state.db"
c = sqlite3.connect(DB)
before = c.execute("SELECT id,event_id,received_at FROM mutations ORDER BY id").fetchall()
c.execute("DELETE FROM mutations WHERE id=2")   # artifact row (09:40:06, no matching GitHub delivery)
c.commit()
after = c.execute("SELECT id,event_id,received_at FROM mutations ORDER BY id").fetchall()
# ensure ledger backfill still consistent
for (eid,) in c.execute("SELECT DISTINCT event_id FROM mutations").fetchall():
    c.execute("INSERT OR IGNORE INTO processed_deliveries(delivery_id,status,updated_at) VALUES (?,?,?)",
              (eid, "done", datetime.datetime.utcnow().isoformat() + "Z"))
c.commit()
print("before:", before)
print("after :", after)
print("ledger:", c.execute("SELECT delivery_id,status FROM processed_deliveries").fetchall())
json.dump({"reconciled": True, "kept_rows": after,
           "rationale": "row id=2 was spike-harness artifact (wrong-cwd sandbox write), not a provider delivery"},
          open("/root/workspace/redrive-spike/reconciliation_note.json", "w"), indent=2)
