#!/usr/bin/env python3
"""TF-5..7: TrueForge sandbox-tool chain inside Daytona.

TF-5: agent clones bhavaygoel/redrive-spike-repo, checks out buggy revision e3157af.
TF-6: replays captured real delivery (captured_body.bin) against it -> HTTP 500,
      mutations=1; replay again -> 500, mutations=2 (duplicate danger).
TF-7: fresh state, fixed revision e86ce71 -> 200/200, mutations=1.

The AGENT drives everything via its sandbox tool (TrueForge -> Daytona).
Fixture enters the sandbox by base64 data URI file upload (user.message content part).
"""
import base64, json, sys
from tf_driver import api, create_session, stream_turn, wait_turn

REPO = "https://github.com/bhavaygoel/redrive-spike-repo.git"
BUGGY = "e3157af"
FIXED = "e86ce71"
BODY = open("/root/workspace/redrive-spike/captured_body.bin", "rb").read()
B64 = base64.b64encode(BODY).decode()

SPEC_TMPL = {
    "model": {"name": "opencode-go/ox-alpha-free"},
    "config": {"sandbox": {"enabled": True}},
    "instructions": (
        "You are a meticulous spike engineer working ONLY via your sandbox shell. "
        "Run every step exactly as instructed and print machine-checkable lines. "
        "Never skip a step; if a command fails, report the exact error."),
}

def run(sid, text):
    tid, events = stream_turn(sid, [{
        "type": "user.message",
        "content": [
            {"type": "text", "text": text},
            {"type": "file", "name": "captured_body.bin",
             "data": f"data:application/octet-stream;base64,{B64}"},
        ]}])
    st = wait_turn(sid, tid, timeout_s=900)
    pers = api("GET", f"/sessions/{sid}/turns/{tid}/events")
    items = pers["data"]
    outputs = []
    for it in items:
        body = it.get("data", it)
        if isinstance(body, str):
            try:
                body = json.loads(body)
            except Exception:
                continue
        if not isinstance(body, dict):
            continue
        t = body.get("type")
        if t == "sandbox.created":
            print("SANDBOX CREATED id:", body.get("sandbox_id"))
        if t in ("tool.response",) or (t is None and "output" in str(it)[:80]):
            c = body.get("content") or ""
            if isinstance(c, str) and len(c) > 0:
                outputs.append(c)
        if t == "model.message" and body.get("content"):
            outputs.append("[final] " + body["content"])
    return st, outputs

def show(outputs, marker_lines=("MUT", "HTTP", "COUNT")):
    for o in outputs[-6:]:
        for line in o.splitlines():
            if any(m in line for m in marker_lines) or line.startswith("[final]"):
                print("  ", line[:220])

# ---------- TF-5 + TF-6: clone, checkout buggy, replay twice ----------
sid = create_session(SPEC_TMPL)
print("session:", sid)

t5 = f"""Do these steps in your sandbox, in order:
0. Locate the uploaded fixture: it is in the sandbox working directory as captured_body.bin (run ls; if missing, find / -name captured_body.bin 2>/dev/null | head -1) and note its absolute path F.
1. git clone {REPO} /workspace/repo && cd /workspace/repo && git checkout {BUGGY}
2. Print 'REV=' followed by git rev-parse HEAD (full sha).
3. Start the receiver: cd /workspace/repo/spike && nohup python3 receiver_buggy.py > /tmp/rec.log 2>&1 & sleep 1.5
4. The uploaded file captured_body.bin is the EXACT raw webhook payload GitHub delivered (delivery guid 44c70d9c-a06b-11f1-914c-d186f381ed14). Replay it faithfully with headers matching the original event:
   curl -s -o /tmp/r1.txt -w '%{{http_code}}' -X POST http://127.0.0.1:8091/webhook \\
     -H 'Content-Type: application/json' -H 'X-GitHub-Event: push' \\
     -H 'X-GitHub-Delivery: 44c70d9c-a06b-11f1-914c-d186f381ed14' --data-binary @captured_body.bin
   then echo. Print as HTTP1=<code>.
5. Print COUNT1= plus sqlite3 queries: SELECT count(*) FROM mutations;
6. Repeat step 4 into HTTP2=<code> and COUNT2= same query (second replay of the SAME delivery).
Report exactly the four tokens REV=, HTTP1=, COUNT1=, HTTP2=, COUNT2=."""
st, outs = run(sid, t5)
print("TF5/TF-6 turn status:", st["status"])
show(outs, ("REV=", "HTTP1=", "COUNT1=", "HTTP2=", "COUNT2="))

# ---------- TF-7: fresh session, fixed rev ----------
sid2 = create_session(SPEC_TMPL)
print("session2:", sid2)
t7 = f"""Do these steps in your sandbox, in order:
0. Locate the uploaded fixture: it is in the sandbox working directory as captured_body.bin (run ls; if missing, find / -name captured_body.bin 2>/dev/null | head -1) and note its absolute path F.
1. git clone {REPO} /workspace/repo && cd /workspace/repo && git checkout {FIXED}
2. Print 'REV=' + git rev-parse HEAD.
3. cd /workspace/repo/spike && nohup python3 receiver_fixed.py > /tmp/rec.log 2>&1 & sleep 1.5
4. Replay the SAME captured delivery twice sequentially (same curl as described: POST http://127.0.0.1:8091/webhook, X-GitHub-Event: push, X-GitHub-Delivery: 44c70d9c-a06b-11f1-914c-d186f381ed14, --data-binary @captured_body.bin), printing HTTP1=<code> then HTTP2=<code>.
5. Print COUNT= from SELECT count(*) FROM mutations; and LEDGER=SELECT count(*) FROM processed_deliveries WHERE status='done';
Report tokens REV=, HTTP1=, HTTP2=, COUNT=, LEDGER=."""
st2, outs2 = run(sid2, t7)
print("TF7 turn status:", st2["status"])
show(outs2, ("REV=", "HTTP1=", "HTTP2=", "COUNT=", "LEDGER="))
