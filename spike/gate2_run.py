#!/usr/bin/env python3
"""Gate2 v2: extract payload correctly; prove byte-exactness via stored signature."""
import json, base64, hashlib, hmac, sqlite3, urllib.request

BASE = "/root/workspace/redrive-spike"
TOK = open(f"{BASE}/.gh_token").read().strip()
OWNER, REPO = "bhavaygoel", "redrive-spike-repo"
HOOK_ID = open(f"{BASE}/hook_id.txt").read().strip()
DELIVERY_ID = "3838950303252611072"

def req(path):
    r = urllib.request.Request("https://api.github.com" + path, headers={
        "Authorization": f"Bearer {TOK}", "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "redrive-spike"})
    with urllib.request.urlopen(r, timeout=30) as resp:
        return resp.status, json.loads(resp.read().decode())

s, det = req(f"/repos/{OWNER}/{REPO}/hooks/{HOOK_ID}/deliveries/{DELIVERY_ID}")
rq, rs = det["request"], det["response"]
hdrs = rq["headers"]                      # dict name->value
pl = rq.get("payload")
print("payload field type:", type(pl).__name__)
# docs: base64-encoded; handle both encodings defensively
if isinstance(pl, str):
    try:
        body = base64.b64decode(pl, validate=True)
        enc = "base64"
    except Exception:
        body = pl.encode(); enc = "plain-text"
else:
    body = json.dumps(pl).encode(); enc = "json-object"
print("payload encoding:", enc, "| bytes:", len(body))
print("payload preview:", body.decode()[:300])

secret = open(f"{BASE}/webhook_secret.txt").read().strip()
sig_recomputed = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
sig_stored = hdrs.get("X-Hub-Signature-256", "")
sha1_recomp = "sha1=" + hmac.new(secret.encode(), body, hashlib.sha1).hexdigest()
sig1_stored = hdrs.get("X-Hub-Signature", "")
print("\n-- BYTE-EXACTNESS PROOF --")
print("stored X-Hub-Signature-256 :", sig_stored)
print("recomputed over captured   :", sig_recomputed)
match = hmac.compare_digest(sig_stored, sig_recomputed)
print("MATCH:", match)
print("sha1 match:", hmac.compare_digest(sig1_stored, sha1_recomp))

rows = sqlite3.connect(f"{BASE}/receiver_state.db").execute("SELECT event_id FROM mutations").fetchall()
print("\nreceiver mutation rows:", rows, "| contains guid:", any(r[0] == det["guid"] for r in rows))

out = {
    "delivery_id": det["id"], "guid": det["guid"], "event": det["event"],
    "status_code": det["status_code"], "delivered_at": det["delivered_at"],
    "redelivery_flag": det["redelivery"],
    "request_headers_returned_by_api": hdrs,
    "payload_encoding": enc, "payload_bytes": len(body),
    "signature_match_replay_fidelity": bool(match),
    "response_body_returned_by_api": rs.get("payload"),
    "attempt_history_available_via_redelivery_flag_and_deliveries_list": True,
}
json.dump(out, open(f"{BASE}/gate2_evidence.json", "w"), indent=2)
open(f"{BASE}/captured_body.bin", "wb").write(body)
open(f"{BASE}/captured_headers.json", "w").write(json.dumps(hdrs, indent=2))
ev = json.load(open(f"{BASE}/gate12_evidence.json"))
ev["gate2"] = {k: out[k] for k in ("payload_bytes","payload_encoding","signature_match_replay_fidelity","response_body_returned_by_api")}
json.dump(ev, open(f"{BASE}/gate12_evidence.json", "w"), indent=2)
print("\nGATE2 VERDICT:", "PASS - faithful replay fixture reconstructable" if match else "PARTIAL - signature mismatch, investigate")
