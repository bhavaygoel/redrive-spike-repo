#!/usr/bin/env bash
# Redrive spike — local end-to-end rehearsal (Gates 3+4 in "sandbox" role).
# Proves: buggy receiver double-mutates on replay; fixed receiver is a safe
# no-op on replay; invariant measured from the DB, not asserted.
set -uo pipefail
cd /root/workspace/redrive-spike

echo "== [0] secret + fixture (HMAC-signed, GitHub-compatible shape) =="
python3 - <<'PY'
import os, json, hashlib, hmac, datetime
sec_path='/root/workspace/redrive-spike/webhook_secret.txt'
if not os.path.exists(sec_path):
    open(sec_path,'w').write(os.urandom(16).hex())
secret=open(sec_path).read().strip()
fixture = {
  "ref": "refs/heads/main",
  "before": "0000000000000000000000000000000000000000",
  "after": "deadbeefcafe1234567890deadbeefcafe12345",
  "repository": {"full_name": "bhavaygoel/redrive-spike-repo"},
  "pusher": {"name": "bhavaygoel"},
  "commits": [{"id": "deadbeefcafe1234567890deadbeefcafe12345",
               "message": "spike: business event (order payment)",
               "timestamp": datetime.datetime.utcnow().isoformat()+"Z"}]
}
body=json.dumps(fixture,separators=(',',':')).encode()
sig='sha256='+hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
open('/root/workspace/redrive-spike/fixture_body.json','wb').write(body)
open('/root/workspace/redrive-spike/fixture_sig.txt','w').write(sig)
print('fixture bytes:',len(body)); print('sig:',sig[:20]+'...')
PY

echo "== [1] cleanup =="
pkill -f 'receiver_buggy.py' 2>/dev/null; pkill -f 'receiver_fixed.py' 2>/dev/null
sleep 1
rm -f /root/workspace/redrive-spike/receiver_state.db /root/workspace/redrive-spike/receiver_state_fixed.db
mkdir -p logs; rm -f logs/*.log

BODY=/root/workspace/redrive-spike/fixture_body.json
SIG=$(cat /root/workspace/redrive-spike/fixture_sig.txt)

replay () {
  curl -s -o /tmp/resp_$2.json -w '%{http_code}' \
    -X POST localhost:$1/webhook \
    -H 'Content-Type: application/json' \
    -H 'X-GitHub-Event: push' \
    -H 'X-GitHub-Delivery: SPIKE-LOCAL-REPLAY-001' \
    -H "X-Hub-Signature-256: $SIG" \
    --data-binary @$BODY
}

echo "== [2] start receivers :8090 buggy / :8091 fixed =="
nohup python3 repo/receiver_buggy.py 8090 > logs/buggy.log 2>&1 &
nohup python3 repo/receiver_fixed.py 8091 > logs/fixed.log 2>&1 &
sleep 2
curl -s localhost:8090/state >/dev/null && echo 'buggy up'
curl -s localhost:8091/state >/dev/null && echo 'fixed up'

echo "== GATE4a: BUGGY first attempt (expect 500, mutation=1) =="
R1=$(replay 8090 b1); C1=$(sqlite3 receiver_state.db 'SELECT COUNT(*) FROM mutations')
echo "buggy attempt#1 http=$R1 mutations=$C1"

echo "== GATE4b: BUGGY replay of SAME delivery (DANGER DEMO) =="
R2=$(replay 8090 b2); C2=$(sqlite3 receiver_state.db 'SELECT COUNT(*) FROM mutations')
echo "buggy replay   http=$R2 mutations=$C2   <-- duplicate side effect if C2=2"

echo "== GATE4c: FIXED first attempt (expect 200, done-ledger=1, mutation rows for delivery=1) =="
R3=$(replay 8091 f1)
FD=$(sqlite3 receiver_state_fixed.db 'SELECT COUNT(*) FROM processed_deliveries WHERE status="done"')
FM=$(sqlite3 receiver_state_fixed.db 'SELECT COUNT(*) FROM mutations')
echo "fixed attempt#1 http=$R3 ledger_done=$FD mutation_rows=$FM"

echo "== GATE4d: FIXED replay of SAME delivery (expect 200 no-op, counts unchanged) =="
R4=$(replay 8091 f2)
FD2=$(sqlite3 receiver_state_fixed.db 'SELECT COUNT(*) FROM processed_deliveries WHERE status="done"')
FM2=$(sqlite3 receiver_state_fixed.db 'SELECT COUNT(*) FROM mutations')
echo "fixed replay   http=$R4 ledger_done=$FD2 mutation_rows=$FM2"

echo "== state evidence =="
echo '--- buggy DB ---'; sqlite3 receiver_state.db 'SELECT id,event_id,kind FROM mutations'
echo '--- fixed DB ledger ---'; sqlite3 receiver_state_fixed.db 'SELECT delivery_id,status FROM processed_deliveries'
echo '--- responses (first attempts + no-op) ---'
echo "b1: $(head -c 200 /tmp/resp_b1.json)"
echo "b2: $(head -c 200 /tmp/resp_b2.json)"
echo "f1: $(head -c 200 /tmp/resp_f1.json)"
echo "f2: $(head -c 200 /tmp/resp_f2.json)"
echo '--- receiver logs tail ---'
tail -6 logs/buggy.log; echo ...; tail -6 logs/fixed.log
pkill -f 'receiver_buggy.py'; pkill -f 'receiver_fixed.py'
echo DONE
