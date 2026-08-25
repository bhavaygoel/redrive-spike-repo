#!/usr/bin/env python3
"""
Minimal MCP server exposing the GitHub webhook redelivery operation:
  redeliver_webhook_delivery(hook_id, delivery_id) -> POST /repos/{o}/{r}/hooks/{id}/deliveries/{d}/attempts
This is the exact operation Redrive would gate behind TrueForge approval.
Runs on stdio; speak MCP via @modelcontextprotocol/sdk on the client side.
"""
import json, os, sys, urllib.request

BASE = "/root/workspace/redrive-spike"
OWNER = "bhavaygoel"
REPO = "redrive-spike-repo"

def github_redeliver(hook_id, delivery_id):
    tok_path = f"{BASE}/.gh_token"
    if not os.path.exists(tok_path):
        return {"error": "no token"}
    tok = open(tok_path).read().strip()
    req = urllib.request.Request(
        f"https://api.github.com/repos/{OWNER}/{REPO}/hooks/{hook_id}/deliveries/{delivery_id}/attempts",
        data=b"", method="POST", headers={
            "Authorization": f"Bearer {tok}", "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28", "Content-Length": "0",
            "User-Agent": "redrive-spike"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return {"status": r.status}          # GitHub returns 204 Accepted-for-redelivery
    except urllib.error.HTTPError as e:
        return {"error": e.code, "body": e.read().decode()[:300]}

TOOLS = [{
    "name": "redeliver_webhook_delivery",
    "description": "Redeliver a specific GitHub webhook delivery by id. DESTRUCTIVE-ish: replays business event at receiver.",
    "inputSchema": {
        "type": "object",
        "properties": {
            "hook_id": {"type": "integer"},
            "delivery_id": {"type": "integer"}},
        "required": ["hook_id", "delivery_id"]}
}]

def handle(msg):
    m = msg.get("method")
    mid = msg.get("id")
    if m == "initialize":
        return {"jsonrpc": "2.0", "id": mid, "result": {
            "protocolVersion": msg.get("params", {}).get("protocolVersion", "2024-11-05"),
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "github-webhook-redrive", "version": "0.0.1"}}}
    if m == "notifications/initialized":
        return None
    if m == "tools/list":
        return {"jsonrpc": "2.0", "id": mid, "result": {"tools": TOOLS}}
    if m == "tools/call":
        name = msg["params"]["name"]
        args = msg["params"].get("arguments", {})
        if name != "redeliver_webhook_delivery":
            return {"jsonrpc": "2.0", "id": mid, "result": {"content": [{"type": "text", "text": f"unknown tool {name}"}], "isError": True}}
        # NOTE: in the real product this call happens only AFTER TrueForge approval.
        out = github_redeliver(args["hook_id"], args["delivery_id"])
        return {"jsonrpc": "2.0", "id": mid, "result": {"content": [{"type": "text", "text": json.dumps(out)}]}}
    if m == "ping":
        return {"jsonrpc": "2.0", "id": mid, "result": {}}
    if mid is not None:
        return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"method not found: {m}"}}
    return None

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--call-now":
        # direct invocation used ONLY for negative test (pre-approval block proof)
        print(json.dumps(github_redeliver(int(sys.argv[2]), int(sys.argv[3]))))
        raise SystemExit
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except Exception:
            continue
        resp = handle(msg)
        if resp is not None:
            sys.stdout.write(json.dumps(resp) + "\n")
            sys.stdout.flush()
