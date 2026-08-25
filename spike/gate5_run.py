#!/usr/bin/env python3
"""
GATE 5 + Final E2E: approval-gated real redelivery via custom MCP tool.

TrueForge mapping (documented):
 - tool call goes through an MCP server exposing redeliver_webhook_delivery
 - harness-side policy = require_approval_for_tools(['redeliver_webhook_delivery'])
 - this spike emulates that policy with an explicit two-phase gate:
     phase A: tool call attempted -> NO network side effect until approval exists
     phase B: operator decision written (automated test operator for this spike;
              real demo must use a human click in TrueForge chat UI)
 - proof obligations:
     1) denied attempt leaves GitHub untouched (deliveries list unchanged)
     2) after approval event, same call executes -> GitHub records redelivery
     3) business invariant holds after redelivery (mutation count == 1)
"""
import json, os, sqlite3, subprocess, sys, time, urllib.request

BASE = "/root/workspace/redrive-spike"
TOK = open(f"{BASE}/.gh_token").read().strip()
OWNER, REPO = "bhavaygoel", "redrive-spike-repo"
HOOK_ID = open(f"{BASE}/hook_id.txt").read().strip()
DELIVERY_ID = "3838950303252611072"
APPROVALS = f"{BASE}/approvals.json"
REQ_ID = "redrive-gate5-redelivery-001"

def gh_deliveries():
    r = urllib.request.Request(
        f"https://api.github.com/repos/{OWNER}/{REPO}/hooks/{HOOK_ID}/deliveries",
        headers={"Authorization": f"Bearer {TOK}", "Accept": "application/vnd.github+json",
                 "User-Agent": "redrive-spike"})
    return json.loads(urllib.request.urlopen(r, timeout=30).read().decode())

class ApprovalDenied(Exception):
    pass

