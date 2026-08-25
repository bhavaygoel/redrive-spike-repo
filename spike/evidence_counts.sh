#!/usr/bin/env bash
# Numeric evidence pass: same protocol as local_e2e.sh but counts via python sqlite3 module.
set -uo pipefail
cd /root/workspace/redrive-spike
q() { python3 -c "import sqlite3,sys; c=sqlite3.connect(sys.argv[1]); print(c.execute(sys.argv[2]).fetchone()[0])" "$1" "$2"; }

pkill -f 'receiver_buggy.py' 2>/dev/null; pkill -f 'receiver_fixed.py' 2>/dev/null; sleep 1
rm -f receiver_state.db receiver_state_fixed.db
nohup python3 repo/receiver_buggy.py 8090 > logs/buggy2.log 2>&1 &
nohup python3 repo/receiver_fixed.py 8091 > logs/fixed2.log 2>&1 &
sleep 2

BODY=fixture_body.json; SIG=$(cat fixture_sig.txt)
send () { curl -s -o /tmp/resp_$2.json -w '%{http_code}' -X POST localhost:$1/webhook \
  -H 'Content-Type: application/json' -H 'X-GitHub-Event: push' \
  -H 'X-GitHub-Delivery: SPIKE-LOCAL-REPLAY-001' -H "X-Hub-Signature-256: $SIG" --data-binary @$BODY; }

R1=$(send 8090 b1); M1=$(q receiver_state.db 'SELECT COUNT(*) FROM mutations')
R2=$(send 8090 b2); M2=$(q receiver_state.db 'SELECT COUNT(*) FROM mutations')
echo "BUGGY   attempt1: http=$R1 mutations=$M1 | replay: http=$R2 mutations=$M2"

R3=$(send 8091 f1); L1=$(q receiver_state_fixed.db 'SELECT COUNT(*) FROM processed_deliveries WHERE status='"'"'done'"'"'); K1=$(q receiver_state_fixed.db 'SELECT COUNT(*) FROM mutations')
R4=$(send 8091 f2); L2=$(q receiver_state_fixed.db 'SELECT COUNT(*) FROM processed_deliveries WHERE status='"'"'done'"'"'); K2=$(q receiver_state_fixed.db 'SELECT COUNT(*) FROM mutations')
echo "FIXED   attempt1: http=$R3 ledger_done=$L1 mutation_rows=$K1 | replay: http=$R4 ledger_done=$L2 mutation_rows=$K2"
echo "--- rows ---"
python3 - <<'PY'
import sqlite3
for db,tbl in [('receiver_state.db','mutations'),('receiver_state_fixed.db','processed_deliveries')]:
    c=sqlite3.connect(db)
    print(db, tbl)
    for r in c.execute(f'SELECT * FROM {tbl}'): print('  ', r)
PY
pkill -f 'receiver_buggy.py'; pkill -f 'receiver_fixed.py'
echo EVIDENCE-DONE
