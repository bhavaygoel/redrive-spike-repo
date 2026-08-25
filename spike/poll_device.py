#!/usr/bin/env python3
"""GitHub OAuth device-flow poller: waits for user authorization, stores token."""
import json, time, os, urllib.request, urllib.parse

BASE = "/root/workspace/redrive-spike"
d = json.load(open(f"{BASE}/device_flow.json"))
data = urllib.parse.urlencode({
    "client_id": "178c6fc778ccc68e1d6a",
    "device_code": d["device_code"],
    "grant_type": "urn:ietf:params:oauth:grant-type:device_code"}).encode()
deadline = time.time() + int(d.get("expires_in", 900)) - 30
while time.time() < deadline:
    req = urllib.request.Request("https://github.com/login/oauth/access_token",
                                 data=data, headers={"Accept": "application/json"})
    r = json.load(urllib.request.urlopen(req, timeout=15))
    err = r.get("error")
    if r.get("access_token"):
        tok = r["access_token"]
        p = f"{BASE}/.gh_token"
        open(p, "w").write(tok)
        os.chmod(p, 0o600)
        print("TOKEN_ACQUIRED scope:", r.get("scope"), flush=True)
        raise SystemExit(0)
    print(err or r, flush=True)
    if err == "authorization_pending":
        time.sleep(int(d.get("interval", 5))); continue
    if err == "slow_down":
        time.sleep(10); continue
    print("FATAL", r, flush=True); raise SystemExit(1)
print("EXPIRED without authorization", flush=True)
