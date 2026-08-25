#!/usr/bin/env python3
"""Gate1: create webhook on redrive-spike-repo -> trigger push -> confirm FAILED delivery."""
import json, os, subprocess, time, urllib.request, urllib.error

BASE = "/root/workspace/redrive-spike"
TOK = open(f"{BASE}/.gh_token").read().strip()
OWNER, REPO = "bhavaygoel", "redrive-spike-repo"
URL = open(f"{BASE}/tunnel_url.txt").read().strip()
SECRET = open(f"{BASE}/webhook_secret.txt").read().strip()

def req(method, path, body=None):
    data = None if body is None else json.dumps(body).encode()
    r = urllib.request.Request("https://api.github.com" + path, data=data, method=method, headers={
        "Authorization": f"Bearer {TOK}", "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28", "Content-Type": "application/json",
        "User-Agent": "redrive-spike"})
    try:
        with urllib.request.urlopen(r, timeout=30) as resp:
            b = resp.read().decode()
            return resp.status, (json.loads(b) if b else {})
    except urllib.error.HTTPError as e:
        b = e.read().decode()
        try: b = json.loads(b)
        except Exception: pass
        return e.code, b

ev = {"repo": f"{OWNER}/{REPO}", "tunnel_url": URL}

# 0) sanity: hook list empty?
s, hooks = req("GET", f"/repos/{OWNER}/{REPO}/hooks")
print("existing hooks:", s, [h.get("id") for h in hooks] if isinstance(hooks, list) else hooks)

# 1) create webhook
s, hook = req("POST", f"/repos/{OWNER}/{REPO}/hooks", {
    "name": "web", "active": True, "events": ["push"],
    "config": {"url": URL.rstrip("/") + "/webhook", "content_type": "json",
               "insecure_ssl": "0", "secret": SECRET}})
print("create hook:", s)
if s != 201:
    raise SystemExit(f"hook create failed: {hook}")
HOOK_ID = hook["id"]
ev["hook_id"] = HOOK_ID
ev["hook_url"] = hook["config"]["url"]
ev["hook_created_at"] = hook["created_at"]
ev["ping_event"] = hook.get("ping_url")
print("hook_id:", HOOK_ID, "->", ev["hook_url"])
open(f"{BASE}/hook_id.txt", "w").write(str(HOOK_ID))
time.sleep(4)

# 2) trigger REAL push (empty commit; business event semantics documented in incident.md)
work = f"{BASE}/gitpush/repo"
p = subprocess.run(["git", "-C", work, "commit", "--allow-empty", "-m",
                    "spike trigger: order payment business event"], capture_output=True, text=True)
print("commit rc:", p.returncode, ((p.stdout or "") + (p.stderr or "")).strip()[:100])
p = subprocess.run(["git", "-C", work, "push"], capture_output=True, text=True)
print("push rc:", p.returncode, ((p.stdout or "") + (p.stderr or "")).strip()[:160])
ev["trigger_commit"] = subprocess.run(["git", "-C", work, "rev-parse", "HEAD"],
                                      capture_output=True, text=True).stdout.strip()

# 3) wait for delivery, then inspect
deadline = time.time() + 60
dels = []
while time.time() < deadline:
    time.sleep(5)
    s, dels = req("GET", f"/repos/{OWNER}/{REPO}/hooks/{HOOK_ID}/deliveries?per_page=20")
    if isinstance(dels, list):
        print("deliveries seen:", [(d.get("id"), d.get("event"), d.get("status_code"), d.get("status")) for d in dels])
        if any(d.get("event") == "push" for d in dels):
            break
    else:
        print("deliveries poll:", s, str(dels)[:200]); break

ev["deliveries"] = [{k: d.get(k) for k in ("id","guid","event","status","status_code","action","delivered_at","redelivery")} for d in dels]
push_dels = [d for d in dels if d.get("event") == "push"]
if not push_dels:
    raise SystemExit("no push delivery observed")
failed = [d for d in push_dels if (d.get("status_code") or 0) >= 500 or d.get("status") != "ok"]
target = failed[0] if failed else push_dels[0]
ev["gate1_failed_push_delivery"] = {k: target.get(k) for k in ("id","guid","delivered_at","status","status_code")}
print("GATE1 target delivery:", ev["gate1_failed_push_delivery"])

# 4) local receiver state at this moment (business mutation already happened!)
import sqlite3
c1 = sqlite3.connect(f"{BASE}/receiver_state.db").execute("SELECT COUNT(*) FROM mutations").fetchone()[0]
rows = sqlite3.connect(f"{BASE}/receiver_state.db").execute("SELECT id,event_id,order_ref FROM mutations").fetchall()
ev["receiver_mutations_after_real_delivery"] = {"count": c1, "rows": rows}
print("receiver mutations after REAL delivery:", c1, rows)

json.dump(ev, open(f"{BASE}/gate12_evidence.json", "w"), indent=2)
print("EVIDENCE SAVED")
