#!/usr/bin/env python3
"""Update Gate2 evidence with byte-exactness finding; build canonical replay fixture."""
import json, hashlib, hmac

BASE = "/root/workspace/redrive-spike"
g2 = json.load(open(f"{BASE}/gate2_evidence.json"))
hdrs = g2["request_headers_returned_by_api"]
stored_sig = hdrs["X-Hub-Signature-256"]
secret = open(f"{BASE}/webhook_secret.txt").read().strip()

# Rebuild canonical fixture: compact re-serialization == original wire bytes (proven)
import urllib.request
TOK = open(f"{BASE}/.gh_token").read().strip()
r = urllib.request.Request(
    f"https://api.github.com/repos/bhavaygoel/redrive-spike-repo/hooks/{open(f'{BASE}/hook_id.txt').read().strip()}/deliveries/{g2['delivery_id']}",
    headers={"Authorization": f"Bearer {TOK}", "Accept": "application/vnd.github+json", "User-Agent": "redrive-spike"})
det = json.loads(urllib.request.urlopen(r, timeout=30).read().decode())
body = json.dumps(det["request"]["payload"], separators=(",", ":")).encode()
sig = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
match = hmac.compare_digest(sig, stored_sig)

open(f"{BASE}/captured_body.bin", "wb").write(body)
open(f"{BASE}/recomputed_sig.txt", "w").write(sig)

g2["byte_exactness"] = {
    "method": "payload returned as JSON object; compact separators re-serialization reproduces wire bytes",
    "recomputed_sig_matches_stored_X-Hub-Signature-256": bool(match),
    "stored_sig": stored_sig,
    "recomputed_sig": sig,
    "fixture_bytes": len(body),
}
json.dump(g2, open(f"{BASE}/gate2_evidence.json", "w"), indent=2)
ev = json.load(open(f"{BASE}/gate12_evidence.json"))
ev["gate2"]["signature_match_replay_fidelity"] = bool(match)
json.dump(ev, open(f"{BASE}/gate12_evidence.json", "w"), indent=2)
print("BYTE-EXACT FIXTURE:", match, "|", len(body), "bytes | sig", sig[:20], "...")
