#!/usr/bin/env python3
"""TF-3: TrueForge-native approval gate on redeliver_webhook_delivery.

Phase A: agent requests redelivery -> expect tool.approval_required pause.
         GitHub deliveries list must be UNCHANGED while paused.
Phase B: resume with official user.tool_approval input (allow).
         Expect the MCP call to execute and GitHub to record a redelivery.
"""
import json, time, urllib.request
from tf_driver import api, create_session, stream_turn, wait_turn

HOOK = 670245925
DELIVERY = 3838953010386436096  # disposable 530 delivery (safe redrive target)

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

ev = {"delivery_target": DELIVERY}

# ---------- Phase A ----------
snap_before = deliveries_snapshot()
ev["github_before"] = snap_before
print(f"GitHub before: {len(snap_before)} deliveries; "
      f"redelivery count = {sum(1 for x in snap_before if x[2])}")

spec = {
    "model": {"name": "opencode-go/ox-alpha-free"},
    "instructions": ("You are a webhook incident operator for repo bhavaygoel/redrive-spike-repo. "
                     "Use the redrive-github tools exactly as instructed by the user."),
    "mcp_servers": [{
        "name": "redrive-github",
        "enable_tools": ["@all"],
        "require_approval_for_tools": ["redeliver_webhook_delivery"],
    }],
}
sid = create_session(spec)
ev["session_id"] = sid
print("session:", sid)

inp = [{"type": "user.message",
        "content": (f"First inspect webhook delivery {DELIVERY} of hook {HOOK} with the read-only tool. "
                    f"Then request redelivery of that same delivery using redeliver_webhook_delivery.")}]
tid, events = stream_turn(sid, inp)
state = wait_turn(sid, tid)
ev["turn1_id"] = tid
ev["turn1_status"] = state["status"]
print("turn1 status:", state["status"])

approval_events = [e for e in events if e.get("type") == "tool.approval_required"]
ev["approval_required_event_count"] = len(approval_events)
ev["approval_required_events"] = approval_events
# tool calls arrive as SSE deltas; fetch PERSISTED (merged) events for the full call
persisted = api("GET", f"/sessions/{sid}/turns/{tid}/events")
pevents = persisted.get("data", persisted if isinstance(persisted, list) else [])
if isinstance(pevents, dict):
    pevents = pevents.get("items", pevents.get("events", []))
calls = []
for e in pevents:
    et = e.get("type") or e.get("event_type")
    body = e.get("data", e)
    if isinstance(body, str):
        try:
            body = json.loads(body)
        except Exception:
            continue
    if body.get("type") == "model.message" and body.get("tool_calls"):
        calls += body["tool_calls"]
gated = [c for c in calls if c.get("function", {}).get("name") == "redeliver_webhook_delivery"]
ev["agent_gated_calls"] = [{"id": c.get("id"),
                            "args": c.get("function", {}).get("arguments")} for c in gated]
print("approval_required events:", len(approval_events))
print("gated call:", ev["agent_gated_calls"])

time.sleep(8)  # grace period to rule out delayed execution
snap_paused = deliveries_snapshot()
ev["github_while_paused"] = snap_paused
ev["unchanged_while_paused"] = snap_before == snap_paused
print("GitHub unchanged while paused:", ev["unchanged_while_paused"])

if not approval_events or not gated:
    print("!! No real approval pause observed — ABORTING before approval.")
    json.dump(ev, open("/root/workspace/redrive-spike/tf/evidence_tf3.json", "w"), indent=1)
    raise SystemExit(2)

# ---------- Phase B: programmatic operator approval via official input type ----------
pend = approval_events[0]["toolCalls"][0]
resume_input = [{
    "type": "user.tool_approval",
    "threadId": pend.get("threadId") or pend.get("thread_id") or "main",
    "toolCallId": pend["id"],
    "approval": {"status": "allow"},
}]
tid2, events2 = stream_turn(sid, resume_input)
state2 = wait_turn(sid, tid2)
ev["turn2_id"] = tid2
ev["turn2_status"] = state2["status"]
resp_events = [e for e in events2 if e.get("type") == "tool.response"]
ev["turn2_tool_responses"] = [e.get("content", "")[:200] for e in resp_events]
for e in resp_events:
    try:
        d = json.loads(e.get("content", "{}"))
        if d.get("http_status"):
            ev["redelivery_http_status"] = d["http_status"]
    except Exception:
        pass
print("turn2 status:", state2["status"], "| redelivery http:",
      ev.get("redelivery_http_status"))

out2 = state2.get("output") or {}
ev["turn2_final"] = out2.get("content", "")[:300]
print("turn2 final:", ev["turn2_final"][:150])

snap_after = deliveries_snapshot()
ev["github_after"] = snap_after
new_redeliveries = [x for x in snap_after if x[2] and x not in snap_before]
ev["new_redelivery_records"] = new_redeliveries
print("GitHub after: redelivery records:", new_redeliveries)

json.dump(ev, open("/root/workspace/redrive-spike/tf/evidence_tf3.json", "w"), indent=1)
print("evidence -> evidence_tf3.json")
