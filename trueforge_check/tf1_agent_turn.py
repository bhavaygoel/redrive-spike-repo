#!/usr/bin/env python3
"""TF-1: trivial real agent turn through TrueForge."""
import json, urllib.request, time, sys

B = "http://localhost:8790/api/v1"

def api(method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(B + path, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req) as r:
        return json.load(r)

# open session with inline agent spec on our provider/model
s = api("POST", "/sessions", {"agent": {"spec": {
    "model": {"name": "opencode-go/ox-alpha-free"},
    "instructions": "You are a terse spike assistant. Answer in one short sentence.",
}}})
sid = s["data"]["id"]
print("session:", sid)

t = api("POST", f"/sessions/{sid}/turns", {
    "input": [{"type": "user.message",
               "content": "Reply with exactly: TRUEFORGE_TF1_OK"}],
})
tid = t["data"]["id"]
print("turn:", tid, "status:", t["data"]["state"]["status"])

for _ in range(60):
    time.sleep(2)
    tr = api("GET", f"/sessions/{sid}/turns/{tid}")
    st = tr["data"]["state"]["status"]
    if st in ("done", "error", "cancelled"):
        print("final status:", st)
        out = tr["data"]["state"].get("output")
        print("output:", json.dumps(out)[:500])
        break
else:
    print("TIMEOUT waiting for turn")
    sys.exit(1)
