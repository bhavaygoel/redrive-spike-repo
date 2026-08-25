#!/usr/bin/env python3
"""
Redrive spike receiver — BUGGY variant (v1, the incident).

Contract:
  POST /webhook   (GitHub webhook, JSON)
    - event == 'push': perform business mutation (INSERT into mutations),
      THEN crash -> HTTP 500.  (Mutation happens BEFORE the failure.)
    - other events (e.g. ping): HTTP 200, no mutation.
  GET  /state     -> JSON snapshot of business state (for evidence).

This variant has NO deduplication: replaying the same delivery inserts a
second mutation row => violates invariant 'mutation count == 1 per event'.
"""
import json
import hmac
import hashlib
import sqlite3
import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

SECRET = open("/root/workspace/redrive-spike/webhook_secret.txt").read().strip()
DB = "/root/workspace/redrive-spike/receiver_state.db"

def db():
    c = sqlite3.connect(DB, timeout=10)
    c.execute("""CREATE TABLE IF NOT EXISTS mutations(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        event_id TEXT NOT NULL,               -- X-GitHub-Delivery guid (NOT unique: this is the bug class)
        kind TEXT NOT NULL,                   -- e.g. 'order_payment_processed'
        order_ref TEXT,
        received_at TEXT NOT NULL)""")
    return c

class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):  # noisy logs are our friend in a spike
        print(f"[receiver-buggy] {self.address_string()} {fmt % args}", flush=True)

    def _send(self, code, body: dict):
        raw = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        if self.path == "/state":
            c = db(); rows = c.execute("SELECT id,event_id,kind,order_ref,received_at FROM mutations ORDER BY id").fetchall()
            self._send(200, {"mutations": [
                {"id": r[0], "event_id": r[1], "kind": r[2], "order_ref": r[3], "received_at": r[4]} for r in rows],
                "count": len(rows)})
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self):
        if self.path != "/webhook":
            return self._send(404, {"error": "not found"})
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        event = self.headers.get("X-GitHub-Event", "unknown")
        delivery = self.headers.get("X-GitHub-Delivery", "unknown")
        sig = self.headers.get("X-Hub-Signature-256", "")

        # Signature verification (transport/payload authenticity check)
        expected = "sha256=" + hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()
        sig_ok = hmac.compare_digest(expected, sig)

        print(f"[receiver-buggy] event={event} delivery={delivery} sig_ok={sig_ok} bytes={len(body)}", flush=True)

        payload = {}
        try:
            payload = json.loads(body)
        except Exception:
            pass

        if event != "push":
            # ping etc.: acknowledge, no business effect
            return self._send(200, {"ok": True, "event": event, "note": "no mutation for non-push"})

        # ---- BUSINESS MUTATION FIRST ----
        order_ref = None
        # push payload: repository.full_name + head_commit.id serve as business ref
        order_ref = f"{payload.get('repository', {}).get('full_name', '?')}@{payload.get('after', '?')[:12]}"
        c = db()
        try:
            c.execute("INSERT INTO mutations(event_id, kind, order_ref, received_at) VALUES (?,?,?,?)",
                      (delivery, "order_payment_processed", order_ref,
                       datetime.datetime.utcnow().isoformat() + "Z"))
            c.commit()
            print(f"[receiver-buggy] MUTATION committed event_id={delivery}", flush=True)
        except sqlite3.IntegrityError:
            # even the buggy receiver's schema has UNIQUE(event_id);
            # simulate legacy behavior: treat as error path too but DO NOT crash silently
            print(f"[receiver-buggy] IntegrityError on {delivery}", flush=True)
            return self._send(500, {"error": "integrity"})

        # ---- SOMETHING FAILS AFTER THE MUTATION (the bug) ----
        print("[receiver-buggy] simulating post-mutation downstream failure", flush=True)
        try:
            # simulate downstream call blow-up after side effect
            raise RuntimeError("downstream payment-notify service unavailable (simulated)")
        except Exception as e:
            return self._send(500, {"error": str(e), "note": "mutation already committed"})

if __name__ == "__main__":
    import sys
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8090
    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()
