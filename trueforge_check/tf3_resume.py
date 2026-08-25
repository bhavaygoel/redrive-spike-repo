#!/usr/bin/env python3
"""TF-3 Phase B: approve the LIVE paused TrueForge session via official user.tool_approval input.
Decision made by automated test operator THROUGH TrueForge's runtime API (no shim)."""
import json, time, urllib.request, urllib.error
from tf_driver import api, stream_turn, wait_turn

HOOK = 670245925
GH = "https://api.github.com/repos/bhavaygoel/redrive-spike-repo/hooks"
TOK = open("/root/workspace/redrive-spike/.gh_token").read().strip()

def deliveries_snapshot():
    req = urllib.request.Request(
        f"{GH}/{HOOK}/deliveries?per_page=100",
        headers={"Authorization": f"Bearer {TOK}",
                 "Accept": "application/vnd.github+json", "User-Agent": "rc"})
    with urllib.request.urlopen(req) as r:
        return [(d["id"], d["status_code"], d.get("redelivery", False))
                for d in json.load(r)]

ev = json.load(open("/root/workspace/redrive-spike/tf/evidence_tf3.json"))
SID = ev["session_id"]
TURN1 = ev["turn1_id"]
ev["decision_type"] = "programmatic operator via TrueForge official approval API (user.tool_approval input); NO human click this spike"

# re-pull persisted events of turn1 to capture exact gated-call identity
pers = api("GET", f"/sessions/{SID}/turns/{TURN1}/events")
items = pers["data"] if isinstance(pers.get("data"), list) else []
appr = None
gated_call = None
for it in items:
    body = it.get("data", it) if isinstance(it, dict) else it
    if isinstance(body, str):
        try:
            body = json.loads(body)
        except Exception:
            continue
    if not isinstance(body, dict):
        continue
    if body.get("type") == "tool.approval_required":
        appr = body
    if body.get("type") == "model.message" and body.get("tool_calls"):
        for tc in body["tool_calls"]:
            fn = tc.get("function", {})
            # deferred-tool harness wraps MCP calls as call_tool(input, mcp_server, tool_name)
            try:
                fargs = json.loads(fn.get("arguments") or "{}")
            except Exception:
                fargs = {}
            target = fn.get("name")
            if target == "call_tool":
                target = fargs.get("tool_name")
            if target == "redeliver_webhook_delivery":
                gated_call = tc
                ev["gated_tool_args_raw"] = fn.get("arguments")
assert appr, "no approval_required in persisted events"
ev["approval_required_event"] = appr
ev["agent_gated_calls"] = [{"id": gated_call["id"], "args": gated_call["function"]["arguments"]}]
print("session:", SID)
print("gated call:", ev["agent_gated_calls"])

# confirm still paused (required_actions present on turn1 state)
t1 = api("GET", f"/sessions/{SID}/turns/{TURN1}")["data"]
ra = t1["state"].get("required_actions") or []
ev["turn1_required_actions"] = ra
print("turn1 required_actions:", json.dumps(ra)[:200])
snap_now = deliveries_snapshot()
ev["github_still_unchanged_pre_approval"] = snap_now == ev["github_before"]
print("GitHub still unchanged pre-approval:", ev["github_still_unchanged_pre_approval"])

tool_call_id = appr["toolCalls"][0]["id"] if "toolCalls" in appr else appr["tool_calls"][0]["id"]

resume = None
for payload in (
    [{"type": "user.tool_approval", "thread_id": "main",
      "tool_call_id": tool_call_id, "approval": {"status": "allow"}}],
    [{"type": "user.tool_approval", "threadId": "main",
      "toolCallId": tool_call_id, "approval": {"status": "allow"}}],
):
    try:
        tid2, events2 = stream_turn(SID, payload)
        resume = (tid2, events2)
        break
    except urllib.error.HTTPError as e:
        print("payload rejected:", e.code, e.read().decode()[:200])
assert resume, "both payload shapes rejected"
tid2, events2 = resume
state2 = wait_turn(SID, tid2)
ev["turn2_id"] = tid2
ev["turn2_status"] = state2["status"]

resp_events = [e for e in events2 if e.get("type") == "tool.response"]
ev["turn2_tool_responses"] = [e.get("content", "")[:300] for e in resp_events]
for e in resp_events:
    try:
        d = json.loads(e.get("content", "{}"))
        if isinstance(d, dict) and d.get("http_status"):
            ev["redelivery_http_status"] = d["http_status"]
    except Exception:
        pass
out2 = state2.get("output") or {}
ev["turn2_final"] = out2.get("content", "")[:400]
print("turn2:", state2["status"], "| redelivery http:", ev.get("redelivery_http_status"))
print("final:", ev["turn2_final"][:180])

time.sleep(5)
snap_after = deliveries_snapshot()
ev["github_after"] = snap_after
before_ids = {x[0] for x in ev["github_before"]}
new_redeliveries = [x for x in snap_after if x[0] not in before_ids]
ev["new_redelivery_records"] = new_redeliveries
print("new delivery records after approval:", new_redeliveries)

json.dump(ev, open("/root/workspace/redrive-spike/tf/evidence_tf3.json", "w"), indent=1)
print("evidence -> evidence_tf3.json")
