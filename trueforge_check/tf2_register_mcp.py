#!/usr/bin/env python3
"""TF-2: register the Redrive MCP server in TrueForge and list its tools."""
import json, urllib.request

B = "http://localhost:8790/api/v1"

def api(method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(B + path, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req) as r:
            raw = r.read().decode()
            return r.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()[:400]

manifest = {
    "type": "remote",
    "name": "redrive-github",
    "url": "http://127.0.0.1:8901/mcp",
    "description": "GitHub webhook delivery inspection + official redelivery for Redrive spike repo",
}
st, resp = api("POST", "/settings/mcp-servers", {"manifest": manifest})
print("register:", st, json.dumps(resp)[:300])

st, tools = api("GET", "/mcp-servers/redrive-github/tools")
print("tools endpoint:", st)
if isinstance(tools, dict):
    data = tools.get("data", [])
    for t in data:
        info = t.get("tool_info") or t
        print("  -", info.get("name"), "| readOnly:",
              (info.get("annotations") or {}).get("read_only_hint"))
