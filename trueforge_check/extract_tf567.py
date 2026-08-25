#!/usr/bin/env python3
"""Extract TF-5..7 evidence from persisted TrueForge turn events into one JSON."""
import json
from tf_driver import api

SESSIONS = {
    "tf5_tf6_buggy": "01m0wbj96p7smnfsm72dgyfd03",
    "tf7_fixed": "01m0wc3g4pyj4rsvxj475ne9ss",
}
out = {}
for label, sid in SESSIONS.items():
    entry = {"session_id": sid, "sandbox_ids": [], "sandbox_exec_outputs": [], "finals": []}
    turns = api("GET", f"/sessions/{sid}/turns")["data"]
    for t in turns:
        tid = t["id"]
        ev = api("GET", f"/sessions/{sid}/turns/{tid}/events")["data"]
        for it in ev:
            body = it.get("data", it)
            if isinstance(body, str):
                try: body = json.loads(body)
                except Exception: continue
            if not isinstance(body, dict): continue
            bt = body.get("type")
            if bt == "sandbox.created":
                entry["sandbox_ids"].append({"sandbox_id": body.get("sandbox_id"),
                                             "event_id": body.get("id"),
                                             "created_at": body.get("created_at")})
            # Daytona exec results come through as tool responses of the sandbox tool
            c = body.get("content")
            if bt == "tool.response" and isinstance(c, str) and len(c) > 0:
                entry["sandbox_exec_outputs"].append(c[:1500])
            if bt == "model.message" and body.get("content"):
                txt = body["content"]
                if any(k in txt for k in ("REV=", "HTTP1=", "COUNT", "LEDGER=")):
                    entry["finals"].append(txt[:1200])
            if bt == "turn.done":
                entry.setdefault("turn_status", []).append(
                    (tid, body.get("state", {}).get("status")))
    out[label] = entry

json.dump(out, open("/root/workspace/redrive-spike/tf/evidence_tf567.json", "w"), indent=1)
print("saved evidence_tf567.json")
for label, e in out.items():
    print(f"\n== {label} == sandbox_ids:", [s["sandbox_id"] for s in e["sandbox_ids"]])
    print("finals:")
    for f in e["finals"][-2:]:
        for line in f.splitlines():
            if any(k in line for k in ("REV=", "HTTP1=", "HTTP2=", "COUNT", "LEDGER=")):
                print("   ", line.strip()[:160])
