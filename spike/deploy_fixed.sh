#!/usr/bin/env bash
# Deploy FIXED receiver into production position (:8090, behind live tunnel)
# with ledger backfill from historical business mutations (repair step).
set -uo pipefail
cd /root/workspace/redrive-spike
pkill -f 'repo/receiver_buggy.py' 2>/dev/null; pkill -f 'receiver_buggy.py' 2>/dev/null
sleep 1
python3 - <<'PY'
import sqlite3, datetime
db='/root/workspace/redrive-spike/receiver_state.db'
c=sqlite3.connect(db)
c.execute("""CREATE TABLE IF NOT EXISTS processed_deliveries(
    delivery_id TEXT PRIMARY KEY,
    status TEXT NOT NULL CHECK(status IN ('processing','done')),
    updated_at TEXT NOT NULL)""")
# backfill ledger from historical side effects (repair/migration step)
for (eid,) in c.execute("SELECT DISTINCT event_id FROM mutations").fetchall():
    c.execute("INSERT OR IGNORE INTO processed_deliveries(delivery_id,status,updated_at) VALUES (?,?,?)",
              (eid,'done',datetime.datetime.utcnow().isoformat()+'Z'))
c.commit()
print('mutations:', c.execute('SELECT COUNT(*) FROM mutations').fetchone()[0])
print('ledger:', c.execute('SELECT delivery_id,status FROM processed_deliveries').fetchall())
PY
export REDRIVE_SECRET=$(cat webhook_secret.txt)
export REDRIVE_DB=/root/workspace/redrive-spike/receiver_state.db
echo "$REDRIVE_DB" > prod_db_path.txt