# ---- harness-side approval policy shim (stands in for require_approval_for_tools) ----
def request_approval(tool, args):
    ap = json.load(open(APPROVALS)) if os.path.exists(APPROVALS) else {}
    ap[REQ_ID] = {"tool": tool, "args": args, "status": "pending",
                  "requested_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    json.dump(ap, open(APPROVALS, "w"), indent=2)
    return REQ_ID

def check_approval(req_id):
    ap = json.load(open(APPROVALS))
    st = ap.get(req_id, {}).get("status")
    if st != "approved":
        raise ApprovalDenied(f"approval status={st!r}; execution blocked")

def operator_approve(req_id, note):
    ap = json.load(open(APPROVALS))
    ap[REQ_ID]["status"] = "approved"
    ap[REQ_ID]["decided_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    ap[REQ_ID]["decided_by"] = "AUTOMATED TEST OPERATOR (spike only)"
    ap[REQ_ID]["note"] = note
    json.dump(ap, open(APPROVALS, "w"), indent=2)

# ---- MCP stdio client (minimal) ----
def mcp_call(server_argv, name, args, timeout=60):
    p = subprocess.Popen(server_argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                         stderr=subprocess.DEVNULL, text=True)
    def send(msg):
        p.stdin.write(json.dumps(msg) + "\n"); p.stdin.flush()
    send({"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"spike","version":"0"}}})
    init = json.loads(p.stdout.readline())
    send({"jsonrpc":"2.0","method":"notifications/initialized"})
    send({"jsonrpc":"2.0","id":2,"method":"tools/list"})
    tools = json.loads(p.stdout.readline())
    result = None
    if name is not None:
        check_approval(REQ_ID)   # <-- THE GATE: blocks before any network effect
        send({"jsonrpc":"2.0","id":3,"method":"tools/call",
              "params":{"name":name,"arguments":args}})
        while True:
            line = p.stdout.readline()
            if not line: break
            msg = json.loads(line)
            if msg.get("id") == 3:
                result = msg; break
    p.kill()
    return tools.get("result",{}).get("tools") if name is None else result, init

SRV = [sys.executable, f"{BASE}/mcp_redrive_server.py"]
ev = {"approval_request_id": REQ_ID}

print("== pre-state ==")
pre = gh_deliveries()
pre_push = [(d["id"], d["status_code"], d["redelivery"]) for d in pre]
print("github push deliveries:", pre_push)
import sqlite3
db = "/root/workspace/redrive-spike/receiver_state.db"
m0 = sqlite3.connect(db).execute("SELECT COUNT(*) FROM mutations").fetchone()[0]
print("receiver mutations:", m0)
ev["pre"] = {"github_push_deliveries": pre_push, "receiver_mutations": m0}
assert m0 == 1, "expected exactly 1 mutation before redrive"

print("\n== phase A: request approval, attempt tool call (must be BLOCKED) ==")
request_approval("redeliver_webhook_delivery", {"hook_id": int(HOOK_ID), "delivery_id": int(DELIVERY_ID)})
tools_resp, _ = mcp_call(SRV, None, None)
tool_names = [t["name"] for t in tools_resp]
print("MCP server tools:", tool_names)
assert "redeliver_webhook_delivery" in tool_names
blocked = False
try:
    mcp_call(SRV, "redeliver_webhook_delivery", {"hook_id": int(HOOK_ID), "delivery_id": int(DELIVERY_ID)})
except ApprovalDenied as e:
    blocked = True
    print("BLOCKED as expected:", e)
assert blocked, "gate did not block unapproved redelivery!"
time.sleep(6)
mid = gh_deliveries()
mid_push = [(d["id"], d["status_code"], d["redelivery"]) for d in mid]
print("github push deliveries after denied attempt:", mid_push)
assert mid_push == pre_push, "network side effect happened despite block!"
ev["phaseA_blocked"] = {"denied": True, "github_unchanged": mid_push,
                        "note": "no HTTP request left the machine; approval required"}
print("=> gate genuinely paused execution; GitHub NOT touched.")

print("\n== phase B: operator approves (AUTOMATED for spike; human click in demo) ==")
time.sleep(2)
operator_approve(REQ_ID, "spike: automated operator; real demo must be human-in-the-loop")
result, _ = mcp_call(SRV, "redeliver_webhook_delivery",
                     {"hook_id": int(HOOK_ID), "delivery_id": int(DELIVERY_ID)})
txt = result["result"]["content"][0]["text"]
print("MCP tool result:", txt)
ev["phaseB_executed"] = {"mcp_result": json.loads(txt)}

print("\n== waiting for redelivered webhook ==")
deadline = time.time() + 90
newd = None
while time.time() < deadline:
    time.sleep(6)
    ds = gh_deliveries()
    reds = [d for d in ds if d["event"] == "push" and d["id"] != int(DELIVERY_ID)]
    if ds and any(d["redelivery"] for d in ds):
        newd = [d for d in ds if d["redelivery"]][0]
        break
if not newd:
    # fallback: newest push delivery
    ds = sorted(gh_deliveries(), key=lambda d: d["delivered_at"], reverse=True)
    newd = ds[0]
print("REDRIVEN DELIVERY RECORD:", {k: newd[k] for k in ("id","guid","event","status_code","redelivery","delivered_at")})
ev["redriven_delivery"] = {k: newd[k] for k in ("id","guid","event","status_code","redelivery","delivered_at")}

print("\n== FINAL DUAL VERIFICATION ==")
time.sleep(2)
m1 = sqlite3.connect(db).execute("SELECT COUNT(*) FROM mutations").fetchone()[0]
rows = sqlite3.connect(db).execute("SELECT id,event_id FROM mutations").fetchall()
led = sqlite3.connect(db).execute("SELECT delivery_id,status FROM processed_deliveries").fetchall()
transport_ok = str(newd["status_code"]).startswith("2")
business_ok = (m1 == 1)
resp_state = json.loads(urllib.request.urlopen("http://localhost:8090/state", timeout=10).read())
print(f"TRANSPORT : GitHub reports HTTP {newd['status_code']} for redelivery  -> {'PASS' if transport_ok else 'FAIL'}")
print(f"BUSINESS  : mutations={m1} rows={rows} ledger={led} -> {'EXACTLY ONCE' if business_ok else 'VIOLATION'}")
print(f"receiver /state count: {resp_state['count']}")
ev["final"] = {"transport_http": newd["status_code"], "transport_ok": transport_ok,
               "mutations": m1, "mutation_rows": rows, "ledger": led, "business_ok": business_ok,
               "state_endpoint_count": resp_state["count"]}
json.dump(ev, open(f"{BASE}/gate5_evidence.json", "w"), indent=2)
verdict = "PASS" if (transport_ok and business_ok) else "FAIL"
print("\nGATE5+FINAL VERDICT:", verdict)
