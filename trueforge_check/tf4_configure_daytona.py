#!/usr/bin/env python3
"""TF-4: configure Daytona sandbox provider in TrueForge.
Key arrives via DAYTONA_API_KEY env var; never printed, never written to repo."""
import json, os, sys, time, urllib.request, urllib.error

B = "http://localhost:8790/api/v1"

def api(method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(B + path, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            raw = r.read().decode()
            return r.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()[:400]

key = os.environ.get("DAYTONA_API_KEY")
if not key or len(key) < 8:
    print("DAYTONA_API_KEY not set"); sys.exit(2)

manifest = {
    "type": "daytona",
    "auth": {"api_key": key},
    "exec_timeout_ms": 120000,
    "auto_stop_interval_in_minutes": 30,
    "auto_archive_interval_in_minutes": 120,
    "auto_delete_interval_in_minutes": 7200,
}
st, resp = api("PUT", "/settings/sandbox-providers", {"manifest": manifest})
s = json.dumps(resp) if not isinstance(resp, str) else resp
print("PUT:", st, s.replace(key, "<REDACTED>")[:300])

for _ in range(45):
    time.sleep(2)
    st, cur = api("GET", "/settings/sandbox-providers")
    txt = json.dumps(cur)
    if isinstance(cur, dict):
        d = cur.get("data", {})
        bs = d.get("build_status") or (d.get("provider") or {}).get("build_status")
        print("status:", bs or txt[:160])
        if bs in ("ready", "failed"):
            break
    else:
        print("raw:", txt.replace(key, "<REDACTED>")[:200]); break
