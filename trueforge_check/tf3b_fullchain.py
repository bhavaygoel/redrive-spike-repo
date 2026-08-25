#!/usr/bin/env python3
"""TF-3b: full chain through TrueForge approval gate with LIVE receiver.
fresh cloudflared tunnel -> repoint hook -> fixed receiver -> gated redelivery -> 200 + exactly-once."""
import json, os, signal, subprocess, time, urllib.request, urllib.error

TF = "/root/workspace/redrive-spike"
HOOK = 670245925
DELIVERY = 3838953010386436096  # the 530 disposable delivery
TOK = open(f"{TF}/.gh_token").read().strip()
GH = f"https://api.github.com/repos/bhavaygoel/redrive-spike-repo/hooks"

def gh_req(path, method="GET", body=None):
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(GH + path, data=data, method=method,
                                 headers={"Authorization": f"Bearer {TOK}",
                                          "Accept": "application/vnd.github+json",
                                          "Content-Type": "application/json",
                                          "User-Agent": "rc"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = r.read().decode()
            return r.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()[:300]

def local_get(url):
    with urllib.request.urlopen(url, timeout=10) as r:
        return r.status, json.loads(r.read().decode())

ev = {}

# 1. fresh disposable DB for the fixed receiver
dbpath = f"{TF}/tf/receiver_state_tf.db"
for suffix in ("", "-wal", "-shm"):
    try: os.remove(dbpath + suffix)
    except FileNotFoundError: pass

# 2. start fixed receiver on :8090 (env-configured db + secret)
secret = open(f"{TF}/webhook_secret.txt").read().strip()
env = {**os.environ, "REDRIVE_DB": dbpath, "REDRIVE_SECRET": secret}
recv = subprocess.Popen(
    ["/usr/bin/python3", f"{TF}/gitpush/repo/spike/receiver_fixed.py"],
    env=env, cwd=f"{TF}/tf",
    stdout=open(f"{TF}/tf/logs/receiver_tf.log", "ab"),
    stderr=subprocess.STDOUT)
for _ in range(30):
    time.sleep(0.5)
    try:
        st, state = local_get("http://127.0.0.1:8091/state")
        break
    except Exception:
        continue
else:
    raise SystemExit("receiver never became ready")
print("receiver up:", st, state)
ev["receiver_initial_state"] = state

# 3. cloudflared quick tunnel
tun = subprocess.Popen(
    [f"{TF}/cloudflared", "tunnel", "--url", "http://localhost:8091", "--no-autoupdate"],
    stdout=open(f"{TF}/tf/logs/tunnel_tf.log", "wb"),
    stderr=subprocess.STDOUT)
url = None
for _ in range(30):
    time.sleep(1)
    log = open(f"{TF}/tf/logs/tunnel_tf.log").read()
    for token in log.split("https://")[1:]:
        cand = "https://" + token.split()[0].rstrip('"')
        if "trycloudflare.com" in cand:
            url = cand.rstrip(".")
            break
    if url: break
assert url, "no tunnel url"
print("tunnel:", url)
ev["tunnel_url"] = url

# 4. repoint the hook
st, resp = gh_req(f"/{HOOK}", method="PATCH",
                  body={"config": {"url": f"{url}/webhook", "content_type": "json"}})
print("hook PATCH:", st)
ev["hook_repoint_status"] = st
assert st == 200

# 5. gated redelivery through a NEW TrueForge session
from tf_driver import api, create_session, stream_turn, wait_turn

spec = {
    "model": {"name": "opencode-go/ox-alpha-free"},
    "instructions": ("You are a webhook incident operator for repo bhavaygoel/redrive-spike-repo. "
                     "Use the redrive-github tools exactly as instructed."),
    "mcp_servers": [{
        "name": "redrive-github",
        "enable_tools": ["@all"],
        "require_approval_for_tools": ["redeliver_webhook_delivery"],
    }],
}
sid = create_session(spec)
tid, events = stream_turn(sid, [{
    "type": "user.message",
    "content": (f"Inspect webhook delivery {DELIVERY} of hook {HOOK} with the read-only tool. "
                f"Then request redelivery of that exact delivery using redeliver_webhook_delivery.")}])
state1 = wait_turn(sid, tid)
pers = api("GET", f"/sessions/{sid}/turns/{tid}/events")
items = pers["data"]
appr = None
for it in items:
    body = it.get("data", it)
    if isinstance(body, dict) and body.get("type") == "tool.approval_required":
        appr = body
print("paused:", bool(appr), "| turn:", state1["status"])
ev["session_id"] = sid
ev["turn1_id"] = tid
ev["paused_with_required_actions"] = bool(appr)

_, pre = local_get("http://127.0.0.1:8091/state")
ev["receiver_state_while_paused"] = pre

tool_call_id = appr["toolCalls"][0]["id"] if "toolCalls" in appr else appr["tool_calls"][0]["id"]
tid2, events2 = stream_turn(sid, [{
    "type": "user.tool_approval", "thread_id": "main",
    "tool_call_id": tool_call_id, "approval": {"status": "allow"}}])
state2 = wait_turn(sid, tid2)
ev["turn2_id"] = tid2
ev["turn2_status"] = state2["status"]

resp_events = [e for e in events2 if e.get("type") == "tool.response"]
mcp_out = None
for e in resp_events:
    try:
        d = json.loads(e.get("content", "{}"))
        if isinstance(d, dict) and d.get("http_status"):
            mcp_out = d
    except Exception:
        pass
ev["mcp_redeliver_response"] = mcp_out
print("MCP redeliver ->", mcp_out)

# 6. poll GitHub for the redelivery record until it lands / settles
final_rec = None
for _ in range(20):
    time.sleep(2)
    st, dl = gh_req(f"/{HOOK}/deliveries?per_page=5")
    for d in dl:
        if d.get("redelivery") and d["id"] > 3838959604597792768:
            final_rec = d
            break
    if final_rec and final_rec.get("status_code") not in (None, "", "  ", "pending"):
        break
ev["new_redelivery_record"] = {k: final_rec.get(k) for k in
                               ("id", "guid", "event", "status_code", "delivered_at", "redelivery")} if final_rec else None
print("new redelivery record:", ev["new_redelivery_record"])

# 7. business state
time.sleep(2)
st, post = local_get("http://127.0.0.1:8091/state")
ev["receiver_state_final"] = post
print("receiver final:", post)

json.dump(ev, open(f"{TF}/tf/evidence_tf3b.json", "w"), indent=1)
print("evidence -> evidence_tf3b.json")

# leave processes running for inspection; cleanup handled separately
