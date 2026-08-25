#!/usr/bin/env python3
"""Extra checks: (1) 10x concurrent replay vs fixed receiver; (2) invalid-signature behavior."""
import base64, concurrent.futures, hashlib, hmac, json, os, signal, sqlite3, subprocess, time, urllib.request

TF = "/root/workspace/redrive-spike"
REPO = f"{TF}/gitpush/repo/spike"
SECRET = open(f"{TF}/webhook_secret.txt").read().strip().encode()
BODY = open(f"{TF}/captured_body.bin", "rb").read()
GUID = "44c70d9c-a06b-11f1-914c-d186f381ed14"

def start(receiver, dbfile, port):
    env = {**os.environ, "REDRIVE_DB": dbfile, "REDRIVE_SECRET": SECRET.decode()}
    p = subprocess.Popen(["/usr/bin/python3", f"{REPO}/{receiver}", str(port)],
                         env=env, cwd="/tmp",
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(30):
        time.sleep(0.4)
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/state", timeout=2)
            return p
        except Exception:
            continue
    raise SystemExit(f"{receiver} not ready")

def post(port, body=BODY, sig="sha256=" + hmac.new(SECRET, BODY, hashlib.sha256).hexdigest()):
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/webhook", data=body, method="POST",
        headers={"Content-Type": "application/json", "X-GitHub-Event": "push",
                 "X-GitHub-Delivery": GUID, "X-Hub-Signature-256": sig})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code
    except Exception:
        return "ERR"  # receiver dropped conn (e.g. sqlite lock under contention)

def counts(dbfile):
    c = sqlite3.connect(dbfile)
    m = c.execute("SELECT count(*) FROM mutations").fetchone()[0]
    try:
        l = c.execute("SELECT count(*) FROM processed_deliveries WHERE status='done'").fetchone()[0]
    except Exception:
        l = None
    return m, l

res = {}

# ---- 1. concurrency: 10 parallel identical replays vs FIXED receiver ----
db1 = "/tmp/conc_state.db"
for s in ("", "-wal", "-shm"):
    try: os.remove(db1 + s)
    except FileNotFoundError: pass
p = start("receiver_fixed.py", db1, 8095)
with concurrent.futures.ThreadPoolExecutor(10) as ex:
    codes = list(ex.map(lambda _: post(8095), range(10)))
p.send_signal(signal.SIGTERM)
m, l = counts(db1)
res["concurrent_fixed"] = {"codes_10x": codes, "mutations": m, "ledger_done": l}
print("CONCURRENT x10 vs fixed -> codes:", codes, "mutations:", m, "ledger_done:", l)

# ---- 2a. invalid signature vs BUGGY receiver (fail-open?) ----
db2 = "/tmp/sig_buggy.db"
for s in ("", "-wal", "-shm"):
    try: os.remove(db2 + s)
    except FileNotFoundError: pass
p = start("receiver_buggy.py", db2, 8096)
code_bad_sig = post(8096, sig="sha256=" + "0"*64)
time.sleep(0.5)
mb, _ = counts(db2)
res["invalid_sig_buggy"] = {"http": code_bad_sig, "mutations": mb}
print("INVALID SIG vs buggy -> http:", code_bad_sig, "mutations:", mb)
p.send_signal(signal.SIGTERM)

# ---- 2b. invalid signature vs FIXED receiver ----
db3 = "/tmp/sig_fixed.db"
for s in ("", "-wal", "-shm"):
    try: os.remove(db3 + s)
    except FileNotFoundError: pass
p = start("receiver_fixed.py", db3, 8097)
code_bad_sig_f = post(8097, sig="sha256=" + "0"*64)
# control: valid sig still processes
code_good = post(8097)
time.sleep(0.5)
mf, lf = counts(db3)
res["invalid_sig_fixed"] = {"http_bad": code_bad_sig_f, "http_valid_control": code_good,
                            "mutations": mf, "ledger_done": lf}
print("INVALID SIG vs fixed -> bad-http:", code_bad_sig_f,
      "| valid-control-http:", code_good, "| mutations:", mf, "(expect 1 if bad sig rejected)")
p.send_signal(signal.SIGTERM)

json.dump(res, open(f"{TF}/tf/evidence_extra.json", "w"), indent=1)
print("evidence -> evidence_extra.json")
