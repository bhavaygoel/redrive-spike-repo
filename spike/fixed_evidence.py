#!/usr/bin/env python3
"""Fixed-receiver replay-safety evidence (Gate 4c/4d) with hard numbers."""
import subprocess, sqlite3, time, json, urllib.request

def http_post(port, body, sig):
    req = urllib.request.Request(f"http://localhost:{port}/webhook", data=body, headers={
        "Content-Type": "application/json", "X-GitHub-Event": "push",
        "X-GitHub-Delivery": "SPIKE-LOCAL-REPLAY-001", "X-Hub-Signature-256": sig})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, r.read().decode()[:160]
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()[:160]

def count(db, sql):
    return sqlite3.connect(db).execute(sql).fetchone()[0]

body = open("/root/workspace/redrive-spike/fixture_body.json", "rb").read()
sig = open("/root/workspace/redrive-spike/fixture_sig.txt").read().strip()

s1, b1 = http_post(8091, body, sig)
time.sleep(0.3)
ld1 = count("/root/workspace/redrive-spike/receiver_state_fixed.db", "SELECT COUNT(*) FROM processed_deliveries WHERE status='done'")
km1 = count("/root/workspace/redrive-spike/receiver_state_fixed.db", "SELECT COUNT(*) FROM mutations")
s2, b2 = http_post(8091, body, sig)
time.sleep(0.3)
ld2 = count("/root/workspace/redrive-spike/receiver_state_fixed.db", "SELECT COUNT(*) FROM processed_deliveries WHERE status='done'")
km2 = count("/root/workspace/redrive-spike/receiver_state_fixed.db", "SELECT COUNT(*) FROM mutations")
rows = sqlite3.connect("/root/workspace/redrive-spike/receiver_state_fixed.db").execute("SELECT delivery_id,status FROM processed_deliveries").fetchall()
muts = sqlite3.connect("/root/workspace/redrive-spike/receiver_state_fixed.db").execute("SELECT event_id,kind FROM mutations").fetchall()

print("FIXED attempt#1:", s1, b1)
print(f"FIXED after attempt#1: ledger_done={ld1} mutation_rows={km1}")
print("FIXED replay   :", s2, b2)
print(f"FIXED after replay   : ledger_done={ld2} mutation_rows={km2}")
print("ledger rows:", rows)
print("mutation rows:", muts)
assert (s1, ld1, km1) == (200, 1, 1), "first-attempt invariant broken"
assert (s2, ld2, km2) == (200, 1, 1), "replay invariant broken: duplicate or wrong status"
print("GATE4 FIXED-RECEIVER INVARIANT: PASS (mutation exactly once across redelivery)")
