#!/usr/bin/env python3
"""
Gates 3+4 (sandbox role): reproduce the captured REAL GitHub delivery in two
isolated sandboxes (fresh dir + disposable SQLite each), buggy vs fixed.

Fidelity: payload = byte-exact captured wire bytes (HMAC-verified against
GitHub's stored signature); headers = same event/delivery/signature values;
transport = local loopback HTTP instead of GitHub->tunnel edge.
"""
import json, os, shutil, signal, sqlite3, subprocess, sys, time, urllib.request

BASE = "/root/workspace/redrive-spike"
SB = f"{BASE}/sandbox_run"
SECRET = open(f"{BASE}/webhook_secret.txt").read().strip()
g2 = json.load(open(f"{BASE}/gate2_evidence.json"))
body = open(f"{BASE}/captured_body.bin", "rb").read()
sig = open(f"{BASE}/recomputed_sig.txt").read().strip()
GUID, EVENT = g2["guid"], g2["event"]
assert len(body) == g2["byte_exactness"]["fixture_bytes"]

def post(port):
    r = urllib.request.Request(f"http://localhost:{port}/webhook", data=body, headers={
        "Content-Type": "application/json", "X-GitHub-Event": EVENT,
        "X-GitHub-Delivery": GUID, "X-Hub-Signature-256": sig})
    try:
        with urllib.request.urlopen(r, timeout=10) as resp:
            return resp.status, resp.read().decode()[:140]
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()[:140]

def q(db, sql):
    return sqlite3.connect(db).execute(sql).fetchone()[0]

results = {}
for variant in ("buggy", "fixed"):
    shutil.rmtree(SB, ignore_errors=True)
    os.makedirs(SB)
    shutil.copy(f"{BASE}/repo/receiver_{variant}.py", f"{SB}/receiver.py")  # 'clone + checkout'
    dbfile = f"{SB}/state.db"                                             # disposable DB
    port = {"buggy": 8092, "fixed": 8093}[variant]
    log = open(f"{BASE}/logs/sandbox_{variant}.log", "w")
    p = subprocess.Popen([sys.executable, f"{SB}/receiver.py", str(port)],
                         stdout=log, stderr=log, cwd=SB)
    time.sleep(1.5)
    try:
        s1, b1 = post(port); time.sleep(0.4)
        c1 = q(dbfile, "SELECT COUNT(*) FROM mutations")
        s2, b2 = post(port); time.sleep(0.4)
        c2 = q(dbfile, "SELECT COUNT(*) FROM mutations")
        extra = ""
        if variant == "fixed":
            l1 = q(dbfile, "SELECT COUNT(*) FROM processed_deliveries WHERE status='done'")
            extra = f" ledger_done={l1}"
        print(f"[{variant}] attempt1 http={s1} mutations={c1} | replay http={s2} mutations={c2}{extra}")
        print(f"   attempt1 body: {b1[:110]}")
        print(f"   replay   body: {b2[:110]}")
        results[variant] = {"attempt1_http": s1, "attempt1_mutations": c1,
                            "replay_http": s2, "replay_mutations": c2}
    finally:
        p.terminate(); time.sleep(0.3)
shutil.rmtree(SB, ignore_errors=True)

json.dump({"captured_delivery": {"guid": GUID, "event": EVENT, "bytes": len(body),
                                 "signature_verified_fixture": True},
           "results": results},
          open(f"{BASE}/gate34_evidence.json", "w"), indent=2)

ok = (results["buggy"]["attempt1_http"], results["buggy"]["attempt1_mutations"],
      results["buggy"]["replay_mutations"]) == (500, 1, 2) and \
     (results["fixed"]["attempt1_http"], results["fixed"]["replay_http"]) == (200, 200) and \
     (results["fixed"]["attempt1_mutations"], results["fixed"]["replay_mutations"]) == (1, 1)
print("\nGATE3+4 SANDBOX VERDICT:", "PASS" if ok else "FAIL")
