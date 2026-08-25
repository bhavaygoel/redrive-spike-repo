#!/usr/bin/env python3
"""Redrive MCP server — streamable-HTTP transport for TrueForge connectors.

Tools:
  get_webhook_delivery(hook_id, delivery_id)       read-only delivery inspection
  redeliver_webhook_delivery(hook_id, delivery_id) GitHub official redelivery (202)

Same operations as spike/mcp_redrive_server.py (stdio), adapted to HTTP.
Token read in-process (env REDRIVE_GH_TOKEN or .gh_token); never logged.
Run: /usr/local/lib/hermes-agent/venv/bin/python3 mcp_redrive_http.py
"""
import json, os, urllib.request
import mcp.server.mcpserver as M
from mcp.types import ToolAnnotations

OWNER, REPO = "bhavaygoel", "redrive-spike-repo"
BASE = f"https://api.github.com/repos/{OWNER}/{REPO}/hooks"

def gh_token():
    tok = os.environ.get("REDRIVE_GH_TOKEN")
    if tok:
        return tok.strip()
    p = "/root/workspace/redrive-spike/.gh_token"
    if os.path.exists(p):
        return open(p).read().strip()
    raise RuntimeError("no github token available")

def as_int(v):
    """Coerce LLM-supplied IDs (may arrive as str/float/sci-notation) to int."""
    if isinstance(v, bool) or v is None:
        raise ValueError(f"invalid id: {v!r}")
    return int(float(v)) if isinstance(v, float) else int(str(v), 10)

def gh(path, method="GET"):
    req = urllib.request.Request(
        BASE + path, data=(b"" if method == "POST" else None), method=method,
        headers={"Authorization": f"Bearer {gh_token()}",
                 "Accept": "application/vnd.github+json",
                 "X-GitHub-Api-Version": "2022-11-28",
                 "User-Agent": "redrive-mcp",
                 **({"Content-Length": "0"} if method == "POST" else {})})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            body = r.read().decode()
            return {"http_status": r.status,
                    "body": json.loads(body) if body else None}
    except urllib.error.HTTPError as e:
        return {"http_status": e.code, "error": e.read().decode()[:300]}

srv = MCPSERVER = M.MCPServer(name="github-webhook-redrive", version="0.1.0")

def get_webhook_delivery(hook_id, delivery_id) -> dict:
    """Read-only inspection of one webhook delivery: event, status_code,
    delivered_at, redelivery flag, payload, request headers incl. signature."""
    hook_id, delivery_id = as_int(hook_id), as_int(delivery_id)
    out = gh(f"/{hook_id}/deliveries/{delivery_id}")
    d = out.get("body") or {}
    summary = {k: d.get(k) for k in ("id", "guid", "event", "status_code",
                                     "delivered_at", "redelivery", "duration")}
    summary["action"] = "inspected"
    summary["full"] = out
    return summary

def redeliver_webhook_delivery(hook_id, delivery_id) -> dict:
    """Trigger GitHub's official redelivery of a specific webhook delivery.
    Replays the business event at the receiver. Requires TrueForge approval."""
    hook_id, delivery_id = as_int(hook_id), as_int(delivery_id)
    return gh(f"/{hook_id}/deliveries/{delivery_id}/attempts", method="POST")

srv.add_tool(get_webhook_delivery,
             annotations=ToolAnnotations(read_only_hint=True,
                                         destructive_hint=False,
                                         idempotent_hint=True))
srv.add_tool(redeliver_webhook_delivery,
             annotations=ToolAnnotations(read_only_hint=False,
                                         destructive_hint=True,
                                         idempotent_hint=False))

if __name__ == "__main__":
    app = srv.streamable_http_app(stateless_http=True, json_response=True)
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=int(os.environ.get("PORT", "8901")),
                log_level="warning")
