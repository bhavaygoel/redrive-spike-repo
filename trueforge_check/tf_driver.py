#!/usr/bin/env python3
"""Shared TrueForge SDK-less driver: sessions, turns (SSE-consuming), polling."""
import json, urllib.request, time

B = "http://localhost:8790/api/v1"

def api(method, path, body=None, timeout=60):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(B + path, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read().decode()
        return json.loads(raw) if raw else None

def create_session(spec):
    r = api("POST", "/sessions", {"agent": {"spec": spec}})
    return r["data"]["id"]

def stream_turn(sid, input_items):
    """POST a turn and consume its SSE stream. Returns (turn_id, events)."""
    data = json.dumps({"input": input_items}).encode() if input_items else b"{}"
    req = urllib.request.Request(f"{B}/sessions/{sid}/turns", data=data,
                                 method="POST",
                                 headers={"Content-Type": "application/json"})
    events = []
    turn_id = None
    with urllib.request.urlopen(req, timeout=1800) as resp:
        ctype = resp.headers.get("content-type", "")
        if "text/event-stream" in ctype:
            cur = {}
            for lineb in resp:
                line = lineb.decode("utf-8", "replace").rstrip("\n")
                if line.startswith("data: "):
                    try:
                        cur = json.loads(line[6:])
                    except Exception:
                        cur = {}
                    if cur.get("type") == "turn.created":
                        turn_id = cur.get("turn_id")
                    events.append(cur)
                # ignore id:/retry: lines and blanks
        else:
            body = json.loads(resp.read().decode() or "{}")
            turn_id = body.get("data", {}).get("id")
            events.append({"type": "non-stream", "body": body})
    return turn_id, events

def wait_turn(sid, tid, timeout_s=300):
    t0 = time.time()
    while time.time() - t0 < timeout_s:
        tr = api("GET", f"/sessions/{sid}/turns/{tid}")
        st = tr["data"]["state"]["status"]
        if st != "running":
            return tr["data"]["state"]
        time.sleep(2)
    raise TimeoutError("turn did not finish")

def summarize(events):
    kinds = {}
    for e in events:
        kinds[e.get("type")] = kinds.get(e.get("type"), 0) + 1
    return kinds

if __name__ == "__main__":
    print("driver module ok")
