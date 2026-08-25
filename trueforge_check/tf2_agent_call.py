#!/usr/bin/env python3
"""TF-2 evidence: agent invokes read-only get_webhook_delivery through TrueForge."""
import json
from tf_driver import api, create_session, stream_turn, wait_turn, summarize

HOOK = 670245925
DELIVERY = 3838953010386436096  # disposable 530 delivery

spec = {
    "model": {"name": "opencode-go/ox-alpha-free"},
    "instructions": "You are a precise webhook-ops assistant. Use the redrive-github tools when asked about webhook deliveries. Be terse.",
    "mcp_servers": [{"name": "redrive-github", "enable_tools": ["@all"]}],
}
sid = create_session(spec)
print("session:", sid)

inp = [{"type": "user.message",
        "content": (f"Inspect GitHub webhook delivery {DELIVERY} of hook {HOOK} "
                    f"(use the get_webhook_delivery tool). Report event type and HTTP status code only.")}]
tid, events = stream_turn(sid, inp)
print("turn:", tid)
state = wait_turn(sid, tid)
print("status:", state["status"])
print("event kinds:", summarize(events))

# extract tool activity
tool_events = [e for e in events if e.get("type") == "tool.response"]
calls = []
for e in events:
    if e.get("type") == "model.message" and e.get("tool_calls"):
        calls += e["tool_calls"]
for tc in calls:
    print("AGENT TOOL CALL:", tc.get("function", {}).get("name"),
          "| args:", str(tc.get("function", {}).get("arguments"))[:120])
for te in tool_events:
    txt = te.get("content", "")
    try:
        d = json.loads(txt)
        head = {k: d.get(k) for k in ("id", "event", "status_code", "redelivery", "action")}
        print("TOOL RESPONSE:", json.dumps(head))
    except Exception:
        print("TOOL RESPONSE(raw):", txt[:150])
out = state.get("output")
print("final:", (out or {}).get("content", "")[:300])

json.dump({"session_id": sid, "turn_id": tid,
           "tool_calls": [{"name": c.get("function", {}).get("name"),
                           "args": c.get("function", {}).get("arguments")} for c in calls],
           "tool_responses": [te.get("content") for te in tool_events],
           "final": (out or {}).get("content")},
          open("/root/workspace/redrive-spike/tf/evidence_tf2.json", "w"), indent=1)
print("evidence -> evidence_tf2.json")
